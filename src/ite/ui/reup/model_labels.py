from __future__ import annotations

BUNDLED_MODEL_DISPLAY_NAMES_BY_MODEL: dict[str, str] = {
    "deepseek-v4": "cortex",
    "deepseek-v4-pro": "cortex",
    "deepseek/deepseek-v4-pro": "cortex",
    "minimax-m3": "contessa",
    "minimax/minimax-m3": "contessa",
    "stealth-ox-alpha": "Stealthy Alpha",
    "stealth/ox-alpha": "Stealthy Alpha",
}

BUNDLED_MODEL_DISPLAY_NAMES_BY_LABEL: dict[str, str] = {
    "deepseek v4 pro": "cortex",
    "minimax m3": "contessa",
    "stealthy alpha": "Stealthy Alpha",
}


def bundled_model_display_label(model_name: str, label: str | None = None) -> str:
    """Return the public UI label for a bundled model without changing its id."""
    normalized_model = str(model_name or "").strip()
    public_name = BUNDLED_MODEL_DISPLAY_NAMES_BY_MODEL.get(normalized_model.lower())
    if public_name:
        return public_name

    fallback = str(label or normalized_model).strip()
    return BUNDLED_MODEL_DISPLAY_NAMES_BY_LABEL.get(fallback.lower(), fallback)
