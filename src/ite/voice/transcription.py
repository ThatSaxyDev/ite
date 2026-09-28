from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from .config import GROQ_BASE_URL, TRANSCRIPTION_LANGUAGE, TRANSCRIPTION_MODEL


class VoiceTranscriptionError(RuntimeError):
    pass


HALLUCINATION_PHRASES = {
    "thank you",
    "thank you for watching",
    "thank you very much",
    "thank you so much",
    "thanks for watching",
    "please subscribe",
    "like and subscribe",
    "subtitles by",
    "subtitles by the amara.org community",
    "you",
}
HALLUCINATION_NO_SPEECH_THRESHOLD = 0.1

_TRANSCRIPTION_MAX_RETRIES = 10


async def transcribe_audio_file(
    audio_path: Path,
    *,
    api_key: str,
    base_url: str = GROQ_BASE_URL,
    model: str = TRANSCRIPTION_MODEL,
    language: str = TRANSCRIPTION_LANGUAGE,
) -> str:
    if not audio_path.is_file():
        raise VoiceTranscriptionError(f"Audio file does not exist: {audio_path}")

    url = f"{base_url.rstrip('/')}/audio/transcriptions"
    data = {
        "model": model,
        "response_format": "verbose_json",
    }
    if language.strip():
        data["language"] = language.strip()

    try:
        with audio_path.open("rb") as audio_file:
            files = {
                "file": (audio_path.name, audio_file, _audio_content_type(audio_path)),
            }
            for attempt in range(_TRANSCRIPTION_MAX_RETRIES + 1):
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(
                            url,
                            headers={"authorization": f"Bearer {api_key}"},
                            data=data,
                            files=files,
                        )
                    break
                except httpx.HTTPError as exc:
                    if attempt < _TRANSCRIPTION_MAX_RETRIES:
                        await asyncio.sleep(min(2**attempt, 30))
                        # Reset file position for retry
                        audio_file.seek(0)
                        continue
                    raise
    except httpx.TimeoutException as exc:
        raise VoiceTranscriptionError("Transcription timed out.") from exc
    except httpx.HTTPError as exc:
        raise VoiceTranscriptionError(f"Transcription request failed: {exc}") from exc

    if response.status_code != 200:
        raise VoiceTranscriptionError(
            _friendly_http_message(response.status_code, base_url)
        )

    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        if not text:
            raise VoiceTranscriptionError("Transcription returned an empty response.")
        return " ".join(text.splitlines()).strip()

    text = str(payload.get("text") or "").strip()
    if _is_hallucination(text=text, payload=payload):
        return ""
    return text


def _audio_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".m4a":
        return "audio/mp4"
    return "application/octet-stream"


def _friendly_http_message(status: int, base_url: str) -> str:
    host = base_url.split("//", 1)[-1].split("/", 1)[0] or "Groq"
    if status == 401:
        return f"Invalid Groq API key for {host}."
    if status == 403:
        return f"Groq key lacks permission for transcription at {host}."
    if status == 404:
        return f"Transcription endpoint was not found at {host}."
    if status == 413:
        return "Audio file is too large. Try a shorter recording."
    if status == 429:
        return "Groq rate limit reached. Wait a moment and try again."
    if 500 <= status < 600:
        return "Groq transcription failed. Try again in a moment."
    return f"Transcription request failed with HTTP {status}."


def _is_hallucination(*, text: str, payload: dict[str, Any]) -> bool:
    normalized = text.lower().strip(" \t\r\n.,!?;:\"'")
    if normalized not in HALLUCINATION_PHRASES:
        return False

    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        return False
    first = segments[0]
    if not isinstance(first, dict):
        return False
    no_speech_prob = first.get("no_speech_prob")
    return (
        isinstance(no_speech_prob, int | float)
        and float(no_speech_prob) >= HALLUCINATION_NO_SPEECH_THRESHOLD
    )
