from typing import Any
from urllib.parse import urlparse
import ast
import re


class AgentError(Exception):
    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.cause = cause

    def __str__(self) -> str:
        base = self.message
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            base = f"{base} ({detail_str})"
        if self.cause:
            base = f"{base} [caused by: {self.cause}]"
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }


class ConfigError(AgentError):
    def __init__(
        self,
        message: str,
        config_key: str | None = None,
        config_file: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {}) or {}
        if config_key:
            details["config_key"] = config_key
        if config_file:
            details["config_file"] = config_file
        super().__init__(message, details=details, **kwargs)
        self.config_key = config_key
        self.config_file = config_file


def format_provider_error(
    *,
    kind: str,
    message: str,
    status_code: int | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
) -> str:
    raw = str(message or "").strip()
    lowered = raw.lower()

    if kind == "rate_limit":
        return "Rate limit reached.\nCheck provider limits or wait a moment before retrying."

    if kind == "connection":
        headline = "Could not connect to the model provider."
        details = _provider_context_details(model_name, base_url) + _connection_details(raw)
        return _render_error(headline, details)

    if kind == "api":
        payload = _extract_error_payload(raw)
        provider_message = _payload_message(payload) or raw
        provider_details = _payload_details(payload)
        context_details = _provider_context_details(model_name, base_url)

        if "model" in provider_message.lower() and "not found" in provider_message.lower():
            headline = "The selected model was not found by the provider."
            details = context_details[:]
            model_name = _extract_quoted_value(provider_message)
            if model_name:
                details.append(f"Model: {model_name}")
            if status_code is not None:
                details.append(f"Status: {status_code}")
            details.append("Check the exact model name and whether it is available on the current backend.")
            return _render_error(headline, details)

        if "no such host" in lowered or "dial tcp" in lowered or "lookup " in lowered:
            headline = "The provider could not reach its upstream host."
            details = context_details + _connection_details(provider_message)
            if status_code is not None:
                details.append(f"Status: {status_code}")
            return _render_error(headline, details)

        if status_code == 502:
            headline = "The provider returned a bad gateway error."
            details = context_details[:]
            if provider_message and provider_message != raw:
                details.append(provider_message)
            elif raw:
                details.append(raw)
            details.extend(provider_details)
            details.append("This usually means a temporary upstream or networking problem.")
            return _render_error(headline, details)

        if is_context_overflow_error(provider_message):
            headline = "The request exceeded the provider's context limit."
            details = context_details[:]
            if status_code is not None:
                details.append(f"Status: {status_code}")
            details.append(provider_message)
            details.append("The thread history is too large for the current model or backend limit.")
            return _render_error(headline, details)

        headline = "The model provider returned an API error."
        details = context_details[:]
        if status_code is not None:
            details.append(f"Status: {status_code}")
        if provider_message:
            details.append(provider_message)
        details.extend(provider_details)
        if provider_message.strip().lower() == "provider returned error":
            details.append("The backend returned a generic upstream failure without a specific cause.")
            details.append("Check whether this model is currently available on the selected provider and whether your account still has access.")
        return _render_error(headline, details)

    return raw or "Unknown error."


def _render_error(headline: str, details: list[str]) -> str:
    cleaned = [str(item).strip() for item in details if str(item or "").strip()]
    if not cleaned:
        return headline
    return headline + "\n" + "\n".join(f"- {item}" for item in cleaned)


def _connection_details(raw: str) -> list[str]:
    details: list[str] = []
    url_match = re.search(r'https?://[^"\s]+', raw)
    if url_match:
        parsed = urlparse(url_match.group(0))
        if parsed.netloc:
            details.append(f"Host: {parsed.netloc}")
    lookup_match = re.search(r"lookup ([^:\s]+)", raw)
    if lookup_match:
        details.append(f"DNS lookup failed for: {lookup_match.group(1)}")
    if "no such host" in raw.lower():
        details.append("DNS could not resolve the hostname.")
    elif raw:
        details.append(raw)
    return details


def _provider_context_details(model_name: str | None, base_url: str | None) -> list[str]:
    details: list[str] = []
    if model_name:
        details.append(f"Model: {model_name}")
    if base_url:
        parsed = urlparse(base_url)
        host = parsed.netloc or base_url
        details.append(f"Backend: {host}")
    return details


def _extract_error_payload(raw: str) -> dict[str, Any] | None:
    if " - " not in raw:
        return None
    payload_text = raw.split(" - ", 1)[1].strip()
    try:
        payload = ast.literal_eval(payload_text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _payload_message(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message", "")).strip()
    if isinstance(error, str):
        return error.strip()
    return ""


def _payload_details(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    error = payload.get("error")
    if not isinstance(error, dict):
        return []
    details: list[str] = []
    err_type = str(error.get("type") or "").strip()
    err_code = str(error.get("code") or "").strip()
    err_param = str(error.get("param") or "").strip()
    if err_type:
        details.append(f"Type: {err_type}")
    if err_code and err_code.lower() != "none":
        details.append(f"Code: {err_code}")
    if err_param and err_param.lower() != "none":
        details.append(f"Param: {err_param}")
    metadata = error.get("metadata")
    if isinstance(metadata, dict):
        provider_name = str(metadata.get("provider_name") or metadata.get("provider") or "").strip()
        raw_message = str(metadata.get("raw") or metadata.get("raw_message") or "").strip()
        if provider_name:
            details.append(f"Provider: {provider_name}")
        if raw_message and raw_message.lower() != "provider returned error":
            details.append(f"Upstream: {raw_message}")
    return details


def _extract_quoted_value(text: str) -> str:
    match = re.search(r"'([^']+)'", text)
    if match:
        return match.group(1)
    return ""


def is_context_overflow_error(message: str) -> bool:
    lowered = str(message or "").lower()
    phrases = (
        "prompt too long",
        "context length",
        "maximum context length",
        "max context length",
        "too many tokens",
        "maximum number of tokens",
        "exceeded max context",
        "exceeded context window",
    )
    return any(phrase in lowered for phrase in phrases)
