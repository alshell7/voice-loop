import numpy as np
import pytest

from voiceloop.assistant_audio import CableAudio, Downsample48k, upsample24k
from voiceloop.devices import Device


def test_downsample_is_continuous_across_uneven_chunks():
    values = np.sin(2 * np.pi * 1000 * np.arange(48_000) / 48_000)
    expected = Downsample48k().convert(values)
    converter = Downsample48k()
    actual = np.concatenate([converter.convert(block) for block in np.array_split(values, 137)])
    assert len(actual) == 24_000
    np.testing.assert_allclose(actual, expected, atol=1e-7)
    assert np.sqrt(np.mean(actual[100:] ** 2)) > 0.7


def test_downsample_suppresses_frequencies_above_new_nyquist():
    values = np.sin(2 * np.pi * 18_000 * np.arange(48_000) / 48_000)
    converted = Downsample48k().convert(values)
    assert np.sqrt(np.mean(converted[100:] ** 2)) < 0.003


def test_upsample_preserves_duration_and_range():
    result = upsample24k(np.array([0, 32767, -32768], dtype="<i2").tobytes())
    assert len(result) == 6
    assert np.max(abs(result)) <= 1
    np.testing.assert_allclose(result[::2], [0, 32767 / 32768, -1])
    assert len(upsample24k(b"")) == 0


def test_physical_microphone_cannot_be_an_assistant_source():
    with pytest.raises(ValueError, match="virtual audio cables"):
        CableAudio(Device("mic", "Jabra microphone", 2), Device("feed", "VoiceLoop Mic Feed", 2))


def test_shared_cable_and_virtual_monitor_are_rejected():
    source = Device("source", "VoiceLoop Speaker", 2, True)
    with pytest.raises(ValueError, match="separate virtual cables"):
        CableAudio(source, Device("source", "VoiceLoop Mic Feed", 2))
    with pytest.raises(ValueError, match="physical speaker"):
        CableAudio(source, Device("feed", "VoiceLoop Mic Feed", 2), source)


def test_close_before_start_is_idempotent_and_does_not_open_hardware():
    audio = CableAudio(
        Device("source", "VoiceLoop Speaker", 2, True), Device("feed", "VoiceLoop Mic Feed", 2)
    )
    audio.close()
    audio.close()
    with pytest.raises(RuntimeError, match="cannot be reused"):
        audio.start()
