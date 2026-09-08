import json
import wave

import numpy as np
import pytest

from voiceloop.audio import SAMPLE_RATE
from voiceloop.recording import Recording


def read_part(path):
    with wave.open(str(path), "rb") as source:
        assert (source.getnchannels(), source.getsampwidth(), source.getframerate()) == (
            2,
            2,
            SAMPLE_RATE,
        )
        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").reshape(-1, 2)


def test_rotation_and_channel_order(tmp_path):
    recording = Recording(tmp_path, {"test": True}, segment_frames=5)
    recording.write(np.tile([0.25, -0.5], (12, 1)))
    directory = recording.close()
    manifest = json.loads((directory / "session.json").read_text())
    assert manifest["frames"] == 12
    assert manifest["status"] == "complete"
    assert manifest["consent"] == "explicit_session"
    assert [p["start_frame"] for p in manifest["parts"]] == [0, 5, 10]
    assert [p["frames"] for p in manifest["parts"]] == [5, 5, 2]
    result = np.concatenate([read_part(directory / p["file"]) for p in manifest["parts"]])
    np.testing.assert_allclose(result / 32767, np.tile([0.25, -0.5], (12, 1)), atol=1 / 32767)


def test_headers_are_readable_before_close(tmp_path):
    recording = Recording(tmp_path, {})
    try:
        recording.write(np.ones((160, 2)) * 0.5)
        recording.flush()
        assert len(read_part(recording.directory / "audio-001.wav")) == 160
        manifest = json.loads((recording.directory / "session.json").read_text())
        assert manifest["status"] == "recording"
        assert manifest["frames"] == 160
    finally:
        recording.close("Simulated interrupted device")
    assert json.loads((recording.directory / "session.json").read_text())["status"] == "interrupted"


def test_recording_names_are_unique_and_close_idempotent(tmp_path):
    first, second = Recording(tmp_path, {}), Recording(tmp_path, {})
    assert first.directory != second.directory
    assert first.close() == first.close()
    second.close()
    with pytest.raises(RuntimeError):
        first.write(np.zeros((1, 2)))


def test_writer_failure_does_not_hide_previously_written_data(tmp_path):
    recording = Recording(tmp_path, {})
    recording.write(np.ones((80, 2)))
    recording.flush()
    with pytest.raises(ValueError):
        recording.write(np.zeros((3, 1)))
    recording.close("Invalid input")
    assert len(read_part(recording.directory / "audio-001.wav")) == 80


def test_output_failure_is_reported(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    with pytest.raises(OSError):
        Recording(blocked, {})


@pytest.mark.parametrize("keep,counts", [(7, [5, 2]), (5, [5]), (0, [0]), (12, [5, 5, 2])])
def test_trim_rotated_wavs_and_manifest_agree(tmp_path, keep, counts):
    recording = Recording(tmp_path, {}, segment_frames=5)
    samples = np.arange(24, dtype=np.float32).reshape(12, 2) / 100
    recording.write(samples)
    directory = recording.close(trim_end_frame=keep)
    manifest = json.loads((directory / "session.json").read_text())
    assert [p["frames"] for p in manifest["parts"]] == counts
    parts = [read_part(directory / part["file"]) for part in manifest["parts"]]
    assert [len(p) for p in parts] == counts
    actual = np.concatenate(parts)
    np.testing.assert_allclose(actual / 32767, samples[:keep], atol=1 / 32767)
    assert len(list(directory.glob("*.wav"))) == len(counts)
    assert not list(directory.glob("*.tmp"))
    assert manifest["frames"] == keep
    assert manifest["duration_seconds"] == keep / SAMPLE_RATE


def test_trim_replacement_failure_preserves_original_audio(tmp_path, monkeypatch):
    import os

    recording = Recording(tmp_path, {}, segment_frames=5)
    recording.write(np.full((12, 2), 0.25))
    original_replace = os.replace

    def fail_audio_replace(source, destination):
        if str(destination).endswith(".wav"):
            raise OSError("Synthetic disk failure")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_audio_replace)
    with pytest.raises(OSError, match="disk failure"):
        recording.close(trim_end_frame=7)
    recording.close("Could not trim recording")
    manifest = json.loads((recording.directory / "session.json").read_text())
    assert manifest["status"] == "interrupted"
    assert manifest["frames"] == 12
    assert sum(len(read_part(path)) for path in recording.directory.glob("*.wav")) == 12
