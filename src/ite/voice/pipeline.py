from __future__ import annotations

from pathlib import Path

from ite.config.config import Config
from ite.cloud.services import CloudServiceError, transcribe_cloud_voice_file

from .cleanup import clean_transcript
from .config import CLEANUP_ENABLED
from .transcription import transcribe_audio_file
from .types import VoiceResult


async def transcribe_voice_file(config: Config, audio_path: Path) -> VoiceResult:
    voice_config = config.voice
    api_key = str(voice_config.groq_api_key or "").strip()
    try:
        raw, transcript = await transcribe_cloud_voice_file(
            config,
            audio_path,
            cleanup=CLEANUP_ENABLED,
        )
        return VoiceResult(raw_transcript=raw, transcript=transcript)
    except CloudServiceError:
        pass

    if not api_key:
        raise RuntimeError("Voice typing needs iTE Cloud sign-in or a local Groq API key.")

    raw = await transcribe_audio_file(audio_path, api_key=api_key)
    if not CLEANUP_ENABLED or not raw.strip():
        return VoiceResult(raw_transcript=raw, transcript=raw.strip())

    try:
        cleaned = await clean_transcript(raw, api_key=api_key)
    except Exception:
        cleaned = raw
    return VoiceResult(raw_transcript=raw, transcript=cleaned.strip())
