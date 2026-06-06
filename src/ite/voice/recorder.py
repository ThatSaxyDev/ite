from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import shutil
import signal
import sys
import tempfile
from pathlib import Path


class VoiceRecorderError(RuntimeError):
    pass


SWIFT_RECORDER_SOURCE = r'''
import AVFoundation
import Foundation

guard CommandLine.arguments.count >= 2 else {
    fputs("missing output path\n", stderr)
    exit(64)
}

let outputPath = CommandLine.arguments[1]
let outputURL = URL(fileURLWithPath: outputPath)

let permission = DispatchSemaphore(value: 0)
var granted = false
AVCaptureDevice.requestAccess(for: .audio) { value in
    granted = value
    permission.signal()
}
permission.wait()

guard granted else {
    fputs("microphone permission denied\n", stderr)
    exit(77)
}

let settings: [String: Any] = [
    AVFormatIDKey: kAudioFormatLinearPCM,
    AVSampleRateKey: 16000.0,
    AVNumberOfChannelsKey: 1,
    AVLinearPCMBitDepthKey: 16,
    AVLinearPCMIsFloatKey: false,
    AVLinearPCMIsBigEndianKey: false
]

do {
    let recorder = try AVAudioRecorder(url: outputURL, settings: settings)
    recorder.prepareToRecord()
    guard recorder.record() else {
        fputs("failed to start audio recorder\n", stderr)
        exit(70)
    }
    _ = FileHandle.standardInput.readDataToEndOfFile()
    recorder.stop()
    Thread.sleep(forTimeInterval: 0.15)
} catch {
    fputs("\(error.localizedDescription)\n", stderr)
    exit(70)
}
'''


class VoiceRecorder:
    """Voice recorder with platform-specific backends.

    macOS: system Swift toolchain + AVFoundation.
    Linux: arecord from alsa-utils (auto-detected).
    A custom recorder can be supplied via ITE_VOICE_RECORDER_CMD; the command
    must accept an output path and stop cleanly when stdin closes or SIGINT.
    """

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._audio_path: Path | None = None
        self._script_path: Path | None = None
        self._arecord_backend: bool = False

    async def start(self) -> Path:
        if self._process is not None:
            raise VoiceRecorderError("Voice recording is already running.")

        output = Path(tempfile.mkstemp(prefix="ite-voice-", suffix=".wav")[1])
        try:
            command = self._recorder_command(output)
        except Exception:
            self._cleanup_paths(output)
            raise
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            self._cleanup_paths(output)
            raise VoiceRecorderError(f"Voice recorder command not found: {command[0]}") from exc

        self._audio_path = output
        await asyncio.sleep(0.35)
        if self._process.returncode is not None:
            stderr = await self._read_stderr()
            self._cleanup_paths(output)
            raise VoiceRecorderError(stderr or "Voice recorder failed to start.")
        return output

    async def stop(self) -> Path:
        process = self._process
        audio_path = self._audio_path
        if process is None or audio_path is None:
            raise VoiceRecorderError("Voice recording is not running.")

        arecord = self._arecord_backend
        self._process = None
        self._audio_path = None
        self._arecord_backend = False
        try:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.5)
            except asyncio.TimeoutError:
                if arecord:
                    process.send_signal(signal.SIGINT)
                else:
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=4.0)
                except asyncio.TimeoutError:
                    process.terminate()
                    await process.wait()
                    raise VoiceRecorderError(
                        "Voice recorder did not stop cleanly."
                    )
        finally:
            self._cleanup_script()

        if process.returncode not in {0, None}:
            stderr = await self._read_stderr(process)
            self._cleanup_paths(audio_path)
            raise VoiceRecorderError(stderr or "Voice recorder failed.")

        if not audio_path.is_file() or audio_path.stat().st_size <= 44:
            self._cleanup_paths(audio_path)
            raise VoiceRecorderError("No audio was recorded.")
        return audio_path

    async def cancel(self) -> None:
        process = self._process
        audio_path = self._audio_path
        self._process = None
        self._audio_path = None
        self._arecord_backend = False
        self._cleanup_script()
        if process is not None and process.returncode is None:
            process.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=2.0)
        if audio_path is not None:
            self._cleanup_paths(audio_path)

    def _recorder_command(self, output: Path) -> list[str]:
        self._arecord_backend = False
        custom = os.environ.get("ITE_VOICE_RECORDER_CMD")
        if custom:
            return [part.format(output=str(output)) for part in shlex.split(custom)]

        if sys.platform == "linux":
            arecord = shutil.which("arecord")
            if arecord:
                self._arecord_backend = True
                return [arecord, "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "wav", str(output)]
            raise VoiceRecorderError(
                "Voice recording is not available. "
                "Install the 'alsa-utils' package to use voice typing on Linux."
            )

        swift = shutil.which("swift")
        if not swift:
            raise VoiceRecorderError(
                "Voice recording is not available. "
                "Install the Xcode command line tools to use voice typing on macOS."
            )
        script = Path(tempfile.mkstemp(prefix="ite-voice-recorder-", suffix=".swift")[1])
        script.write_text(SWIFT_RECORDER_SOURCE, encoding="utf-8")
        self._script_path = script
        return [swift, str(script), str(output)]

    async def _read_stderr(
        self,
        process: asyncio.subprocess.Process | None = None,
    ) -> str:
        proc = process or self._process
        if proc is None or proc.stderr is None:
            return ""
        data = await proc.stderr.read()
        return data.decode("utf-8", errors="replace").strip()

    def _cleanup_script(self) -> None:
        if self._script_path is not None:
            self._cleanup_paths(self._script_path)
            self._script_path = None

    @staticmethod
    def _cleanup_paths(*paths: Path) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
