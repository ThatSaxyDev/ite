import json
import hashlib
from datetime import datetime
from ite.config.loader import get_data_dir
from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import BaseModel, Field


VALID_STORES = ("short_term", "long_term", "episodic", "semantic")
MAX_EPISODIC_ENTRIES = 50


class MemoryParams(BaseModel):
    action: str = Field(
        ..., description="Action: 'set', 'get', 'delete', 'list', 'clear'"
    )
    store: str = Field(
        "long_term",
        description="Memory store: 'short_term' (session-scoped scratch notes), 'long_term' (persistent user preferences), 'episodic' (session summaries/milestones), 'semantic' (project-specific knowledge). Defaults to 'long_term'.",
    )
    key: str | None = Field(
        None, description="Memory key (required for `set`, `get`, `delete`)"
    )
    value: str | None = Field(None, description="Value to store (required for `set`)")


def _get_project_hash(cwd: str) -> str:
    return hashlib.sha256(cwd.encode()).hexdigest()[:12]


class MemoryTool(Tool):
    name = "memory"
    description = (
        "Store and retrieve persistent memory across multiple stores. "
        "Stores: 'short_term' (session scratch), 'long_term' (user preferences, default), "
        "'episodic' (session milestones), 'semantic' (project knowledge)."
    )
    kind = ToolKind.MEMORY
    schema = MemoryParams

    def _get_memory_path(self, store: str, cwd: str | None = None):
        data_dir = get_data_dir()
        memory_dir = data_dir / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        if store == "semantic" and cwd:
            project_dir = memory_dir / "projects"
            project_dir.mkdir(parents=True, exist_ok=True)
            return project_dir / f"{_get_project_hash(cwd)}.json"

        return memory_dir / f"{store}.json"

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

        if store not in VALID_STORES:
            return ToolResult.error_result(
                f"Invalid store: '{store}'. Valid stores: {', '.join(VALID_STORES)}"
            )

        self._migrate_legacy()

        action = params.action.lower()

        if store == "episodic":
            return self._handle_episodic(action, params, cwd)

        if action == "set":
            return self._handle_set(store, params, cwd)
        elif action == "get":
            return self._handle_get(store, params, cwd)
        elif action == "delete":
            return self._handle_delete(store, params, cwd)
        elif action == "list":
            return self._handle_list(store, cwd)
        elif action == "clear":
            return self._handle_clear(store, cwd)
        else:
            return ToolResult.error_result(f"Unknown action: {action}")

    def _handle_set(self, store: str, params: MemoryParams, cwd: str) -> ToolResult:
        if not params.key or not params.value:
            return ToolResult.error_result(
                "`key` and `value` are required for 'set' action"
            )
        data = self._load_store(store, cwd)
        data.setdefault("entries", {})[params.key] = params.value
        self._save_store(store, data, cwd)
        return ToolResult.success_result(f"[{store}] Set: {params.key}")

    def _handle_get(self, store: str, params: MemoryParams, cwd: str) -> ToolResult:
        if not params.key:
            return ToolResult.error_result("`key` required for 'get' action")
        data = self._load_store(store, cwd)
        entries = data.get("entries", {})
        if params.key not in entries:
            return ToolResult.success_result(
                f"[{store}] Not found: {params.key}",
                metadata={"found": False},
            )
        return ToolResult.success_result(
            f"[{store}] {params.key}: {entries[params.key]}",
            metadata={"found": True},
        )

    def _handle_delete(self, store: str, params: MemoryParams, cwd: str) -> ToolResult:
        if not params.key:
            return ToolResult.error_result("`key` required for 'delete' action")
        data = self._load_store(store, cwd)
        entries = data.get("entries", {})
        if params.key not in entries:
            return ToolResult.success_result(f"[{store}] Not found: {params.key}")
        del entries[params.key]
        self._save_store(store, data, cwd)
        return ToolResult.success_result(f"[{store}] Deleted: {params.key}")

    def _handle_list(self, store: str, cwd: str) -> ToolResult:
        data = self._load_store(store, cwd)
        entries = data.get("entries", {})
        if not entries:
            return ToolResult.success_result(
                f"[{store}] No memories stored", metadata={"found": False}
            )
        lines = [f"[{store}] Stored memories:"]
        for key, value in sorted(entries.items()):
            lines.append(f"  {key}: {value}")
        return ToolResult.success_result("\n".join(lines), metadata={"found": True})

    def _handle_clear(self, store: str, cwd: str) -> ToolResult:
        data = self._load_store(store, cwd)
        count = len(data.get("entries", {}))
        data["entries"] = {}
        self._save_store(store, data, cwd)
        return ToolResult.success_result(f"[{store}] Cleared {count} entries")

    # --- Episodic memory (append-only list with timestamps) ---

    def _handle_episodic(
        self, action: str, params: MemoryParams, cwd: str
    ) -> ToolResult:
        data = self._load_store("episodic", cwd)
        episodes = data.get("episodes", [])

        if action == "set":
            if not params.value:
                return ToolResult.error_result(
                    "`value` is required for episodic 'set' action"
                )
            entry = {
                "timestamp": datetime.now().isoformat(),
                "summary": params.value,
                "key": params.key,
            }
            episodes.append(entry)
            if len(episodes) > MAX_EPISODIC_ENTRIES:
                episodes = episodes[-MAX_EPISODIC_ENTRIES:]
            data["episodes"] = episodes
            self._save_store("episodic", data, cwd)
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
                key = f" ({ep['key']})" if ep.get("key") else ""
                lines.append(f"  {ts}{key}: {ep['summary']}")
            return ToolResult.success_result("\n".join(lines), metadata={"found": True})

        elif action == "clear":
            count = len(episodes)
            data["episodes"] = []
            self._save_store("episodic", data, cwd)
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
        data_dir = get_data_dir()
        memory_dir = data_dir / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / "episodic.json"

        data = {"episodes": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

        episodes = data.get("episodes", [])
        episodes.append(
            {
                "timestamp": datetime.now().isoformat(),
                "summary": summary,
                "key": key or "auto_save",
            }
        )
        if len(episodes) > MAX_EPISODIC_ENTRIES:
            episodes = episodes[-MAX_EPISODIC_ENTRIES:]
        data["episodes"] = episodes
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @staticmethod
    def load_all_memory(cwd: str) -> dict:
        """Load all memory stores for system prompt injection."""
        data_dir = get_data_dir()
        memory_dir = data_dir / "memory"
        result = {
            "short_term": {},
            "long_term": {},
            "episodic": [],
            "semantic": {},
        }

        # Long-term
        lt_path = memory_dir / "long_term.json"
        if lt_path.exists():
            try:
                data = json.loads(lt_path.read_text(encoding="utf-8"))
                result["long_term"] = data.get("entries", {})
            except Exception:
                pass

        # Short-term
        st_path = memory_dir / "short_term.json"
        if st_path.exists():
            try:
                data = json.loads(st_path.read_text(encoding="utf-8"))
                result["short_term"] = data.get("entries", {})
            except Exception:
                pass

        # Episodic (last 5 for system prompt)
        ep_path = memory_dir / "episodic.json"
        if ep_path.exists():
            try:
                data = json.loads(ep_path.read_text(encoding="utf-8"))
                result["episodic"] = data.get("episodes", [])[-5:]
            except Exception:
                pass

        # Semantic (per-project)
        project_hash = _get_project_hash(cwd)
        sem_path = memory_dir / "projects" / f"{project_hash}.json"
        if sem_path.exists():
            try:
                data = json.loads(sem_path.read_text(encoding="utf-8"))
                result["semantic"] = data.get("entries", {})
            except Exception:
                pass

        return result
