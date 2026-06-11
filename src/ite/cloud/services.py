from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import httpx

from ite.agent.session_naming import sanitize_model_session_title
from ite.config.config import Config

from .auth import CloudSession, _load_cloud_session, _refresh_cloud_session

_CLOUD_SERVICE_MAX_RETRIES = 10


class CloudServiceError(RuntimeError):
    pass


async def transcribe_cloud_voice_file(
    config: Config,
    audio_path: Path,
    *,
    cleanup: bool,
) -> tuple[str, str]:
    """Transcribe a voice recording via the iTE Cloud voice endpoint.

    Uses _load_cloud_session (file I/O only) instead of get_cloud_session()
    to avoid blocking the event loop with synchronous /auth/me validation.
    The transcription endpoint itself validates the bearer token; a 401 is
    surfaced as CloudServiceError so the pipeline can fall back to direct Groq.
    """
    session = _load_cloud_session()
    if session is None:
        raise CloudServiceError("No active iTE Cloud session.")

    api_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if session.api_url.rstrip("/") != api_url:
        raise CloudServiceError("No active iTE Cloud session.")

    if not session.is_access_valid and session.refresh_token:
        try:
            refreshed = await asyncio.to_thread(_refresh_cloud_session, session)
        except Exception:
            refreshed = None
        if refreshed is not None and refreshed.access_token:
            session = refreshed
        else:
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
        for attempt in range(_CLOUD_SERVICE_MAX_RETRIES + 1):
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
                break
            except httpx.HTTPError as exc:
                if attempt < _CLOUD_SERVICE_MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, 30))
                    continue
                raise
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
    session = await _get_cloud_session_for_metadata(config)
    if session is None:
        return None
    api_url = session.api_url.rstrip("/")
    payload = {
        "firstUser": str(context.get("first_user") or "")[:500],
        "firstAssistant": str(context.get("first_assistant") or "")[:300],
        "latestUser": str(context.get("latest_user") or "")[:500],
        "focusHint": str(context.get("focus_hint") or "")[:300],
        "firstTurn": str(context.get("first_turn") or "")[:1000],
        "turnCount": _coerce_int(context.get("turn_count")),
    }
    try:
        # The cloud API may be cold-starting (Render free tier: 5-15 s).
        # It then calls Groq with a 3 s AbortSignal. 18 s total covers both.
        for attempt in range(_CLOUD_SERVICE_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=18.0) as client:
                    response = await client.post(
                        f"{api_url}/metadata/session-title",
                        headers={
                            "authorization": f"Bearer {session.access_token}",
                            "content-type": "application/json",
                        },
                        json=payload,
                    )
                break
            except httpx.HTTPError:
                if attempt < _CLOUD_SERVICE_MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, 30))
                    continue
                raise
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None
    data = _response_json(response)
    if not data.get("ok"):
        return None
    title = sanitize_model_session_title(str(data.get("title") or ""))
    return title or None


async def _get_cloud_session_for_metadata(config: Config) -> CloudSession | None:
    # Disk-only load first. Avoid get_cloud_session(), which performs a sync
    # /auth/me validation and can block the Textual event loop during cloud
    # cold starts. The metadata route still validates the bearer token.
    session = _load_cloud_session()
    if session is None:
        return None
    api_url = session.api_url.rstrip("/")
    cloud_api_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if api_url != cloud_api_url:
        return None
    if session.is_access_valid and session.access_token:
        return session
    try:
        refreshed = await asyncio.to_thread(_refresh_cloud_session, session)
    except Exception:
        return None
    if refreshed is None or not refreshed.access_token:
        return None
    if refreshed.api_url.rstrip("/") != cloud_api_url:
        return None
    return refreshed


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


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
