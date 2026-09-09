"""Poll a Notion task database and fill Todo tasks with deep research notes."""

import json
import re
import sys
import time
import traceback

from deep_research import get_model, run_deep_research_with_sources
from notion_tasks import (
    append_result_to_task_page,
    get_todo_task,
    update_resource_urls,
    update_result_summary,
    update_task_status,
    update_task_topics,
)

POLL_INTERVAL_SECONDS = 60

# Shortest plausible full note. Below this the writer almost certainly
# returned a summary or an apology instead of the note.
MIN_RESULT_CHARS = 1000

# The Resource URLs property is a summary, not a bibliography. Research
# can easily surface 100+ URLs, which makes the property unreadable.
MAX_RESOURCE_URLS = 25

ALLOWED_TOPICS = [
    "Theory",
    "Technique",
    "Coding Skill",
    "Tool / Framework",
    "Paper / Article",
    "Math Foundation",
    "Engineering Practice",
    "Research Resource",
]


def classify_task_topics(question: str, source_url: str = "") -> list[str]:
    """Use the LLM to classify the task into Notion Topic categories."""
    prompt = f"""
You are a task classification assistant.

Classify the user's research question into 1 to 3 topic categories.

Allowed categories:
{ALLOWED_TOPICS}

Category meanings:
- Theory: concepts, principles, mechanisms, conceptual explanations
- Technique: methods, algorithms, technical workflows, design patterns
- Coding Skill: Python, APIs, debugging, implementation, coding exercises
- Tool / Framework: libraries, frameworks, platforms, tools, SDKs
- Paper / Article: papers, articles, official documentation, course materials
- Math Foundation: linear algebra, probability, optimization, gradients, matrix math
- Engineering Practice: deployment, reliability, systems, logging, retries, concurrency
- Research Resource: learning plans, reading resources, documentation recommendations

User question:
{question}

Source URL:
{source_url or "Not provided"}

Return only valid JSON.
Do not include markdown.
Do not explain.

Format:
{{"topics": ["Theory", "Technique"]}}
"""

    try:
        response = get_model().invoke(prompt)
        content = str(response.content).strip()
    except Exception as e:
        print(f"Could not classify topics with LLM: {e}")
        return ["Theory"]

    # The model sometimes wraps JSON in a markdown fence despite the
    # instruction, so strip one if present.
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", content, flags=re.DOTALL)

    if fenced:
        content = fenced.group(1)

    try:
        topics = json.loads(content).get("topics", [])
    except Exception as e:
        print(f"Could not parse topic JSON: {e}")
        topics = []

    cleaned_topics = []

    for topic in topics:
        if topic in ALLOWED_TOPICS and topic not in cleaned_topics:
            cleaned_topics.append(topic)

    if not cleaned_topics:
        cleaned_topics = ["Theory"]

    return cleaned_topics[:3]


def summarize_result_one_sentence(result: str, output_language: str = "Chinese") -> str:
    """Summarize the final result into one sentence for Notion Result Summary."""
    if not result or not result.strip():
        return ""

    if output_language == "English":
        instruction = (
            "Summarize the following note in exactly one concise English sentence."
        )
    else:
        instruction = "请把下面这篇学习笔记压缩成一句中文总结，不要超过 80 个中文字符。"

    prompt = f"""
{instruction}

要求：
1. 只输出一句话。
2. 不要使用 bullet points。
3. 不要输出“这篇笔记总结了”这种套话。
4. 不要输出 Markdown 标题。

学习笔记：
{result[:6000]}
"""

    try:
        response = get_model().invoke(prompt)
        summary = str(response.content).strip()
    except Exception as e:
        print(f"Could not summarize result with LLM: {e}")
        summary = result.strip().splitlines()[0][:200]

    summary = summary.replace("\n", " ").strip()

    return summary[:300]


def clean_agent_output(text: str) -> str:
    """Remove meta-commentary lines from model output before writing to Notion."""
    if not text:
        return ""

    banned_patterns = [
        r"^Now let me compile",
        r"^Now I will compile",
        r"^Let me compile",
        r"^I will now compile",
        r"^以上是完整",
        r"^以上就是完整",
        r"^可以直接复制到 Notion",
        r"^这份笔记可以直接",
        r"^笔记涵盖了",
        r"^好的[，,]",
        r"^我已经",
    ]

    cleaned_lines = []

    for line in text.splitlines():
        stripped = line.strip()

        if not stripped:
            cleaned_lines.append(line)
            continue

        if any(
            re.match(pattern, stripped, flags=re.IGNORECASE)
            for pattern in banned_patterns
        ):
            continue

        cleaned_lines.append(line)

    cleaned_text = "\n".join(cleaned_lines).strip()

    # Drop any leading chatter before the note's own H1 title.
    heading = re.search(r"^# .+$", cleaned_text, flags=re.MULTILINE)

    if heading and heading.start() > 0:
        cleaned_text = cleaned_text[heading.start():].strip()

    return cleaned_text


def validate_result(result: str) -> None:
    """Raise ValueError if the result is clearly not a full study note."""
    if not result or len(result.strip()) < MIN_RESULT_CHARS:
        raise ValueError(
            f"Result is only {len(result.strip())} characters, below the "
            f"{MIN_RESULT_CHARS} character minimum. The writer likely "
            "returned a summary instead of the full Markdown note."
        )

    if not result.lstrip().startswith("#"):
        raise ValueError(
            "Result does not start with a Markdown heading, so it is "
            "probably not the note body."
        )

    # A virtual-filesystem path in the output means the note leaked the
    # research agent's scratch work instead of real content.
    if "/home/user/notes" in result:
        raise ValueError(
            "Result references a virtual file path instead of containing "
            "the note itself."
        )


def build_question_from_task(task: dict) -> str:
    """Build a richer research prompt from Notion task properties."""
    question = task.get("question", "")
    priority = task.get("priority", "")
    topics = task.get("topics", [])
    difficulty = task.get("difficulty", "")
    source_url = task.get("source_url", "")
    output_language = task.get("output_language", "")

    topics_text = ", ".join(topics) if topics else "Not specified"

    if not difficulty:
        difficulty = "Beginner"

    if not output_language:
        output_language = "Chinese"

    if difficulty == "Beginner":
        difficulty_instruction = """
你需要用 Beginner 模式回答：
- 用初学者能理解的语言解释，但不要过度简化。
- 先解释直觉，再逐步引入 technical 细节。
- 每个重要术语都要用一句人话解释。
- 少用公式；如果必须用公式，要解释每个符号。
- 重点回答：它是什么、为什么重要、解决什么问题、我现在该掌握什么。
- 最后请推荐相关基础知识，鼓励我继续学习。
"""
    elif difficulty == "Medium":
        difficulty_instruction = """
你需要用 Medium 模式回答：
- 在基础解释之后，加入技术结构、关键流程、优缺点和典型使用方式。
- 可以加入伪代码、流程图式描述、关键 API 思路。
- 要解释它和相关技术的关系。
- 要给出适合继续深入的学习资源。
"""
    elif difficulty == "Advanced":
        difficulty_instruction = """
你需要用 Advanced 模式回答：
- 先简洁定义，再深入讲原理、架构、实现方式、失败模式、边界条件。
- 讨论性能、成本、可扩展性、工程可靠性、错误处理和设计 trade-off。
- 可以加入系统设计和源码级思路。
- 输出要比普通教程更 technical，但仍然要结合我的学习背景解释清楚。
"""
    else:
        difficulty_instruction = """
请根据问题本身选择合适难度。
如果不确定，使用 Medium 模式：既解释基础，也提供一定技术深度。
"""

    topic_rules = {
        "Theory": "- Topic 包含 Theory：请重点解释概念、基本原理、直觉理解、知识结构，以及它和相似概念的区别。",
        "Technique": "- Topic 包含 Technique：请重点解释技术方法、流程、适用场景、优缺点和替代方案。",
        "Coding Skill": "- Topic 包含 Coding Skill：请加入一个具体代码练习，并解释输入、处理过程和输出。",
        "Tool / Framework": "- Topic 包含 Tool / Framework：请解释这个工具/框架解决什么问题、核心组件、典型用法，以及它在工程系统中的位置。",
        "Paper / Article": "- Topic 包含 Paper / Article：请按文章、论文或文档结构总结，区分主要观点、方法、结论和我现在需要掌握的部分。",
        "Math Foundation": "- Topic 包含 Math Foundation：请用直觉解释数学概念。如果有公式，解释每个符号的含义和公式解决的问题。",
        "Engineering Practice": "- Topic 包含 Engineering Practice：请重点解释工程实现、系统设计、可靠性、错误处理、日志、重试、并发、部署和维护。",
        "Research Resource": "- Topic 包含 Research Resource：请重点推荐学习资源，优先推荐非视频内容，例如官方文档、书籍、论文、技术博客、课程讲义和 GitHub repo。",
    }

    topic_instructions = [topic_rules[t] for t in topics if t in topic_rules]

    topic_instruction_text = "\n".join(topic_instructions) if topic_instructions else (
        "- Topic 未指定：请根据用户问题自动判断最合适的主题类型，并在回答中说明你的判断。"
    )

    if source_url:
        source_instruction = f"""
参考链接 Source URL：
{source_url}

请优先围绕这个链接进行研究。
如果你无法读取该链接，请明确说明，并通过搜索查找相关可靠资料辅助回答。
"""
    else:
        source_instruction = """
参考链接 Source URL：
Not provided

请根据用户问题进行必要的网络搜索，并优先使用官方文档、论文、课程页面、技术博客或可靠技术资料。
"""

    prompt = f"""
请根据下面的 Notion 任务信息完成 Deep Research，并生成适合保存到 Notion 的深入学习笔记。

用户问题 Question：
{question}

任务优先级 Priority：
{priority or "Not specified"}

任务类型 Topic：
{topics_text}

难度 Difficulty：
{difficulty}

输出语言 Output Language：
{output_language}

{source_instruction}

难度要求：
{difficulty_instruction}

Topic 要求：
{topic_instruction_text}

额外要求：
1. 如果 Output Language 是 Chinese，请必须用中文输出。
2. 如果 Output Language 是 English，请用英文输出。
3. 最终回答必须直接输出完整 Markdown 笔记正文。
4. 如果信息不足，请明确说明，不要编造。
5. 如果用了来源，请尽量保留来源名称和 URL。
6. 输出内容需要适合直接写入 Notion 页面正文。
7. 回答不能太短，要深入解释基本原理、technical 机制、相关知识和后续学习路线。
8. 推荐学习资源时，优先推荐非视频内容。
9. 不要解释你将要做什么，直接输出最终学习笔记正文。
10. 如果使用了网页来源，请在正文的“推荐学习资源”或“参考来源”部分列出来源名称和 URL。
11. 最终正文必须完整，不要因为内容较长而提前总结收尾。
"""

    return prompt.strip()


def process_one_task() -> bool:
    """Process one Todo task from Notion. Returns True if a task was found."""
    task = get_todo_task()

    if not task:
        print("No Todo task found.")
        return False

    page_id = task["page_id"]
    question = task["question"]
    source_url = task.get("source_url", "")
    current_topics = task.get("topics", [])

    print("=" * 60)
    print("Found task:")
    print("Page ID:", page_id)
    print("Question:", question)
    print("Topic:", current_topics)
    print("Difficulty:", task.get("difficulty", ""))
    print("Source URL:", source_url)
    print("=" * 60)

    if not question or not question.strip():
        print("Question is empty. Marking task as Error.")
        update_task_status(page_id, "Error", "Question is empty.")
        return True

    try:
        # 1. Claim the task.
        print("Updating status to Running...")
        update_task_status(page_id, "Running")

        # 2. Classify Topic if the user left it blank.
        if not current_topics:
            print("Topic is empty. Classifying topic with LLM...")

            detected_topics = classify_task_topics(question, source_url)

            print("Detected topics:", detected_topics)

            update_task_topics(page_id, detected_topics)
            task["topics"] = detected_topics
        else:
            print("Topic already exists. Keeping current topics:", current_topics)

        # 3. Build the prompt.
        print("Building full research prompt...")
        full_question = build_question_from_task(task)

        # 4. Research, then write the note.
        print("Running deep research pipeline...")
        result, research_urls = run_deep_research_with_sources(full_question)

        # 5. Strip any meta-commentary and validate.
        print("Cleaning model output...")
        result = clean_agent_output(result)

        validate_result(result)

        # 6. Record the sources the research stage actually used.
        urls = [source_url] if source_url else []

        for url in research_urls:
            if url not in urls:
                urls.append(url)

        if urls:
            print(
                f"Updating Resource URLs "
                f"({len(urls)} found, writing up to {MAX_RESOURCE_URLS})..."
            )

            try:
                update_resource_urls(page_id, urls[:MAX_RESOURCE_URLS])
            except Exception as e:
                print(f"Could not update Resource URLs: {e}")

        # 7. Write the note body.
        print("Appending result to Notion page...")
        append_result_to_task_page(page_id, result)

        # 8. Generate the one-sentence summary. A failure here must not
        #    discard a note that is already written to the page.
        print("Generating Result Summary...")

        try:
            summary = summarize_result_one_sentence(
                result,
                task.get("output_language", "Chinese"),
            )

            update_result_summary(page_id, summary)
        except Exception as e:
            print(f"Could not update Result Summary: {e}")

        # 9. Done.
        print("Updating status to Done...")
        update_task_status(page_id, "Done")

        print("Task completed successfully.")

    except Exception as e:
        print("Task failed.")
        print(traceback.format_exc())

        try:
            update_task_status(page_id, "Error", str(e))
        except Exception:
            print("Failed to update task status to Error.")
            print(traceback.format_exc())

    return True


def main() -> None:
    """Continuously check Notion for Todo tasks."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    run_once = "--once" in sys.argv

    if run_once:
        print("Notion worker running a single pass.")
        process_one_task()
        return

    print("Notion worker started.")
    print(f"Polling every {POLL_INTERVAL_SECONDS} seconds.")
    print("Press Ctrl + C to stop.")

    while True:
        try:
            found = process_one_task()
        except KeyboardInterrupt:
            print("Stopped.")
            return
        except Exception:
            # Never let a polling-loop error kill the worker.
            print("Unexpected error while polling Notion.")
            print(traceback.format_exc())
            found = False

        # Only sleep when the queue is empty, so a backlog drains quickly.
        if not found:
            try:
                time.sleep(POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                print("Stopped.")
                return


if __name__ == "__main__":
    main()
