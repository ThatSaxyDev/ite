import json
from ite.config.loader import get_data_dir
from ite.memory import MemoryManager, VALID_STORES, should_reject_durable_memory_capture
from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class MemoryParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    action: str = Field(
        ...,
        description="Action: 'set', 'get', 'delete', 'list', 'clear'",
        validation_alias=AliasChoices(
            "action",
            "op",
            "operation",
            "mode",
            "verb",
            "type",
            "command",
        ),
    )
    store: str = Field(
        "long_term",
        description="Memory store: 'short_term' (session-scoped scratch notes), 'long_term' (persistent user preferences), 'episodic' (session summaries/milestones), 'semantic' (project-specific knowledge). Defaults to 'long_term'.",
    )
    key: str | None = Field(
        None, description="Memory key (required for `set`, `get`, `delete`)"
    )
    value: str | None = Field(None, description="Value to store (required for `set`)")

    @model_validator(mode="before")
    @classmethod
    def _infer_action_when_missing(cls, data):
        if not isinstance(data, dict):
            return data
        if any(
            key in data
            for key in ("action", "op", "operation", "mode", "verb", "type", "command")
        ):
            return data
        inferred = dict(data)
        if inferred.get("value") not in (None, ""):
            inferred["action"] = "set"
        elif inferred.get("key") not in (None, ""):
            inferred["action"] = "get"
        else:
            inferred["action"] = "list"
        return inferred


class MemoryTool(Tool):
    name = "memory"
    description = (
        "Store and retrieve persistent memory across multiple stores. "
        "Stores: 'short_term' (session scratch), 'long_term' (user preferences, default), "
        "'episodic' (session milestones), 'semantic' (project knowledge)."
    )
    kind = ToolKind.MEMORY
    schema = MemoryParams

    def __init__(self, config) -> None:
        super().__init__(config)
        self._session_id: str | None = None
        self._managers: dict[tuple[str, str | None], MemoryManager] = {}

    def set_session_id(self, session_id: str | None) -> None:
        self._session_id = session_id

    def _manager(self, cwd: str | None = None, session_id: str | None = None) -> MemoryManager:
        resolved_cwd = str(cwd or self.config.cwd)
        resolved_session_id = session_id or self._session_id
        key = (resolved_cwd, resolved_session_id)
        manager = self._managers.get(key)
        if manager is None:
            manager = MemoryManager(
                resolved_cwd,
                session_id=resolved_session_id,
            )
            self._managers[key] = manager
        return manager

    def _get_memory_path(self, store: str, cwd: str | None = None):
        return self._manager(cwd)._store_path(store)

    def _migrate_legacy(self):
        """Migrate old user_memory.json to new long_term.json if needed."""
        data_dir = get_data_dir()
        legacy_path = data_dir / "user_memory.json"

        if not legacy_path.exists():
            return

        try:
            content = legacy_path.read_text(encoding="utf-8")
            data = json.loads(content)
            entries = data.get("entries", {})

            if entries:
                lt_path = self._get_memory_path("long_term")
                lt_data = self._load_store_file(lt_path)

                for key, value in entries.items():
                    if key not in lt_data.get("entries", {}):
                        lt_data.setdefault("entries", {})[key] = value

                self._save_store_file(lt_path, lt_data)

            legacy_path.rename(legacy_path.with_suffix(".json.bak"))
        except Exception:
            pass

    def _load_store_file(self, path) -> dict:
        if not path.exists():
            return {"entries": {}}
        try:
            content = path.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception:
            return {"entries": {}}

    def _save_store_file(self, path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load_store(self, store: str, cwd: str | None = None) -> dict:
        path = self._get_memory_path(store, cwd)
        return self._load_store_file(path)

    def _save_store(self, store: str, data: dict, cwd: str | None = None) -> None:
        path = self._get_memory_path(store, cwd)
        self._save_store_file(path, data)

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = MemoryParams(**invocation.params)
        store = params.store.lower()
        cwd = str(invocation.cwd)
        manager = self._manager(cwd)

        if store not in VALID_STORES:
            return ToolResult.error_result(
                f"Invalid store: '{store}'. Valid stores: {', '.join(VALID_STORES)}"
            )

        self._migrate_legacy()

        action = self._normalize_action(params.action, params)

        if store == "episodic":
            return self._handle_episodic(manager, action, params)

        if action == "set":
            result = self._handle_set(manager, store, params)
        elif action == "get":
            result = self._handle_get(manager, store, params)
        elif action == "delete":
            result = self._handle_delete(manager, store, params)
        elif action == "list":
            result = self._handle_list(manager, store)
        elif action == "clear":
            result = self._handle_clear(manager, store)
        else:
            result = ToolResult.error_result(f"Unknown action: {action}")

        metadata = result.metadata or {}
        metadata.setdefault("store", store)
        metadata["persistent"] = manager.persistent_available
        metadata["degraded_mode"] = manager.degraded_mode
        result.metadata = metadata
        return result

    def _normalize_action(self, action: str, params: MemoryParams) -> str:
        normalized = (action or "").strip().lower()
        synonyms = {
            "update": "set",
            "save": "set",
            "store": "set",
            "remember": "set",
            "append": "set",
            "add": "set",
            "read": "get",
            "fetch": "get",
            "show": "get" if params.key else "list",
            "remove": "delete",
            "forget": "delete",
            "erase": "delete",
        }
        return synonyms.get(normalized, normalized)

    def _handle_set(self, manager: MemoryManager, store: str, params: MemoryParams) -> ToolResult:
        if not params.key or not params.value:
            return ToolResult.error_result(
                "`key` and `value` are required for 'set' action"
            )
        if should_reject_durable_memory_capture(store, params.value):
            return ToolResult.success_result(
                f"[{store}] Skipped weak or speculative memory: {params.key}",
                metadata={"stored": False, "reason": "weak_or_speculative"},
            )
        manager.set_entry(store, params.key, params.value, source="memory_tool")
        return ToolResult.success_result(
            f"[{store}] Set: {params.key}",
            metadata={"stored": True},
        )

    def _handle_get(self, manager: MemoryManager, store: str, params: MemoryParams) -> ToolResult:
        if not params.key:
            return ToolResult.error_result("`key` required for 'get' action")
        record = manager.get_entry(store, params.key)
        if record is None:
            return ToolResult.success_result(
                f"[{store}] Not found: {params.key}",
                metadata={"found": False},
            )
        return ToolResult.success_result(
            f"[{store}] {params.key}: {record.get('value', '')}",
            metadata={"found": True, "summary": record.get("summary")},
        )

    def _handle_delete(self, manager: MemoryManager, store: str, params: MemoryParams) -> ToolResult:
        if not params.key:
            return ToolResult.error_result("`key` required for 'delete' action")
        deleted = manager.delete_entry(store, params.key)
        if not deleted:
            return ToolResult.success_result(f"[{store}] Not found: {params.key}")
        return ToolResult.success_result(f"[{store}] Deleted: {params.key}")

    def _handle_list(self, manager: MemoryManager, store: str) -> ToolResult:
        entries = manager.list_entries(store)
        if not entries:
            return ToolResult.success_result(
                f"[{store}] No memories stored", metadata={"found": False}
            )
        lines = [f"[{store}] Stored memories:"]
        for record in entries:
            lines.append(
                f"  {record.get('key')}: {record.get('summary') or record.get('value', '')}"
            )
        return ToolResult.success_result("\n".join(lines), metadata={"found": True})

    def _handle_clear(self, manager: MemoryManager, store: str) -> ToolResult:
        count = manager.clear_store(store)
        return ToolResult.success_result(f"[{store}] Cleared {count} entries")

    # --- Episodic memory (append-only list with timestamps) ---

    def _handle_episodic(
        self, manager: MemoryManager, action: str, params: MemoryParams
    ) -> ToolResult:
        episodes = manager.list_episodes()

        if action == "set":
            if not params.value:
                return ToolResult.error_result(
                    "`value` is required for episodic 'set' action"
                )
            manager.append_episode(
                params.value,
                detail=params.value,
                source="memory_tool",
            )
            return ToolResult.success_result(
                f"[episodic] Recorded: {params.value[:80]}"
            )

        elif action == "list":
            if not episodes:
                return ToolResult.success_result(
                    "[episodic] No episodes recorded", metadata={"found": False}
                )
            lines = ["[episodic] Recent episodes:"]
            for ep in episodes[-10:]:
                ts = ep.get("timestamp", "?")[:10]
                session_id = ep.get("session_id")
                tag = f" ({session_id})" if session_id else ""
                lines.append(f"  {ts}{tag}: {ep['summary']}")
            return ToolResult.success_result("\n".join(lines), metadata={"found": True})

        elif action == "clear":
            count = len(episodes)
            manager.clear_store("episodic")
            return ToolResult.success_result(f"[episodic] Cleared {count} episodes")

        elif action in ("get", "delete"):
            return ToolResult.error_result(
                "Episodic memory is append-only. Use 'set' to add, 'list' to view, or 'clear' to reset."
            )
        else:
            return ToolResult.error_result(f"Unknown action: {action}")

    # --- Static helper for auto-save from /save command ---

    @staticmethod
    def append_episodic_entry(summary: str, cwd: str, key: str | None = None) -> None:
        """Append a one-line episodic entry (called from /save command)."""
        MemoryManager(cwd, session_id=key).append_episode(
            summary,
            detail=summary,
            source="session_save",
            session_id=key,
        )

    @staticmethod
    def load_all_memory(cwd: str) -> dict:
        """Load all memory stores for system prompt injection."""
        return MemoryManager(cwd).load_prompt_memory(None) or {
            "short_term": {},
            "long_term": {},
            "episodic": [],
            "semantic": {},
        }
