"""Two-stage deep research pipeline.

Stage 1 (research): a deepagents agent searches the web with Tavily and
returns evidence. `create_deep_agent` always installs filesystem tools
(`write_file`, `read_file`, `execute`, ...), so this agent may decide to
stash its work in a virtual file and reply with only a short summary.
That is fine here, because we harvest evidence from the tool messages
rather than trusting the final message.

Stage 2 (writing): a plain, tool-free model call turns that evidence into
the full Markdown study note. With no tools available the model cannot
"save the note to a file and report success" -- the note is the direct
output of the call, which is what the Notion worker needs.
"""

import re

from deepagents import create_deep_agent
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
)
from tools import fetch_webpage_content, tavily_search

# Tools whose output counts as research evidence.
RESEARCH_TOOL_NAMES = {"tavily_search", "fetch_webpage_content"}

# How much evidence text to pass into the writing stage.
MAX_EVIDENCE_CHARS = 40000

_URL_PATTERN = re.compile(r"https?://[^\s\)\]\"'<>，。；]+")


NOTE_WRITER_PROMPT = """
你是 Elliot 的私人 AI Deep Research 学习助手。

你的任务：
根据用户的问题、Notion database 中的 Difficulty / Topic / Source URL / Output Language 等信息，
以及提供给你的研究材料，生成适合保存到 Notion 的结构化、深入、technical 的学习笔记。

用户背景：
- 用户是输电工程本科背景，即将进入 AI / MSAI 方向学习。
- 用户正在系统学习 AI、机器学习、LangChain、Agent、RAG、Transformer、Python、API、后端部署等内容。
- 用户希望不仅知道“是什么”，还希望理解“为什么这样设计”“底层原理是什么”“和其他技术有什么关系”“下一步该学什么”。
- 不要默认用户已经懂深度学习、概率统计、Transformer、系统设计或复杂工程架构。
- 解释时要适合初学者进入，但内容不要停留在浅层科普，要逐步引导到更 technical 的理解。

重要输出限制：
1. 你的回答必须直接就是完整学习笔记正文，不要有任何前言或结语。
2. 不要输出“以上是完整笔记”“可以复制到 Notion”“我已经保存”等说明性文字。
3. 不要只返回摘要、文件路径或任务完成说明。
4. 调用方会自动把你的回答写入 Notion，所以你只需要返回完整 Markdown 正文。
5. 回答必须以 "# 标题" 开头。
6. 回答必须包含至少以下章节：
   - ## 1. 一句话总结
   - ## 2. 为什么这个概念重要
   - ## 3. 基本原理
   - ## 4. 核心概念表
   - ## 5. 工作流程 / 架构理解
   - ## 6. 关键机制深入解释
   - ## 7. 和相关知识的关系
   - ## 8. 代码 / 伪代码 / 实践练习
   - ## 9. 推荐学习资源
   - ## 10. 我现在应该掌握什么
   - ## 11. 下一步学习路线
   - ## 12. Notion 摘要卡片

研究材料使用规则：
- 优先使用提供的研究材料中的事实、定义和结论。
- 引用来源时保留来源名称和 URL。
- 如果研究材料不足以回答某个部分，请依靠你自己的知识，但要明确标注哪些部分缺少来源支撑。
- 不要编造 URL 或不存在的资料。

输出语言：
- 默认使用中文输出。
- 如果任务明确要求 English，再使用英文。

整体输出风格：
- 不要太短。
- 不要只给定义。
- 要解释基本原理。
- 要适度发散，告诉用户还应该学习哪些相关知识。
- 要比普通 ChatGPT 简答更系统、更 technical。
- 每个重要术语都要解释。
- 如果有公式，要解释每个符号是什么意思，以及公式解决什么问题。
- 如果有代码或算法，要用“输入是什么 → 处理过程是什么 → 输出是什么”的方式解释。
- 如果涉及工具或框架，要解释它在真实工程里的位置。

Markdown 格式要求（会被转换成 Notion blocks）：
- 标题只使用 #、##、###。
- 表格使用标准 Markdown 表格语法（带 | --- | 分隔行）。
- 代码使用带语言标注的三反引号代码块。
- 列表使用 "- " 或 "1. "。

Difficulty 输出规则：

如果 Difficulty = Beginner：
- 用适合初学者的语言解释，但不要过度简化。
- 重点讲清楚：它是什么、为什么重要、解决什么问题、最小工作流程是什么。
- 每个重要术语都要用“一句话人话解释”。
- 可以加入少量技术细节，但必须先用直觉解释。
- 最后要告诉用户下一步应该补哪些基础知识。

如果 Difficulty = Medium：
- 在 Beginner 的基础上，加入更多技术结构、核心流程、典型用法、优缺点。
- 可以加入伪代码、简单架构图式描述、关键 API 使用思路。
- 要解释它和相关技术的关系，比如 RAG、Agent、Workflow、Chain、Tool、State、Memory 等。
- 输出要适合用户做项目实践和系统学习。

如果 Difficulty = Advanced：
- 更深入解释原理、架构、工程实现、失败模式、边界条件、性能、成本和可扩展性。
- 可以加入系统设计、源码级思路、状态管理、任务调度、错误恢复、并发处理等内容。
- 不要跳过基础定义，但基础部分可以更简洁。
- 要帮助用户形成技术地图，而不是只回答单个问题。

Topic 输出规则：

如果 Topic 包含 Theory：
- 重点解释概念、原理、直觉理解、知识结构、和相关概念的区别。

如果 Topic 包含 Technique：
- 重点解释技术方法、流程、适用场景、优缺点、替代方案。

如果 Topic 包含 Coding Skill：
- 必须加入一个具体代码练习。
- 解释代码的输入、处理过程、输出。
- 尽量给出适合初学者实现的小任务。

如果 Topic 包含 Tool / Framework：
- 重点解释工具是什么、解决什么问题、核心组件、典型使用方式。
- 说明它和其他工具的区别。
- 说明它在工程系统中的位置。

如果 Topic 包含 Paper / Article：
- 按文章/论文/文档结构总结。
- 区分作者主要观点、方法、结论和用户现在需要掌握的部分。

如果 Topic 包含 Math Foundation：
- 用直觉解释数学概念。
- 如果有公式，解释每个符号是什么意思，以及公式解决什么问题。
- 不要默认用户已经熟悉线代、概率、优化或微积分。

如果 Topic 包含 Engineering Practice：
- 重点解释工程实现、系统设计、可靠性、错误处理、日志、重试、并发、部署和维护。

如果 Topic 包含 Research Resource：
- 重点推荐学习资源。
- 优先推荐非视频资源，例如官方文档、论文、书籍章节、技术博客、课程讲义、GitHub repo、interactive tutorial。
- 视频资源只能作为补充，不要放在第一优先级。

默认输出结构：

# 标题

原文链接：
类型：Topic / Article / Paper / Documentation / Course
难度：Beginner / Medium / Advanced
主题标签：

## 1. 一句话总结
用 1-3 句话说明这个内容到底讲什么。

## 2. 为什么这个概念重要
解释它解决了什么问题，为什么值得学。

## 3. 基本原理
从最基础的直觉讲起，然后逐步过渡到 technical explanation。

## 4. 核心概念表
用表格输出：
| 概念 | 人话解释 | 更 technical 的解释 | 它解决的问题 |

## 5. 工作流程 / 架构理解
如果涉及系统、工具、框架、算法，请解释它的流程：
输入是什么 → 中间发生什么 → 输出是什么。

## 6. 关键机制深入解释
不要只停留在表面定义。
请解释背后的机制、设计原因、优缺点和常见误区。

## 7. 和相关知识的关系
发散说明它和哪些知识有关。
例如：
- 前置知识
- 相似概念
- 后续应该学习的概念
- 它在 AI / ML / Agent / 软件工程中的位置

## 8. 代码 / 伪代码 / 实践练习
如果适合代码练习，请给一个小练习。
如果暂时不适合代码，请说明原因，并给一个阅读或理解任务。

## 9. 推荐学习资源
优先推荐非视频内容：
- 官方文档
- 论文 / 原始资料
- 技术博客
- 书籍章节
- GitHub repo
- 课程讲义
每个资源请说明：为什么推荐、适合什么阶段、应该重点看什么。

## 10. 我现在应该掌握什么
分成：
- 必须掌握
- 暂时了解
- 以后深入

## 11. 下一步学习路线
给出 3-5 个后续学习方向，按优先级排序。

## 12. Notion 摘要卡片
- Summary:
- Key Concepts:
- Technical Depth:
- Recommended Resources:
- Next Action:
"""


RESEARCH_LEAD_PROMPT = """
You are the research lead for a study-note pipeline.

Your only job in this stage is to GATHER EVIDENCE. Another model writes
the final note, so do not write it yourself.

Instructions:
1. Break the question into 3-6 concrete sub-questions.
2. Use tavily_search to find sources. Use fetch_webpage_content to read
   any specific URL the user provided, or a promising search result.
3. Delegate focused sub-questions to the web-researcher subagent when
   that keeps your own context small.
4. Prefer official documentation, primary sources, papers and reliable
   technical references over blog aggregators and video pages.
5. Return concise, factual research notes: definitions, mechanisms,
   numbers, trade-offs, and code or API details you actually found.
6. Always keep the URL next to each fact.
7. Do not produce the 12-section study note. Do not write a polished
   report. Evidence and sources only.
"""


RESEARCH_SUBAGENT_PROMPT = """
You are a focused web research subagent.

Your job is to investigate one specific research question at a time.

Instructions:
1. Use tavily_search to find relevant sources.
2. Prefer official documentation, primary sources, and reliable technical
   references.
3. Extract concrete facts, definitions, and claims.
4. Preserve URLs next to the facts they support.
5. Do not write the final report.
6. Return concise research notes for the research lead.
"""


_model: ChatOpenAI | None = None
_research_agent = None


def get_model() -> ChatOpenAI:
    """Return a cached DeepSeek chat model."""
    global _model

    if _model is None:
        _model = ChatOpenAI(
            model=DEEPSEEK_MODEL,
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            temperature=0,
        )

    return _model


def build_agent():
    """Create and return the research-stage deep agent."""
    subagents = [
        {
            "name": "web-researcher",
            "description": (
                "Use this subagent for focused web research tasks. "
                "It searches the web, reads sources, and returns concise "
                "evidence-backed notes."
            ),
            "system_prompt": RESEARCH_SUBAGENT_PROMPT,
            "tools": [tavily_search, fetch_webpage_content],
        }
    ]

    return create_deep_agent(
        model=get_model(),
        tools=[tavily_search, fetch_webpage_content],
        system_prompt=RESEARCH_LEAD_PROMPT,
        subagents=subagents,
    )


def get_research_agent():
    """Return a cached research agent so it is not rebuilt per task."""
    global _research_agent

    if _research_agent is None:
        _research_agent = build_agent()

    return _research_agent


def message_text(content) -> str:
    """Normalize LangChain message content to a plain string.

    Message content is a `str` for most providers but a list of content
    blocks for others, so callers must not assume `.content` is a string.
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []

        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text") or block.get("content") or "")

        return "\n".join(part for part in parts if part)

    return str(content)


def extract_urls(text: str) -> list[str]:
    """Extract unique http(s) URLs from text, preserving order."""
    urls: list[str] = []

    for match in _URL_PATTERN.findall(text):
        url = match.rstrip(".,;:!?)]}。，")

        if url not in urls:
            urls.append(url)

    return urls


def run_research(question: str) -> tuple[str, list[str]]:
    """Run the research stage.

    Returns the collected evidence text and the source URLs that research
    tools actually returned.
    """
    agent = get_research_agent()

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": question,
                }
            ]
        }
    )

    messages = result.get("messages", [])

    evidence_parts: list[str] = []
    urls: list[str] = []

    for message in messages:
        text = message_text(getattr(message, "content", None))

        if not text:
            continue

        # Raw tool output is the trustworthy evidence: it exists even if the
        # agent decides to summarize its findings into a file instead of a
        # message.
        if isinstance(message, ToolMessage):
            if getattr(message, "name", "") in RESEARCH_TOOL_NAMES:
                evidence_parts.append(text)

                for url in extract_urls(text):
                    if url not in urls:
                        urls.append(url)

    # The agent's own closing summary, if any, goes last as synthesis.
    if messages:
        final_text = message_text(getattr(messages[-1], "content", None))

        if final_text and not isinstance(messages[-1], ToolMessage):
            evidence_parts.append(f"研究员总结：\n{final_text}")

    evidence = "\n\n---\n\n".join(evidence_parts)

    return evidence[:MAX_EVIDENCE_CHARS], urls


def write_note(question: str, evidence: str) -> str:
    """Run the writing stage: turn evidence into the full Markdown note.

    This is a tool-free model call, so the note cannot be replaced by a
    "saved to file" style completion message.
    """
    if evidence.strip():
        evidence_section = f"""
以下是研究阶段收集到的资料（含来源 URL）：

<research_evidence>
{evidence}
</research_evidence>
"""
    else:
        evidence_section = """
研究阶段没有收集到可用资料。请依靠你自己的知识回答，
并在“推荐学习资源”部分说明这次没有获取到实时来源。
"""

    prompt = f"""
{question}

{evidence_section}

现在请直接输出完整的 Markdown 学习笔记正文。
"""

    response = get_model().invoke(
        [
            {"role": "system", "content": NOTE_WRITER_PROMPT},
            {"role": "user", "content": prompt},
        ]
    )

    return message_text(response.content).strip()


def run_deep_research_with_sources(question: str) -> tuple[str, list[str]]:
    """Run the full pipeline and return the note plus the source URLs used."""
    if not question or not question.strip():
        return "Error: question is empty.", []

    evidence, urls = run_research(question)

    note = write_note(question, evidence)

    return note, urls


def run_deep_research(question: str) -> str:
    """Run the full pipeline and return the Markdown study note."""
    note, _urls = run_deep_research_with_sources(question)

    return note


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    user_question = input("请输入你的研究问题：\n")

    answer, sources = run_deep_research_with_sources(user_question)

    print("\n=== Final Answer ===\n")
    print(answer)

    if sources:
        print("\n=== Sources ===\n")

        for source in sources:
            print(source)
