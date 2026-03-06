import os
import json
from io import BytesIO

import streamlit as st
from dotenv import load_dotenv
from docx import Document

import researcher
import generator
from citation_utils import check_citations
from document_processor import AcademicBrain

load_dotenv()

st.set_page_config(page_title="AcademiSync Ultra", layout="wide")

st.title("🎓 全自动学术研究系统")

# 侧边栏：API Key 与参数
SEARCH_LANG_OPTIONS = [
    "中文 (SerpApi/百度学术替代)",
    "英文 (Semantic Scholar/arXiv)",
]

with st.sidebar:
    st.header("配置")
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

        # 2. 自动化多路搜索
        st.write("📡 正在全网检索相关文献（双引擎驱动）...")
        all_papers = []
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
        # 去重且保持顺序
        seen = set()
        search_keywords = []
        for k in keywords_to_try:
            k = (k or "").strip()
            if not k or k.lower() in seen:
                continue
            seen.add(k.lower())
            search_keywords.append(k)

        lang_codes = _resolve_lang_codes(search_lang)

        for kw in search_keywords:
            st.write(f"🔍 正在检索核心概念: {kw}...")
            try:
                results = researcher.fetch_academic_papers(
                    kw, languages=lang_codes, limit=num_papers
                )
            except Exception as e:
                st.warning(f"检索关键词 {kw} 时出现错误：{e}")
                results = []
            all_papers.extend(results or [])

        # 首轮无结果时用备用词再试一次
        if not all_papers and en_keywords:
            st.write("📡 首轮无结果，正在用备用检索词重试...")
            for alt in ["gut microbiota", "pulmonary fibrosis", "acute lung injury", "traditional Chinese medicine"]:
                if alt.lower() in seen:
                    continue
                st.write(f"🔍 备用检索: {alt}...")
                try:
                    results = researcher.fetch_papers(alt, limit=num_papers)
                    all_papers.extend(results or [])
                except Exception:
                    pass

        # 本地文献：PDF/Word 用 AcademicBrain 解析，txt/md 并入 all_papers
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
                label="❌ 所有数据库均未找到结果且无本地文献，请更换关键词或上传 PDF/Word。", state="error"
            )
            st.stop()

        if unique_papers:
            st.success(f"✅ 找到 {len(unique_papers)} 篇高度相关的参考资料！")
        if local_context:
            st.success("✅ 已加载本地文献精华，生成时将优先参考其实验数据、逻辑与术语。")

        context_data = ""
        ref_list = "### 📚 参考文献\n"
        if local_context:
            context_data = local_context + "\n\n【在线检索文献】\n"
        for i, p in enumerate(unique_papers, 1):
            context_data += (
                f"[{i}] 标题: {p.get('title', '')}, 摘要: {p.get('abstract', '无')}\n"
            )
            ref_list += (
                f"{i}. {p.get('title', '')}. ({p.get('year', 'N/A')}). "
                f"[链接]({p.get('url', '')})\n"
            )

        # 3. 规划与写作（支持断点续写）
        st.write("📋 正在生成或更新万字学术大纲...")
        outline = generator.generate_outline(research_title, context_data)

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
                    research_title, outline, dim, chapter_context, target_words
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