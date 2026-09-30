from __future__ import annotations

import httpx


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(str(value))
    except (ValueError, TypeError):
        return None
    return result if result > 0 else None


async def discover_context_window(base_url: str, model_name: str) -> int | None:
    """Read metadata only; never load a model or spend inference credits."""
    root = base_url.rstrip("/").removesuffix("/v1")
    cloud = model_name.endswith((":cloud", "-cloud"))
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
        async def read(url: str, model: str | None = None) -> dict:
            try:
                response = (
                    await client.post(url, json={"model": model})
                    if model is not None
                    else await client.get(url)
                )
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except (httpx.HTTPError, ValueError):
                return {}

        if not cloud:
            running = await read(f"{root}/api/ps")
            models = running.get("models")
            for item in models if isinstance(models, list) else []:
                if isinstance(item, dict) and item.get("name", item.get("model")) in {
                    model_name, f"{model_name}:latest",
                }:
                    allocated = _positive_int(item.get("context_length"))
                    if allocated:
                        return allocated

        details = await read(f"{root}/api/show", model_name)
        if cloud and not details.get("model_info"):
            remote_name = (
                model_name.removesuffix(":cloud")
                if model_name.endswith(":cloud")
                else model_name.removesuffix("-cloud")
            )
            details = await read("https://ollama.com/api/show", remote_name)
        info = details.get("model_info")
        architecture = info.get("general.architecture") if isinstance(info, dict) else None
        maximum = (
            _positive_int(info.get(f"{architecture}.context_length"))
            if architecture and isinstance(info, dict)
            else None
        )
        if maximum is None and isinstance(info, dict):
            limits = [
                limit for key, value in info.items()
                if key.endswith(".context_length")
                and (limit := _positive_int(value)) is not None
            ]
            maximum = min(limits) if limits else None
        if cloud:
            return maximum
        for line in str(details.get("parameters") or "").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "num_ctx":
                configured = _positive_int(parts[1])
                if configured:
                    return min(configured, maximum) if maximum else configured
        # The model maximum does not reveal the server's allocation.
        return None
