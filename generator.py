import os
import json
from zhipuai import ZhipuAI
from dotenv import load_dotenv

load_dotenv()

# 学术规范模板（参考《中药药理与临床》等期刊）
ACADEMIC_TEMPLATE = """
撰写规范参考《中药药理与临床》期刊：
1. 引言：必须交代背景、临床痛点（如肺纤维化的高死亡率）及中药干预的必要性。
2. 作用机制：必须深入到分子水平。禁止只说“减轻炎症”，必须说明“通过抑制XX磷酸化，阻断XX核转位”。
3. 信号通路：重点讨论 TLR4/NF-κB、TGF-β1/Smad、Nrf2 等关键路径。
4. 引用规范：文中观点必须严格对应参考文献 [1], [2] 等编号。
"""

# 强制每一章均需体现的“分子水平”过程（分子对撞/分子机制）
CRITICAL_STRUCTURE = """
【必选结构】每一章若涉及机制或药理，必须包含“分子水平”的解析过程：
- 明确写出具体分子、通路或靶点（如：磷酸化、核转位、受体-配体、代谢产物对细胞的影响）；
- 若涉及肠道菌群，须具体到门/属水平（如拟杆菌门、厚壁菌门）及代谢物（如短链脂肪酸 SCFAs）对下游细胞的具体作用；
- 采用“现象描述 → 实验数据/证据 → 机制解析”的递进逻辑，严禁空洞表述。
"""

# 综述范例质量规范（参考王荌、邱小晶、杨婷、罗志明、马川等已发表综述）
REVIEW_QUALITY_TEMPLATE = """
【综述范例写作规范】请严格模仿《基于肠道菌群及其代谢产物探讨中药干预急性肺损伤的研究现状》《肠道菌群与急性肺损伤关系的研究进展》《肠道菌群在肺部疾病中的作用机制与潜在治疗价值》《3D打印器官芯片研究进展》《肺部疾病潜在靶点研究进展》等已发表综述的写法：

1. 术语规范：专业术语首次出现时必须写“中文全称（英文全称，英文缩写）”，例如：急性肺损伤（acute lung injury，ALI）、短链脂肪酸（short chain fatty acids，SCFAs）、核转录因子κB（nuclear factor kappa B，NF-κB）、Toll样受体4（TLR4）。后文可仅用缩写或中文。

2. 引用格式：文中每个观点或数据必须对应文献，使用 [1]、[2] 或“作者等[3]”“Tang等[10]”形式，严禁编造未在参考文献中出现的引用。表述示例：“有研究发现[6]……”“汪玉磊等[11]利用……表明……”。

3. 段落逻辑：每段采用“总起句 → 具体研究/数据支撑 → 机制或小结”。涉及机制时必须写到分子/通路层面，例如“通过抑制NF-κB磷酸化”“上调TLR4/NF-κB信号通路中间产物”“厚壁菌门/拟杆菌门比例升高”“SCFAs通过……影响肺泡巨噬细胞极化”。

4. 结构一致：各节若有多个子主题，用 2.1、2.2 或加粗小标题区分；可适当在段首用“一是……二是……”“此外，”等衔接词，使层次清晰。

5. 数据与对象：若文献中有剂量、模型、指标，尽量在文中点出（如“LPS诱导的ALI大鼠”“150 mg/kg”“IL-1β、IL-6、TNF-α水平”），增强可信度。
"""

# 大纲结构规范：与范例综述一致的章节逻辑
OUTLINE_STRUCTURE_HINT = """
综述大纲应包含：引言（背景、临床意义、本综述目的与范围）；若干主题节（按“关系/机制/应用”等逻辑分节，每节可有 2.1、2.2 子标题）；小结与展望（总结主要发现、指出现有研究局限、提出 3～5 个未来方向）。标题用简洁名词短语，避免“讨论”“分析”等空洞词。
"""


def get_client():
    # 确保智谱调用不受全局代理影响
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.setdefault("NO_PROXY", "open.bigmodel.cn,api.zhipu.ai")

    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key:
        raise ValueError("未在环境变量或 .env 中找到 ZHIPUAI_API_KEY")
    return ZhipuAI(api_key=api_key)


def analyze_research_title(title):
    client = get_client()
    prompt = f"""
    你是一个学术搜索专家。请分析标题内容：{title}

    任务：
    1. 去掉所有无意义的词（如：研究、讨论、通过、探讨、分析）。
    2. 提取核心学术概念，并翻译成标准的英文术语。
    3. 给出3个独立的英文关键词（用于API检索）。

    检索用词请优先使用英文学术库中常见的写法，例如：
    - 中药 -> "traditional Chinese medicine" 或 "TCM"（勿用 Chinese herbal medicine）
    - 肠道菌群 -> "gut microbiota"（勿用 intestinal microbiota）
    - 肺纤维化 -> "pulmonary fibrosis"
    - 肺损伤 -> "acute lung injury" 或 "lung injury"
    例如标题“中药通过肠道菌群治疗肺纤维化”，你应该提取：
    ["traditional Chinese medicine", "gut microbiota", "pulmonary fibrosis"]

    请严格以 JSON 格式输出：
    {{
        "en_keywords": ["keyword1", "keyword2", "keyword3"],
        "dimensions": ["研究背景", "作用机制", "临床应用", "未来挑战"]
    }}
    """
    response = client.chat.completions.create(
        model="glm-4-flash",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def generate_outline(title, paper_data):
    """第二步：根据文献规划综述大纲，结构对齐已发表范例（引言→主题节→小结与展望）"""
    client = get_client()
    prompt = f"""
{OUTLINE_STRUCTURE_HINT}

针对课题《{title}》，基于以下文献线索，规划一份 5000～8000 字综述的详细大纲（至二级或三级标题，用 1、2、3 和 2.1、2.2 形式）。

文献线索摘要：
{paper_data[:4000]}

要求：章节标题简洁、有信息量（如“肠道菌群及其代谢产物与 ALI 的关系”“NF-κB 信号通路”“中药干预 ALI 中对肠道菌群的影响”“展望”），避免“讨论”“分析”等空洞词。直接输出大纲正文，无需解释。
"""
    response = client.chat.completions.create(
        model="glm-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()


def generate_chapter(title, outline, chapter_title, paper_data):
    """扩写单章，含术语规范与引用要求（与 generate_chapter_deep 共用范例质量规范）"""
    client = get_client()
    prompt = f"""
{REVIEW_QUALITY_TEMPLATE}

正在撰写《{title}》的【{chapter_title}】章节。
参考大纲：{outline}

参考文献（已编号 [1]、[2]…，写作时严格使用对应编号）：
{paper_data}

要求：严谨学术风，约 1500 字；术语首次出现用“中文全称（英文，缩写）”；观点对应 [1]、[2] 或“作者等[3]”；涉及机制时写到分子/通路层面。直接输出正文。
"""
    response = client.chat.completions.create(
        model="glm-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def generate_chapter_deep(title, outline, chapter, context, target_words=1500):
    """
    深度章节撰写：使用学术模板与 CRITICAL_STRUCTURE，低 temperature 保证严谨。
    整篇综述目标 5000～8000 字，每章需达到 target_words 以保障总篇幅。
    """
    client = get_client()
    chapter_min = max(target_words - 200, 800)  # 每章至少约 target_words 字，最低 800

    prompt = f"""
{ACADEMIC_TEMPLATE}
{CRITICAL_STRUCTURE}
{REVIEW_QUALITY_TEMPLATE}

任务：撰写综述《{title}》中的「{chapter}」章节。
本综述目标总字数 5000～8000 字，各章需充实展开以达成该篇幅。
参考大纲：{outline}

参考背景资料（参考文献已按 [1]、[2]… 编号，写作时严格使用对应编号）：
{context}

深度要求：
- 字数：本章必须超过 {chapter_min} 字（约 {target_words} 字），以支撑整篇 5000～8000 字目标。
- 术语：专业词首次出现用“中文全称（英文全称，缩写）”，如短链脂肪酸（short chain fatty acids，SCFAs）。
- 颗粒度：若涉及肠道菌群，须具体到门/属（拟杆菌门、厚壁菌门）及代谢物（SCFAs）对下游细胞或通路的作用；若涉及机制，须写出具体通路或分子（如 TLR4/NF-κB、磷酸化、核转位）。
- 逻辑：现象描述 → 实验/数据支撑 → 机制解析。
- 引用：每个观点对应 [1]、[2] 或“作者等[3]”，严禁编造文献。直接输出章节正文，不要输出“根据文献”等元说明。
"""
    response = client.chat.completions.create(
        model="glm-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def generate_conclusion_and_future(title, context_or_draft):
    """
    生成“小结与展望”：先小结全文发现，再写当前局限与未来方向，对齐范例综述结尾（王荌、邱小晶、杨婷、马川等）。
    """
    client = get_client()
    prompt = f"""
{REVIEW_QUALITY_TEMPLATE}

请基于以下综述主题与已有正文，撰写「小结与展望」段落。

综述题目：《{title}》

已有正文摘要（供你总结与呼应）：
{context_or_draft[:6000]}

要求（模仿《基于肠道菌群及其代谢产物探讨中药干预急性肺损伤的研究现状》《肠道菌群在肺部疾病中的作用机制与潜在治疗价值》《肺部疾病潜在靶点研究进展》等文的结尾）：
1. 小结：用 2～4 句话概括本综述的主要发现与结论，与上文各节内容呼应，保持引用 [1]、[2] 等编号。
2. 当前局限：指出 2～3 个瓶颈，例如：研究多停留在动物实验阶段、缺乏高质量大样本临床证据、因果关系尚未明确、个体差异或菌群定植差异等。
3. 未来方向：提出 3～4 个具体研究或临床方向，如：开展随机对照临床试验、多组学整合、个体化/精准干预、靶点与通路深入验证等。
4. 语言简洁、条理清晰；可用“然而，”“此外，”“未来研究需……”等衔接；若分点可用 ### 小标题或“一是……二是……”形式。直接输出正文，不要输出“小结与展望”标题（由程序添加）。
"""
    response = client.chat.completions.create(
        model="glm-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()


def polish_review(full_text):
    """审稿润色：衔接与语病修正，保留引用编号与术语规范"""
    client = get_client()
    prompt = (
        "你是一位学术期刊主编。请对以下综述全文进行润色：修正语病、加强章节与段落间的逻辑衔接、统一专业术语表述。"
        "务必保留文中所有文献引用标记（如 [1]、[2]、作者等[3]）及首次出现的“中文全称（英文，缩写）”格式。"
        "若全文过长则重点润色前 8000 字。"
    )
    response = client.chat.completions.create(
        model="glm-4",
        messages=[{"role": "user", "content": prompt + "\n\n" + full_text[:8000]}],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def generate_abstract(title, outline_snippet, context_snippet, max_chars=600):
    """
    生成结构化摘要（背景-目的-方法/内容-结论），对齐范例综述摘要写法。
    可用于在 app 中在正文前插入摘要。
    """
    client = get_client()
    prompt = f"""
请为以下综述撰写一段结构化中文摘要，总字数控制在 {max_chars} 字以内。

综述题目：《{title}》

大纲摘要：{outline_snippet[:800]}

参考内容摘要：{context_snippet[:1200]}

要求：分两层意思写（可合并为一段）。第一句交代背景与临床/研究意义；随后概括本综述主要涉及的内容与结论（如“本文综述了……发现/表明……”）。用语与已发表综述摘要一致，不要出现“本文作者”等第一人称，不要列出参考文献。直接输出摘要正文。
"""
    response = client.chat.completions.create(
        model="glm-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def generate_review(topic: str, paper_data: str) -> str:
    """
    兼容旧接口：直接根据文献生成一篇完整综述（不走多阶段流水线）。
    目前简化为：调用 generate_outline + 一个综合章节。
    """
    try:
        outline = generate_outline(topic, paper_data)
        chapter = generate_chapter(topic, outline, "综合讨论与分析", paper_data)
        draft = f"# {topic}\n\n{outline}\n\n## 综合讨论与分析\n\n{chapter}"
        return polish_review(draft)
    except Exception as e:
        return f"❌ 生成失败：{e}"