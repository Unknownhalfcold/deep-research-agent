from notion_tasks import get_todo_task, append_result_to_task_page

task = get_todo_task()

if not task:
    print("No Todo task found.")
else:
    print("Found task:")
    print("Page ID:", task["page_id"])
    print("Question:", task["question"])

    append_result_to_task_page(
        task["page_id"],
        """
# Test Result

## Summary
This is a test result written by Python.

## Key findings
- Notion task reading works.
- Notion page appending works.
- The agent can later write research results here.
""",
    )

    print("Result appended to Notion page.")