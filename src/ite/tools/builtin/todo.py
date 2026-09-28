import uuid
from datetime import datetime
from dataclasses import dataclass
from ite.config.config import Config
from ite.tools.base import ToolResult, ToolInvocation, ToolKind, Tool
from pydantic import BaseModel, Field
from typing import Literal, Any


class TodosParams(BaseModel):
    action: Literal["add", "complete", "list", "clear", "remove", "reopen", "update"] = Field(
        ...,
        description="Action: `add`, `complete`, `list`, `clear`, `remove`, `reopen`, `update`",
    )
    scope: Literal["planning", "execution"] | None = Field(
        None,
        description="Todo scope. Use `planning` for plan-only tasks and `execution` for user-visible implementation tasks.",
    )
    id: str | None = Field(None, description="Todo ID (for `complete`)")
    content: str | None = Field(None, description="Single todo item text (for `add`)")
    items: list[str] | None = Field(
        None,
        description="Multiple todo items to add at once (for `add`). Preferred over `content` when adding more than one.",
    )
    new_content: str | None = Field(
        None,
        description="Updated todo text (for `update`).",
    )


@dataclass
class TodoItem:
    id: str
    content: str
    completed: bool = False
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "completed": self.completed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TodoItem":
        return cls(
            id=str(data.get("id", "")),
            content=str(data.get("content", "")),
            completed=bool(data.get("completed", False)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            completed_at=(
                str(data.get("completed_at"))
                if data.get("completed_at") is not None
                else None
            ),
        )


class TodosTool(Tool):
    name = "todos"
    description = (
        "Manage scoped task lists for the current session. "
        "Use scope=`planning` for internal planning tasks and scope=`execution` for user-facing implementation progress. "
        "Start with execution todos for multi-step work, update them as work evolves, complete items immediately, and remove invalidated tasks."
    )
    kind = ToolKind.MEMORY
    schema = TodosParams

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._todos_by_scope: dict[str, dict[str, TodoItem]] = {
            "planning": {},
            "execution": {},
        }

    def _scope_bucket(self, scope: str) -> dict[str, TodoItem]:
        if scope not in self._todos_by_scope:
            self._todos_by_scope[scope] = {}
        return self._todos_by_scope[scope]

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _render_list(self, scope: str) -> str:
        """Render the todo list with checkbox indicators."""
        bucket = self._scope_bucket(scope)
        if not bucket:
            return f"No todos in {scope} scope"

        pending = [t for t in bucket.values() if not t.completed]
        completed = [t for t in bucket.values() if t.completed]
        total = len(bucket)
        done = len(completed)

        lines = [f"Scope: {scope}", f"Tasks: {done}/{total} completed"]
        lines.append("")

        for item in pending:
            lines.append(f"  ☐  [{item.id}] {item.content}")

        for item in completed:
            lines.append(f"  ☑  [{item.id}] {item.content}")

        return "\n".join(lines)

    def _make_metadata(self, action: str, scope: str, message: str = "", **extra) -> dict:
        bucket = self._scope_bucket(scope)
        return {
            "action": action,
            "scope": scope,
            "pending": sum(1 for t in bucket.values() if not t.completed),
            "completed": sum(1 for t in bucket.values() if t.completed),
            "total": len(bucket),
            "changed_ids": extra.pop("changed_ids", []),
            "message": message,
            **extra,
        }

    def export_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "planning": [item.to_dict() for item in self._scope_bucket("planning").values()],
            "execution": [item.to_dict() for item in self._scope_bucket("execution").values()],
        }

    def load_state(self, state: dict[str, Any] | None) -> None:
        self._todos_by_scope = {"planning": {}, "execution": {}}
        if not isinstance(state, dict):
            return
        for scope in ("planning", "execution"):
            entries = state.get(scope, [])
            if not isinstance(entries, list):
                continue
            bucket = self._scope_bucket(scope)
            for item_raw in entries:
                if not isinstance(item_raw, dict):
                    continue
                item = TodoItem.from_dict(item_raw)
                if item.id and item.content:
                    bucket[item.id] = item

    def replace_scope_items(self, scope: str, items: list[str]) -> list[str]:
        bucket = self._scope_bucket(scope)
        bucket.clear()
        changed_ids: list[str] = []
        now = self._now()
        for text in items:
            content = text.strip()
            if not content:
                continue
            todo_id = str(uuid.uuid4())[:8]
            bucket[todo_id] = TodoItem(
                id=todo_id,
                content=content,
                completed=False,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            changed_ids.append(todo_id)
        return changed_ids

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = TodosParams(**invocation.params)
        action = params.action
        scope = (params.scope or "execution").lower()
        bucket = self._scope_bucket(scope)

        if action == "add":
            # Collect items from both 'items' list and single 'content'
            to_add: list[str] = []
            if params.items:
                to_add.extend(str(i) for i in params.items)
            if params.content:
                to_add.append(params.content)
            to_add = [item.strip() for item in to_add if item and item.strip()]

            if not to_add:
                return ToolResult.error_result(
                    "'content' or 'items' is required for 'add' action",
                    metadata=self._make_metadata(
                        "add",
                        scope,
                        message="No todo items were provided.",
                    ),
                )

            added_ids = []
            now = self._now()
            for text in to_add:
                todo_id = str(uuid.uuid4())[:8]
                bucket[todo_id] = TodoItem(
                    id=todo_id,
                    content=text,
                    created_at=now,
                    updated_at=now,
                )
                added_ids.append(todo_id)

            return ToolResult.success_result(
                self._render_list(scope),
                metadata=self._make_metadata(
                    "add",
                    scope,
                    changed_ids=added_ids,
                    message=(
                        f"Checklist created with {len(added_ids)} item(s)."
                        if len(added_ids) > 1
                        else "Checklist created with 1 item."
                    ),
                ),
            )

        elif action == "complete":
            if not params.id:
                return ToolResult.error_result(
                    "'id' is required for 'complete' action",
                    metadata=self._make_metadata(
                        "complete",
                        scope,
                        message="Missing todo id.",
                    ),
                )
            if params.id not in bucket:
                return ToolResult.error_result(
                    f"Todo '{params.id}' not found in {scope} scope",
                    metadata=self._make_metadata(
                        "complete",
                        scope,
                        message=f"Todo '{params.id}' not found.",
                    ),
                )

            bucket[params.id].completed = True
            bucket[params.id].completed_at = self._now()
            bucket[params.id].updated_at = self._now()

            return ToolResult.success_result(
                self._render_list(scope),
                metadata=self._make_metadata(
                    "complete",
                    scope,
                    changed_ids=[params.id],
                    message="Marked one checklist item complete.",
                ),
            )

        elif action == "reopen":
            if not params.id:
                return ToolResult.error_result(
                    "'id' is required for 'reopen' action",
                    metadata=self._make_metadata("reopen", scope, message="Missing todo id."),
                )
            if params.id not in bucket:
                return ToolResult.error_result(
                    f"Todo '{params.id}' not found in {scope} scope",
                    metadata=self._make_metadata("reopen", scope, message=f"Todo '{params.id}' not found."),
                )
            bucket[params.id].completed = False
            bucket[params.id].completed_at = None
            bucket[params.id].updated_at = self._now()
            return ToolResult.success_result(
                self._render_list(scope),
                metadata=self._make_metadata(
                    "reopen",
                    scope,
                    changed_ids=[params.id],
                    message="Reopened one checklist item.",
                ),
            )

        elif action == "update":
            if not params.id:
                return ToolResult.error_result(
                    "'id' is required for 'update' action",
                    metadata=self._make_metadata("update", scope, message="Missing todo id."),
                )
            if not params.new_content or not params.new_content.strip():
                return ToolResult.error_result(
                    "'new_content' is required for 'update' action",
                    metadata=self._make_metadata("update", scope, message="Missing new_content."),
                )
            if params.id not in bucket:
                return ToolResult.error_result(
                    f"Todo '{params.id}' not found in {scope} scope",
                    metadata=self._make_metadata("update", scope, message=f"Todo '{params.id}' not found."),
                )
            bucket[params.id].content = params.new_content.strip()
            bucket[params.id].updated_at = self._now()
            return ToolResult.success_result(
                self._render_list(scope),
                metadata=self._make_metadata(
                    "update",
                    scope,
                    changed_ids=[params.id],
                    message="Updated one checklist item.",
                ),
            )

        elif action == "remove":
            if not params.id:
                return ToolResult.error_result(
                    "'id' is required for 'remove' action",
                    metadata=self._make_metadata("remove", scope, message="Missing todo id."),
                )
            if params.id not in bucket:
                return ToolResult.error_result(
                    f"Todo '{params.id}' not found in {scope} scope",
                    metadata=self._make_metadata("remove", scope, message=f"Todo '{params.id}' not found."),
                )
            del bucket[params.id]
            return ToolResult.success_result(
                self._render_list(scope),
                metadata=self._make_metadata(
                    "remove",
                    scope,
                    changed_ids=[params.id],
                    message="Removed one checklist item.",
                ),
            )

        elif action == "list":
            return ToolResult.success_result(
                self._render_list(scope),
                metadata=self._make_metadata("list", scope, message=f"Listed {scope} todos."),
            )

        elif action == "clear":
            count = len(bucket)
            bucket.clear()
            return ToolResult.success_result(
                f"Cleared all {scope} todos",
                metadata=self._make_metadata(
                    "clear",
                    scope,
                    changed_ids=[],
                    cleared=count,
                    message=f"Cleared {count} checklist item(s).",
                ),
            )

        else:
            return ToolResult.error_result(
                "Invalid action. Use: add, complete, list, clear, remove, reopen, update",
                metadata=self._make_metadata("invalid", scope, message="Invalid action."),
            )
