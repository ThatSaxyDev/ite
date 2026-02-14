import uuid
from dataclasses import dataclass
from config.config import Config
from tools.base import ToolResult, ToolInvocation, ToolKind, Tool
from pydantic import BaseModel, Field


class TodosParams(BaseModel):
    action: str = Field(
        ...,
        description="Action: `add`, `complete`, `list`, `clear`",
    )
    id: str | None = Field(None, description="Todo ID (for `complete`)")
    content: str | None = Field(None, description="Single todo item text (for `add`)")
    items: list[str] | None = Field(
        None,
        description="Multiple todo items to add at once (for `add`). Preferred over `content` when adding more than one.",
    )


@dataclass
class TodoItem:
    id: str
    content: str
    completed: bool = False


class TodosTool(Tool):
    name = "todos"
    description = (
        "Manage a task list for the current session to track multi-step work. "
        "WORKFLOW: First call 'add' with 'items' to create ALL planned tasks upfront, "
        "then call 'complete' with each task's ID as you finish each step. "
        "Do NOT add and complete one task at a time — plan all tasks first, then execute."
    )
    kind = ToolKind.MEMORY
    schema = TodosParams

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._todos: dict[str, TodoItem] = {}

    def _render_list(self) -> str:
        """Render the todo list with checkbox indicators."""
        if not self._todos:
            return "No todos"

        pending = [t for t in self._todos.values() if not t.completed]
        completed = [t for t in self._todos.values() if t.completed]
        total = len(self._todos)
        done = len(completed)

        lines = [f"Tasks: {done}/{total} completed"]
        lines.append("")

        for item in pending:
            lines.append(f"  ☐  [{item.id}] {item.content}")

        for item in completed:
            lines.append(f"  ☑  [{item.id}] {item.content}")

        return "\n".join(lines)

    def _make_metadata(self, action: str, **extra) -> dict:
        return {
            "action": action,
            "pending": sum(1 for t in self._todos.values() if not t.completed),
            "completed": sum(1 for t in self._todos.values() if t.completed),
            "total": len(self._todos),
            **extra,
        }

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = TodosParams(**invocation.params)
        action = params.action.lower()

        if action == "add":
            # Collect items from both 'items' list and single 'content'
            to_add: list[str] = []
            if params.items:
                to_add.extend(params.items)
            if params.content:
                to_add.append(params.content)

            if not to_add:
                return ToolResult.error_result(
                    "'content' or 'items' is required for 'add' action"
                )

            added_ids = []
            for text in to_add:
                todo_id = str(uuid.uuid4())[:8]
                self._todos[todo_id] = TodoItem(id=todo_id, content=text)
                added_ids.append(todo_id)

            return ToolResult.success_result(
                self._render_list(),
                metadata=self._make_metadata("add", added_ids=added_ids),
            )

        elif action == "complete":
            if not params.id:
                return ToolResult.error_result("'id' is required for 'complete' action")
            if params.id not in self._todos:
                return ToolResult.error_result(f"Todo '{params.id}' not found")

            self._todos[params.id].completed = True

            return ToolResult.success_result(
                self._render_list(),
                metadata=self._make_metadata("complete", todo_id=params.id),
            )

        elif action == "list":
            return ToolResult.success_result(
                self._render_list(),
                metadata=self._make_metadata("list"),
            )

        elif action == "clear":
            count = len(self._todos)
            self._todos.clear()
            return ToolResult.success_result(
                "Cleared all todos",
                metadata=self._make_metadata("clear", cleared=count),
            )

        else:
            return ToolResult.error_result(
                f"Invalid action: '{params.action}'. Use: add, complete, list, clear"
            )
