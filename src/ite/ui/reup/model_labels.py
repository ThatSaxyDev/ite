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


# DeepSeek reasoning-effort levels, 1:1 with the upstream API. `none` disables
# thinking mode entirely; `low` / `high` / `max` enable it at increasing
# effort. The default effort is `high`. (For API compatibility `minimal` is
# accepted upstream and mapped to `low`; `medium`/`xhigh` map to `high`.)
REASONING_LEVELS: list[tuple[str, str, str]] = [
    ("none", "Off", "No extended thinking"),
    ("low", "Low", "Minimal reasoning"),
    ("high", "High", "Deep reasoning"),
    ("max", "Extra High", "Maximum reasoning"),
]

DEFAULT_REASONING_EFFORT = "low"


def reasoning_effort_display_label(value: str | None) -> str:
    """Return the human label for a reasoning-effort value (defaults to High)."""
    normalized = str(value or "").strip().lower()
    if normalized == "minimal":
        normalized = "low"
    if normalized in {"xhigh", "medium"}:
        normalized = "high"
    for wire_value, label, _description in REASONING_LEVELS:
        if wire_value == normalized:
            return label
    return "Low"
