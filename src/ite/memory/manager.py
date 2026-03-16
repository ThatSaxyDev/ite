from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ite.config.loader import get_data_dir
from ite.memory.intent import (
    extract_preference_controls,
    is_memory_probe,
    parse_explicit_memory_instruction,
)
from ite.memory.response_intent import resolve_response_intent

VALID_STORES = ("short_term", "long_term", "episodic", "semantic")
MAX_EPISODIC_ENTRIES = 50


def _project_hash(cwd: str | Path) -> str:
    return hashlib.sha256(str(Path(cwd).resolve()).encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def _make_summary(value: str, limit: int = 140) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _hotness_score(access_count: int, updated_at: str | None) -> float:
    freq = 1.0 / (1.0 + math.exp(-math.log1p(max(access_count, 0))))
    if not updated_at:
        return 0.0
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return 0.0

    now = datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age_days = max((now - updated).total_seconds() / 86400.0, 0.0)
    decay_rate = math.log(2) / 7.0
    recency = math.exp(-decay_rate * age_days)
    return freq * recency


def _lexical_score(query: str, haystack: str) -> float:
    query = _normalize_text(query).lower()
    haystack = _normalize_text(haystack).lower()
    if not query or not haystack:
        return 0.0

    score = 0.0
    if query in haystack:
        score += 0.75

    tokens = [token for token in query.split() if len(token) > 2]
    if not tokens:
        return min(score, 1.0)

    matches = sum(1 for token in tokens if token in haystack)
    score += min(matches / max(len(tokens), 1), 1.0) * 0.5
    return min(score, 1.0)


def _query_profile(query: str) -> dict[str, bool]:
    text = _normalize_text(query).lower()
    return {
        "has_query": bool(text),
        "wants_memory": any(
            token in text
            for token in (
                "remember",
                "memory",
                "last time",
                "previous",
                "decide",
                "decided",
                "focus",
                "focused",
                "working on",
                "session",
            )
        ),
    }


def _updated_sort_key(record: dict[str, Any]) -> tuple[int, str]:
    updated_at = str(record.get("updated_at") or "")
    return (1 if updated_at else 0, updated_at)


class MemoryManager:
    def __init__(
        self,
        cwd: str | Path,
        *,
        session_id: str | None = None,
    ) -> None:
        self.cwd = Path(cwd).resolve()
        self._session_id = session_id

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def set_session_id(self, session_id: str | None) -> None:
        self._session_id = session_id

    def _memory_root(self) -> Path:
        root = get_data_dir() / "memory"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _session_root(self) -> Path:
        root = self._memory_root() / "sessions"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _project_root(self) -> Path:
        root = self._memory_root() / "projects" / _project_hash(self.cwd)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _store_path(self, store: str) -> Path:
        if store == "long_term":
            return self._memory_root() / "long_term.json"
        if store == "semantic":
            return self._project_root() / "semantic.json"
        if store == "episodic":
            return self._project_root() / "episodic.json"
        if store == "short_term":
            if self._session_id:
                session_dir = self._session_root() / self._session_id
                session_dir.mkdir(parents=True, exist_ok=True)
                return session_dir / "short_term.json"
            return self._memory_root() / "short_term.json"
        raise ValueError(f"Unknown store: {store}")

    def _legacy_semantic_path(self) -> Path:
        return self._memory_root() / "projects" / f"{_project_hash(self.cwd)}.json"

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
            os.chmod(path, 0o600)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _load_json(self, path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return default
        if not isinstance(data, dict):
            return default
        return data

    def _normalize_record(
        self,
        key: str,
        value: str | dict[str, Any],
        *,
        scope: str,
        default_source: str = "memory_tool",
    ) -> dict[str, Any]:
        if isinstance(value, str):
            record = {
                "key": key,
                "value": value,
                "summary": _make_summary(value),
                "scope": scope,
                "updated_at": None,
                "access_count": 0,
                "source": "legacy",
            }
        else:
            record = dict(value)
            record.setdefault("key", key)
            record.setdefault("value", str(record.get("value", "")))
            record.setdefault("summary", _make_summary(str(record.get("value", ""))))
            record.setdefault("scope", scope)
            record.setdefault("updated_at", None)
            record.setdefault("access_count", 0)
            record.setdefault("source", default_source)
            record.setdefault("conditional_preferences", [])
        return record

    def _load_entries(self, store: str) -> dict[str, dict[str, Any]]:
        path = self._store_path(store)
        data = self._load_json(path, default={"entries": {}})

        if store == "semantic" and not data.get("entries"):
            legacy_path = self._legacy_semantic_path()
            legacy = self._load_json(legacy_path, default={"entries": {}})
            if legacy.get("entries"):
                data = legacy

        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            return {}

        normalized: dict[str, dict[str, Any]] = {}
        for key, value in entries.items():
            normalized[str(key)] = self._normalize_record(str(key), value, scope=store)
        return normalized

    def _save_entries(self, store: str, entries: dict[str, dict[str, Any]]) -> None:
        self._atomic_write_json(
            self._store_path(store),
            {"entries": entries},
        )

    def _normalize_episode(self, value: dict[str, Any]) -> dict[str, Any]:
        summary = str(value.get("summary", "")).strip()
        return {
            "summary": summary,
            "detail": str(value.get("detail", summary)).strip(),
            "timestamp": str(value.get("timestamp") or _now_iso()),
            "session_id": value.get("session_id"),
            "workspace_id": str(value.get("workspace_id") or self.cwd),
            "source": str(value.get("source") or "memory_tool"),
            "access_count": int(value.get("access_count", 0) or 0),
        }

    def _load_episodes(self) -> list[dict[str, Any]]:
        data = self._load_json(self._store_path("episodic"), default={"episodes": []})
        episodes = data.get("episodes", [])
        if not isinstance(episodes, list):
            episodes = []

        normalized: list[dict[str, Any]] = []
        for episode in episodes:
            if isinstance(episode, dict):
                normalized.append(self._normalize_episode(episode))
        return normalized

    def _save_episodes(self, episodes: list[dict[str, Any]]) -> None:
        self._atomic_write_json(
            self._store_path("episodic"),
            {"episodes": episodes[-MAX_EPISODIC_ENTRIES:]},
        )

    def set_entry(
        self,
        store: str,
        key: str,
        value: str,
        *,
        source: str = "memory_tool",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entries = self._load_entries(store)
        if store == "long_term":
            entries = self._supersede_overlapping_long_term_preferences(
                entries,
                key=key,
                value=value,
                metadata=metadata,
            )
        existing = entries.get(key, {})
        record = self._normalize_record(key, existing or value, scope=store, default_source=source)
        record["value"] = value
        record["summary"] = _make_summary(value)
        record["updated_at"] = _now_iso()
        record["source"] = source
        if metadata:
            for meta_key, meta_value in metadata.items():
                record[meta_key] = meta_value
        entries[key] = record
        self._save_entries(store, entries)
        return record

    def _supersede_overlapping_long_term_preferences(
        self,
        entries: dict[str, dict[str, Any]],
        *,
        key: str,
        value: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        conditional_specs = list((metadata or {}).get("conditional_preferences") or [])
        if conditional_specs:
            updated_entries = dict(entries)
            new_pairs = {
                (str(spec.get("condition", "")), control_key)
                for spec in conditional_specs
                for control_key in dict(spec.get("controls", {}))
            }
            for existing_key, record in list(updated_entries.items()):
                if existing_key == key:
                    continue
                existing_specs = list(record.get("conditional_preferences") or [])
                if not existing_specs:
                    continue
                existing_pairs = {
                    (str(spec.get("condition", "")), control_key)
                    for spec in existing_specs
                    for control_key in dict(spec.get("controls", {}))
                }
                if new_pairs.intersection(existing_pairs):
                    del updated_entries[existing_key]
            return updated_entries

        new_controls = extract_preference_controls(value)
        if not new_controls:
            return entries

        updated_entries = dict(entries)
        control_keys = set(new_controls)
        for existing_key, record in list(updated_entries.items()):
            if existing_key == key:
                continue
            existing_controls = extract_preference_controls(str(record.get("value", "")))
            if not existing_controls:
                continue
            if control_keys.intersection(existing_controls):
                del updated_entries[existing_key]
        return updated_entries

    def get_entry(self, store: str, key: str, *, increment_access: bool = True) -> dict[str, Any] | None:
        entries = self._load_entries(store)
        record = entries.get(key)
        if record is None:
            return None
        if increment_access:
            record["access_count"] = int(record.get("access_count", 0) or 0) + 1
            record["updated_at"] = str(record.get("updated_at") or _now_iso())
            entries[key] = record
            self._save_entries(store, entries)
        return record

    def delete_entry(self, store: str, key: str) -> bool:
        entries = self._load_entries(store)
        if key not in entries:
            return False
        del entries[key]
        self._save_entries(store, entries)
        return True

    def list_entries(self, store: str) -> list[dict[str, Any]]:
        return [entries for _, entries in sorted(self._load_entries(store).items())]

    def latest_entry(self, store: str) -> dict[str, Any] | None:
        entries = self.list_entries(store)
        if not entries:
            return None
        entries.sort(key=_updated_sort_key, reverse=True)
        return entries[0]

    def clear_store(self, store: str) -> int:
        if store == "episodic":
            episodes = self._load_episodes()
            self._save_episodes([])
            return len(episodes)
        entries = self._load_entries(store)
        self._save_entries(store, {})
        return len(entries)

    def append_episode(
        self,
        summary: str,
        *,
        detail: str | None = None,
        source: str = "session",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        episodes = self._load_episodes()
        entry = self._normalize_episode(
            {
                "summary": summary,
                "detail": detail or summary,
                "timestamp": _now_iso(),
                "session_id": session_id or self._session_id,
                "workspace_id": str(self.cwd),
                "source": source,
            }
        )
        episodes.append(entry)
        self._save_episodes(episodes)
        return entry

    def list_episodes(self) -> list[dict[str, Any]]:
        return self._load_episodes()

    def clear_session_short_term(self, session_id: str | None = None) -> None:
        target = session_id or self._session_id
        if not target:
            legacy_path = self._memory_root() / "short_term.json"
            if legacy_path.exists():
                try:
                    legacy_path.unlink()
                except OSError:
                    pass
            return

        session_file = self._session_root() / target / "short_term.json"
        if session_file.exists():
            try:
                session_file.unlink()
            except OSError:
                pass

    def load_prompt_memory(self, current_user_text: str | None = None, *, limit: int = 5) -> dict[str, Any] | None:
        query = current_user_text or ""
        profile = _query_profile(query)
        candidates: list[dict[str, Any]] = []
        controls = self._build_active_controls(query)

        for store in ("short_term", "semantic", "long_term"):
            for record in self.list_entries(store):
                if store == "long_term" and extract_preference_controls(str(record.get("value", ""))):
                    continue
                base = _lexical_score(query, f"{record.get('key', '')} {record.get('summary', '')} {record.get('value', '')}")
                hotness = _hotness_score(
                    int(record.get("access_count", 0) or 0),
                    str(record.get("updated_at") or ""),
                )
                store_boost = {
                    "short_term": 0.25,
                    "semantic": 0.15,
                    "long_term": 0.08,
                }[store]
                candidates.append(
                    {
                        "store": store,
                        "record": record,
                        "base_score": base,
                        "score": base + hotness * 0.35 + store_boost,
                    }
                )

        for episode in self.list_episodes():
            summary_text = str(episode.get("summary", "") or "")
            lowered_summary = summary_text.lower()
            if parse_explicit_memory_instruction(summary_text) is not None:
                continue
            if is_memory_probe(summary_text):
                continue
            if "for this session only, remember" in lowered_summary:
                continue
            if "remember this for this workspace" in lowered_summary:
                continue
            base = _lexical_score(query, f"{episode.get('summary', '')} {episode.get('detail', '')}")
            hotness = _hotness_score(
                int(episode.get("access_count", 0) or 0),
                str(episode.get("timestamp") or ""),
            )
            candidates.append(
                {
                    "store": "episodic",
                    "record": episode,
                    "base_score": base,
                    "score": base + hotness * 0.35 + 0.1,
                }
            )

        selected: list[dict[str, Any]] = []
        if candidates:
            candidates.sort(key=lambda item: item["score"], reverse=True)
            seen: set[str] = set()
            long_term_selected = 0
            for candidate in candidates:
                record = candidate["record"]
                store = str(candidate["store"])
                base_score = float(candidate.get("base_score", 0.0) or 0.0)

                if profile["has_query"]:
                    if store == "long_term":
                        if long_term_selected >= 1:
                            continue
                    elif store == "short_term":
                        if base_score < 0.12 and not profile["wants_memory"]:
                            continue
                    elif store == "semantic":
                        if base_score < 0.1:
                            continue
                    elif store == "episodic":
                        if base_score < 0.12 and not profile["wants_memory"]:
                            continue

                summary = str(record.get("summary") or record.get("value") or "").strip().lower()
                dedupe_key = f"{store}:{summary}"
                if not summary or dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                selected.append(candidate)
                if store == "long_term":
                    long_term_selected += 1
                if len(selected) >= limit:
                    break

        bundle = {
            "controls": controls,
            "short_term": {},
            "long_term": {},
            "episodic": [],
            "semantic": {},
        }

        touched_entry_keys: dict[str, list[str]] = {"short_term": [], "long_term": [], "semantic": []}
        episodic_updates = self.list_episodes()
        episodic_dirty = False
        episodic_lookup = {episode["timestamp"]: episode for episode in episodic_updates}

        for item in selected:
            store = item["store"]
            record = item["record"]
            if store == "episodic":
                bundle["episodic"].append(
                    {
                        "timestamp": record.get("timestamp", ""),
                        "summary": record.get("summary", ""),
                    }
                )
                episode = episodic_lookup.get(str(record.get("timestamp", "")))
                if episode is not None:
                    episode["access_count"] = int(episode.get("access_count", 0) or 0) + 1
                    episodic_dirty = True
                continue

            key = str(record.get("key", "")).strip()
            bundle[store][key] = str(record.get("summary") or record.get("value") or "")
            if key:
                touched_entry_keys[store].append(key)

        for store in ("short_term", "long_term", "semantic"):
            if not touched_entry_keys[store]:
                continue
            entries = self._load_entries(store)
            dirty = False
            for key in touched_entry_keys[store]:
                record = entries.get(key)
                if record is None:
                    continue
                record["access_count"] = int(record.get("access_count", 0) or 0) + 1
                entries[key] = record
                dirty = True
            if dirty:
                self._save_entries(store, entries)

        if episodic_dirty:
            self._save_episodes(episodic_updates)

        has_data = (
            bool(bundle["controls"])
            or any(bundle["short_term"])
            or any(bundle["long_term"])
            or any(bundle["semantic"])
            or bool(bundle["episodic"])
        )
        return bundle if has_data else None

    def _build_active_controls(self, query: str | None = None) -> dict[str, Any]:
        controls: dict[str, Any] = {}
        sources: dict[str, str] = {}
        intent = resolve_response_intent(query or "")
        query_contexts = list(intent.contexts)
        requested_controls = dict(intent.requested_controls)
        applied_contexts: list[str] = []
        entries = sorted(self.list_entries("long_term"), key=_updated_sort_key)
        touched_keys: list[str] = []

        for record in entries:
            key = str(record.get("key", "")).strip()
            summary = str(record.get("summary") or record.get("value") or "").strip()
            conditional_specs = list(record.get("conditional_preferences") or [])
            if conditional_specs:
                matched = False
                for spec in conditional_specs:
                    condition = str(spec.get("condition", "")).strip()
                    if query_contexts and condition not in query_contexts:
                        continue
                    spec_controls = dict(spec.get("controls", {}))
                    if not spec_controls:
                        continue
                    for control_key, control_value in spec_controls.items():
                        controls[control_key] = control_value
                        if summary:
                            sources[control_key] = summary
                    matched = True
                    if condition:
                        applied_contexts.append(condition)
                if matched and key:
                    touched_keys.append(key)
                continue

            record_controls = extract_preference_controls(str(record.get("value", "")))
            if not record_controls:
                continue
            for control_key, control_value in record_controls.items():
                controls[control_key] = control_value
                if summary:
                    sources[control_key] = summary
            if key:
                touched_keys.append(key)

        if touched_keys:
            entries_by_key = self._load_entries("long_term")
            dirty = False
            for key in touched_keys:
                record = entries_by_key.get(key)
                if record is None:
                    continue
                record["access_count"] = int(record.get("access_count", 0) or 0) + 1
                entries_by_key[key] = record
                dirty = True
            if dirty:
                self._save_entries("long_term", entries_by_key)

        for control_key, control_value in requested_controls.items():
            controls[control_key] = control_value
            sources[control_key] = "current request"

        if not controls:
            return {}

        controls["sources"] = sources
        if applied_contexts:
            controls["matched_contexts"] = list(dict.fromkeys(applied_contexts))
        return controls

    def load_active_controls(self, query: str | None = None) -> dict[str, Any]:
        return self._build_active_controls(query)

    def debug_prompt_memory(self, query: str | None, *, limit: int = 5) -> dict[str, Any]:
        return self.load_prompt_memory(query, limit=limit) or {
            "controls": {},
            "short_term": {},
            "long_term": {},
            "episodic": [],
            "semantic": {},
        }
