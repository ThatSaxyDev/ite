from collections import deque
from pathlib import Path
from typing import Any


class LoopDetector:
    def __init__(self):
        self.max_exact_repeats = 3
        self.max_cycle_length = 3
        self._history: deque[str] = deque(maxlen=20)

    def record_action(self, action_type: str, **details: Any):
        output = [action_type]

        if action_type == "tool_call":
            tool_name = details.get("tool_name", "")
            output.append(tool_name)
            args = details.get("args", {})
            cwd = details.get("cwd")

            # Network calls often vary args (different URLs/queries) while still
            # being semantically repetitive. Normalize these to catch loops early.
            if tool_name in {"web_search", "web_fetch"}:
                args = {}
            else:
                args = self._normalize_tool_args(
                    tool_name,
                    args,
                    cwd=cwd,
                )

            if isinstance(args, dict):
                for k in sorted(args.keys()):
                    output.append(f"{k}={str(args[k])}")
        elif action_type == "response":
            output.append(details.get("text", ""))

        signature = "|".join(output)
        self._history.append(signature)

    def check_for_loop(self) -> str | None:
        if len(self._history) < 2:
            return None

        if len(self._history) >= self.max_exact_repeats:
            recent = list(self._history)[-self.max_exact_repeats :]
            if len(set(recent)) == 1:
                return f"Same action repeated {self.max_exact_repeats} times"

        if len(self._history) >= self.max_cycle_length * 2:
            history = list(self._history)

            for cycle_len in range(
                2, min(self.max_cycle_length + 1, len(history) // 2 + 1)
            ):
                recent = history[-cycle_len * 2 :]
                if recent[:cycle_len] == recent[cycle_len:]:
                    return f"Detected repeating cycle of length {cycle_len}"

        return None

    def clear(self) -> None:
        self._history.clear()

    def _normalize_tool_args(
        self,
        tool_name: str,
        args: Any,
        *,
        cwd: Any = None,
    ) -> Any:
        if not isinstance(args, dict):
            return args

        normalized = dict(args)
        if tool_name in {"list_dir", "glob", "grep", "read_file"}:
            for key in ("path",):
                if key in normalized:
                    normalized[key] = self._normalize_path_arg(
                        normalized.get(key),
                        cwd=cwd,
                    )
        if tool_name == "glob":
            pattern = str(normalized.get("pattern") or "").strip()
            normalized["pattern"] = pattern or "**/*"
        if tool_name == "list_dir":
            normalized["include_hidden"] = bool(normalized.get("include_hidden", False))
        return normalized

    def _normalize_path_arg(self, value: Any, *, cwd: Any = None) -> str:
        path_text = str(value or ".").strip() or "."
        if cwd is None:
            return path_text
        try:
            base = Path(str(cwd)).resolve(strict=False)
            candidate = Path(path_text)
            if not candidate.is_absolute():
                candidate = (base / candidate).resolve(strict=False)
            else:
                candidate = candidate.resolve(strict=False)
            return str(candidate)
        except Exception:
            return path_text
