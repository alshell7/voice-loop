"""Bounded native playback worker with pause and session-relative seeking."""

import multiprocessing as mp
import queue
import wave

import numpy as np

from voiceloop.audio import SAMPLE_RATE, mono
from voiceloop.devices import is_virtual


def _play(paths, device_id, position, target, paused, stop, events):
    try:
        import soundcard as sc

        device = next(d for d in sc.all_speakers() if str(d.id) == device_id)
        counts = []
        for path in paths:
            with wave.open(path, "rb") as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (
                    2,
                    2,
                    SAMPLE_RATE,
                ):
                    raise ValueError("Playback expects Voice Loop 48 kHz stereo WAV files.")
                counts.append(audio.getnframes())
        boundaries = np.cumsum([0, *counts])
        total = int(boundaries[-1])
        channels = min(2, device.channels)
        with device.player(samplerate=SAMPLE_RATE, channels=channels, blocksize=4800) as player:
            stream, current = None, -1
            try:
                while not stop.is_set():
                    with target.get_lock():
                        requested = target.value
                        target.value = -1
                    if requested >= 0:
                        position.value = max(0, min(total, requested))
                        if stream:
                            stream.close()
                        stream, current = None, -1
                    if position.value >= total:
                        events.put(("complete", ""))
                        return
                    if paused.is_set():
                        stop.wait(0.05)
                        continue
                    index = int(np.searchsorted(boundaries, position.value, side="right") - 1)
                    if index != current:
                        if stream:
                            stream.close()
                        current = index
                        stream = wave.open(paths[index], "rb")
                        stream.setpos(position.value - int(boundaries[index]))
                    data = np.frombuffer(stream.readframes(4800), dtype="<i2").reshape(-1, 2)
                    if not len(data):
                        position.value = int(boundaries[index + 1])
                        continue
                    samples = data.astype(np.float32) / 32768
                    player.play(mono(samples)[:, None] if channels == 1 else samples)
                    position.value += len(data)
            finally:
                if stream:
                    stream.close()
    except Exception as exc:
        events.put(("error", "Playback: " + str(exc)))


class Player:
    def __init__(self, paths, device, start=0):
        if is_virtual(device):
            raise ValueError("Choose a physical playback speaker first.")
        context = mp.get_context("spawn")
        self.position = context.Value("q", int(start * SAMPLE_RATE))
        self.target = context.Value("q", -1)
        self.paused, self.stop = context.Event(), context.Event()
        self.events = context.Queue()
        self.process = context.Process(
            target=_play,
            args=(
                [str(p) for p in paths],
                device.id,
                self.position,
                self.target,
                self.paused,
                self.stop,
                self.events,
            ),
            daemon=True,
        )
        self.process.start()

    def poll(self):
        try:
            return self.events.get_nowait()
        except queue.Empty:
            if self.process.exitcode is not None:
                return (
                    ("complete", "")
                    if self.process.exitcode == 0
                    else ("error", "Playback stopped.")
                )
            return None

    def seek(self, seconds):
        self.target.value = int(seconds * SAMPLE_RATE)

    def close(self):
        self.stop.set()
        self.process.join(timeout=0.2)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=1)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=1)
        self.process.close()
        self.events.close()
        self.events.cancel_join_thread()
