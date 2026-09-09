print("test_notion.py is running...")

from notion_tasks import get_todo_task, update_task_status

print("Imported notion_tasks successfully.")

task = get_todo_task()

print("get_todo_task finished.")

if not task:
    print("No Todo task found.")
else:
    print("Found task:")
    print("Page ID:", task["page_id"])
    print("Question:", task["question"])

    update_task_status(task["page_id"], "Running")
    print("Status updated to Running.")

    update_task_status(task["page_id"], "Todo")
    print("Status updated back to Todo.")