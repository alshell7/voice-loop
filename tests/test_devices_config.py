import json

import pytest

from voiceloop.config import Settings, atomic_json
from voiceloop.devices import Device, Devices, SessionConfig, loopback_for

MIC = Device("mic", "Microphone", 1)
SPEAKER = Device("speaker", "Speaker", 2)
MEETING = Device("virtual-meeting", "Meeting", 2, True)
FEED = Device("virtual-feed", "Mic feed", 2)


def test_direct_and_bridge_routes():
    SessionConfig(MIC, MEETING, SPEAKER).validate()
    SessionConfig(MIC, MEETING, SPEAKER, FEED, "bridge").validate()


@pytest.mark.parametrize(
    "microphone,meeting,speaker,feed,mode",
    [
        (MIC, MIC, SPEAKER, None, "direct"),
        (MEETING, MIC, SPEAKER, None, "direct"),
        (MIC, MEETING, SPEAKER, None, "bridge"),
        (MIC, MEETING, SPEAKER, SPEAKER, "bridge"),
        (MIC, Device("speaker", "Loopback", 2, True), SPEAKER, FEED, "bridge"),
        (MIC, Device("virtual-feed.monitor", "Loopback", 2, True), SPEAKER, FEED, "bridge"),
        (MIC, MEETING, SPEAKER, FEED, "bogus"),
    ],
)
def test_feedback_and_invalid_routes_are_rejected(microphone, meeting, speaker, feed, mode):
    with pytest.raises(ValueError):
        SessionConfig(microphone, meeting, speaker, feed, mode).validate()


def test_loopback_matches_stable_ids():
    source = Device("speaker", "Speaker", 2, True)
    assert loopback_for(SPEAKER, Devices([source], [SPEAKER])) == source
    assert loopback_for(SPEAKER, Devices([MIC], [SPEAKER])) is None


def test_settings_round_trip_and_unknown_fields(tmp_path):
    path = tmp_path / "settings.json"
    Settings(microphone_id="mic-α", mode="bridge", recording_directory=str(tmp_path)).save(path)
    settings = Settings.load(path)
    assert settings.microphone_id == "mic-α"
    assert settings.recordings == tmp_path
    data = json.loads(path.read_text())
    data["future_field"] = True
    data["speaker_id"] = []
    atomic_json(path, data)
    assert Settings.load(path).speaker_id == ""
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("content", ["{broken", "[]", "null", "42"])
def test_corrupted_settings_use_safe_defaults(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    assert Settings.load(path) == Settings()
