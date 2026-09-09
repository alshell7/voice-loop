import queue
import sys
from types import SimpleNamespace

import numpy as np
import pytest

import voiceloop.assistant_audio as audio_module
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


@pytest.fixture
def buffered_audio(monkeypatch):
    """Exercise real staging and acknowledgments without native devices."""

    class LocalQueue(queue.Queue):
        def cancel_join_thread(self):
            pass

        def close(self):
            pass

    audio = CableAudio(
        Device("source", "VoiceLoop Speaker", 2, True), Device("feed", "VoiceLoop Mic Feed", 2)
    )
    for name, size in (("_incoming", 64), ("_outgoing", 8), ("_status", 512)):
        getattr(audio, name).close()
        setattr(audio, name, LocalQueue(maxsize=size))
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(audio_module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    yield audio, clock
    audio.close()


def acknowledge_packet(audio, clock):
    pcm, item, epoch, serial = audio._outgoing.get_nowait()
    if epoch == audio._generation.value:
        clock.now += len(pcm) / 2 / audio_module.REALTIME_RATE
        audio._status.put_nowait(("played", (serial, item, len(pcm) // 2, epoch)))
        played = pcm
    else:
        audio._status.put_nowait(("discarded", serial))
        played = b""
    audio._poll()
    return played


def test_fast_generation_burst_preserves_all_speech_with_short_device_queue(buffered_audio):
    audio, clock = buffered_audio
    # The actual regression: 11.52 seconds generated before playback catches up.
    pcm = np.arange(276_480, dtype=np.int16).tobytes()
    assert audio.write(pcm, "opening") is True
    assert audio._outgoing.qsize() == audio_module.PLAYBACK_QUEUE_PACKETS
    assert not audio.drained()
    played = []
    while audio.stats()["buffered_frames"]:
        assert audio._outgoing.qsize() <= audio_module.PLAYBACK_QUEUE_PACKETS
        played.append(acknowledge_packet(audio, clock))
    assert b"".join(played) == pcm
    assert not audio.drained()
    clock.now += 0.16
    assert audio.drained()
    stats = audio.stats()
    assert stats["generated_frames"] == stats["played_frames"] == 276_480
    assert stats["buffer_high_water_frames"] <= stats["buffer_limit_frames"]
    assert stats["playback_backpressure_count"] == 0


def test_full_staging_returns_atomic_backpressure_and_can_be_retried(buffered_audio, monkeypatch):
    audio, clock = buffered_audio
    monkeypatch.setattr(audio_module, "MAX_BUFFERED_FRAMES", 2400)
    first, second = b"\x01\x00" * 2000, b"\x02\x00" * 1000
    assert audio.write(first, "one")
    assert audio.write(second, "two") is False
    assert audio.stats()["generated_frames"] == 2000
    played = [acknowledge_packet(audio, clock), acknowledge_packet(audio, clock)]
    assert audio.write(second, "two")
    while audio.stats()["buffered_frames"]:
        played.append(acknowledge_packet(audio, clock))
    assert b"".join(played) == first + second
    assert audio.stats()["generated_frames"] == audio.stats()["played_frames"] == 3000
    assert audio.stats()["buffer_high_water_frames"] <= 2400


def test_interruption_discards_staging_and_stale_device_packets(buffered_audio):
    audio, clock = buffered_audio
    audio.write(b"\x01\x00" * 240_000, "old")
    assert len(acknowledge_packet(audio, clock)) == 960
    assert audio.interrupt() == [{"item_id": "old", "audio_end_ms": 20}]
    assert not audio._buffer
    audio.write(b"\x02\x00" * 1000, "new")
    after_interrupt = []
    while audio.stats()["buffered_frames"]:
        after_interrupt.append(acknowledge_packet(audio, clock))
    assert b"".join(after_interrupt) == b"\x02\x00" * 1000
    assert audio.stats()["discarded_frames"] == 240_000 - 480
    assert audio.stats()["played_frames"] == 1480


def test_only_missing_playback_progress_is_fatal(buffered_audio):
    audio, clock = buffered_audio
    audio.write(b"\x01\x00" * 24_000, "test")
    clock.now += audio_module.PLAYBACK_STALL_SECONDS + 0.1
    with pytest.raises(RuntimeError, match="stopped making playback progress"):
        audio.read()


def test_audio_chunk_larger_than_total_bound_is_rejected(buffered_audio, monkeypatch):
    audio, _ = buffered_audio
    monkeypatch.setattr(audio_module, "MAX_BUFFERED_FRAMES", 1000)
    with pytest.raises(RuntimeError, match="larger than the bounded"):
        audio.write(b"\x01\x00" * 1001, "test")
    assert audio.stats()["buffered_frames"] == 0


def test_normal_reply_never_truncates_a_fully_played_question(buffered_audio):
    audio, clock = buffered_audio
    for item in ("greeting-and-question", "second-question", "closing"):
        audio.write(b"\x01\x00" * 1000, item)
        while audio.stats()["buffered_frames"]:
            acknowledge_packet(audio, clock)
        clock.now += 0.16
        assert audio.drained()
        assert audio.interrupt() == []
    assert audio.stats()["played_frames"] == 3000
    assert audio.stats()["discarded_frames"] == 0


def test_interruption_covers_current_and_queued_items_but_keeps_completed_history(buffered_audio):
    audio, clock = buffered_audio
    audio.write(b"\x01\x00" * 480, "heard-question")
    acknowledge_packet(audio, clock)
    audio.write(b"\x02\x00" * 2400, "currently-speaking")
    acknowledge_packet(audio, clock)
    audio.write(b"\x03\x00" * 960, "queued-followup")
    assert audio.interrupt() == [
        {"item_id": "currently-speaking", "audio_end_ms": 20},
        {"item_id": "queued-followup", "audio_end_ms": 0},
    ]
    # Repeated speech-start notifications and late discard acknowledgments
    # must not truncate those turns again or touch the completed question.
    assert audio.interrupt() == []
    while audio.stats()["buffered_frames"]:
        acknowledge_packet(audio, clock)
    assert audio.interrupt() == []
    assert audio.stats()["played_frames"] == 960


def test_late_playback_ack_cannot_change_new_epoch_unplayed_accounting(buffered_audio):
    audio, clock = buffered_audio
    audio.write(b"\x01\x00" * 480, "old-turn")
    packet = audio._outgoing.get_nowait()  # A native write already in progress.
    assert audio.interrupt() == [{"item_id": "old-turn", "audio_end_ms": 0}]
    audio.write(b"\x02\x00" * 960, "new-turn")
    _pcm, item, epoch, serial = packet
    audio._status.put_nowait(("played", (serial, item, 480, epoch)))
    audio._poll()
    assert audio.interrupt() == [{"item_id": "new-turn", "audio_end_ms": 0}]
    assert audio.stats()["played_frames"] == 480


def test_final_pending_playback_ack_is_processed_before_deciding_to_truncate(buffered_audio):
    audio, _ = buffered_audio
    audio.write(b"\x01\x00" * 480, "heard-question")
    _pcm, item, epoch, serial = audio._outgoing.get_nowait()
    audio._status.put_nowait(("played", (serial, item, 480, epoch)))
    assert audio.interrupt() == []


def test_native_playback_pacing_does_not_stretch_packets_with_coarse_event_timer(monkeypatch):
    clock = SimpleNamespace(now=100.0, stopped=False)
    channel = queue.Queue()
    channel.put((b"\x01\x00" * 480, "tone", 0, 1))

    class Status(queue.Queue):
        def put(self, event):
            super().put(event)
            if event[0] == "played":
                clock.stopped = True

    class Stop:
        def is_set(self):
            return clock.stopped

        def wait(self, duration):
            # Windows kernel event timeouts round a 20-ms wait to ~31 ms.
            clock.now += max(duration, 0.031)

        def set(self):
            clock.stopped = True

    class Player:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def play(self, data):
            assert len(data) == 960

    def sleep(duration):
        clock.now += duration

    device = SimpleNamespace(id="virtual", channels=2, player=lambda **_: Player())
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_speakers=lambda: [device]))
    monkeypatch.setattr(
        audio_module, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep)
    )
    status = Status()
    audio_module._playback("virtual", channel, status, Stop(), SimpleNamespace(value=0))
    assert clock.now - 100 == pytest.approx(0.02)
    assert status.get()[0] == "ready"
    assert status.get() == ("played", (1, "tone", 480, 0))
