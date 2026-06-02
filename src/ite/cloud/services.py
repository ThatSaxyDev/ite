from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from ite.agent.session_naming import sanitize_model_session_title
from ite.config.config import Config

from .auth import get_cloud_session


class CloudServiceError(RuntimeError):
    pass


async def transcribe_cloud_voice_file(
    config: Config,
    audio_path: Path,
    *,
    cleanup: bool,
) -> tuple[str, str]:
    session = get_cloud_session(config)
    if session is None:
        raise CloudServiceError("No active iTE Cloud session.")
    try:
        audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise CloudServiceError(f"Could not read voice recording: {exc}") from exc

    payload = {
        "filename": audio_path.name,
        "contentType": _audio_content_type(audio_path),
        "audioBase64": audio_base64,
        "cleanup": cleanup,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{session.api_url.rstrip('/')}/voice/transcribe",
                headers={
                    "authorization": f"Bearer {session.access_token}",
                    "content-type": "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise CloudServiceError("Cloud voice transcription timed out.") from exc
    except httpx.HTTPError as exc:
        raise CloudServiceError(f"Cloud voice transcription failed: {exc}") from exc

    data = _response_json(response)
    if response.status_code != 200 or not data.get("ok"):
        raise CloudServiceError(_cloud_error_message(data) or "Cloud voice transcription failed.")
    return (
        str(data.get("rawTranscript") or ""),
        str(data.get("transcript") or "").strip(),
    )


async def generate_cloud_session_title(
    config: Config,
    context: dict[str, str],
) -> str | None:
    session = get_cloud_session(config)
    if session is None:
        return None
    payload = {
        "firstUser": str(context.get("first_user") or "")[:500],
        "firstAssistant": str(context.get("first_assistant") or "")[:300],
        "latestUser": str(context.get("latest_user") or "")[:500],
        "focusHint": str(context.get("focus_hint") or "")[:300],
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{session.api_url.rstrip('/')}/metadata/session-title",
                headers={
                    "authorization": f"Bearer {session.access_token}",
                    "content-type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None
    data = _response_json(response)
    if not data.get("ok"):
        return None
    title = sanitize_model_session_title(str(data.get("title") or ""))
    return title or None


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _cloud_error_message(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return message
    return str(data.get("message") or "").strip()


def _audio_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".m4a":
        return "audio/mp4"
    return "application/octet-stream"
