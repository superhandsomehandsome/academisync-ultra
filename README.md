# AcademiSync 文献综述助手

AcademiSync 是一个基于 **Semantic Scholar** 与 **智谱 GLM-4** 的文献综述原型工具，目标是：

- 从 Semantic Scholar 抓取真实学术文献元数据；
- 将文献标题、摘要等信息拼接成结构化上下文；
- 调用智谱 GLM-4 生成结构化的 Markdown 学术综述；
- 尽量避免“凭空编造参考文献”的幻觉。

当前版本实现了从 0-1 的最小可用原型，聚焦在线文献检索与综述生成。

## 功能特性（V1 基础能力）

- **文献检索**：基于 Semantic Scholar 的公开接口，按话题关键词检索真实论文。
- **上下文构造**：将多篇文献整理为统一格式的上下文字符串，包含编号、标题、摘要与链接。
- **综述生成**：封装智谱 GLM-4 调用，按固定结构输出 Markdown 学术综述。
- **可视化前端**：使用 Streamlit 构建单页应用，包含侧边栏配置、主流程按钮、结果与文献列表 Tab。

## 环境要求

- Python 版本：推荐 **3.10+**（在 Windows 10/11 上测试通过）。
- 网络：需要能够访问 `api.semanticscholar.org` 与 `api.zhipu.ai`。

## 安装与运行

1. 克隆 / 下载本项目代码到本地。
2. 在项目根目录创建虚拟环境（推荐）：

   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows PowerShell
   ```

3. 安装依赖：

   ```bash
   python -m pip install -r requirements.txt
   ```

4. 配置环境变量：

   - 复制 `.env.example` 为 `.env`：

     ```bash
     copy .env.example .env  # Windows
     ```

   - 将其中的 `ZHIPUAI_API_KEY` 替换为你在智谱官网申请的 Key。
   - 如果你更习惯直接在系统环境变量中配置，也可以设置 `ZHIPUAI_API_KEY`，应用会自动读取。
   - **重要**：不要将 `.env` 文件提交到 Git（本项目已用 `.gitignore` 排除，防止 API Key 泄露）。

5. 启动应用：

   ```bash
   python -m streamlit run app.py
   ```

   浏览器中打开 `http://localhost:8501` 即可访问 AcademiSync。

## 使用流程（V1 基本模式）

1. 在侧边栏：
   - 填写 **智谱 API Key**（如果 `.env` 已配置会自动带入）；
   - 调整“检索文献篇数”；
   - 可选勾选“显示调试信息”。
2. 在主区域输入研究话题（建议使用英文或中英文结合的技术关键词）。
3. 点击“开始生成”：
   - 应用会首先调用 `researcher.fetch_papers` 从 Semantic Scholar 获取文献；
   - 使用 `build_context_from_papers` 拼接上下文；
   - 调用 `generator.generate_review` 生成 Markdown 综述；
   - 通过 Tab 展示“综述正文 / 文献列表 / 调试信息”。

## 模块说明（V1 架构）

- `app.py`：Streamlit 前端与整体用户流程入口。
- `researcher.py`：
  - `fetch_papers(query, limit)`：从 Semantic Scholar 抓取文献元数据；
  - `build_context_from_papers(papers, ...)`：将文献信息拼成传入 LLM 的上下文字符串与元数据列表。
- `generator.py`：
  - `_get_api_key()`：从环境或 `.env` 中读取智谱 Key；
  - `_build_prompt(topic, paper_context)`：构造严格限制“只根据提供文献撰写”的 Prompt；
  - `generate_review(topic, paper_context)`：封装 GLM-4 调用并返回 Markdown 综述。
- `reftrace/jishu.md`：技术规格与数据流说明。
- `reftrace/chanpin.md`：产品定义与目标用户描述（已补充当前实现状态）。
- `reftrace/ui.md`：交互与 UI 草图说明。

## 与 Roadmap 的对齐

结合 `reftrace/jishu.md` 中的 Roadmap，本仓库当前实现进度大致如下：

- **V1.0（当前）**：
  - ✅ 在线文献检索（Semantic Scholar）；
  - ✅ 上下文构造与 LLM 调用；
  - ✅ Streamlit 单页应用与基础交互；
  - ✅ 基本错误提示与调试信息。
- **V1.1（计划）**：
  - 引入 `python-docx`，在生成综述后增加“一键导出 Word”按钮；
  - UI 中为导出功能预留入口（当前版本尚未实现，只在依赖中预留）。
- **V1.2（计划）**：
  - 在文献元数据基础上支持 APA/MLA/BibTeX 等引用格式切换；
  - 在“文献列表”或单独 Tab 中按所选格式展示引用条目。
- **V1.3（计划）**：
  - 支持本地 PDF 上传与解析，将本地文献与在线文献合并进入上下文；
  - 允许用户选择“仅本地 / 仅在线 / 混合模式”。

## 常见问题（FAQ）

- **Q: 一直提示无法从 Semantic Scholar 获取文献？**  
  **A:** 请检查：
  - 是否使用了过于冷门或非英文关键词；
  - 当前网络能否访问 `https://api.semanticscholar.org`；
  - 是否开启了会拦截该域名的代理 / 防火墙。

- **Q: 生成综述时提示智谱 API 相关错误？**  
  **A:** 通常与以下因素有关：
  - API Key 填写错误或已失效；
  - 网络无法正常访问 `https://open.bigmodel.cn` / `https://api.zhipu.ai`；
  - 账号额度不足或调用频率受限（可在智谱控制台查看）。

- **Q: 参考文献是否完全真实？**  
  **A:** 文献元数据直接来源于 Semantic Scholar，但大模型在撰写自然语言时仍可能出现措辞不严谨等问题。对于正式论文写作，请务必仔细核对原文献内容。

---

## 高级用法（V2.0 全自动模式）

自 v2.0 起，AcademiSync 增加了面向“万字级综述”的全自动流水线能力，入口为 `app.py` 中的 **“全自动学术研究系统”**（Streamlit 页面标题为 `AcademiSync Ultra`）。

### 1. 标题驱动的语义解析

- 在主界面输入完整的中文或英文综述标题，例如：
  - `中药干预糖尿病肾病的效果及分子机制研究进展`
  - `Applications of multimodal large models in medical imaging`
- 系统会通过 `generator.analyze_research_title`：
  - 去除“研究、讨论、通过、探讨、分析”等无效词；
  - 提取 3 个标准化的英文核心概念（用于 API 检索）；
  - 给出 3–4 个推荐的章节维度（如“研究背景 / 作用机制 / 临床应用 / 未来挑战”）。

### 2. 多源并行检索与本地文献合并

- 对每个英文关键词，`app.py` 会分别调用 `researcher.fetch_papers(kw, limit=N)`：
  - 优先从 Semantic Scholar 检索（可选配置 `SEMANTIC_SCHOLAR_API_KEY` 与专用代理变量 `HTTP_PROXY_FOR_SCHOLAR` / `HTTPS_PROXY_FOR_SCHOLAR`）；
  - 如遇 429 / 空结果，则自动降级到 arXiv；
  - 所有结果统一标注 `source` 字段（`Semantic Scholar` / `arXiv` / `local`）。
- 你可以在侧边栏上传本地中文文献（txt/md）：
  - 这些文件将被解析为伪“文献条目”，与在线检索结果一起参与综述写作；
  - 为后续接入 RAG / 向量检索预留了接口。

### 3. 万字大纲与分章节生成（支持断点续写）

- 应用会基于汇总的文献上下文调用 `generator.generate_outline` 生成一份**至三级标题**的万字大纲。
- 随后，对每个维度或章节标题调用 `generator.generate_chapter`：
  - 单章目标字数约 1500 字；
  - Prompt 中要求在正文中显式引用文献编号（如 `[1]` 或 `[Source_ID: 1]`）。
- 为了避免中途失败导致“全盘重来”，v2.0 做了两级进度保存：
  - 使用 `draft_state.json` 持久化：
    - 当前标题、生成的大纲、章节列表、已完成章节内容；
    - 再次点击“启动全链路写作”时，已完成的章节会被自动跳过，只补齐缺失部分。
  - 使用 `temp_draft.md` 保存当前草稿全文，方便你手动查看或导入其他工具。

### 4. AI 审稿与引用对齐检查

- 所有章节拼接后，应用会调用 `generator.polish_review`：
  - 作为“AI 主编”统一润色语法与章节衔接；
  - 保留原有文献引用标记。
- 生成完成后，`citation_utils.check_citations` 会对正文中的引用编号进行检查：
  - 找出超出参考文献数量范围的编号；
  - 找出从未在正文被引用的参考文献；
  - 在“调试信息”折叠框中给出简单报告，方便你人工二次校对。

### 5. 一键导出 Word

- v2.0 集成了 `python-docx`，生成完成后可点击：
  - 「📥 下载完整综述 (Word)」
- 系统会将当前 Markdown 文本逐行写入 `Review.docx`，便于在 Word / WPS 中继续排版与修改。

---

# AcademiSync 文献综述助手 (V1.0)

AcademiSync 是一个基于 **Semantic Scholar** 和 **智谱 GLM-4** 的本地小工具，帮助你在几分钟内生成一份结构化的文献综述初稿，并尽可能避免 AI 虚构参考文献的问题。

---

## 功能概览

- 基于 **研究话题** 自动从 Semantic Scholar 检索真实学术文献（无需额外 API Key）。
- 将多篇论文的 **标题、摘要、链接** 组装成结构化上下文。
- 调用 **智谱 GLM-4** 生成包含背景、技术演进、对比分析和参考文献列表的 Markdown 综述。
- 在 Web 界面中以 **Tab 形式** 展示：
  - 综述正文
  - 文献列表（含原文链接）
  - 调试信息（可选）

---

## 环境要求

- Python 版本：建议 **3.10+**
- 操作系统：Windows / macOS / Linux 均可（本仓库以 Windows 示例为主）
- 网络要求：
  - 能访问 `api.semanticscholar.org`（文献检索）
  - 能访问智谱 API（`https://open.bigmodel.cn/` 等域名）

---

## 安装与运行

### 1. 克隆或下载项目

将本仓库下载到本地，例如：

```bash
git clone <your-repo-url>
cd PP09
```

（如果你是通过压缩包获得代码，只需解压后进入目录即可。）

### 2. 创建虚拟环境（推荐）

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows PowerShell
# 或 source .venv/bin/activate  # macOS / Linux
```

### 3. 安装依赖

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. 配置智谱 API Key

在项目根目录创建 `.env` 文件（如果已经存在可直接编辑），内容示例：

```env
ZHIPUAI_API_KEY=你的智谱APIKey
```

> 安全提示：请不要将 `.env` 文件提交到任何公共代码仓库。

同时，运行时也可以在 **Streamlit 侧边栏** 中直接填写 / 覆盖 API Key。

### 5. 启动应用

```bash
python -m streamlit run app.py
```

浏览器会自动打开页面（或访问 `http://localhost:8501`）。

---

## 使用流程

1. 在侧边栏中确认或填写：
   - `智谱 API Key`
   - `检索文献篇数`（3–20，默认 8）
   - （可选）勾选「显示调试信息」
2. 在主界面输入研究话题，例如：
   - `Transformer 在医学影像中的应用`
   - `large language models for education`
3. 点击「开始生成」按钮：
   - 应用会调用 `researcher.fetch_papers` 从 Semantic Scholar 拉取文献。
   - 使用 `build_context_from_papers` 组装文献上下文。
   - 调用 `generator.generate_review`（智谱 GLM-4）生成综述。
4. 在 Tabs 中查看结果：
   - `📄 综述正文`：Markdown 格式的完整综述，可直接复制到笔记或论文草稿中。
   - `📚 文献列表`：每篇文献的标题、摘要和原文链接。
   - `🔍 调试信息`：用于开发和排查问题（如返回篇数、原始 JSON 等）。

---

## 常见问题 (FAQ)

- **Q：为什么没有检索到文献？**
  - 尝试使用更通用的英文关键词。
  - 检查当前网络是否能访问 `api.semanticscholar.org`。

- **Q：为什么提示智谱连接超时或 Key 无效？**
  - 确认 `.env` 中的 `ZHIPUAI_API_KEY` 正确无误且仍在有效期内。
  - 尝试在侧边栏重新输入 Key。
  - 某些网络环境（如开着海外 VPN）可能无法访问智谱 API，可尝试关闭 VPN 或切换网络。

- **Q：生成的综述能直接当论文交吗？**
  - 不建议。AcademiSync 的目标是帮你「快速形成结构化认知和初稿」，你仍然需要：
    - 手动阅读关键文献原文；
    - 校对和润色内容；
    - 按学校/期刊要求调整引用格式。

---

## 与技术规格 / 产品文档的对齐

- 技术实现细节与 Roadmap 见：
  - `reftrace/jishu.md`（技术规格）
  - `reftrace/chanpin.md`（产品定义与范围）
  - `reftrace/ui.md`（交互与界面草图）

当前 V1.0 已覆盖：

- 真实文献抓取（Semantic Scholar）。
- 上下文构造与 GLM-4 调用。
- Streamlit 单页 UI（侧边栏配置 + 主流程交互）。
- 基础错误提示与调试信息展示。

未来版本计划（V1.1+）包括：

- 导出 Word（集成 `python-docx`）。
- 多种引用格式（APA / MLA / BibTeX）。
- 本地 PDF 上传与解析等。

你可以根据自己的使用体验，在上述 reftrace 文档中继续补充需求和想法，一起把 AcademiSync 打磨得更好用。
