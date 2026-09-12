"""Turn retry / silent-recovery logic, shared by the TUI and the headless daemon.

Extracted from ``ReupApp`` (``ite/src/ite/ui/reup/_composer.py:1619-1680``) so both
surfaces decide "retry, continue, or give up" with the SAME code. These functions are
pure: they read and write fields on a :class:`SessionRunState` and nothing else.

This is the drift-prone part of the turn loop — keep it here, not duplicated.
"""

from __future__ import annotations

from typing import Any

from ite.runtime.state import SessionRunState

MAX_FAILURE_RECOVERY_ATTEMPTS = 3
MAX_IN_STREAM_RECOVERY_ATTEMPTS = 1

CONTINUE_AFTER_FAILURE_PROMPT = (
    "Continue from the last successful step only. "
    "Do not repeat completed tool work, repeated file reads, or already-finished analysis. "
    "Use the existing results already in the conversation and finish the interrupted task."
)


def is_retryable_bundled_inference_error(message: str) -> bool:
    """True for transient transport/provider failures worth retrying."""

    text = str(message or "").strip().lower()
    if not text:
        return False
    return (
        "bundled inference provider failed" in text
        or "bundled usage is temporarily unavailable right now" in text
        or "bundled inference request failed" in text
        or "could not reach ite bundled inference" in text
        or "incomplete chunked read" in text
        or "peer closed connection" in text
        or "ssl/tls alert bad record mac" in text
        or "sslv3_alert_bad_record_mac" in text
        or "ssl: decryption_failed_or_bad_record_mac" in text
        or "remote end closed connection" in text
        or "connection reset by peer" in text
        or "connection lost" in text
        or "could not reach ite cloud api" in text
        or "connection error" in text
        or "ssl error" in text
    )


def mark_retryable_turn_failure(run_state: SessionRunState, error_message: str) -> None:
    run_state.last_error_message = error_message
    if (
        is_retryable_bundled_inference_error(error_message)
        and run_state.last_turn_payload is not None
    ):
        run_state.retryable_turn_payload = dict(run_state.last_turn_payload)
    else:
        run_state.retryable_turn_payload = None


def build_silent_retry_payload(run_state: SessionRunState) -> dict[str, Any] | None:
    payload = run_state.retryable_turn_payload or run_state.last_turn_payload
    if payload is None:
        return None
    retry_payload = dict(payload)
    retry_payload["suppress_user_echo"] = True
    retry_payload["display_message"] = ""
    return retry_payload


def build_followup_recovery_payload(run_state: SessionRunState) -> dict[str, Any] | None:
    if not run_state.last_turn_payload:
        return None
    return {
        "message": CONTINUE_AFTER_FAILURE_PROMPT,
        "display_message": "",
        "attachments": [],
        "suppress_user_echo": True,
    }
