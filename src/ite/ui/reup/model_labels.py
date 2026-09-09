from __future__ import annotations

BUNDLED_MODEL_DISPLAY_NAMES_BY_MODEL: dict[str, str] = {
    "deepseek-v4": "DeepSeek V4",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro",
    "minimax-m3": "MiniMax M3",
    "minimax/minimax-m3": "MiniMax M3",
    "stealth-ox-alpha": "Stealth OX Alpha",
    "stealth/ox-alpha": "Stealth OX Alpha",
}


def bundled_model_display_label(model_name: str, label: str | None = None) -> str:
    """Return the public UI label for a bundled model without changing its id."""
    normalized_model = str(model_name or "").strip()
    public_name = BUNDLED_MODEL_DISPLAY_NAMES_BY_MODEL.get(normalized_model.lower())
    if public_name:
        return public_name
    return str(label or normalized_model).strip()
