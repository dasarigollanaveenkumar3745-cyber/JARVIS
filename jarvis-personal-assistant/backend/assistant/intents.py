from enum import Enum


class Intent(str, Enum):
    CREATE_TASK = "create_task"
    LIST_TASKS = "list_tasks"
    CREATE_NOTE = "create_note"
    LIST_NOTES = "list_notes"
    UNKNOWN = "unknown"


def detect_intent(text: str):

    text = text.lower().strip()

    if "create task" in text:
        return Intent.CREATE_TASK

    if "add task" in text:
        return Intent.CREATE_TASK

    if "show tasks" in text:
        return Intent.LIST_TASKS

    if "list tasks" in text:
        return Intent.LIST_TASKS

    if "create note" in text:
        return Intent.CREATE_NOTE

    if "show notes" in text:
        return Intent.LIST_NOTES

    return Intent.UNKNOWN