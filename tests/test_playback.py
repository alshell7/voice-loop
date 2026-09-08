import multiprocessing as mp
import queue
import sys
import threading
import wave
from types import SimpleNamespace

import numpy as np

from voiceloop.audio import SAMPLE_RATE
from voiceloop.playback import _play


def audio_file(path, value, frames):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((2, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        stream.writeframes(np.full((frames, 2), value, dtype="<i2").tobytes())
    return str(path)


def worker_state(monkeypatch):
    blocks, opened = [], threading.Event()

    class Output:
        def __enter__(self):
            opened.set()
            return self

        def __exit__(self, *_):
            pass

        def play(self, samples):
            blocks.append(samples.copy())

    device = SimpleNamespace(id="test", channels=2, player=lambda **_: Output())
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_speakers=lambda: [device]))
    context = mp.get_context("spawn")
    position, target = context.Value("q", 0), context.Value("q", -1)
    paused, stop, events = threading.Event(), threading.Event(), queue.Queue()
    return blocks, opened, ("test", position, target, paused, stop, events)


def test_playback_crosses_wav_parts_without_repeating_or_dropping_samples(tmp_path, monkeypatch):
    paths = [audio_file(tmp_path / "a.wav", 8192, 5000), audio_file(tmp_path / "b.wav", -4096, 21)]
    blocks, _, args = worker_state(monkeypatch)
    _play(paths, *args)
    samples = np.concatenate(blocks)
    assert samples.shape == (5021, 2)
    np.testing.assert_array_equal(samples[:5000], 0.25)
    np.testing.assert_array_equal(samples[5000:], -0.125)
    assert args[1].value == 5021
    assert args[-1].get_nowait() == ("complete", "")


def test_playback_pause_and_seek_to_later_part(tmp_path, monkeypatch):
    paths = [audio_file(tmp_path / "a.wav", 8192, 5000), audio_file(tmp_path / "b.wav", -4096, 21)]
    blocks, opened, args = worker_state(monkeypatch)
    _, position, target, paused, stop, events = args
    paused.set()
    thread = threading.Thread(target=_play, args=(paths, *args))
    thread.start()
    try:
        assert opened.wait(2)
        assert blocks == [] and position.value == 0
        target.value = 5010
        paused.clear()
        thread.join(2)
        assert not thread.is_alive()
        samples = np.concatenate(blocks)
        assert samples.shape == (11, 2)
        np.testing.assert_array_equal(samples, -0.125)
        assert events.get_nowait() == ("complete", "")
    finally:
        stop.set()
        thread.join(2)
