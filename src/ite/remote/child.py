from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


def main() -> int:
    """Entry point for one provisioned runtime process.

    Started by the host supervisor as an isolated child. Everything it needs
    arrives in the environment; it holds no user login of its own.
    """
    api_url = os.environ.get("ITE_CLOUD_API_URL", "").strip()
    runtime_id = os.environ.get("ITE_RUNTIME_ID", "").strip()
    runtime_token = os.environ.get("ITE_RUNTIME_TOKEN", "").strip()

    if not api_url or not runtime_token:
        print(
            "This entry point is internal: it is started by `ite remote serve` "
            "with a cloud-issued runtime token. Run that instead.",
            file=sys.stderr,
        )
        return 2

    from ite.remote.runtime import run_provisioned_runtime

    workspace = Path(os.environ.get("ITE_WORKSPACE") or Path.cwd())
    asyncio.run(
        run_provisioned_runtime(
            workspace,
            api_url=api_url,
            runtime_id=runtime_id,
            runtime_token=runtime_token,
            token_file=os.environ.get("ITE_RUNTIME_TOKEN_FILE", ""),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
