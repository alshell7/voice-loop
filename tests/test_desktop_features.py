import json
import queue
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from voiceloop.config import Settings, atomic_json
from voiceloop.engine import _capture
from voiceloop.library import Contacts, SessionLibrary, audio_parts, update_metadata
from voiceloop.recording import Recording
from voiceloop.startup import set_enabled, startup_file


def test_typed_settings_and_opacity_limits(tmp_path):
    path = tmp_path / "settings.json"
    atomic_json(
        path,
        {
            "launch_at_login": False,
            "auto_transcribe": "yes",
            "floating_opacity": 4,
            "session_mode": "record",
        },
    )
    settings = Settings.load(path)
    assert settings.launch_at_login is False
    assert settings.auto_transcribe is False
    assert settings.floating_opacity == 65
    assert settings.session_mode == "record"


def test_contacts_remember_normalize_and_deduplicate(tmp_path):
    contacts = Contacts(tmp_path / "contacts.json")
    assert contacts.remember("  Maya   Shah ") == "Maya Shah"
    assert contacts.remember("maya shah") == "Maya Shah"
    assert contacts.remember("") == ""
    assert Contacts(contacts.path).names() == ["Maya Shah"]


def test_library_filters_pagination_and_changed_metadata(tmp_path):
    paths = []
    for i in range(19):
        recording = Recording(
            tmp_path,
            {},
            metadata={
                "contact": "Maya" if i < 10 else "Alex",
                "tool": "Zoom" if i % 2 else "Google Meet",
            },
        )
        recording.manifest["started_at"] = f"2026-09-{i + 1:02d}T10:00:00+00:00"
        paths.append(recording.close())
    index = SessionLibrary()
    page = index.query(tmp_path)
    assert page.total == 19 and page.pages == 3 and len(page.items) == 8
    assert index.query(tmp_path, page=3).items[-1].directory == paths[0]
    assert len(index.query(tmp_path, page=999).items) == 3
    assert index.query(tmp_path, text="maya", tool="Zoom").total == 5
    atomic_json(paths[0] / "transcript.json", {"segments": []})
    assert index.query(tmp_path, state="transcribed").total == 1
    update_metadata(paths[0], tool="Phone", contact="Sam")
    assert index.query(tmp_path, tool="Phone", contact="Sam").total == 1
    assert index.query(tmp_path, text="absent").items == []


def test_audio_paths_and_live_metadata_are_protected(tmp_path):
    recording = Recording(tmp_path, {})
    with pytest.raises(ValueError, match="Finish"):
        update_metadata(recording.directory, tool="Zoom", contact="Maya")
    with pytest.raises(ValueError, match="inside"):
        audio_parts(recording.directory, {"parts": [{"file": "../outside.wav"}]})
    recording.close()


@pytest.mark.parametrize("channel,muted,expected", [(0, True, 0), (0, False, 1), (1, True, 1)])
def test_mute_silences_both_recording_and_route(monkeypatch, channel, muted, expected):
    stop, go, mute = threading.Event(), threading.Event(), threading.Event()
    go.set()
    if muted:
        mute.set()

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def record(self, **_):
            stop.set()
            return np.ones((960, 2), dtype=np.float32)

    device = SimpleNamespace(id="test", channels=2, recorder=lambda **_: Recorder())
    monkeypatch.setitem(
        __import__("sys").modules,
        "soundcard",
        SimpleNamespace(all_microphones=lambda **_: [device]),
    )
    audio, route, status = queue.Queue(), queue.Queue(), queue.Queue()
    audio.cancel_join_thread = route.cancel_join_thread = lambda: None
    _capture("test", channel, audio, status, route, stop, go, mute)
    np.testing.assert_array_equal(audio.get_nowait()[2], np.full(960, expected))
    np.testing.assert_array_equal(route.get_nowait(), np.full((960, 2), expected))
    assert status.qsize() == 1  # Ready, no error.


def test_login_files_use_user_paths_and_never_start_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    command = ["/Applications/Voice Loop.app/Contents/MacOS/VoiceLoop", "--background"]
    set_enabled(True, command=command, platform="darwin", home=tmp_path)
    import plistlib

    data = plistlib.loads(startup_file("darwin", tmp_path).read_bytes())
    assert data["RunAtLoad"] is True and data["ProgramArguments"] == command
    set_enabled(False, platform="darwin", home=tmp_path)
    assert not startup_file("darwin", tmp_path).exists()
    set_enabled(
        True, command=["/opt/a $b/VoiceLoop", "--background"], platform="linux", home=tmp_path
    )
    content = startup_file("linux", tmp_path).read_text()
    assert 'Exec="/opt/a \\$b/VoiceLoop" "--background"' in content
    assert "Terminal=false" in content


def test_recording_carries_contact_and_tool(tmp_path):
    recording = Recording(tmp_path, {}, metadata={"contact": "Maya", "tool": "Zoom"})
    recording.write(np.zeros((16, 2)))
    result = json.loads((recording.close() / "session.json").read_text())
    assert result["metadata"] == {"contact": "Maya", "tool": "Zoom"}
