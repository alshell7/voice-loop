import json

import numpy as np
import pytest

from voiceloop.activity import EnergyActivity
from voiceloop.audio import SAMPLE_RATE, Timeline
from voiceloop.engine import Engine
from voiceloop.recording import Recording


def test_energy_threshold_and_streaming_window_boundaries():
    activity = EnergyActivity()
    # Quiet background stays below -45 dBFS; mic activity does not reset speaker quiet.
    data = np.full((SAMPLE_RATE * 31, 2), 0.001, dtype=np.float32)
    data[-SAMPLE_RATE:, 0] = 0.1
    for block in np.array_split(data, 197):
        activity.update(block)
    activity.finish()
    assert activity.speaker_quiet_seconds == 31
    assert activity.last_active[0] == len(data)
    assert activity.trim_frame == len(data)
    activity.update(np.full((960, 2), 0.1))
    assert activity.speaker_quiet_seconds == 0
    assert len(activity.pending) < activity.window_frames


def test_trim_retains_end_padding_and_partial_final_voice():
    activity = EnergyActivity()
    activity.update(np.full((SAMPLE_RATE, 2), 0.1))
    activity.update(np.zeros((SAMPLE_RATE * 31, 2)))
    assert activity.speaker_quiet_seconds == 31
    assert activity.trim_frame == SAMPLE_RATE * 1.25
    activity.update(np.full((11, 2), 0.1))
    activity.finish()
    assert activity.trim_frame == SAMPLE_RATE * 32 + 11


def test_wholly_quiet_recording_has_no_voice_padding():
    activity = EnergyActivity()
    activity.update(np.zeros((SAMPLE_RATE, 2)))
    assert activity.trim_frame == 0


@pytest.mark.parametrize("swapped", [False, True])
def test_coordinator_tracks_speaker_but_trim_preserves_later_microphone(tmp_path, swapped):
    devices = {"left_channel": "meeting", "right_channel": "microphone"} if swapped else {}
    recording = Recording(tmp_path, devices, segment_frames=SAMPLE_RATE * 2)
    engine, timeline = Engine(), Timeline()
    # Speaker ends at 1s; local speech continues until 3s. Preserve both tracks
    # through 3.25s even though speaker silence is what prompted the stop.
    for second in range(35):
        timeline.insert(0, second * SAMPLE_RATE, np.full(SAMPLE_RATE, 0.1 if second < 3 else 0))
        timeline.insert(1, second * SAMPLE_RATE, np.full(SAMPLE_RATE, 0.1 if second < 1 else 0))
        engine._write_to(timeline, (second + 1) * SAMPLE_RATE, recording)
    assert engine.activity.speaker_quiet_seconds == 34
    engine.activity.finish()
    directory = recording.close(trim_end_frame=engine.activity.trim_frame)
    manifest = json.loads((directory / "session.json").read_text())
    assert manifest["duration_seconds"] == 3.25
    assert manifest["trim"]["removed_frames"] == SAMPLE_RATE * 31.75
    assert len(manifest["parts"]) == len(list(directory.glob("*.wav"))) == 2
