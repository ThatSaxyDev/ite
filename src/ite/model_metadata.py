from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelMetadata:
    model_name: str
    context_window: int | None = None
    source: str | None = None
    supports_vision: bool = False


# Vision-capable model identifiers. Models whose name contains any of these
# prefixes/substrings are assumed to support image inputs.
_VISION_MODEL_PATTERNS = (
    "claude",
    "gpt-4o",
    "gpt-4.1",
    "gemini",
    "gemma-3",
    "gemma3",
    "pixtral",
    "llava",
    "bakllava",
    "cogvlm",
    "deepseek-v4",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "minicpm-v",
    "phi-3-vision",
    "phi-3.5-vision",
    "phi-4-vision",
    "internvl",
    "internlm-xcomposer",
    "yi-vision",
    "fuyu",
    "paligemma",
    "ovis",
    "moondream",
    "instructblip",
    "florence",
    "janus",
    "mantis",
    "aria",
)


def detect_vision_from_model_name(model_name: str) -> bool:
    """Heuristic: detect multimodal/vision support from model name patterns."""
    normalized = model_name.strip().lower()
    for pattern in _VISION_MODEL_PATTERNS:
        if pattern in normalized:
            return True
    return False


def _openrouter_modality_from_item(item: dict[str, Any]) -> str | None:
    architecture = item.get("architecture")
    if isinstance(architecture, dict):
        modality = architecture.get("modality")
        if isinstance(modality, str):
            return modality.strip().lower()
    return None


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

    modality = _openrouter_modality_from_item(item)
    if modality:
        supports_vision = modality == "multimodal"
    else:
        supports_vision = detect_vision_from_model_name(model_name)

    return ModelMetadata(
        model_name=model_name,
        context_window=context_window,
        source="openrouter_models_api",
        supports_vision=supports_vision,
    )


def parse_ollama_model_metadata(
    *,
    model_name: str,
    payload: dict[str, Any],
) -> ModelMetadata:
    context_window = _extract_ollama_context_window(payload)
    supports_vision = detect_vision_from_model_name(model_name)
    return ModelMetadata(
        model_name=model_name,
        context_window=context_window,
        source="ollama_show_api",
        supports_vision=supports_vision,
    )


def format_context_window_label(value: int | None) -> str:
    if not value or value <= 0:
        return "Unknown"
    if value >= 1_000_000:
        millions = value / 1_000_000
        if millions >= 10:
            return f"{round(millions)}M"
        if millions == int(millions):
            return f"{int(millions)}M"
        result = f"{millions:.1f}M"
        if result.endswith(".0M"):
            return f"{round(millions)}M"
        return result
    rounded = round(value / 1000) * 1000
    if rounded >= 1_000_000:
        return f"{rounded // 1_000_000}M" if rounded % 1_000_000 == 0 else f"{rounded / 1_000_000:.1f}M"
    return f"{rounded // 1000}K"


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
