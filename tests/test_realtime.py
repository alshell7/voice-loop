import asyncio
import base64
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest

import voiceloop.realtime as realtime_module
from voiceloop.realtime import RealtimeConfig, RealtimeWorker, session_configuration, summarize_call


class FakeAudio:
    def __init__(self, *, drain=True):
        self.started = self.activated = self.closed = False
        self.drain_allowed = drain
        self.writes = []
        self.incoming = deque([b"\x00\x00" * 480])
        self.interruption = None

    def start(self, cancelled=None):
        self.started = True

    def activate(self):
        self.activated = True

    def read(self):
        return self.incoming.popleft() if self.activated and self.incoming else None

    def write(self, pcm, item_id):
        self.writes.append((pcm, item_id))

    def drained(self):
        return self.drain_allowed

    def interrupt(self):
        return self.interruption

    def close(self):
        self.closed = True

    def stats(self):
        return {"played_frames": sum(len(p[0]) // 2 for p in self.writes)}


class FakeConnection:
    def __init__(self, responses=None, *, initial=None):
        self.events = deque(initial or [])
        self.responses = deque(responses or [])
        self.requests = []
        self.uploads = []
        self.truncations = []
        self.items = []
        self.cancellations = 0
        self.closed = False
        self.session = SimpleNamespace(update=self.update)
        self.response = SimpleNamespace(create=self.create, cancel=self.cancel)
        self.input_audio_buffer = SimpleNamespace(append=self.append)
        self.conversation = SimpleNamespace(
            item=SimpleNamespace(truncate=self.truncate, create=self.create_item)
        )

    async def update(self, **kwargs):
        self.configuration = kwargs["session"]
        self.events.append({"type": "session.updated"})

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.responses:
            events = self.responses.popleft()
            for event in events:
                if event["type"] == "response.done":
                    event["response"]["metadata"] = kwargs.get("response", {}).get("metadata")
            self.events.extend(events)

    async def cancel(self):
        self.cancellations += 1

    async def append(self, **kwargs):
        self.uploads.append(kwargs)

    async def truncate(self, **kwargs):
        self.truncations.append(kwargs)

    async def create_item(self, **kwargs):
        self.items.append(kwargs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        while not self.events:
            await asyncio.sleep(0.005)
        return self.events.popleft()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True


class FakeClient:
    def __init__(self, connection):
        self.connection = connection
        self.realtime = SimpleNamespace(connect=self.connect)
        self.closed = False

    def connect(self, **kwargs):
        self.options = kwargs
        return self.connection

    async def close(self):
        self.closed = True


def await_condition(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Condition did not become true")
        time.sleep(0.01)


def worker_for(connection=None, audio=None, **config):
    connection = connection or FakeConnection()
    audio = audio or FakeAudio()
    client = FakeClient(connection)
    worker = RealtimeWorker(
        "test-secret",
        RealtimeConfig(objective="Ask whether the test is audible.", **config),
        audio,
        client_factory=lambda **_: client,
    )
    worker.start()
    await_condition(lambda: any(e["type"] == "ready" for e in worker.drain_events()))
    return worker, connection, audio, client


def audio_event(item="assistant-1"):
    return {
        "type": "response.output_audio.delta",
        "item_id": item,
        "delta": base64.b64encode(b"\x01\x00" * 1000).decode(),
    }


def done(*, finish=False):
    return {
        "type": "response.done",
        "response": {
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 12},
            "output": (
                [{"type": "function_call", "name": "finish_call", "call_id": "finish-1"}]
                if finish
                else []
            ),
        },
    }


def transcript(text, *, role="assistant", item="assistant-1"):
    kind = (
        "response.output_audio_transcript.done"
        if role == "assistant"
        else "conversation.item.input_audio_transcription.completed"
    )
    return {"type": kind, "item_id": item, "transcript": text}


def test_preparation_never_uploads_or_speaks_before_activation():
    worker, connection, audio, client = worker_for()
    try:
        assert audio.started and not audio.activated
        assert not connection.requests and not connection.uploads
        assert connection.configuration["audio"]["input"]["format"]["rate"] == 24000
        assert client.options["max_retries"] == 0
    finally:
        worker.stop()
        assert worker.join(2)
    assert worker.result["reason"] == "cancelled"
    assert audio.closed and client.closed and connection.closed


def test_opening_response_keeps_effective_objective_owner_instructions_and_call_rules():
    worker, connection, _, _ = worker_for(instructions="Use short sentences.", language="Marathi")
    try:
        worker.activate()
        await_condition(lambda: bool(connection.requests))
        # Realtime response instructions replace session instructions, rather
        # than appending to them. Inspect what the actual opening request uses.
        effective = (
            connection.requests[0]
            .get("response", {})
            .get("instructions", connection.configuration["instructions"])
        )
        assert worker.config.objective in effective
        assert worker.config.instructions in effective
        assert "identify yourself as an AI assistant" in effective
        assert "If the person declines, is busy, or asks to stop" in effective
        assert "Never impersonate the account owner" in effective
        assert "use finish_call promptly" in effective
        assert (
            "Speak in Marathi for the entire call, including the opening and goodbye" in effective
        )
    finally:
        worker.stop()
        assert worker.join(2)


def test_finish_waits_for_actual_playback_drain():
    connection = FakeConnection(
        [[done(finish=True)], [audio_event(), transcript("Thanks for testing. Goodbye."), done()]]
    )
    worker, connection, audio, _ = worker_for(connection, FakeAudio(drain=False))
    worker.activate()
    await_condition(lambda: bool(connection.items))
    await_condition(lambda: bool(audio.writes))
    assert worker.is_running and worker.result is None
    assert audio.writes
    audio.drain_allowed = True
    assert worker.join(2)
    assert worker.result["reason"] == "completed"
    assert worker.result["audio"]["played_frames"] == 1000
    assert worker.result["audio"]["uploaded_frames"] == 480
    assert worker.result["remote_receipt_verified"] is False
    assert worker.result["transcript"][0]["text"] == "Thanks for testing. Goodbye."


def test_finish_without_spoken_goodbye_requests_one_before_closing():
    connection = FakeConnection(
        [[done(finish=True)], [audio_event(), transcript("Thank you. Goodbye."), done()]]
    )
    worker, connection, audio, _ = worker_for(connection)
    worker.activate()
    assert worker.join(2)
    assert len(connection.requests) == 2
    assert connection.requests[-1]["response"]["tool_choice"] == "none"
    assert worker.result["reason"] == "completed" and audio.writes


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("Portuguese", "in Portuguese"),
        ("auto", "in the language already used in this conversation"),
    ],
)
def test_fallback_goodbye_preserves_the_configured_language(language, expected):
    connection = FakeConnection(
        [[done(finish=True)], [audio_event(), transcript("Obrigado. Adeus."), done()]]
    )
    worker, connection, _, _ = worker_for(connection, language=language)
    worker.activate()
    assert worker.join(2)
    assert expected in connection.requests[-1]["response"]["instructions"]
    assert worker.result["language"] == language
    assert worker.result["reason"] == "completed"


def test_automatic_language_uses_objective_then_recipient_without_saying_auto():
    instructions = session_configuration(RealtimeConfig("Test", language="AUTO"))["instructions"]
    assert "Adapt the spoken language to the recipient" in instructions
    assert "Until they speak, use the language of the owner's objective" in instructions
    assert "Speak in AUTO" not in instructions


def test_hard_time_limit_closes_silent_or_stalled_response():
    worker, _, audio, _ = worker_for(max_duration_seconds=0.08)
    worker.activate()
    assert worker.join(2)
    assert worker.result["reason"] == "time_limit" and audio.closed


def test_stop_during_connect_cancels_promptly():
    class SlowConnect(FakeConnection):
        async def __aenter__(self):
            await asyncio.sleep(90)

    audio = FakeAudio()
    client = FakeClient(SlowConnect())
    worker = RealtimeWorker(
        "test-secret", RealtimeConfig("Test"), audio, client_factory=lambda **_: client
    )
    worker.start()
    await_condition(lambda: audio.started)
    worker.stop()
    assert worker.join(2)
    assert worker.result["reason"] == "cancelled" and client.closed and audio.closed


def test_server_error_is_fatal_and_secret_is_redacted():
    connection = FakeConnection(
        [[{"type": "error", "error": {"message": "Invalid key test-secret sk-project-hidden"}}]]
    )
    worker, _, audio, _ = worker_for(connection)
    worker.activate()
    assert worker.join(2)
    assert worker.result["reason"] == "error"
    assert "test-secret" not in worker.result["error"]
    assert "sk-project-hidden" not in worker.result["error"]
    assert audio.closed


def test_interruption_truncates_at_played_offset_and_marks_transcript():
    connection = FakeConnection(
        [
            [
                audio_event(),
                {"type": "input_audio_buffer.speech_started"},
                audio_event(),
                transcript("Long reply"),
            ]
        ]
    )
    audio = FakeAudio()
    audio.interruption = {"item_id": "assistant-1", "audio_end_ms": 42}
    worker, connection, _, _ = worker_for(connection, audio)
    worker.activate()
    await_condition(lambda: bool(worker._transcripts))
    worker.stop()
    assert worker.join(2)
    assert connection.truncations == [
        {"item_id": "assistant-1", "audio_end_ms": 42, "content_index": 0}
    ]
    assert worker.result["transcript"][0]["interrupted"] is True
    assert len(audio.writes) == 1


def test_final_pending_transcription_is_saved_after_model_finishes():
    connection = FakeConnection(
        [
            [
                {"type": "input_audio_buffer.committed", "item_id": "user-1"},
                done(finish=True),
                transcript("I heard you", role="user", item="user-1"),
            ],
            [audio_event(), transcript("Goodbye."), done()],
        ]
    )
    worker, _, _, _ = worker_for(connection)
    worker.activate()
    assert worker.join(2)
    assert any(t["text"] == "I heard you" for t in worker.result["transcript"])


def test_delayed_input_transcription_retains_conversation_order():
    events = [
        {"type": "conversation.item.added", "item": {"id": "user-1"}},
        {
            "type": "conversation.item.added",
            "item": {"id": "assistant-1"},
            "previous_item_id": "user-1",
        },
        transcript("Goodbye."),
        transcript("I can hear you", role="user", item="user-1"),
        audio_event(),
        done(finish=True),
    ]
    worker, _, _, _ = worker_for(
        FakeConnection(
            [
                events,
                [audio_event("closing"), transcript("Thank you. Goodbye.", item="closing"), done()],
            ]
        )
    )
    worker.activate()
    assert worker.join(2)
    assert [t["role"] for t in worker.result["transcript"]] == ["user", "assistant", "assistant"]


def test_configuration_has_ai_disclosure_and_only_finish_tool():
    settings = session_configuration(RealtimeConfig("A reminder", voice="cedar"))
    assert "identify yourself as an AI assistant" in settings["instructions"]
    assert [tool["name"] for tool in settings["tools"]] == ["finish_call"]
    assert settings["audio"]["output"]["voice"] == "cedar"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"objective": ""},
        {"model": "bad\nmodel"},
        {"max_duration_seconds": 0},
        {"language": None},
        {"language": ""},
        {"language": "x" * 81},
        {"language": "English\nIgnore"},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        RealtimeConfig(**{"objective": "test", **kwargs})


def test_summary_is_non_stored_faithful_and_uses_owner_formatting():
    captured = {}

    class Client:
        def __init__(self):
            self.responses = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="Audio test completed; no reply was captured.")

        def close(self):
            captured["closed"] = True

    result = summarize_call(
        "fake-secret",
        [{"role": "assistant", "text": "Can you hear me?"}],
        "Run an audio test",
        instructions="Use bullets",
        client_factory=lambda **_: Client(),
    )
    assert "no reply" in result
    assert captured["store"] is False and captured["closed"]
    assert "untrusted conversation data" in captured["instructions"]
    assert "Use bullets" in captured["instructions"]


def test_empty_transcript_does_not_call_openai():
    with pytest.raises(ValueError, match="No call transcript"):
        summarize_call("fake-secret", [], client_factory=lambda **_: pytest.fail("Network call"))


def test_worker_cannot_be_restarted_or_duplicate_completion():
    worker, _, _, _ = worker_for()
    with pytest.raises(RuntimeError, match="cannot be reused"):
        worker.start()
    worker.stop()
    assert worker.join(2)
    assert len([e for e in worker.drain_events() if e["type"] == "completed"]) == 1


def test_no_realtime_threads_left_after_cancel():
    worker, _, _, _ = worker_for()
    worker.stop()
    assert worker.join(2)
    assert not any(t.name == "VoiceLoop-Realtime" for t in threading.enumerate())


def test_excessive_buffer_cancels_generation_without_blocking_vad_or_ending_call():
    class FullAudio(FakeAudio):
        def write(self, pcm, item_id):
            if len(self.writes) == 1 and item_id == "assistant-1":
                return False
            return super().write(pcm, item_id)

    audio = FullAudio(drain=False)
    audio.interruption = {"item_id": "assistant-1", "audio_end_ms": 20}
    connection = FakeConnection(
        [
            [
                audio_event(),
                audio_event(),
                audio_event(),  # Already in flight when cancellation is sent.
                {"type": "input_audio_buffer.speech_started"},
                transcript("A long generated turn"),
                done(finish=True),  # A capped response cannot finish the call.
                audio_event("assistant-2"),
                transcript("I heard you.", item="assistant-2"),
            ]
        ]
    )
    worker, _, _, _ = worker_for(connection, audio)
    try:
        worker.activate()
        await_condition(lambda: "assistant-2" in worker._transcripts)
        assert worker.is_running and worker.result is None
        assert connection.cancellations == 1
        assert len(connection.truncations) == 2
        assert connection.truncations[-1]["audio_end_ms"] == 20
        assert [item for _, item in audio.writes] == ["assistant-1", "assistant-2"]
        assert worker._transcripts["assistant-1"]["interrupted"] is True
        assert len(connection.requests) == 1
        assert not connection.items
        assert worker._warnings
    finally:
        worker.stop()
        assert worker.join(2)
    assert worker.result["reason"] == "cancelled"


def test_late_interjection_cannot_restart_conversation_after_accepted_finish_call():
    connection = FakeConnection(
        [[done(finish=True)], [audio_event(), transcript("Thank you. Goodbye."), done()]]
    )
    audio = FakeAudio(drain=False)
    audio.interruption = {"item_id": "assistant-1", "audio_end_ms": 20}
    worker, _, _, _ = worker_for(connection, audio)
    try:
        worker.activate()
        await_condition(lambda: bool(audio.writes))
        uploaded = len(connection.uploads)
        audio.incoming.append(b"\x01\x00" * 480)
        await_condition(lambda: len(connection.uploads) > uploaded)
        connection.events.extend(
            [
                {"type": "input_audio_buffer.speech_started", "item_id": "user-1"},
                audio_event("new-automatic-response"),
                transcript("Tomorrow. Thank you, goodbye.", item="new-automatic-response"),
                done(finish=True),
                transcript("Wait, which day?", role="user", item="user-1"),
            ]
        )
        await_condition(lambda: bool(connection.truncations))
        audio.drain_allowed = True
        assert worker.join(2)
        assert worker.result["reason"] == "completed"
        assert len(audio.writes) == 1
        assert len(connection.requests) == 2
        assert len(connection.items) == 1
        assert any(t["text"] == "Wait, which day?" for t in worker.result["transcript"])
        assert worker.result["transcript"][0]["interrupted"] is True
    finally:
        worker.stop()
        assert worker.join(2)


def test_normal_replies_preserve_completed_questions_in_server_context():
    events = [
        audio_event(),
        transcript("I am an AI assistant. Is tomorrow convenient?"),
        done(),
        {"type": "input_audio_buffer.speech_started"},
        transcript("Yes, tomorrow is fine.", role="user", item="user-1"),
        audio_event("assistant-2"),
        transcript("Great. Is 10 AM suitable?", item="assistant-2"),
        done(),
        {"type": "input_audio_buffer.speech_started"},
        transcript("Yes, 10 AM.", role="user", item="user-2"),
        done(finish=True),
    ]
    audio = FakeAudio()
    audio.interruption = []  # All generated frames were actually played.
    worker, connection, _, _ = worker_for(
        FakeConnection(
            [
                events,
                [
                    audio_event("assistant-3"),
                    transcript("Thank you. Goodbye.", item="assistant-3"),
                    done(),
                ],
            ]
        ),
        audio,
    )
    worker.activate()
    assert worker.join(2)
    assert worker.result["reason"] == "completed"
    assert not connection.truncations
    assert all(not turn["interrupted"] for turn in worker.result["transcript"])
    assert len(connection.requests) == 2  # Opening and one controlled goodbye.
    assert [turn["role"] for turn in worker.result["transcript"]] == [
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_interruption_truncates_each_unfinished_item_at_its_own_offset():
    audio = FakeAudio()
    audio.interruption = [
        {"item_id": "partly-heard", "audio_end_ms": 120},
        {"item_id": "not-yet-heard", "audio_end_ms": 0},
    ]
    worker = RealtimeWorker("test-secret", RealtimeConfig("Test"), audio)
    connection = FakeConnection()
    worker._transcript("completed", "assistant", "The already answered question.")
    worker._transcript("partly-heard", "assistant", "An interrupted sentence.")
    asyncio.run(worker._interrupt_audio(connection))
    worker._transcript("not-yet-heard", "assistant", "This was queued but never heard.")
    assert connection.truncations == [
        {"item_id": "partly-heard", "audio_end_ms": 120, "content_index": 0},
        {"item_id": "not-yet-heard", "audio_end_ms": 0, "content_index": 0},
    ]
    assert worker._transcripts["completed"]["interrupted"] is False
    assert worker._transcripts["partly-heard"]["interrupted"] is True
    assert worker._transcripts["not-yet-heard"]["interrupted"] is True


def test_slow_audio_upload_does_not_delay_vad_or_response_events():
    class SlowUpload(FakeConnection):
        def __init__(self):
            super().__init__()
            self.upload_started = threading.Event()
            self.release_upload = threading.Event()

        async def append(self, **kwargs):
            self.upload_started.set()
            while not self.release_upload.is_set():
                await asyncio.sleep(0.005)
            await super().append(**kwargs)

    connection = SlowUpload()
    audio = FakeAudio(drain=False)
    audio.interruption = [{"item_id": "assistant-1", "audio_end_ms": 10}]
    worker, _, _, _ = worker_for(connection, audio)
    try:
        worker.activate()
        assert connection.upload_started.wait(1)
        connection.events.extend(
            [
                audio_event(),
                {"type": "input_audio_buffer.speech_started", "item_id": "user-1"},
                transcript("A reply arrived while upload was busy.", role="user", item="user-1"),
            ]
        )
        await_condition(lambda: bool(connection.truncations))
        await_condition(lambda: "user-1" in worker._transcripts)
        assert not connection.uploads  # The blocked send never completed.
    finally:
        worker.stop()
        assert worker.join(2)  # Cancellation also cancels the independent sender.
    assert worker.result["reason"] == "cancelled"
    assert any(
        e["type"] == "input_audio_buffer.speech_started"
        for e in worker.result["diagnostics"]["events"]
    )
    assert "A reply arrived" not in str(worker.result["diagnostics"])


def test_capture_backlog_uploads_in_bounded_batches_without_reordering_or_loss():
    audio = FakeAudio()
    audio.activated = True
    chunks = [bytes([index, 0]) * 480 for index in range(20)]
    audio.incoming = deque(chunks)
    worker = RealtimeWorker("test-secret", RealtimeConfig("Test"), audio)

    class SlowConnection(FakeConnection):
        async def append(self, **kwargs):
            await asyncio.sleep(0.04)  # Slower than one native 20-ms packet.
            await super().append(**kwargs)
            if len(self.uploads) == 4:
                worker.stop()

    connection = SlowConnection()

    async def run():
        await asyncio.wait_for(worker._upload_audio(connection), timeout=1)

    asyncio.run(run())
    batches = [base64.b64decode(upload["audio"]) for upload in connection.uploads]
    assert b"".join(batches) == b"".join(chunks)
    assert all(len(batch) // 2 <= 2400 for batch in batches)
    assert worker._uploaded == 9600
    assert worker._upload_batches == 4
    assert worker._upload_max_batch == 2400


def test_independent_uploader_failure_stops_worker_and_closes_resources():
    class BrokenUpload(FakeConnection):
        async def append(self, **kwargs):
            raise RuntimeError("Synthetic upload failed")

    worker, connection, audio, client = worker_for(BrokenUpload())
    worker.activate()
    assert worker.join(2)
    assert worker.result["reason"] == "error"
    assert worker.result["error"] == "Synthetic upload failed"
    assert audio.closed and connection.closed and client.closed


def test_prompt_introduces_once_per_call_and_resumes_after_barge_in():
    instructions = session_configuration(RealtimeConfig("Test"))["instructions"]
    assert "At the beginning of this call" in instructions
    assert "identify yourself as an AI assistant once" in instructions
    assert "Do not introduce yourself again unless asked" in instructions
    assert "continue with the next unanswered part" in instructions
    assert "repeat questions that have already been answered" in instructions


def test_diagnostics_replace_provider_identifiers_with_stable_local_ordinals():
    worker = RealtimeWorker("private-test-key", RealtimeConfig("Private objective"), FakeAudio())
    worker._trace("input_audio_buffer.speech_started", item_id="private-provider-item-A")
    worker._trace("input_audio_buffer.committed", item_id="private-provider-item-A")
    worker._trace("response.created", response_id="private-provider-response-A")
    worker._trace("conversation.item.truncate", item_id="private-provider-item-B", audio_end_ms=20)
    worker._trace("response.done", response_id="private-provider-response-A", status="completed")
    assert [event.get("item_id") for event in worker._diagnostics] == [
        "item1",
        "item1",
        None,
        "item2",
        None,
    ]
    assert (
        worker._diagnostics[2]["response_id"]
        == worker._diagnostics[4]["response_id"]
        == "response1"
    )
    assert "private" not in str(worker._diagnostics).casefold()
    for _ in range(300):
        worker._trace("response.created", response_id="private-provider-response-B")
    assert len(worker._diagnostics) == 200


def test_prompt_commits_finish_before_the_application_speaks_one_goodbye():
    config = session_configuration(RealtimeConfig("Test"))
    assert "use finish_call promptly" in config["instructions"]
    assert "application will speak one short thank-you and goodbye" in config["instructions"]
    assert "Do not announce or repeat a goodbye yourself" in config["instructions"]
    assert "Commit to ending this call" in config["tools"][0]["description"]


def test_finish_is_terminal_during_vad_and_cancelled_response_flood(monkeypatch):
    monkeypatch.setattr(realtime_module, "CLOSING_SECONDS", 0.2)
    monkeypatch.setattr(realtime_module, "FINAL_TRANSCRIPT_SECONDS", 0.08)
    events = [audio_event(), {"type": "input_audio_buffer.speech_started", "item_id": "late-user"}]
    for number in range(40):
        cancelled = done(finish=True)
        cancelled["response"]["status"] = "cancelled"
        events.extend(
            [
                {"type": "response.created", "response": {"id": f"provider-response-{number}"}},
                audio_event(f"unheard-{number}"),
                {"type": "input_audio_buffer.speech_started", "item_id": f"noise-{number}"},
                cancelled,
            ]
        )
    connection = FakeConnection([[done(finish=True)], events])
    audio = FakeAudio(drain=False)
    audio.interruption = [{"item_id": "assistant-1", "audio_end_ms": 10}]
    worker, _, _, _ = worker_for(connection, audio)
    started = time.monotonic()
    worker.activate()
    assert worker.join(1)
    assert time.monotonic() - started < 1
    assert worker.result["reason"] == "completed"
    assert len(connection.requests) == 2
    assert len(connection.items) == 1
    assert len(audio.writes) == 1
    diagnostics = worker.result["diagnostics"]["events"]
    assert sum(bool(event.get("finish_accepted")) for event in diagnostics) == 1
    assert any(event.get("wants_finish") for event in diagnostics)
    assert "provider-response" not in str(diagnostics)


def test_cancelled_scripted_goodbye_finishes_without_waiting_for_call_time_limit():
    cancelled = done()
    cancelled["response"]["status"] = "cancelled"
    connection = FakeConnection([[done(finish=True)], [audio_event(), cancelled]])
    worker, _, _, _ = worker_for(connection, max_duration_seconds=85)
    worker.activate()
    assert worker.join(1)
    assert worker.result["reason"] == "completed"
    assert len(connection.requests) == 2


def test_closing_deadline_also_cancels_a_stalled_goodbye_request(monkeypatch):
    monkeypatch.setattr(realtime_module, "CLOSING_SECONDS", 0.08)

    class StalledGoodbye(FakeConnection):
        async def create(self, **kwargs):
            if kwargs.get("response", {}).get("metadata", {}).get("voiceloop_goodbye") == "true":
                self.requests.append(kwargs)
                await asyncio.sleep(90)
            else:
                await super().create(**kwargs)

    connection = StalledGoodbye([[done(finish=True)]])
    worker, _, audio, client = worker_for(connection, max_duration_seconds=85)
    worker.activate()
    assert worker.join(1)
    assert worker.result["reason"] == "completed"
    assert len(connection.requests) == 2
    assert audio.closed and connection.closed and client.closed
