"""Exercise the real coordinator with spawned synthetic audio, never microphones."""

import json
import multiprocessing
import queue
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

import voiceloop.engine as engine_module
from voiceloop.audio import BLOCK_FRAMES, SAMPLE_RATE
from voiceloop.devices import Device, SessionConfig
from voiceloop.engine import Engine


def synthetic_capture(device_id, channel, audio, status, route, stop, go, muted=None):
    audio.cancel_join_thread()
    if route is not None:
        route.cancel_join_thread()
    if device_id == "fail":
        status.put(("error", "Synthetic device failure"))
        return
    status.put(("ready", f"capture-{channel}"))
    while not go.wait(0.01):
        if stop.is_set():
            return
    origin = time.monotonic()
    position = 0
    while not stop.is_set():
        data = (
            np.sin(
                2
                * np.pi
                * (220 if channel == 0 else 660)
                * (np.arange(BLOCK_FRAMES) + position)
                / SAMPLE_RATE
            ).astype(np.float32)
            * 0.3
        )
        if device_id.startswith("tail-") and position >= SAMPLE_RATE * (
            0.6 if channel == 0 else 0.3
        ):
            data.fill(0)
        stamp = origin + position / SAMPLE_RATE
        audio.put((channel, stamp, data))
        if route is not None:
            route.put(np.repeat(data[:, None], 2, axis=1))
        position += BLOCK_FRAMES
        stop.wait(max(0, origin + position / SAMPLE_RATE - time.monotonic()))


def synthetic_playback(device_id, route, status, stop, go):
    status.put(("ready", "playback-" + device_id))
    while not go.wait(0.01):
        if stop.is_set():
            return
    while not stop.is_set():
        try:
            data = route.get(timeout=0.1)
            assert data.ndim == 2 and data.shape[1] == 2
        except queue.Empty:
            pass


def wait_running(engine):
    deadline = time.monotonic() + 15
    while engine.state == "starting" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert engine.state == "running", (engine.state, engine.error)


def main():
    engine_module._capture = synthetic_capture
    engine_module._playback = synthetic_playback
    microphone = Device("mic", "Synthetic mic", 2)
    meeting = Device("meeting", "Synthetic meeting", 2)
    speaker = Device("speaker", "Synthetic speaker", 2)
    feed = Device("feed", "Synthetic virtual mic", 2)
    config = SessionConfig(microphone, meeting, speaker)
    with tempfile.TemporaryDirectory(prefix="voiceloop-test-") as directory:
        root = Path(directory)
        engine = Engine()
        engine.start(config, root, record=True)
        wait_running(engine)
        time.sleep(0.8)
        engine.stop()
        assert engine.wait(8), "Shutdown timed out"
        assert not engine.error, engine.error
        manifest = json.loads((engine.saved_path / "session.json").read_text())
        assert manifest["status"] == "complete"
        with wave.open(str(engine.saved_path / "audio-001.wav"), "rb") as source:
            data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").reshape(-1, 2)
        assert 0.7 < len(data) / SAMPLE_RATE < 1.1
        chunk = data[SAMPLE_RATE // 4 : SAMPLE_RATE // 2].astype(float)
        for channel, frequency in enumerate((220, 660)):
            frequencies = np.fft.rfftfreq(len(chunk), 1 / SAMPLE_RATE)
            peak = frequencies[np.argmax(abs(np.fft.rfft(chunk[:, channel])))]
            assert abs(peak - frequency) < 8, (channel, peak)
        assert "trim" not in manifest, "Ordinary Stop unexpectedly trimmed audio"
        tail = SessionConfig(
            Device("tail-mic", "Synthetic mic", 2),
            Device("tail-meeting", "Synthetic meeting", 2),
            speaker,
        )
        engine.start(tail, root, record=True)
        wait_running(engine)
        time.sleep(1.5)
        engine.stop(trim_silence=True)
        assert engine.wait(8)
        assert not engine.error, engine.error
        trimmed = json.loads((engine.saved_path / "session.json").read_text())
        assert 0.8 <= trimmed["duration_seconds"] <= 1.1, trimmed
        assert trimmed["trim"]["removed_frames"] > SAMPLE_RATE * 0.3, trimmed
        with wave.open(str(engine.saved_path / "audio-001.wav"), "rb") as source:
            assert source.getnframes() == trimmed["frames"]
        before = list(root.iterdir())
        bridge = SessionConfig(microphone, meeting, speaker, feed, "bridge")
        engine.start(bridge, root, record=False)
        wait_running(engine)
        time.sleep(0.3)
        engine.stop()
        assert engine.wait(8)
        assert not engine.error, engine.error
        assert list(root.iterdir()) == before, "Routing-only wrote files"
        failing = SessionConfig(Device("fail", "Fail", 2), meeting, speaker)
        engine.start(failing, root, record=True)
        assert engine.wait(8)
        assert engine.state == "error" and "failure" in engine.error
        assert list(root.iterdir()) == before
        engine.start(config, root, record=True)
        engine.stop()
        assert engine.wait(8)
        assert list(root.iterdir()) == before, "Cancelled startup wrote files"
        assert not multiprocessing.active_children(), "Leaked audio workers"
    print(
        "PASS: stereo recording, timing, bridge routing without files, "
        "energy-based tail trim, device failure, cancelled startup, worker cleanup"
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
