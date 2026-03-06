🛠️ AcademiSync 技术规格文档 (v2.0)

1. 项目简介

AcademiSync 是一款基于 Python 的自动化文献综述工具。它通过多源学术数据库（Semantic Scholar + arXiv + 本地文本）获取真实学术元数据，并利用 智谱 AI (GLM-4 / GLM-4-Flash) 进行智能汇总，旨在解决以下问题：

- AI 幻觉（编造参考文献）；
- 中文课题下英文文献难以精确检索；
- 长篇综述生成中途超时/中断导致的重复扣费与时间浪费。

2. 技术栈 (Tech Stack)

- 前端框架: Streamlit (用于快速构建交互式 Web 界面)。
- 大语言模型: 智谱 AI (ZhipuAI SDK / GLM-4 / GLM-4-Flash 模型)。
- 文献数据源:
  - Semantic Scholar API（可选官方 Key，支持更高频率）；
  - arXiv API（备用英文文献源，XML + feedparser 解析）；
  - 本地文本文件（txt/md，作为中文 / 自备文献源）。
- 环境管理: python-dotenv (处理 .env 配置文件)。
- HTTP 请求: requests (用于学术数据库 API 调用)。
- 文档导出: python-docx (导出 Word 文档)。

3. 核心架构设计 (System Architecture)

模块化分层：

- UI 层：`app.py`
  - 负责标题输入、参数配置、按钮交互、进度状态与结果展示。
- 检索层：`researcher.py`
  - 语义关键词驱动的多源文献检索（Semantic Scholar + arXiv + local）。
  - 并发与重试控制、代理配置与降级策略。
- 生成层：`generator.py`
  - 标题解析 / 关键词抽取；
  - 大纲生成 / 分章节写作；
  - 全文润色与审稿。
- 工具层：`citation_utils.py`
  - 引用编号与参考文献列表的一致性检查。

4. 关键数据流 (Data Flow, v2.0)

4.1 标题驱动的全文流水线（Ultra 模式）

1. 用户输入：用户在 `app.py` 中输入综述标题（多为中文长标题）。
2. 标题解析：`generator.analyze_research_title`：
   - 去除功能词；
   - 输出 3 个英文关键词（`en_keywords`）与推荐章节维度（`dimensions`）。
3. 多源检索：
   - 对每个英文关键词调用 `researcher.fetch_papers(kw, limit)`：
     - 优先访问 Semantic Scholar，命中 429 / 空结果时自动切换到 `fetch_from_arxiv`；
     - 合并本地上传的 txt/md 文献条目；
     - 按标题去重，形成统一的 `unique_papers` 列表。
4. 上下文构造：
   - 将 `unique_papers` 转为 `context_data` 字符串（包含编号、标题、摘要）。
   - 同时构造 Markdown 参考文献列表 `ref_list`。
5. 大纲生成：
   - `generator.generate_outline(title, context_data)` 基于文献线索与维度建议生成 8000 字级大纲（至三级标题）。
6. 分章节生成与断点续写：
   - 章节列表来源于 `analysis.dimensions` 或默认列表；
   - 每个维度调用 `generator.generate_chapter` 生成约 1500 字正文：
     - 内部 Prompt 要求引用编号与参考文献列表对齐；
   - 生成进度持久化至 `draft_state.json`（标题 / 大纲 / 维度 / 各章节文本）和 `temp_draft.md`（纯文本草稿）。
7. 全文审稿：
   - `generator.polish_review(full_draft)` 对整篇综述进行语法与衔接润色。
8. 引用校验与导出：
   - `citation_utils.check_citations(final_text, ref_count)` 检查正文引用编号合法性；
   - 前端展示引用校验报告，用户可据此人工修订；
   - 最终结果可一键导出为 Word (`Review.docx`)。

4.2 传统模式（V1 向下兼容）

- 简化路径：话题输入 → `researcher.fetch_papers` → `build_context_from_papers` → `generator.generate_review`。
- 目前仍保留，但推荐在 v2.0 中使用 Ultra 模式进行长文写作。

5. 核心接口与函数规范（v2.0）

5.1 `researcher.py`

- `fetch_papers(query: str, limit: int) -> List[Dict]`
  - 描述：主引擎检索，优先 Semantic Scholar，失败或空结果时降级到 arXiv。
  - 输入：
    - `query`: 英文检索关键词；
    - `limit`: 期望返回篇数。
  - 输出：列表元素形如 `{'title': str, 'abstract': str, 'url': str, 'year': str, 'source': str}`。
- `fetch_from_arxiv(query: str, limit: int) -> List[Dict]`
  - 描述：备份引擎，直接访问 arXiv API 并解析 XML。
- `build_context_from_papers(papers: List[Dict], max_papers: int, max_chars: int) -> Tuple[str, List[Dict]]`
  - 描述：将文献列表转换为 LLM 上下文字符串与元数据列表。
- `fetch_papers_for_keywords(keywords: List[str], limit_per_keyword: int, max_workers: int) -> List[Dict]`
  - 描述：对多个关键词并发检索，并汇总去重。
- 代理配置：
  - `_get_scholar_proxies()` 读取 `HTTP_PROXY_FOR_SCHOLAR` / `HTTPS_PROXY_FOR_SCHOLAR`；
  - `_request_with_retry(...)` 对 Semantic Scholar 请求增加指数退避重试。

5.2 `generator.py`

- `get_client() -> ZhipuAI`
  - 描述：从 `ZHIPUAI_API_KEY` 创建智谱客户端，并确保不使用全局 HTTP 代理（清理 `HTTP_PROXY` / `HTTPS_PROXY`，设置 `NO_PROXY`）。
- `analyze_research_title(title: str) -> dict`
  - 描述：解析中文/英文标题，去除功能词，抽取标准英文关键词和研究维度。
  - 约定返回 JSON：
    - `{"en_keywords": [...], "dimensions": [...]}`。
- `generate_outline(title: str, paper_data: str) -> str`
  - 描述：基于文献上下文与维度提示生成 Markdown 大纲。
- `generate_chapter(title: str, outline: str, chapter_title: str, paper_data: str) -> str`
  - 描述：为单个章节生成约 1500 字的正文，并在 Prompt 中明确引用要求。
- `polish_review(full_text: str) -> str`
  - 描述：对整篇综述做审稿级润色。
- `generate_review(topic: str, paper_data: str) -> str`
  - 描述：兼容旧接口的“一步到位”综述生成，内部通过大纲 + 综合章节 + 审稿实现。

5.3 `citation_utils.py`

- `check_citations(text: str, ref_count: int) -> dict`
  - 描述：解析正文中的 `[n]` 或 `[Source_ID: n]` 标记，检查与参考文献数量是否一致。
  - 返回：
    - `used_ids`: 正文中出现过的编号；
    - `invalid_ids`: 超出 `[1, ref_count]` 范围的编号；
    - `unreferenced_ids`: 参考文献中从未被正文引用的编号。

6. 安全与配置 (Security & Config)

- API Key 管理：
  - 智谱：`ZHIPUAI_API_KEY` 存放在 `.env` 或系统环境变量中；
  - Semantic Scholar 官方 Key（可选）：`SEMANTIC_SCHOLAR_API_KEY`，通过 HTTP 头 `x-api-key` 传递。
- 代理配置：
  - 学术检索专用：
    - `HTTP_PROXY_FOR_SCHOLAR`
    - `HTTPS_PROXY_FOR_SCHOLAR`
  - 智谱调用默认直连（通过 `get_client` 清理常见代理变量，增加 `NO_PROXY`）。
- 超时与重试：
  - 所有外部 HTTP 调用设置 `timeout=10`；
  - 对 Semantic Scholar 请求引入指数退避重试，减轻临时网络抖动影响。

7. 未来扩展 (Roadmap)

- V2.x：
  - 接入 RAG：对本地 PDF/中文文本进行向量化，与在线文献一起参与检索与上下文构造；
  - 完善引用格式（APA / MLA / BibTeX）与导出模板；
  - 提供更多可视化分析（文献年份分布、主题聚类等）。
