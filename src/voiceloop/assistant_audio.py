"""Isolated, bounded audio paths for the voice assistant.

Only the virtual speaker return is captured. The physical microphone is never
opened. Driver calls live in child processes so cancellation remains bounded.
"""

import multiprocessing as mp
import queue
import sys
import time
from collections import deque

import numpy as np

from voiceloop.audio import mono, pcm16
from voiceloop.devices import Device, is_virtual

DEVICE_RATE = 48_000
REALTIME_RATE = 24_000
FRAMES = 960
PLAYBACK_FRAMES = REALTIME_RATE // 50
PLAYBACK_QUEUE_PACKETS = 8
MAX_BUFFERED_FRAMES = REALTIME_RATE * 60
PLAYBACK_STALL_SECONDS = 5


class Downsample48k:
    """Streaming antialiased 2:1 conversion, including across uneven blocks."""

    def __init__(self):
        positions = np.arange(63) - 31
        kernel = 0.45 * np.sinc(0.45 * positions) * np.hamming(63)
        self.kernel = kernel / kernel.sum()
        self.tail = np.zeros(62)
        self.offset = 0

    def convert(self, data):
        values = np.asarray(data, dtype=np.float32).reshape(-1)
        if not len(values):
            return np.empty(0, dtype=np.float32)
        joined = np.concatenate((self.tail, values))
        filtered = np.convolve(joined, self.kernel, mode="valid")
        result = filtered[self.offset :: 2].astype(np.float32)
        self.offset = (self.offset - len(values)) % 2
        self.tail = joined[-62:]
        return result


def upsample24k(data):
    """Linear interpolation at 48 kHz; the final sample is held for one frame."""
    values = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
    if not len(values):
        return values
    result = np.empty(len(values) * 2, dtype=np.float32)
    result[::2] = values
    result[1:-1:2] = (values[:-1] + values[1:]) * 0.5
    result[-1] = values[-1]
    return result


def _capture(device_id, incoming, status, stop, go, monitor):
    import soundcard as sc

    incoming.cancel_join_thread()
    try:
        device = next(
            d for d in sc.all_microphones(include_loopback=True) if str(d.id) == device_id
        )
        channels = 2 if sys.platform == "win32" else min(device.channels, 2)
        converter = Downsample48k()
        with device.recorder(samplerate=DEVICE_RATE, channels=channels, blocksize=FRAMES) as reader:
            status.put(("ready", "capture"))
            # Keep the native input drained during preflight; no pre-call audio
            # is queued or uploaded when activation eventually occurs.
            while not stop.is_set():
                values = mono(reader.record(numframes=FRAMES))
                if not go.is_set():
                    continue
                converted = converter.convert(values)
                incoming.put(pcm16(converted), timeout=0.1)
                if monitor is not None:
                    monitor.put(pcm16(converted), timeout=0.1)
    except Exception as exc:
        status.put(("error", f"Meeting audio capture: {exc}"))
        stop.set()


def _playback(device_id, outgoing, status, stop, generation, *, monitor=False):
    import soundcard as sc

    try:
        device = next(d for d in sc.all_speakers() if str(d.id) == device_id)
        channels = min(device.channels, 2)
        with device.player(samplerate=DEVICE_RATE, channels=channels, blocksize=FRAMES) as player:
            status.put(("ready", "monitor" if monitor else "playback"))
            while not stop.is_set():
                try:
                    packet = outgoing.get(timeout=0.05)
                except queue.Empty:
                    continue
                if monitor:
                    pcm, item, epoch, serial = packet, "", 0, 0
                else:
                    pcm, item, epoch, serial = packet
                    if epoch != generation.value:
                        status.put(("discarded", serial))
                        continue
                data = upsample24k(pcm)
                started = time.monotonic()
                player.play(np.repeat(data[:, None], channels, axis=1))
                # SoundCard can return after queuing frames. Do not acknowledge
                # the packet before its duration has elapsed on the device.
                # multiprocessing.Event.wait uses a coarse Windows timer: a
                # 20-ms packet can wait ~31 ms, inserting gaps into speech.
                # Python's high-resolution sleep keeps packet duration accurate;
                # cancellation still waits at most one 20-ms packet.
                time.sleep(max(0, len(data) / DEVICE_RATE - (time.monotonic() - started)))
                if not monitor:
                    status.put(("played", (serial, item, len(pcm) // 2, epoch)))
    except Exception as exc:
        status.put(("error", f"Assistant audio output: {exc}"))
        stop.set()


class CableAudio:
    """A single-use assistant audio transport with explicit activation."""

    def __init__(
        self,
        meeting_source: Device,
        microphone_feed: Device,
        monitor: Device | None = None,
    ):
        if not is_virtual(meeting_source) or not is_virtual(microphone_feed):
            raise ValueError("AI Assistant requires the separate VoiceLoop virtual audio cables.")
        if meeting_source.id.removesuffix(".monitor") == microphone_feed.id:
            raise ValueError("Assistant input and output must use separate virtual cables.")
        if min(meeting_source.channels, microphone_feed.channels) < 1:
            raise ValueError("A virtual audio device has no channels.")
        if monitor and (
            is_virtual(monitor)
            or monitor.id in (meeting_source.id.removesuffix(".monitor"), microphone_feed.id)
        ):
            raise ValueError("The assistant monitor must be a separate physical speaker.")
        self.meeting_source = meeting_source
        self.microphone_feed = microphone_feed
        self.monitor = monitor
        self._ctx = mp.get_context("spawn")
        self._incoming = self._ctx.Queue(maxsize=64)
        # Keep the device queue short for interruption; generated responses may
        # arrive much faster than speech can play, so stage them separately.
        self._outgoing = self._ctx.Queue(maxsize=PLAYBACK_QUEUE_PACKETS)
        self._status = self._ctx.Queue(maxsize=512)
        self._monitor = self._ctx.Queue(maxsize=16) if monitor else None
        self._stop = self._ctx.Event()
        self._go = self._ctx.Event()
        self._generation = self._ctx.Value("i", 0)
        self._processes = []
        self._pending = {}
        self._buffer = deque()
        self._buffered_frames = 0
        self._last_progress_at = 0.0
        self._serial = 0
        self._unplayed = {}
        self._played = {}
        self._last_played_at = 0.0
        self._started = False
        self._closed = False
        self._stats = {
            "captured_frames": 0,
            "voiced_frames": 0,
            "generated_frames": 0,
            "played_frames": 0,
            "input_peak": 0.0,
            "sample_rate": REALTIME_RATE,
            "buffer_high_water_frames": 0,
            "playback_backpressure_count": 0,
            "discarded_frames": 0,
        }

    def start(self, cancelled=None):
        if self._started or self._closed:
            raise RuntimeError("Assistant audio transports cannot be reused.")
        self._started = True
        self._processes = [
            self._ctx.Process(
                target=_capture,
                args=(
                    self.meeting_source.id,
                    self._incoming,
                    self._status,
                    self._stop,
                    self._go,
                    self._monitor,
                ),
                daemon=True,
            ),
            self._ctx.Process(
                target=_playback,
                args=(
                    self.microphone_feed.id,
                    self._outgoing,
                    self._status,
                    self._stop,
                    self._generation,
                ),
                daemon=True,
            ),
        ]
        if self.monitor:
            self._processes.append(
                self._ctx.Process(
                    target=_playback,
                    args=(
                        self.monitor.id,
                        self._monitor,
                        self._status,
                        self._stop,
                        self._generation,
                    ),
                    kwargs={"monitor": True},
                    daemon=True,
                )
            )
        try:
            for process in self._processes:
                process.start()
            deadline = time.monotonic() + 12
            ready = 0
            while ready < len(self._processes):
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("Assistant preparation was cancelled.")
                if time.monotonic() > deadline:
                    raise RuntimeError("Virtual audio devices did not open within 12 seconds.")
                self._check_alive()
                try:
                    kind, value = self._status.get(timeout=0.05)
                except queue.Empty:
                    continue
                if kind == "error":
                    raise RuntimeError(value)
                ready += kind == "ready"
        except BaseException:
            self.close()
            raise

    def activate(self):
        self._go.set()

    def _check_alive(self):
        if self._stop.is_set() or any(p.pid and not p.is_alive() for p in self._processes):
            raise RuntimeError("An assistant audio worker stopped unexpectedly.")

    def _poll(self):
        for _ in range(512):
            try:
                kind, value = self._status.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                raise RuntimeError(value)
            if kind == "discarded":
                self._stats["discarded_frames"] += self._pending.pop(value, 0)
                self._last_progress_at = time.monotonic()
            elif kind == "played":
                serial, item, count, _epoch = value
                self._pending.pop(serial, None)
                self._played[item] = self._played.get(item, 0) + count
                if _epoch == self._generation.value and item in self._unplayed:
                    remaining = self._unplayed[item] - count
                    if remaining > 0:
                        self._unplayed[item] = remaining
                    else:
                        del self._unplayed[item]
                self._stats["played_frames"] += count
                self._last_played_at = time.monotonic()
                self._last_progress_at = self._last_played_at
        if not self._closed:
            self._check_alive()
            self._pump()
            if self._pending and time.monotonic() - self._last_progress_at > PLAYBACK_STALL_SECONDS:
                raise RuntimeError("Assistant audio output stopped making playback progress.")

    def _pump(self):
        while self._buffer:
            packet = self._buffer[0]
            try:
                self._outgoing.put_nowait(packet)
            except queue.Full:
                break
            self._buffer.popleft()
            count = len(packet[0]) // 2
            self._buffered_frames -= count
            if not self._pending:
                self._last_progress_at = time.monotonic()
            self._pending[packet[3]] = count

    def read(self):
        self._poll()
        try:
            pcm = self._incoming.get_nowait()
        except queue.Empty:
            return None
        values = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        self._stats["captured_frames"] += len(values)
        if len(values):
            self._stats["input_peak"] = max(self._stats["input_peak"], float(np.max(abs(values))))
            if np.sqrt(np.mean(values * values)) >= 0.01:
                self._stats["voiced_frames"] += len(values)
        return pcm

    def write(self, pcm, item_id):
        """Accept a complete delta, or return False to apply bounded backpressure.

        Full native queues are normal during faster-than-realtime generation.
        The caller can retry an unaccepted delta or cancel an excessive response
        while continuing input/control processing. Acceptance is atomic.
        """
        if len(pcm) % 2:
            raise ValueError("Realtime audio must contain complete PCM16 samples.")
        self._poll()
        count = len(pcm) // 2
        if count > MAX_BUFFERED_FRAMES:
            raise RuntimeError(
                "OpenAI returned an audio chunk larger than the bounded response buffer."
            )
        queued = self._buffered_frames + sum(self._pending.values())
        if queued + count > MAX_BUFFERED_FRAMES:
            self._stats["playback_backpressure_count"] += 1
            return False
        epoch = self._generation.value
        for offset in range(0, len(pcm), PLAYBACK_FRAMES * 2):
            packet = pcm[offset : offset + PLAYBACK_FRAMES * 2]
            self._serial += 1
            self._buffer.append((packet, item_id, epoch, self._serial))
        self._buffered_frames += count
        if count:
            self._unplayed[item_id] = self._unplayed.get(item_id, 0) + count
        self._stats["generated_frames"] += count
        self._stats["buffer_high_water_frames"] = max(
            self._stats["buffer_high_water_frames"], queued + count
        )
        self._pump()
        return True

    def interrupt(self):
        """Discard queued speech and return only unfinished items to truncate.

        A completed item's transcript must stay in the server conversation.
        Generation can run ahead across several items, so each queued item has
        its own actual played offset; the latest generated item is insufficient.
        """
        self._poll()
        truncations = [
            {"item_id": item, "audio_end_ms": self._played.get(item, 0) * 1000 // REALTIME_RATE}
            for item in self._unplayed
        ]
        with self._generation.get_lock():
            self._generation.value += 1
        self._unplayed.clear()
        self._stats["discarded_frames"] += self._buffered_frames
        self._buffer.clear()
        self._buffered_frames = 0
        return truncations

    def drained(self):
        self._poll()
        # Account for the final host mixer/device buffer before hanging up.
        return (
            not self._buffer
            and not self._pending
            and time.monotonic() - self._last_played_at >= 0.15
        )

    def stats(self):
        return {
            **self._stats,
            "buffered_frames": self._buffered_frames + sum(self._pending.values()),
            "buffer_limit_frames": MAX_BUFFERED_FRAMES,
        }

    def close(self):
        if self._closed:
            return
        self._stop.set()
        for process in self._processes:
            if process.pid:
                process.join(timeout=0.25)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=0.3)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.3)
                process.close()
        self._closed = True
        for channel in (self._incoming, self._outgoing, self._status, self._monitor):
            if channel is not None:
                channel.cancel_join_thread()
                channel.close()
