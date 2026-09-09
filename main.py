import sys

from deep_research import run_deep_research_with_sources


def main():
    # Windows consoles default to a legacy code page, which makes printing
    # Chinese output raise UnicodeEncodeError.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    question = input(
        "请输入你的研究问题：\n"
    )

    answer, sources = run_deep_research_with_sources(question)

    print("\n=== Final Answer ===\n")
    print(answer)

    if sources:
        print("\n=== Sources ===\n")

        for source in sources:
            print(source)


if __name__ == "__main__":
    main()
