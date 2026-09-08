"""Optional transcription extension point; the recorder never calls this module."""

import hashlib
import json
import tempfile
import wave
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from voiceloop.audio import SAMPLE_RATE
from voiceloop.config import atomic_json
from voiceloop.library import audio_parts


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None


class Transcriber(Protocol):
    """Adapters can wrap local Whisper, OpenAI, Groq, or another provider.

    Return timestamps relative to the supplied WAV. Cloud adapters must declare
    uploads_audio=True so callers can require a separate explicit upload decision.
    """

    name: str
    uploads_audio: bool

    def transcribe(self, wav_path: Path) -> Iterable[Segment]: ...


class WhisperLocal:
    name = "whisper-local"
    uploads_audio = False

    def __init__(self, model: str = "base"):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                'Install the optional adapter: pip install "voice-loop[whisper]"'
            ) from exc
        self.model = WhisperModel(model, device="cpu", compute_type="int8")

    def transcribe(self, wav_path: Path) -> Iterable[Segment]:
        segments, _ = self.model.transcribe(str(wav_path), vad_filter=True)
        for segment in segments:
            yield Segment(segment.start, segment.end, segment.text.strip())


def transcribe_session(
    directory: Path,
    provider: Transcriber,
    *,
    allow_upload: bool = False,
    cancel=None,
    progress=None,
) -> Path:
    if provider.uploads_audio and not allow_upload:
        raise ValueError("This provider uploads audio. Explicit upload consent is required.")
    directory = directory.resolve()
    manifest = json.loads((directory / "session.json").read_text(encoding="utf-8"))
    if manifest.get("status") == "recording":
        raise ValueError("Stop the recording before transcribing it.")
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported session manifest version.")
    paths = audio_parts(directory, manifest)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "provider": provider.name,
                "channels": manifest.get("channels", {}),
                "files": [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in paths],
                "parts": manifest["parts"],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    checkpoint = directory / "transcription-progress.json"
    completed = {}
    try:
        cached = json.loads(checkpoint.read_text(encoding="utf-8"))
        if cached.get("fingerprint") == fingerprint and isinstance(cached.get("chunks"), dict):
            completed = cached["chunks"]
    except (OSError, ValueError, AttributeError):
        pass
    segments = []
    # Two-minute mono chunks bound memory for long meetings and most providers.
    # Cloud adapters may impose a smaller chunk size in their implementation.
    with tempfile.TemporaryDirectory(prefix="voiceloop-stt-") as temporary:
        for part_number, (part, path) in enumerate(zip(manifest["parts"], paths, strict=True)):
            with wave.open(str(path), "rb") as source:
                if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (
                    2,
                    2,
                    SAMPLE_RATE,
                ):
                    raise ValueError("Expected Voice Loop 48 kHz, 16-bit stereo audio.")
                position = 0
                while raw := source.readframes(SAMPLE_RATE * 120):
                    samples = np.frombuffer(raw, dtype="<i2").reshape(-1, 2)
                    for channel in (0, 1):
                        if cancel is not None and cancel.is_set():
                            raise RuntimeError(
                                "Transcription canceled. Completed chunks can be resumed."
                            )
                        chunk_id = f"{part_number}:{position}:{channel}"
                        if chunk_id in completed:
                            segments.extend(completed[chunk_id])
                            continue
                        role = manifest.get("channels", {}).get(
                            str(channel), "microphone" if channel == 0 else "meeting"
                        )
                        label = "You" if role == "microphone" else "Meeting"
                        # Exact digital silence has no speech to transcribe.
                        if not np.any(samples[:, channel]):
                            continue
                        mono_file = Path(temporary) / "channel.wav"
                        with wave.open(str(mono_file), "wb") as target:
                            target.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
                            target.writeframes(samples[:, channel].tobytes())
                        offset = (part["start_frame"] + position) / SAMPLE_RATE
                        chunk_segments = []
                        for segment in provider.transcribe(mono_file):
                            speaker = segment.speaker or label
                            chunk_number = position // (SAMPLE_RATE * 120) + 1
                            scope = f"{label.lower()}-{part_number + 1}-{chunk_number}"
                            if getattr(provider, "diarizes", False):
                                # Speaker letters reset for every API request. Never pretend
                                # two different chunks' speaker A is the same person.
                                speaker = (
                                    "You"
                                    if role == "microphone"
                                    else f"Speaker {speaker} · clip {int(offset // 120) + 1}"
                                )
                            chunk_segments.append(
                                {
                                    **asdict(segment),
                                    "start": offset + segment.start,
                                    "end": offset + segment.end,
                                    "channel": channel,
                                    "speaker": speaker,
                                    "speaker_scope": scope,
                                }
                            )
                        completed[chunk_id] = chunk_segments
                        segments.extend(chunk_segments)
                        atomic_json(checkpoint, {"fingerprint": fingerprint, "chunks": completed})
                        if progress:
                            through = int(offset + len(samples) / SAMPLE_RATE)
                            progress(f"Transcribed through {through}s · {label}")
                    position += len(samples)
    segments.sort(key=lambda s: (s["start"], s["channel"]))
    output = directory / "transcript.json"
    atomic_json(
        output,
        {
            "schema_version": 1,
            "provider": provider.name,
            "metadata": json.loads((directory / "session.json").read_text(encoding="utf-8")).get(
                "metadata", {}
            ),
            "started_at": manifest.get("started_at", ""),
            "duration_seconds": manifest.get("duration_seconds", 0),
            "speaker_labels": (
                "Microphone is You; meeting speakers are diarized within each 2-minute chunk. "
                "Speaker identities are not matched across chunks; "
                "contact tags are not speaker identities."
                if getattr(provider, "diarizes", False)
                else "Channel labels; remote speakers are not diarized. "
                "Non-timestamped models use chunk times."
            ),
            "segments": segments,
        },
    )
    from voiceloop.transcript_html import save_html

    save_html(directory)
    checkpoint.unlink(missing_ok=True)
    return output
