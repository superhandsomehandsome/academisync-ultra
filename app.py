import os

import streamlit as st
from dotenv import load_dotenv

# 1. 优先从 Streamlit Secrets 读取（Streamlit Cloud 云端环境）
# 2. 否则加载本地 .env（本地开发环境）
try:
    if "SERPAPI_KEY" in st.secrets:
        os.environ["SERPAPI_KEY"] = st.secrets["SERPAPI_KEY"]
        if "ZHIPUAI_API_KEY" in st.secrets:
            os.environ["ZHIPUAI_API_KEY"] = st.secrets["ZHIPUAI_API_KEY"]
except Exception:
    pass
if not os.getenv("SERPAPI_KEY"):
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(dotenv_path=_env_path, override=True)

import json
from pathlib import Path
from io import BytesIO

from docx import Document

_path_obj = Path(__file__).resolve().parent / ".env"


def _ensure_env_loaded():
    """若 dotenv 未生效，直接读取 .env 并写入 os.environ（兼容 Streamlit 多进程）"""
    if os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY"):
        return
    if not _path_obj.exists():
        return
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            for line in _path_obj.read_text(encoding=enc).splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip().strip('"').strip("'")
                    if key and val:
                        os.environ[key] = val
            break
        except Exception:
            continue


_ensure_env_loaded()

import researcher
import generator
from citation_utils import check_citations
from document_processor import AcademicBrain

st.set_page_config(page_title="AcademiSync Ultra", layout="wide")

if not os.getenv("SERPAPI_KEY"):
    st.error("⚠️ 未检测到 SerpApi 密钥，请在后台配置 Secrets 或本地 .env 文件")

st.title("🎓 全自动学术研究系统")

# 侧边栏：API Key 与参数
SEARCH_LANG_OPTIONS = [
    "中文 (SerpApi/百度学术替代)",
    "英文 (Semantic Scholar/arXiv)",
]

with st.sidebar:
    _ensure_env_loaded()
    st.header("配置")
    serp_ready = bool(os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY"))
    st.caption(f"SerpApi: {'✅ 已配置' if serp_ready else '❌ 未配置'}")
    default_key = os.getenv("ZHIPUAI_API_KEY", "")
    api_key = st.text_input("智谱 API Key", value=default_key, type="password")
    num_papers = st.slider("每个关键词检索篇数", 3, 20, 5)
    uploaded_files = st.file_uploader(
        "上传参考文献（最多10篇，PDF/Word 优先用于实验数据与术语）",
        type=["pdf", "docx", "txt", "md"],
        accept_multiple_files=True,
    )
    st.header("🔍 搜索配置")
    search_lang = st.multiselect(
        "检索语言选择",
        SEARCH_LANG_OPTIONS,
        default=SEARCH_LANG_OPTIONS,
    )
    show_debug = st.checkbox("显示调试信息", value=False)
    gen_abstract = st.checkbox("生成摘要（置于文首，对齐范例综述）", value=True)
    st.caption("目标篇幅：5000～8000 字综述")


research_title = st.text_input(
    "请输入综述标题（AI将自动理解并搜寻文献）：",
    placeholder="例如：中药干预糖尿病肾病的效果及分子机制研究进展",
)

DRAFT_STATE_FILE = "draft_state.json"


def load_draft_state() -> dict:
    if os.path.exists(DRAFT_STATE_FILE):
        try:
            with open(DRAFT_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_draft_state(state: dict) -> None:
    try:
        with open(DRAFT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


if "chapters" not in st.session_state:
    st.session_state.chapters = {}


def _resolve_lang_codes(selection):
    langs: list[str] = []
    if "中文 (SerpApi/百度学术替代)" in selection:
        langs.append("zh")
    if "英文 (Semantic Scholar/arXiv)" in selection:
        langs.append("en")
    if not langs:
        # 默认至少保留英文检索，避免完全无结果
        langs = ["en"]
    return langs


if st.button("🚀 启动全链路写作", type="primary"):
    _ensure_env_loaded()  # 确保 .env 在 Streamlit 多进程下也能被正确加载
    if not research_title:
        st.error("请输入标题")
        st.stop()

    if api_key:
        os.environ["ZHIPUAI_API_KEY"] = api_key

    with st.status("🛠️ 正在执行学术工作流...", expanded=True) as status:
        # 1. 语义解析
        st.write("🧠 正在深度解析课题语义...")
        analysis = generator.analyze_research_title(research_title)
        en_keywords = analysis.get("en_keywords", [])

        if not en_keywords:
            en_keywords = [research_title]

        # 2. 自动化多路搜索（强制中英双轨，中文优先）
        st.write("🔍 正在启动中英双轨强力检索...")
        # 检索用词备用映射（提高 Semantic Scholar/arXiv 命中率）
        _search_aliases = {
            "chinese herbal medicine": "traditional Chinese medicine",
            "intestinal microbiota": "gut microbiota",
            "intestinal flora": "gut microbiota",
        }
        def _expand_keyword(k: str):
            k_lower = (k or "").strip().lower()
            if k_lower in _search_aliases:
                return [k, _search_aliases[k_lower]]
            return [k]
        keywords_to_try = []
        for kw in en_keywords:
            keywords_to_try.extend(_expand_keyword(kw))
        seen_kw = set()
        search_keywords = []
        for k in keywords_to_try:
            k = (k or "").strip()
            if not k or k.lower() in seen_kw:
                continue
            seen_kw.add(k.lower())
            search_keywords.append(k)

        # 调用 researcher.fetch_all_papers（第一要务：中文文献）
        all_papers = researcher.fetch_all_papers(
            research_title.strip(),
            en_keywords=search_keywords,
            limit=num_papers,
        )

        # 兜底：若无中文文献，多轮重试不同检索变体（中文为第一要务）
        chinese_papers = [p for p in all_papers if p.get("is_chinese")]
        if not chinese_papers:
            st.write("⚠️ 首轮无中文文献，正在多轮破冰重试...")
            for q_try in [
                research_title.strip(),
                research_title.replace("研究", "").replace("探讨", "").strip()[:15],
                research_title[:10],
            ]:
                if not q_try.strip():
                    continue
                extra = researcher.fetch_chinese_papers(q_try, limit=8)
                for p in extra:
                    if p.get("title") and not any(x.get("title") == p.get("title") for x in all_papers):
                        p["is_chinese"] = True
                        all_papers.append(p)
                if any(p.get("is_chinese") for p in all_papers):
                    st.success(f"✅ 备用检索成功，获得 {len(extra)} 篇中文文献")
                    break

        if not any(p.get("is_chinese") for p in all_papers) and all_papers:
            st.warning("⚠️ 当前仅检索到英文文献，未找到中文文献。建议：1) 检查 SERPAPI_KEY；2) 使用更具体的中文关键词；3) 上传中文 PDF/Word 作为补充。")

        # 终极兜底：若 SerpApi 全失败导致 0 条，尝试 Semantic Scholar/arXiv（无需 SerpApi）
        if not all_papers:
            st.write("⚠️ SerpApi 未返回结果，尝试 Semantic Scholar + arXiv...")
            try:
                for kw in search_keywords[:3]:
                    en_res = researcher.fetch_papers(kw, limit=5)
                    for p in en_res or []:
                        if p.get("title") and not any(x.get("title") == p.get("title") for x in all_papers):
                            p["is_chinese"] = False
                            all_papers.append(p)
            except Exception as e:
                if show_debug:
                    st.warning(f"英文兜底失败: {e}")

        st.session_state.all_results = all_papers
        local_context = ""
        if uploaded_files:
            pdf_docx = [f for f in uploaded_files if (f.name or "").lower().endswith((".pdf", ".docx"))]
            txt_md = [f for f in uploaded_files if (f.name or "").lower().endswith((".txt", ".md"))]
            if pdf_docx:
                st.write("📂 正在解析本地 PDF/Word 文献（实验数据、逻辑架构、专业术语）...")
                brain = AcademicBrain()
                load_status = brain.load_from_uploaded_files(pdf_docx, max_files=10)
                st.success(load_status)
                local_context = brain.get_context_for_ai()
            if txt_md:
                st.write("📂 正在合并本地上传的 txt/md 文献...")
                for f in txt_md:
                    try:
                        content = f.read().decode("utf-8", errors="ignore")
                    finally:
                        f.seek(0)
                    all_papers.append(
                        {
                            "title": f.name,
                            "abstract": content[:3000],
                            "url": "",
                            "year": "N/A",
                            "source": "local",
                        }
                    )

        # 文献去重与格式化
        unique_map = {}
        for p in all_papers:
            title = (p.get("title") or "").strip()
            if not title:
                continue
            if title not in unique_map:
                unique_map[title] = p
        unique_papers = list(unique_map.values())

        if not unique_papers and not local_context:
            status.update(
                label="❌ 未检索到任何文献（含中文）。",
                state="error",
            )
            st.error("未检索到任何文献（含中文）。")
            with st.expander("🔧 故障排查", expanded=True):
                serp_ok = bool(os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY"))
                st.write(f"**SERPAPI_KEY**: {'✅ 已配置' if serp_ok else '❌ 未配置'}")
                st.write("**建议**：")
                st.write("1. 确认 `.env` 中存在 `SERPAPI_KEY=你的密钥`（可在 [serpapi.com](https://serpapi.com) 获取）")
                st.write("2. 使用更具体的中文关键词，如「中药 肠道菌群 肺损伤」")
                st.write("3. 上传 PDF/Word 文献，系统将直接解析作为参考")
            st.stop()

        if unique_papers:
            zh_n = sum(1 for p in unique_papers if p.get("is_chinese"))
            en_n = len(unique_papers) - zh_n
            detail = f"（中文 {zh_n} 篇，英文 {en_n} 篇）" if zh_n and en_n else ""
            st.success(f"✅ 找到 {len(unique_papers)} 篇高度相关的参考资料！{detail}")
        if local_context:
            st.success("✅ 已加载本地文献精华，生成时将优先参考其实验数据、逻辑与术语。")

        # 在 UI 中展示可点击的中英文文献溯源表
        if unique_papers:
            with st.expander("📚 参考文献溯源列表 (点击标题跳转)", expanded=True):
                for i, p in enumerate(unique_papers, 1):
                    st.markdown(f"**[{i}] [{p.get('title', '无标题')}]({p.get('url', '#')})**")
                    lang_tag = "【中文】" if p.get("is_chinese") else "【英文】"
                    st.caption(f"{lang_tag} 来源: {p.get('source', '未知')} | 年份: {p.get('year', 'N/A')}")
                    with st.expander("查看摘要预览"):
                        st.write(p.get("abstract", "暂无摘要"))
                    st.divider()

        context_data = ""
        ref_list = "## 参考文献与溯源\n\n"
        if local_context:
            context_data = local_context + "\n\n【在线检索文献】\n"
        for i, p in enumerate(unique_papers, 1):
            title = (p.get("title") or "").strip()
            abstract = p.get("abstract", "无")
            url = (p.get("url") or "").strip()
            year = str(p.get("year", "N/A"))
            source = p.get("source", "") or "在线文献"

            context_data += f"[{i}] 标题: {title}, 摘要: {abstract}\n"

            # 文末溯源表：仅在文末统一列出可点击链接，正文中不直接出现 URL
            source_label = "本地文献" if source == "local" else source
            if url:
                ref_list += f"[{i}] [{title}]({url}) - {source_label} ({year})\n"
            else:
                ref_list += f"[{i}] {title} - {source_label} ({year})\n"

        # 构建文献元数据供权威引用 prompt 使用（含 index、is_chinese）
        papers_metadata = [
            {
                "index": i,
                "title": p.get("title", ""),
                "url": p.get("url", "") or "",
                "abstract": p.get("abstract", "") or "",
                "is_chinese": p.get("is_chinese", False),
            }
            for i, p in enumerate(unique_papers, 1)
        ]

        # 3. 规划与写作（支持断点续写）
        st.write("📋 正在生成或更新万字学术大纲...")
        outline = generator.generate_outline(research_title, context_data, papers_metadata)

        # 加载历史章节进度
        draft_state = load_draft_state()
        if draft_state.get("title") != research_title:
            draft_state = {
                "title": research_title,
                "outline": outline,
                "dimensions": analysis.get(
                    "dimensions", ["引言", "核心技术", "挑战与展望"]
                ),
                "chapters": {},
            }

        dimensions = draft_state.get(
            "dimensions", analysis.get("dimensions", ["引言", "核心技术", "挑战与展望"])
        )
        chapters = draft_state.get("chapters", {})

        full_draft = f"# {research_title}\n\n{outline}\n\n"
        target_words = 1500  # 每章目标字数，用于深度撰写

        for dim in dimensions:
            if dim in chapters:
                st.write(f"⏩ 已存在章节，跳过重新生成：{dim}")
                chapter_text = chapters[dim]
            else:
                st.write(f"✍️ 正在深度挖掘章节内容：{dim}...")
                # 二次检索：针对本章节再搜 3 篇针对性文献
                try:
                    specific_papers = researcher.fetch_papers(
                        f"{research_title} {dim}", limit=3
                    )
                except Exception:
                    specific_papers = []
                chapter_extra = ""
                if specific_papers:
                    chapter_extra = "\n\n🎯 本章专属文献：\n" + "\n".join(
                        f"- {p.get('title', '')}: {str(p.get('abstract', ''))[:500]}"
                        for p in specific_papers
                    )
                chapter_context = context_data + chapter_extra
                chapter_text = generator.generate_chapter_deep(
                    research_title, outline, dim, chapter_context, target_words,
                    papers_metadata=papers_metadata,
                )
                chapters[dim] = chapter_text
                draft_state["chapters"] = chapters
                save_draft_state(draft_state)

            full_draft += f"## {dim}\n\n{chapter_text}\n\n"

        # 总结与展望：3 个瓶颈 + 3 个未来方向（模仿桂皮醛等文结尾）
        st.write("📝 正在生成总结与展望...")
        conclusion = generator.generate_conclusion_and_future(
            research_title, full_draft
        )
        full_draft += "\n\n## 总结与展望\n\n" + conclusion + "\n\n"

        # 可选：生成结构化摘要并置于文首
        if gen_abstract:
            st.write("📄 正在生成摘要...")
            try:
                abstract = generator.generate_abstract(
                    research_title, outline, context_data[:2000]
                )
                parts = full_draft.split("\n", 2)
                if len(parts) >= 3:
                    full_draft = (
                        f"{parts[0]}\n\n## 摘要\n\n{abstract}\n\n---\n\n{parts[2]}"
                    )
                else:
                    full_draft = f"# {research_title}\n\n## 摘要\n\n{abstract}\n\n---\n\n{full_draft}"
            except Exception:
                pass

        # 将最新草稿保存到本地，便于手动查看
        try:
            with open("temp_draft.md", "w", encoding="utf-8") as f:
                f.write(full_draft)
        except Exception:
            pass

        # 4. 审稿润色
        st.write("✨ 正在进行 AI 专家级润色...")
        polished_text = generator.polish_review(full_draft)
        final_text = polished_text + "\n\n---\n" + ref_list

        status.update(label="✅ 生成成功！", state="complete")

    # 结果展示
    st.markdown(final_text)

    # 引用对齐检查
    citation_report = check_citations(final_text, ref_count=len(unique_papers))

    # 下载 Word
    doc = Document()
    for line in final_text.split("\n"):
        doc.add_paragraph(line)
    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)
    st.download_button(
        "📥 下载完整综述 (Word)",
        data=bio.getvalue(),
        file_name="Review.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    if show_debug:
        with st.expander("调试信息（标题分析、原始文献与引用校验）", expanded=False):
            st.write("标题分析结果：", analysis)
            st.write("文献条目数：", len(unique_papers))
            st.write("引用校验报告：", citation_report)