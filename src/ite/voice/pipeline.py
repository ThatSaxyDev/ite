from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ite.config.config import Config

from .cleanup import clean_transcript
from .config import CLEANUP_ENABLED
from .transcription import transcribe_audio_file


@dataclass(frozen=True)
class VoiceResult:
    raw_transcript: str
    transcript: str


async def transcribe_voice_file(config: Config, audio_path: Path) -> VoiceResult:
    voice_config = config.voice
    api_key = str(voice_config.groq_api_key or "").strip()
    if not api_key:
        raise RuntimeError("Voice typing needs a Groq API key.")

    raw = await transcribe_audio_file(audio_path, api_key=api_key)
    if not CLEANUP_ENABLED or not raw.strip():
        return VoiceResult(raw_transcript=raw, transcript=raw.strip())

    try:
        cleaned = await clean_transcript(raw, api_key=api_key)
    except Exception:
        cleaned = raw
    return VoiceResult(raw_transcript=raw, transcript=cleaned.strip())
