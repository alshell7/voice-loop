import numpy as np
import pytest

from voiceloop.audio import Timeline, mono, pcm16, stereo


def test_channels_remain_separate_and_gaps_are_silence():
    timeline = Timeline(32)
    timeline.insert(0, 0, np.ones(8))
    timeline.insert(1, 4, np.full(8, -0.5))
    output = timeline.read(16)
    np.testing.assert_equal(output[:8, 0], 1)
    np.testing.assert_equal(output[8:, 0], 0)
    np.testing.assert_equal(output[:4, 1], 0)
    np.testing.assert_equal(output[4:12, 1], -0.5)
    np.testing.assert_equal(output[12:, 1], 0)


def test_wraparound_does_not_replay_old_audio():
    timeline = Timeline(8)
    timeline.insert(0, 0, np.ones(8))
    timeline.read(6)
    timeline.insert(1, 8, np.ones(6) * 0.4)
    result = timeline.read(8)
    np.testing.assert_equal(result[:2, 0], 1)
    np.testing.assert_equal(result[2:, 0], 0)
    np.testing.assert_allclose(result[2:, 1], 0.4)
    np.testing.assert_equal(timeline.read(8), 0)


def test_late_packets_are_trimmed_not_shifted():
    timeline = Timeline(8)
    timeline.read(4)
    timeline.insert(0, 2, np.arange(6))
    np.testing.assert_equal(timeline.read(4)[:, 0], [2, 3, 4, 5])
    assert timeline.late_frames == 2


def test_negative_start_and_future_overflow_are_bounded():
    timeline = Timeline(8)
    timeline.insert(0, -3, np.ones(4))
    timeline.insert(1, 7, np.ones(6))
    timeline.insert(1, 100, np.ones(6))
    assert timeline.late_frames == 3
    assert timeline.overflow_frames == 11
    assert timeline.read(8).sum() == 2


def test_invalid_timeline_operations():
    with pytest.raises(ValueError):
        Timeline(0)
    timeline = Timeline(8)
    with pytest.raises(ValueError):
        timeline.read(9)
    with pytest.raises(ValueError):
        timeline.insert(2, 0, np.ones(2))


def test_pcm_is_finite_clipped_little_endian():
    data = np.array([-2, -1, 0, 1, 2, np.nan, np.inf, -np.inf])
    converted = np.frombuffer(pcm16(data), dtype="<i2")
    np.testing.assert_equal(converted, [-32767, -32767, 0, 32767, 32767, 0, 32767, -32767])


def test_stereo_and_downmix_handle_mono_and_multichannel():
    np.testing.assert_equal(stereo(np.array([1, 2])), [[1, 1], [2, 2]])
    np.testing.assert_equal(mono(np.array([[1, -1, 1, 1]])), [0])
    assert np.isfinite(stereo(np.array([np.nan]))).all()
    with pytest.raises(ValueError):
        stereo(np.empty((2, 0)))
