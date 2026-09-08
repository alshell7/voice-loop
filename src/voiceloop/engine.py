"""Audio workers live in child processes; a blocked driver cannot freeze the UI.

The coordinator is the only recording writer. Routing queues are bounded and
independent from disk I/O. Every session needs an explicit record=True decision.
"""

import multiprocessing as mp
import queue
import threading
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from voiceloop.activity import EnergyActivity
from voiceloop.audio import BLOCK_FRAMES, SAMPLE_RATE, Timeline, mono, stereo
from voiceloop.devices import SessionConfig
from voiceloop.recording import Recording


def _capture(device_id, channel, audio, status, route, stop, go, muted=None):
    import sys

    import soundcard as sc

    audio.cancel_join_thread()
    if route is not None:
        route.cancel_join_thread()
    try:
        # Resolve exact IDs; SoundCard's get_microphone also does fuzzy matching.
        device = next(
            d for d in sc.all_microphones(include_loopback=True) if str(d.id) == device_id
        )
        # WASAPI single-channel capture is a documented SoundCard limitation.
        channels = 2 if sys.platform == "win32" else min(device.channels, 2)
        with device.recorder(
            samplerate=SAMPLE_RATE, channels=channels, blocksize=BLOCK_FRAMES
        ) as recorder:
            status.put(("ready", f"capture-{channel}"))
            while not go.wait(0.05):
                if stop.is_set():
                    return
            expected = None
            while not stop.is_set():
                data = stereo(recorder.record(numframes=BLOCK_FRAMES))
                if channel == 0 and muted is not None and muted.is_set():
                    data = np.zeros_like(data)
                measured = time.monotonic() - len(data) / SAMPLE_RATE
                # Preserve contiguous device frames through scheduler jitter, but
                # re-anchor after a real stall or accumulated clock drift.
                stamp = measured if expected is None or abs(measured - expected) > 0.1 else expected
                expected = stamp + len(data) / SAMPLE_RATE
                try:
                    audio.put((channel, stamp, mono(data)), timeout=0.1)
                    if route is not None:
                        routed = np.repeat(mono(data)[:, None], 2, axis=1) if channel == 0 else data
                        route.put(routed, timeout=0.1)
                except queue.Full as exc:
                    raise RuntimeError(
                        "Audio buffer full; stopped to prevent growing latency."
                    ) from exc
    except Exception as exc:
        status.put(("error", f"{'Microphone' if channel == 0 else 'Meeting audio'}: {exc}"))
        stop.set()


def _playback(device_id, route, status, stop, go):
    import soundcard as sc

    try:
        device = next(d for d in sc.all_speakers() if str(d.id) == device_id)
        channels = min(device.channels, 2)
        with device.player(
            samplerate=SAMPLE_RATE, channels=channels, blocksize=BLOCK_FRAMES * 2
        ) as player:
            status.put(("ready", f"playback-{device_id}"))
            while not go.wait(0.05):
                if stop.is_set():
                    return
            while not stop.is_set():
                try:
                    data = route.get(timeout=0.1)
                except queue.Empty:
                    continue
                player.play(mono(data)[:, None] if channels == 1 else data)
    except Exception as exc:
        status.put(("error", f"Audio output: {exc}"))
        stop.set()


class Engine:
    def __init__(self):
        self.state = "idle"
        self.error = ""
        self.levels = [0.0, 0.0]
        self.started = 0.0
        self.duration = 0.0
        self.saved_path: Path | None = None
        self.recording = False
        self._thread: threading.Thread | None = None
        self._request_stop = threading.Event()
        self._stopped_at = 0.0
        self._muted = mp.get_context("spawn").Event()
        self.metadata = {}
        self._processes = []
        self.activity = EnergyActivity()
        self._trim_silence = False

    @property
    def muted(self) -> bool:
        return self._muted.is_set()

    def set_muted(self, muted: bool) -> None:
        (self._muted.set if muted else self._muted.clear)()

    def terminate_workers(self):
        """Last resort for the explicit Force quit action, limited to our workers."""
        for process in list(self._processes):
            try:
                if process.pid and process.is_alive():
                    process.terminate()
                    process.join(timeout=0.3)
                    if process.is_alive():
                        process.kill()
            except (ValueError, AssertionError, OSError):
                pass  # The coordinator may already have closed this process.

    @property
    def active(self) -> bool:
        return self.state in ("starting", "running", "stopping")

    def start(
        self, config: SessionConfig, root: Path, *, record: bool, metadata: dict | None = None
    ) -> None:
        if self.active:
            raise RuntimeError("A session is already active.")
        config.validate()
        self.state = "starting"
        self.error = ""
        self.saved_path = None
        self.started = self.duration = self._stopped_at = 0.0
        self.levels = [0.0, 0.0]
        self.recording = record
        self.activity = EnergyActivity()
        self._trim_silence = False
        self.metadata = dict(metadata or {})
        self._request_stop.clear()
        self._thread = threading.Thread(target=self._run, args=(config, root, record), daemon=True)
        self._thread.start()

    def stop(self, *, trim_silence: bool = False) -> None:
        if self.active:
            self._trim_silence = self._trim_silence or (trim_silence and self.recording)
            self._stopped_at = time.monotonic()
            self.state = "stopping"
            self._request_stop.set()

    def wait(self, timeout: float = 12) -> bool:
        if self._thread:
            self._thread.join(timeout)
        return not self.active

    def _run(self, config: SessionConfig, root: Path, record: bool):
        ctx = mp.get_context("spawn")
        audio, status = ctx.Queue(maxsize=128), ctx.Queue()
        stop, go = ctx.Event(), ctx.Event()
        routes = [ctx.Queue(maxsize=16), ctx.Queue(maxsize=16)] if config.mode == "bridge" else []
        processes = []
        self._processes = processes
        timeline = Timeline()
        recording = None
        try:
            if routes:
                for device, route in zip((config.virtual_mic, config.speaker), routes, strict=True):
                    processes.append(
                        ctx.Process(
                            target=_playback, args=(device.id, route, status, stop, go), daemon=True
                        )
                    )
            for channel, device in enumerate((config.microphone, config.meeting)):
                processes.append(
                    ctx.Process(
                        target=_capture,
                        args=(
                            device.id,
                            channel,
                            audio,
                            status,
                            routes[channel] if routes else None,
                            stop,
                            go,
                            self._muted,
                        ),
                        daemon=True,
                    )
                )
            for process in processes:
                process.start()
            ready = 0
            deadline = time.monotonic() + 12
            while ready < len(processes):
                if self._request_stop.is_set():
                    return
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        "An audio device did not open. Check permissions and refresh devices."
                    )
                try:
                    kind, value = status.get(timeout=0.1)
                except queue.Empty:
                    if any(p.exitcode is not None for p in processes):
                        raise RuntimeError(
                            "An audio worker exited while opening a device."
                        ) from None
                    continue
                if kind == "error":
                    raise RuntimeError(value)
                ready += kind == "ready"
            if self._request_stop.is_set():
                return
            if record:
                recording = Recording(root, asdict(config), metadata=self.metadata)
                self.saved_path = recording.directory
            self.started = time.monotonic()
            last_audio = [self.started, self.started]
            last_flush = self.started
            self.state = "running"
            go.set()
            while not self._request_stop.is_set():
                self._consume_status(status)
                self._consume_audio(audio, timeline, last_audio)
                now = time.monotonic()
                self.duration = now - self.started
                # 250 ms disk-write delay tolerates normal capture/IPC scheduling.
                target = max(0, int((self.duration - 0.25) * SAMPLE_RATE))
                self._write_to(timeline, target, recording)
                if now - last_flush >= 2:
                    if recording:
                        recording.flush()
                    last_flush = now
                if stop.is_set() or any(not p.is_alive() for p in processes):
                    self._consume_status(status)
                    raise RuntimeError(
                        "An audio device stopped unexpectedly. Check the connection."
                    )
                if any(now - last > 8 for last in last_audio):
                    raise RuntimeError(
                        "No data from an audio device for 8 seconds. Refresh and retry."
                    )
                self._request_stop.wait(0.01)
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.state = "stopping"
            stop.set()
            end = self._stopped_at or time.monotonic()
            # Drain while workers exit so producers cannot block shutdown.
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and any(p.is_alive() for p in processes if p.pid):
                try:
                    self._consume_audio(audio, timeline, [end, end])
                except Exception as exc:
                    self.error = self.error or str(exc)
                    break
                time.sleep(0.02)
            for process in processes:
                if process.pid:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=0.5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=0.5)
                    process.close()
            if self.started:
                self.duration = max(0, end - self.started)
            try:
                if recording:
                    self._write_to(timeline, int(self.duration * SAMPLE_RATE), recording)
                    self.activity.finish()
                    recording.close(
                        self.error or None,
                        {
                            "late_frames": timeline.late_frames,
                            "overflow_frames": timeline.overflow_frames,
                            "timing": "shared_monotonic_clock; best-effort device alignment",
                        },
                        trim_end_frame=(
                            self.activity.trim_frame
                            if self._trim_silence and not self.error
                            else None
                        ),
                    )
            except Exception as exc:
                self.error = self.error or f"Could not finish recording: {exc}"
                if recording and not recording.closed:
                    try:
                        recording.close(self.error)
                    except OSError:
                        pass  # Existing WAV headers are repaired on every write.
            for channel_queue in [audio, status, *routes]:
                channel_queue.close()
                channel_queue.cancel_join_thread()
            self.levels = [0.0, 0.0]
            self.state = "error" if self.error else "idle"

    def _consume_status(self, status):
        for _ in range(32):
            try:
                kind, value = status.get_nowait()
            except queue.Empty:
                return
            if kind == "error":
                raise RuntimeError(value)

    def _consume_audio(self, audio, timeline, last_audio):
        for _ in range(128):
            try:
                channel, stamp, samples = audio.get_nowait()
            except queue.Empty:
                return
            if not self.started:
                continue
            last_audio[channel] = time.monotonic()
            self.levels[channel] = float(np.max(np.abs(samples))) if len(samples) else 0.0
            timeline.insert(channel, round((stamp - self.started) * SAMPLE_RATE), samples)

    def _write_to(self, timeline, target, recording):
        while timeline.cursor < target:
            count = min(BLOCK_FRAMES, target - timeline.cursor)
            data = timeline.read(count)
            if recording:
                self.activity.update(data)
                recording.write(data)
