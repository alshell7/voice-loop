import json
import wave

import numpy as np
import pytest

from voiceloop.config import atomic_json
from voiceloop.recording import Recording
from voiceloop.transcription import Segment, transcribe_session


class FakeProvider:
    name = "test"
    uploads_audio = False

    def transcribe(self, wav_path):
        with wave.open(str(wav_path), "rb") as source:
            assert source.getnchannels() == 1
            assert source.getnframes() > 0
        yield Segment(0, 0.0001, "Hello")


def test_separate_channel_transcripts_and_offsets(tmp_path):
    recording = Recording(tmp_path, {}, segment_frames=16)
    recording.write(np.ones((32, 2)) * 0.2)
    directory = recording.close()
    output = transcribe_session(directory, FakeProvider())
    result = json.loads(output.read_text())
    assert len(result["segments"]) == 4
    assert [s["speaker"] for s in result["segments"]] == ["You", "Meeting", "You", "Meeting"]
    assert result["segments"][2]["start"] == 16 / 48000


def test_silence_is_skipped(tmp_path):
    recording = Recording(tmp_path, {})
    recording.write(np.zeros((16, 2)))
    directory = recording.close()
    result = json.loads(transcribe_session(directory, FakeProvider()).read_text())
    assert result["segments"] == []


def test_cloud_provider_requires_separate_consent(tmp_path):
    provider = FakeProvider()
    provider.uploads_audio = True
    with pytest.raises(ValueError, match="consent"):
        transcribe_session(tmp_path, provider)


def test_running_recording_and_path_escape_are_rejected(tmp_path):
    recording = Recording(tmp_path, {})
    with pytest.raises(ValueError, match="Stop"):
        transcribe_session(recording.directory, FakeProvider())
    directory = recording.close()
    path = directory / "session.json"
    manifest = json.loads(path.read_text())
    manifest["parts"] = [{"file": "../outside.wav", "start_frame": 0}]
    atomic_json(path, manifest)
    with pytest.raises(ValueError, match="inside"):
        transcribe_session(directory, FakeProvider())
