import os
from pathlib import Path

from dotenv import load_dotenv

# 最顶端强制加载 .env（必须在其他 import 之前）
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)

import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple

import requests
import feedparser
from serpapi import GoogleSearch


def _fallback_read_env() -> None:
    """当 os.getenv('SERPAPI_KEY') 为 None 时的后备函数：直接读取 .env 文件内容。"""
    if not _ENV_PATH.exists():
        return
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le"):
        try:
            with open(_ENV_PATH, "r", encoding=enc) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, _, value = line.partition("=")
                        key, value = key.strip(), value.strip().replace('"', "").replace("'", "")
                        if key and value:
                            os.environ[key] = value
            break
        except (UnicodeDecodeError, UnicodeError):
            continue


# 优先加载 .env，若 SERPAPI_KEY 仍为空则执行后备读取
if _ENV_PATH.exists():
    _fallback_read_env()
if not os.getenv("SERPAPI_KEY") and not os.getenv("SERPAPI_API_KEY"):
    _fallback_read_env()
print(f"诊断：SERPAPI_KEY -> {'已识别' if os.getenv('SERPAPI_KEY') else '未识别'}")


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
    中文文献引擎：通过 SerpApi 调用 Google Scholar（中文界面），
    尽可能保留指向 CNKI/万方/维普 等平台的原始跳转链接。

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

    # 预处理：删除“的研究”“讨论”等虚词，仅保留前 3 个核心关键词
    _fillers = ("的研究", "的讨论", "探讨", "研究进展", "研究现状", "讨论")
    q = query
    for w in _fillers:
        q = q.replace(w, "")
    q = q.strip()
    parts = q.split()
    if len(parts) > 3:
        short_query = " ".join(parts[:3])
    elif len(parts) == 1 and len(q) > 8:
        segs = re.split(r"[通过与之及]", q)
        segs = [s.strip() for s in segs if len(s.strip()) >= 2][:3]
        short_query = " ".join(segs) if segs else q[:10]
    else:
        short_query = q[:12] if len(q) > 12 else q

    params = {
        "engine": "google_scholar",
        "q": short_query,
        "hl": "zh-CN",   # 强制锁定中文
        "gl": "cn",      # 强制锁定中国区
        "as_sdt": "0,5",     # 搜索所有文章
        "num": max(1, limit),
        "api_key": api_key,
    }

    try:
        print(f"[检索] 通过 SerpApi (Google Scholar 中文) 检索: {query} ...")
        search = GoogleSearch(params)
        data = search.get_dict() or {}
        clean_results: List[Dict] = []

        for item in data.get("organic_results", [])[:limit]:
            title = (item.get("title") or "").strip()
            if not title:
                continue

            # 主跳转链接：通常指向 CNKI / 万方 / 维普 / 期刊官网
            main_link = (item.get("link") or "").strip()

            pub_info = (item.get("publication_info") or {}) or {}
            summary = (pub_info.get("summary") or "").strip()
            outline = (pub_info.get("outline") or "").strip()

            # 尽量从 publication_info 中抽取“来源”和“年份”
            source = outline or pub_info.get("publisher", "") or "学术资源"
            year = str(pub_info.get("year") or "").strip() or "N/A"
            if year == "N/A" and summary:
                m = re.search(r"(19|20)\d{2}", summary)
                if m:
                    year = m.group(0)

            snippet = (item.get("snippet") or "").replace("\n", " ").strip()

            clean_item: Dict[str, Dict | str] = {
                "title": title,
                "abstract": snippet or summary,
                "url": main_link,  # 对应 SerpApi 的 link 字段，用于溯源
                "year": year or "N/A",
                "source": source or "SerpApi-CN",
                "engine": "SerpApi-CN",
                "is_chinese": True,
            }

            # 如果有直接 PDF 下载链接，也记录下来（备用，不影响现有逻辑）
            resources = item.get("resources") or []
            if resources and isinstance(resources, list):
                pdf_link = (resources[0].get("link") or "").strip()
                if pdf_link:
                    clean_item["pdf_link"] = pdf_link

            clean_results.append(clean_item)

        return clean_results
    except Exception as e:
        print(f"[警告] 中文引擎（SerpApi Google Scholar）调用失败：{e}")
        return []


def _parse_serpapi_result(item: dict) -> dict | None:
    """解析 SerpApi organic_results 单条，返回统一格式。"""
    title = (item.get("title") or "").strip()
    if not title:
        return None
    main_link = (item.get("link") or "").strip()
    pub_info = (item.get("publication_info") or {}) or {}
    summary = (pub_info.get("summary") or "").strip()
    outline = (pub_info.get("outline") or "").strip()
    source = outline or pub_info.get("publisher", "") or "学术资源"
    year = str(pub_info.get("year") or "").strip() or "N/A"
    if year == "N/A" and summary:
        m = re.search(r"(19|20)\d{2}", summary)
        if m:
            year = m.group(0)
    snippet = (item.get("snippet") or "").replace("\n", " ").strip()
    return {
        "title": title,
        "abstract": snippet or summary,
        "url": main_link,
        "year": year or "N/A",
        "source": source or "SerpApi",
    }


def fetch_all_papers(topic_chinese: str, en_keywords: List[str] | None = None, limit: int = 10) -> List[Dict]:
    """
    第一要务：检索中文文献。多级回退直至拿到中文，绝不让英文掩盖中文。
    """
    api_key = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY")
    final_list = []
    seen = set()

    # 精简中文检索词（多级备用）
    zh_full = (topic_chinese or "").strip()
    zh_q = zh_full.replace("研究", "").replace("探讨", "").replace("讨论", "")[:15].strip() or zh_full[:12]
    zh_short = zh_q[:8] if len(zh_q) > 8 else zh_q  # 更短变体，提高命中率

    def _add_chinese(item: dict) -> None:
        title = item.get("title")
        if title and title not in seen:
            seen.add(title)
            final_list.append({
                "title": title,
                "url": item.get("link") or item.get("url", ""),
                "source": item.get("source", "中国学术库"),
                "year": (item.get("publication_info") or {}).get("year") or "2025",
                "abstract": item.get("snippet", item.get("abstract", "")) or "",
                "is_chinese": True,
            })

    if api_key:
        # --- 第1级：site: 强制定向知网/万方 ---
        try:
            zh_params = {
                "engine": "google_scholar",
                "q": f"{zh_q} site:cnki.net OR site:wanfangdata.com.cn",
                "hl": "zh-CN", "gl": "cn", "num": 8, "api_key": api_key
            }
            res = GoogleSearch(zh_params).get_dict().get("organic_results", [])
            for item in res or []:
                item["source"] = "中国学术库 (CNKI/万方)"
                _add_chinese(item)
            print(f"DEBUG: 中文第1级 site:cnki -> {len([p for p in final_list if p.get('is_chinese')])} 条")
        except Exception as e:
            print(f"DEBUG: 中文第1级故障: {e}")

        # --- 第2级：若仍无中文，启用百度学术（全是中文）---
        if not any(p.get("is_chinese") for p in final_list):
            try:
                baidu_params = {"engine": "baidu_scholar", "q": zh_q, "api_key": api_key}
                data = GoogleSearch(baidu_params).get_dict() or {}
                raw = data.get("organic_results", data.get("academic_results", []))
                for item in raw or []:
                    item["source"] = "百度学术"
                    _add_chinese(item)
                print(f"DEBUG: 中文第2级 百度学术 -> {len([p for p in final_list if p.get('is_chinese')])} 条")
            except Exception as e:
                print(f"DEBUG: 中文第2级故障: {e}")

        # --- 第3级：纯中文 q（去掉 site:，更宽松）---
        if not any(p.get("is_chinese") for p in final_list):
            try:
                params = {
                    "engine": "google_scholar",
                    "q": zh_q, "hl": "zh-CN", "gl": "cn", "num": 8, "api_key": api_key
                }
                res = GoogleSearch(params).get_dict().get("organic_results", [])
                for item in res or []:
                    item["source"] = "SerpApi-中文"
                    _add_chinese(item)
                print(f"DEBUG: 中文第3级 纯中文q -> {len([p for p in final_list if p.get('is_chinese')])} 条")
            except Exception as e:
                print(f"DEBUG: 中文第3级故障: {e}")

        # --- 第4级：fetch_chinese_papers（内部有精简逻辑）---
        if not any(p.get("is_chinese") for p in final_list):
            for q_try in [zh_full, zh_q, zh_short]:
                extra = fetch_chinese_papers(q_try, limit=8)
                for p in extra:
                    if p.get("title") and p["title"] not in seen:
                        seen.add(p["title"])
                        final_list.append({**p, "is_chinese": True})
                if any(p.get("is_chinese") for p in final_list):
                    print(f"DEBUG: 中文第4级 fetch_chinese_papers 成功")
                    break

    # --- 英文文献：SerpApi Google Scholar（优先）+ Semantic Scholar/arXiv 补充 ---
    en_quota = max(5, limit // 2)  # 至少 5 篇英文
    en_to_fetch = min(8, en_quota)  # 最多 8 篇

    if en_to_fetch > 0 and api_key:
        # 1. SerpApi Google Scholar 英文检索（与中文并列，确保有英文）
        en_q = " ".join((en_keywords or [])[:3]) if en_keywords else "Traditional Chinese Medicine gut microbiota lung injury"
        try:
            en_params = {
                "engine": "google_scholar",
                "q": en_q,
                "hl": "en",
                "gl": "us",
                "num": min(8, en_to_fetch),
                "api_key": api_key,
            }
            en_res = GoogleSearch(en_params).get_dict().get("organic_results", [])
            for item in en_res or []:
                title = item.get("title")
                if title and title not in seen:
                    seen.add(title)
                    final_list.append({
                        "title": title,
                        "url": item.get("link", ""),
                        "source": "Google Scholar (International)",
                        "year": (item.get("publication_info") or {}).get("year") or "N/A",
                        "abstract": item.get("snippet", ""),
                        "is_chinese": False,
                    })
            print(f"DEBUG: 英文 SerpApi -> {len([p for p in final_list if not p.get('is_chinese')])} 条")
        except Exception as e:
            print(f"DEBUG: 英文 SerpApi 故障: {e}")

    # 2. 若英文仍不足，用 Semantic Scholar + arXiv 补充
    en_count = sum(1 for p in final_list if not p.get("is_chinese"))
    if en_count < en_quota:
        try:
            en_q = " ".join((en_keywords or [])[:3]) if en_keywords else "Traditional Chinese Medicine gut microbiota lung injury"
            extra = fetch_papers(en_q, limit=min(5, en_quota - en_count))
            for p in extra:
                if p.get("title") and p["title"] not in seen:
                    seen.add(p["title"])
                    final_list.append({**dict(p), "is_chinese": False})
        except Exception:
            pass

    return final_list


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