from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelMetadata:
    model_name: str
    context_window: int | None = None
    source: str | None = None


def parse_openrouter_model_metadata(item: dict[str, Any]) -> ModelMetadata | None:
    model_name = str(item.get("id") or "").strip()
    if not model_name:
        return None

    context_window = _parse_int(
        item.get("top_provider", {}).get("context_length")
        if isinstance(item.get("top_provider"), dict)
        else None
    )
    if context_window is None:
        context_window = _parse_int(item.get("context_length"))

    return ModelMetadata(
        model_name=model_name,
        context_window=context_window,
        source="openrouter_models_api",
    )


def parse_ollama_model_metadata(
    *,
    model_name: str,
    payload: dict[str, Any],
) -> ModelMetadata:
    context_window = _extract_ollama_context_window(payload)
    return ModelMetadata(
        model_name=model_name,
        context_window=context_window,
        source="ollama_show_api",
    )


def format_context_window_label(value: int | None) -> str:
    if not value or value <= 0:
        return "Unknown"
    if value % 1024 == 0:
        return f"{value // 1024}K"
    return f"{value:,}"


def _extract_ollama_context_window(payload: dict[str, Any]) -> int | None:
    model_info = payload.get("model_info")
    if isinstance(model_info, dict):
        candidates: list[tuple[str, Any]] = []
        for key, value in model_info.items():
            key_text = str(key or "").strip().lower()
            if key_text.endswith(".context_length") or key_text == "context_length":
                candidates.append((key_text, value))
        if candidates:
            parsed = [
                parsed_value
                for _key, value in candidates
                if (parsed_value := _parse_int(value)) is not None and parsed_value > 0
            ]
            if parsed:
                return max(parsed)

    details = payload.get("details")
    if isinstance(details, dict):
        parsed = _parse_int(details.get("context_length"))
        if parsed and parsed > 0:
            return parsed

    return None


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None
