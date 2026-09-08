"""Crash-recoverable local WAV segments and a versioned session manifest."""

import os
import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from voiceloop.activity import ENERGY_THRESHOLD_DBFS, TAIL_PADDING_SECONDS
from voiceloop.audio import SAMPLE_RATE, pcm16
from voiceloop.config import atomic_json


class Recording:
    def __init__(
        self,
        root: Path,
        devices: dict,
        segment_frames: int = SAMPLE_RATE * 1800,
        *,
        metadata: dict | None = None,
    ):
        if segment_frames < 1:
            raise ValueError("Segment length must be positive.")
        roles = [devices.get("left_channel", "microphone"), devices.get("right_channel", "meeting")]
        if set(roles) != {"microphone", "meeting"}:
            raise ValueError("Recording channels must contain microphone and meeting audio.")
        now = datetime.now(UTC)
        self.directory = root / (now.strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True, mode=0o700)
        self.segment_frames = segment_frames
        self.frames = 0
        self.part_frames = 0
        self.writer = None
        self.stream = None
        self.closed = False
        self.channel_order = [0 if role == "microphone" else 1 for role in roles]
        self.manifest = {
            "schema_version": 1,
            "started_at": now.isoformat(),
            "status": "recording",
            "consent": "explicit_session",
            "sample_rate": SAMPLE_RATE,
            "channels": {str(index): role for index, role in enumerate(roles)},
            "format": "PCM_S16LE",
            "devices": devices,
            "parts": [],
            "frames": 0,
            "metadata": metadata or {},
        }
        self._checkpoint()

    def _checkpoint(self) -> None:
        self.manifest["frames"] = self.frames
        self.manifest["duration_seconds"] = self.frames / SAMPLE_RATE
        atomic_json(self.directory / "session.json", self.manifest)

    def _open_part(self) -> None:
        name = f"audio-{len(self.manifest['parts']) + 1:03d}.wav"
        path = self.directory / name
        self.stream = path.open("xb")
        if os.name != "nt":
            path.chmod(0o600)
        self.writer = wave.open(self.stream, "wb")
        self.writer.setparams((2, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        self.writer.writeframes(b"")
        self.part_frames = 0
        self.manifest["parts"].append({"file": name, "start_frame": self.frames, "frames": 0})
        self._checkpoint()

    def _close_part(self) -> None:
        try:
            if self.writer is not None:
                self.writer.close()
        finally:
            self.writer = None
            if self.stream is not None:
                try:
                    self.stream.flush()
                    os.fsync(self.stream.fileno())
                finally:
                    self.stream.close()
                    self.stream = None

    def write(self, data: np.ndarray) -> None:
        if self.closed:
            raise RuntimeError("Recording is closed.")
        if data.ndim != 2 or data.shape[1] != 2:
            raise ValueError("Recording requires two audio channels.")
        offset = 0
        while offset < len(data):
            if self.writer is None:
                self._open_part()
            count = min(len(data) - offset, self.segment_frames - self.part_frames)
            self.writer.writeframes(pcm16(data[offset : offset + count, self.channel_order]))
            self.frames += count
            self.part_frames += count
            self.manifest["parts"][-1]["frames"] = self.part_frames
            offset += count
            if self.part_frames == self.segment_frames:
                self._close_part()
                self._checkpoint()

    def flush(self) -> None:
        if self.stream is not None:
            self.stream.flush()
            os.fsync(self.stream.fileno())
        self._checkpoint()

    def _trim_tail(self, keep_frames: int) -> None:
        """Atomically replace the boundary WAV, then retire unreferenced tail parts."""
        keep_frames = max(0, min(self.frames, int(keep_frames)))
        if keep_frames == self.frames:
            return
        original_frames = self.frames
        kept, obsolete = [], []
        for part in self.manifest["parts"]:
            count = max(0, min(part["frames"], keep_frames - part["start_frame"]))
            if not count and kept:
                obsolete.append(self.directory / part["file"])
                continue
            path = self.directory / part["file"]
            if count < part["frames"]:
                temporary = path.with_suffix(".trim.tmp")
                try:
                    with wave.open(str(path), "rb") as source, temporary.open("xb") as stream:
                        with wave.open(stream, "wb") as target:
                            target.setparams(source.getparams())
                            remaining = count
                            while remaining:
                                data = source.readframes(min(remaining, SAMPLE_RATE * 5))
                                if not data:
                                    raise OSError("Recording ended before the trim boundary.")
                                target.writeframesraw(data)
                                remaining -= len(data) // 4
                        stream.flush()
                        os.fsync(stream.fileno())
                    if os.name != "nt":
                        temporary.chmod(0o600)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            kept.append({**part, "frames": count})
        self.frames = keep_frames
        self.manifest["parts"] = kept
        self.manifest["trim"] = {
            "reason": "trailing_low_energy",
            "original_frames": original_frames,
            "removed_frames": original_frames - keep_frames,
            "threshold_dbfs": ENERGY_THRESHOLD_DBFS,
            "tail_padding_seconds": TAIL_PADDING_SECONDS,
        }
        # A crash during deletion must not leave the manifest referring to a
        # deleted WAV. Unreferenced files can survive a crash harmlessly.
        self._checkpoint()
        for path in obsolete:
            path.unlink()

    def close(
        self,
        error: str | None = None,
        diagnostics: dict | None = None,
        *,
        trim_end_frame: int | None = None,
    ) -> Path:
        if self.closed:
            return self.directory
        self._close_part()
        if trim_end_frame is not None and not error:
            self._trim_tail(trim_end_frame)
        self.manifest["status"] = "interrupted" if error else "complete"
        self.manifest["ended_at"] = datetime.now(UTC).isoformat()
        self.manifest["diagnostics"] = diagnostics or {}
        if error:
            self.manifest["error"] = error
        self._checkpoint()
        self.closed = True
        return self.directory
