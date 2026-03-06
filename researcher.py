import os
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple

import requests
import feedparser  # 用于解析 arXiv 数据
from serpapi import GoogleSearch  # SerpApi 官方客户端
from dotenv import load_dotenv

load_dotenv()


def build_context_from_papers(
    papers: List[Dict], max_papers: int = 10, max_chars: int = 6000
) -> Tuple[str, List[Dict]]:
    """
    将文献列表组装为传入 LLM 的上下文字符串及元数据结构。

    返回 (context_str, papers_meta)。
    """
    if not papers:
        return "", []

    selected = papers[: max(1, max_papers)]
    blocks = []
    meta_list: List[Dict] = []

    for idx, p in enumerate(selected, start=1):
        # 某些数据源可能返回 None，这里统一做安全转换
        raw_title = p.get("title") or ""
        raw_abstract = p.get("abstract") or ""
        raw_url = p.get("url") or ""

        title = str(raw_title).strip()
        abstract = str(raw_abstract).strip()
        url = str(raw_url).strip()

        block = f"[{idx}] 标题：{title}\n摘要：{abstract}\n链接：{url}".strip()
        blocks.append(block)

        meta_list.append(
            {
                "index": idx,
                "title": title,
                "abstract": abstract,
                "url": url,
            }
        )

    context_str = "\n\n".join(blocks)

    # 简单长度控制，超过则截断字符串；元数据保留完整
    if len(context_str) > max_chars:
        context_str = context_str[:max_chars] + "\n\n...[内容因长度限制被截断]"

    return context_str, meta_list


# arXiv 无结果时的备用检索词（提高命中率）
_ARXIV_QUERY_ALIASES = {
    "chinese herbal medicine": "traditional Chinese medicine",
    "intestinal microbiota": "gut microbiota",
    "intestinal flora": "gut microbiota",
}


def _arxiv_search_once(query: str, limit: int) -> List[Dict]:
    """执行一次 arXiv 查询，返回论文列表（可能为空）。"""
    base_url = "http://export.arxiv.org/api/query?"
    search_query = f"all:{query}"
    params = f"search_query={search_query}&start=0&max_results={limit}"
    feed = feedparser.parse(base_url + params)
    papers: List[Dict] = []
    for entry in getattr(feed, "entries", []):
        title = getattr(entry, "title", "").replace("\n", " ").strip()
        abstract = getattr(entry, "summary", "").replace("\n", " ").strip()
        url = getattr(entry, "link", "").strip()
        published = getattr(entry, "published", "")
        year = published[:4] if published else "N/A"
        if not (title and abstract):
            continue
        papers.append(
            {
                "title": title,
                "abstract": abstract,
                "url": url,
                "year": year,
                "source": "arXiv",
            }
        )
    return papers


def fetch_from_arxiv(query: str, limit: int = 5) -> List[Dict]:
    """
    备份引擎：从 arXiv 搜索（几乎无频率限制）。
    若首查无结果，会尝试用常用同义表述再查一次。
    """
    query = (query or "").strip()
    if not query:
        return []

    try:
        print(f"[切换] 正在启动备用引擎 arXiv 搜索: {query}...")
        papers = _arxiv_search_once(query, limit)
        if not papers:
            q_lower = query.lower()
            for orig, alias in _ARXIV_QUERY_ALIASES.items():
                if orig in q_lower or q_lower == orig:
                    print(f"[切换] arXiv 无结果，尝试备用词: {alias}...")
                    papers = _arxiv_search_once(alias, limit)
                    if papers:
                        break
        return papers
    except Exception as e:
        print(f"[失败] arXiv 引擎也故障了: {e}")
        return []


def _get_scholar_proxies() -> Dict[str, str]:
    """
    从环境变量读取用于 Semantic Scholar 的代理配置。

    - HTTP_PROXY_FOR_SCHOLAR
    - HTTPS_PROXY_FOR_SCHOLAR
    """
    proxies: Dict[str, str] = {}
    http_proxy = os.getenv("HTTP_PROXY_FOR_SCHOLAR")
    https_proxy = os.getenv("HTTPS_PROXY_FOR_SCHOLAR")
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


def _request_with_retry(
    url: str,
    params: Dict,
    headers: Dict,
    proxies: Dict | None,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
) -> requests.Response:
    """
    对 Semantic Scholar 的请求增加指数退避重试。

    - 对网络错误和 5xx 状态进行重试；
    - 对 429 不重试，由上层逻辑决定降级策略。
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=10,
                proxies=proxies or None,
            )
            if resp.status_code >= 500 and resp.status_code != 501:
                # 服务端异常，适当重试
                if attempt < max_retries - 1:
                    sleep_secs = backoff_factor * (2**attempt)
                    time.sleep(sleep_secs)
                    continue
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                sleep_secs = backoff_factor * (2**attempt)
                time.sleep(sleep_secs)
                continue
            raise
    # 理论上不会走到这里，防御性返回
    if last_exc:
        raise last_exc  # type: ignore[misc]
    raise RuntimeError("unexpected error when requesting Semantic Scholar")


def fetch_papers(query: str, limit: int = 5) -> List[Dict]:
    """
    主引擎：带自动重试和故障切换的搜索。

    - 优先从 Semantic Scholar（可选用官方 API Key，支持更高频率）。
    - 如果触发 429 或返回为空，则自动切换到 arXiv。
    """
    query = (query or "").strip()
    if not query:
        return []

    # 优先从环境变量读取官方 Key
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    headers = {"x-api-key": api_key} if api_key else {}

    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": limit,
        "fields": "title,abstract,url,year",
    }

    try:
        print("[检索] 尝试从 Semantic Scholar 检索...")
        proxies = _get_scholar_proxies()
        response = _request_with_retry(url, params=params, headers=headers, proxies=proxies)

        # 如果触发 429 频率限制，立即切换到备用源
        if response.status_code == 429:
            print("[警告] Semantic Scholar 提示太频繁了，正在自动切换到 arXiv...")
            return fetch_from_arxiv(query, limit)

        response.raise_for_status()
        data = response.json() or {}
        results = data.get("data", []) or []

        if not results:
            return fetch_from_arxiv(query, limit)

        for p in results:
            p["source"] = "Semantic Scholar"
        return results
    except Exception as e:
        print(f"[警告] 主引擎连接异常: {e}，尝试备用引擎...")
        return fetch_from_arxiv(query, limit)


def fetch_chinese_papers(query: str, limit: int = 5) -> List[Dict]:
    """
    中文文献引擎：通过 SerpApi 调用 Google Scholar（中文界面）。

    说明：
    - 需要在环境变量或 .env 中配置 SERPAPI_KEY（兼容旧名 SERPAPI_API_KEY）；
    - 若未配置或请求失败，则返回空列表，不影响英文检索。
    """
    query = (query or "").strip()
    if not query:
        return []

    # 优先使用新名字 SERPAPI_KEY，兼容旧的 SERPAPI_API_KEY
    api_key = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY")
    if not api_key:
        print("[提示] 未配置 SERPAPI_KEY，中文检索暂时跳过。")
        return []

    params = {
        "engine": "google_scholar",
        "q": query,
        "hl": "zh-CN",  # 强制中文界面
        "num": max(1, limit),
        "api_key": api_key,
    }

    try:
        print(f"[检索] 通过 SerpApi (Google Scholar 中文) 检索: {query} ...")
        search = GoogleSearch(params)
        data = search.get_dict() or {}
        results: List[Dict] = []
        for item in data.get("organic_results", [])[:limit]:
            title = (item.get("title") or "").strip()
            snippet = (item.get("snippet") or "").replace("\n", " ").strip()
            url = (item.get("link") or "").strip()
            pub_info = (item.get("publication_info") or {}) or {}
            summary = (pub_info.get("summary") or "").strip()
            year = "N/A"
            m = re.search(r"(19|20)\\d{2}", summary)
            if m:
                year = m.group(0)
            if not title:
                continue
            results.append(
                {
                    "title": title,
                    "abstract": snippet or summary,
                    "url": url,
                    "year": year,
                    "source": "SerpApi-GoogleScholar-zh",
                }
            )
        return results
    except Exception as e:
        print(f"[警告] 中文引擎（SerpApi Google Scholar）调用失败：{e}")
        return []


def fetch_academic_papers(
    query: str, languages: List[str] | None = None, limit: int = 5
) -> List[Dict]:
    """
    双语检索入口：
    - languages 包含 "en" 时：使用 Semantic Scholar + arXiv；
    - languages 包含 "zh" 时：使用 SerpApi Google Scholar（中文界面）；
    - 最后按标题去重。
    """
    query = (query or "").strip()
    if not query:
        return []

    if not languages:
        languages = ["en", "zh"]

    all_results: List[Dict] = []
    if "en" in languages:
        all_results.extend(fetch_papers(query, limit))
    if "zh" in languages:
        all_results.extend(fetch_chinese_papers(query, limit))

    # 按标题去重
    unique_map: Dict[str, Dict] = {}
    for p in all_results:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        if title not in unique_map:
            unique_map[title] = p
    return list(unique_map.values())


def fetch_papers_for_keywords(
    keywords: List[str], limit_per_keyword: int = 5, max_workers: int = 4
) -> List[Dict]:
    """
    对多个关键词并发检索文献，并汇总去重。

    - 每个关键词调用一次 fetch_papers（内部已包含降级与重试）；
    - 返回合并后的文献列表（按标题去重）。
    """
    keywords = [kw.strip() for kw in keywords if kw and kw.strip()]
    if not keywords:
        return []

    all_results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_kw = {
            executor.submit(fetch_papers, kw, limit_per_keyword): kw for kw in keywords
        }
        for future in as_completed(future_to_kw):
            kw = future_to_kw[future]
            try:
                papers = future.result() or []
                all_results.extend(papers)
            except Exception as exc:
                print(f"[警告] 关键词 {kw} 检索失败：{exc}")

    # 按标题去重
    unique_map: Dict[str, Dict] = {}
    for p in all_results:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        if title not in unique_map:
            unique_map[title] = p

    return list(unique_map.values())