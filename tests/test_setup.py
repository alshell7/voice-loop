import hashlib
import io
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from voiceloop import installation
from voiceloop.devices import Device, Devices, bridge_endpoints, simple_config
from voiceloop.recording import Recording


def hardware(bridge=False):
    mic = Device("physical-mic", "Headset microphone", 2)
    speaker = Device("physical-speaker", "Headphones", 2)
    inputs = [mic, Device(speaker.id, speaker.name, 2, True)]
    outputs = [speaker]
    if bridge:
        inputs += [
            Device("cable-capture", "VoiceLoop Mic", 2),
            Device("hifi-render", "VoiceLoop Speaker", 2, True),
        ]
        outputs += [
            Device("cable-render", "VoiceLoop Mic Feed", 2),
            Device("hifi-render", "VoiceLoop Speaker", 2),
        ]
    return Devices(inputs, outputs, mic.id, speaker.id)


def test_simple_uses_direct_without_virtual_devices():
    devices = hardware()
    config = simple_config(devices.inputs[0], devices.outputs[0], devices)
    assert config.mode == "direct"
    assert config.meeting.loopback


def test_simple_resolves_two_independent_named_cables():
    devices = hardware(True)
    config = simple_config(devices.inputs[0], devices.outputs[0], devices)
    assert config.mode == "bridge"
    assert config.meeting.id == "hifi-render"
    assert config.virtual_mic.id == "cable-render"
    assert config.speaker.id == "physical-speaker"


def test_partial_bridge_never_reports_ready():
    devices = hardware(True)
    devices.outputs.pop()
    assert bridge_endpoints(devices) is None


def test_windows_manufacturer_suffixes_resolve_without_false_prefix_matches():
    devices = hardware(True)
    devices.inputs = [
        Device(d.id, d.name + " (VB-Audio Virtual Cable)", d.channels, d.loopback)
        if d.name.startswith("VoiceLoop")
        else d
        for d in devices.inputs
    ]
    devices.outputs = [
        Device(d.id, d.name + " (VB-Audio Virtual Cable)", d.channels)
        if d.name.startswith("VoiceLoop")
        else d
        for d in devices.outputs
    ]
    assert bridge_endpoints(devices)
    devices.outputs[-1] = Device("other", "VoiceLoop Speaker Clone", 2)
    assert bridge_endpoints(devices) is None


def test_macos_duplex_aliases_resolve():
    devices = hardware()
    aliases = [
        Device("mic-alias", "VoiceLoop Mic", 2),
        Device("speaker-alias", "VoiceLoop Speaker", 16),
    ]
    devices.inputs += aliases
    devices.outputs += aliases
    bridge = bridge_endpoints(devices)
    assert bridge.microphone_feed.id == "mic-alias"
    assert bridge.meeting_source.id == "speaker-alias"


def test_simple_rejects_virtual_physical_selection():
    devices = hardware(True)
    with pytest.raises(ValueError, match="physical"):
        simple_config(devices.inputs[-2], devices.outputs[0], devices)


def test_swapped_recording_channels_match_manifest(tmp_path):
    recording = Recording(tmp_path, {"left_channel": "meeting", "right_channel": "microphone"})
    recording.write(np.tile([0.25, -0.75], (200, 1)))
    directory = recording.close()
    with wave.open(str(directory / "audio-001.wav")) as source:
        data = np.frombuffer(source.readframes(200), dtype="<i2").reshape(-1, 2)
    assert data[:, 0].mean() < 0
    assert data[:, 1].mean() > 0
    assert json.loads((directory / "session.json").read_text())["channels"] == {
        "0": "meeting",
        "1": "microphone",
    }


def test_invalid_channel_map_writes_nothing(tmp_path):
    with pytest.raises(ValueError, match="channels"):
        Recording(tmp_path, {"left_channel": "meeting", "right_channel": "meeting"})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("valid", [False, True])
def test_download_is_verified_before_promotion(tmp_path, monkeypatch, valid):
    payload = b"driver fixture"
    response = io.BytesIO(payload)
    response.url = "https://vendor.example/driver.pkg"
    monkeypatch.setattr(installation.urllib.request, "urlopen", lambda *a, **k: response)
    output = tmp_path / "driver.pkg"
    digest = hashlib.sha256(payload).hexdigest() if valid else "0" * 64
    if valid:
        installation.download_verified(response.url, output, digest)
        assert output.read_bytes() == payload
    else:
        with pytest.raises(RuntimeError, match="checksum"):
            installation.download_verified(response.url, output, digest)
        assert not output.exists()
    assert not list(tmp_path.glob("*.partial"))


def test_download_refuses_http(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        installation.download_verified("http://vendor.example/file", tmp_path / "file", "0" * 64)


def test_powershell_paths_cannot_become_commands():
    assert installation.powershell_literal("C:\\O'Brien\\$app.ps1") == "'C:\\O''Brien\\$app.ps1'"


def test_driver_helpers_are_in_source_distribution():
    for name in ("windows-audio.ps1", "WindowsAudio.cs", "macos-audio.swift"):
        assert (Path(installation.RESOURCES) / name).is_file()
