from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    cwd = Path(os.environ.get("ITE_CWD") or ".").resolve()
    log_path = cwd / ".ite" / "hook.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": os.environ.get("ITE_TRIGGER"),
        "cwd": os.environ.get("ITE_CWD"),
        "tool_name": os.environ.get("ITE_TOOL_NAME"),
        "tool_params": os.environ.get("ITE_TOOL_PARAMS"),
        "user_message": os.environ.get("ITE_USER_MESSAGE"),
        "response_present": bool(os.environ.get("ITE_RESPONSE")),
        "error": os.environ.get("ITE_ERROR"),
    }

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("[HOOK] " + json.dumps(payload, sort_keys=True) + "\n")

    print(f"hook logged: {payload['trigger']}")


if __name__ == "__main__":
    main()
