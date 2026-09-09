import http.client
import json
import os
import socket
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_assistant import service as service

from voiceloop.assistant_config import ChatTarget, RecipientResolutionError
from voiceloop.assistant_control import ControlServer
from voiceloop.browser_bridge import pairing_token


class Service:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.jobs = []
        self.clock = datetime(2026, 9, 9, 10, tzinfo=UTC)
        self.store = SimpleNamespace(
            get=lambda job_id: next(j for j in self.jobs if j["id"] == job_id)
        )
        self.config = SimpleNamespace(
            cliq_company_id="123456",
            cliq_origin="https://cliq.zoho.com",
            language="English",
            timezone="Asia/Kolkata",
            resolve_recipient=self.resolve_recipient,
            targets=[
                SimpleNamespace(
                    id="42", name="Test Contact", url="https://example.test", enabled=True
                )
            ],
        )

    def snapshot(self):
        return {"status": "idle", "jobs": self.jobs}

    def now(self):
        return self.clock

    def resolve_recipient(self, name):
        matches = {"alex": "42", "zoë ahmed": "43"}
        if name.casefold() not in matches:
            raise RecipientResolutionError("recipient_not_found")
        return SimpleNamespace(id=matches[name.casefold()])

    def trigger(self, chat_id, objective, *, contact_name=""):
        if self.failure:
            raise self.failure
        self.calls.append(
            ("call", chat_id, objective, contact_name)
            if contact_name
            else ("call", chat_id, objective)
        )
        return {"id": "job-1", "state": "queued"}

    def schedule(self, chat_id, objective, when, *, contact_name=""):
        call = ("schedule", chat_id, objective, when)
        self.calls.append((*call, contact_name) if contact_name else call)
        return {"id": "job-2", "state": "scheduled"}

    def cancel(self, job_id):
        self.calls.append(("cancel", job_id))


@pytest.fixture
def control(tmp_path):
    service = Service()
    server = ControlServer(service, port=0, token_path=tmp_path / "control-token")
    server.start()
    yield server
    server.stop()


def request(control, path="/v1/status", payload=None, *, headers=None, raw=None, method="POST"):
    connection = http.client.HTTPConnection("127.0.0.1", control.port, timeout=3)
    try:
        connection.request(
            method,
            path,
            body=json.dumps(payload or {}) if raw is None else raw,
            headers={
                "Authorization": "Bearer " + control.token,
                "Content-Type": "application/json",
                **(headers or {}),
            },
        )
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_control_loopback_status_and_operations(control):
    control.start()
    assert control.server.server_address[0] == "127.0.0.1"
    status, headers, body = request(control)
    assert status == 200
    assert json.loads(body)["targets"][0]["id"] == "42"
    assert json.loads(body)["cliq"] == {"company_id": "123456", "origin": "https://cliq.zoho.com"}
    assert json.loads(body)["language"] == "English"
    assert json.loads(body)["busy_fallback_enabled"] is False
    control.service.config.busy_fallback_enabled = True
    assert json.loads(request(control)[2])["busy_fallback_enabled"] is True
    assert json.loads(body)["current_time"] == control.service.clock.isoformat()
    assert json.loads(body)["timezone"] == "Asia/Kolkata"
    assert headers["Cache-Control"] == "no-store"
    assert not any(name.lower().startswith("access-control") for name in headers)
    assert request(control, "/v1/call", {"chat_id": "42", "objective": "Audio test"})[0] == 200
    assert (
        request(
            control,
            "/v1/schedule",
            {"chat_id": "42", "objective": "Reminder", "when": "2026-10-01T09:00:00+05:30"},
        )[0]
        == 200
    )
    assert request(control, "/v1/cancel", {"job_id": "job-1"})[0] == 200
    assert control.service.calls == [
        ("call", "42", "Audio test"),
        ("schedule", "42", "Reminder", datetime.fromisoformat("2026-10-01T09:00:00+05:30")),
        ("cancel", "job-1"),
    ]


@pytest.mark.parametrize("operation", ["call", "schedule"])
def test_new_chat_contact_name_is_forwarded_to_desktop_policy(control, operation):
    data = {
        "chat_id": "987654321",
        "objective": "Confirm the appointment",
        "contact_name": "  Zoë Ahmed  ",
    }
    if operation == "schedule":
        data["when"] = "2026-10-01T09:00:00+05:30"
    assert request(control, "/v1/" + operation, data)[0] == 200
    action = control.service.calls[0]
    assert action[:3] == (operation, data["chat_id"], data["objective"])
    assert action[-1] == "Zoë Ahmed"
    assert len(control.service.config.targets) == 1


def test_saved_recipient_and_relative_delay_use_the_desktop_clock(control):
    data = {"recipient": "  Alex  ", "objective": "Ask about the report", "delay_minutes": 180}
    assert request(control, "/v1/schedule", data)[0] == 200
    assert control.service.calls == [
        ("schedule", "42", data["objective"], control.service.clock + timedelta(hours=3))
    ]
    assert (
        request(control, "/v1/call", {"recipient": "Zoë Ahmed", "objective": "A reminder"})[0]
        == 200
    )
    assert control.service.calls[-1] == ("call", "43", "A reminder")


@pytest.mark.parametrize(
    "recipient", ["987654321", "https://cliq.zoho.com/company/123/chats/987654321"]
)
def test_saved_name_selector_cannot_create_unknown_id_or_url_contacts(control, recipient):
    status, _, body = request(
        control, "/v1/call", {"recipient": recipient, "objective": "A reminder"}
    )
    assert status == 400 and json.loads(body)["error_code"] == "recipient_not_found"
    assert not control.service.calls


def test_saved_name_and_delay_integrate_with_real_service_policy(service, tmp_path):
    server = ControlServer(service, port=0, token_path=tmp_path / "integration-token")
    server.start()
    try:
        status, _, body = request(
            server,
            "/v1/schedule",
            {
                "recipient": "aLeX",
                "objective": "Remind them about the report",
                "delay_minutes": 180,
            },
        )
        assert status == 200
        job = service.store.get(json.loads(body)["id"])
        assert job["target_id"] == "456" and job["target_name"] == "Alex"
        assert datetime.fromisoformat(job["scheduled_at"]) == service.now() + timedelta(hours=3)
        service.save_config(
            replace(
                service.config,
                targets=[
                    *service.config.targets,
                    ChatTarget.from_url(
                        "Alex Smith", "https://cliq.zoho.com/company/123/chats/789"
                    ),
                ],
            )
        )
        code, _, body = request(server, "/v1/call", {"recipient": "Al", "objective": "A reminder"})
        assert code == 400 and json.loads(body)["error_code"] == "recipient_ambiguous"
        assert len(service.store.list()) == 1
        assert not service.test_workers and not service.test_bridge.commands
    finally:
        server.stop()


def test_relative_delay_means_elapsed_time_across_daylight_saving_transition(control):
    from zoneinfo import ZoneInfo

    control.service.clock = datetime(2026, 11, 1, 0, 30, tzinfo=ZoneInfo("America/New_York"))
    assert (
        request(
            control,
            "/v1/schedule",
            {"recipient": "Alex", "objective": "A reminder", "delay_minutes": 180},
        )[0]
        == 200
    )
    result = control.service.calls[0][3]
    assert result == datetime(2026, 11, 1, 7, 30, tzinfo=UTC)
    assert result.astimezone(ZoneInfo("America/New_York")).hour == 2


@pytest.mark.parametrize(
    "selector",
    [
        {},
        {"recipient": "Alex", "chat_id": "42"},
        {"recipient": " "},
        {"recipient": 42},
        {"recipient": "x" * 121},
        {"recipient": "Alex\nOther"},
        {"recipient": "Alex\x7f"},
        {"recipient": "Alex", "contact_name": "Other"},
    ],
)
def test_invalid_or_conflicting_recipient_selector_has_no_side_effect(control, selector):
    assert request(control, "/v1/call", {"objective": "A reminder", **selector})[0] == 400
    assert not control.service.calls


@pytest.mark.parametrize(
    "timing",
    [
        {},
        {"delay_minutes": 0},
        {"delay_minutes": -1},
        {"delay_minutes": True},
        {"delay_minutes": 1.5},
        {"delay_minutes": "180"},
        {"delay_minutes": 527041},
        {"delay_minutes": 180, "when": "2026-10-01T09:00:00Z"},
        {"when": "2026-10-01T09:00:00"},
        {"when": None},
    ],
)
def test_invalid_relative_or_absolute_schedule_has_no_side_effect(control, timing):
    assert (
        request(
            control, "/v1/schedule", {"recipient": "Alex", "objective": "A reminder", **timing}
        )[0]
        == 400
    )
    assert not control.service.calls


@pytest.mark.parametrize("code", ["recipient_ambiguous", "recipient_not_found"])
def test_recipient_resolution_errors_are_actionable_without_private_exception_text(control, code):
    error = ValueError("private-token private-contact")
    error.code = code
    control.service.failure = error
    status, _, body = request(control, "/v1/call", {"recipient": "Alex", "objective": "A reminder"})
    assert status == 400
    result = json.loads(body)
    assert result["error_code"] == code and "voice_loop_status" in result["error"]
    assert b"private-" not in body


@pytest.mark.parametrize(
    "fields",
    [
        {"contact_name": 42},
        {"contact_name": "x" * 121},
        {"contact_name": "First\nSecond"},
        {"contact_name": "First\x00Second"},
        {"chat_id": "../42"},
        {"chat_id": 42},
        {"chat_id": "٤٢"},
        {"objective": {}},
        {"objective": " "},
    ],
)
def test_invalid_new_chat_request_never_reaches_desktop(control, fields):
    data = {"chat_id": "42", "objective": "Audio test", **fields}
    assert request(control, "/v1/call", data)[0] == 400
    assert not control.service.calls


def test_status_is_compact_and_job_transcripts_are_paginated(control):
    turns = [{"role": "user", "text": f"Spoken turn {index}"} for index in range(60)]
    control.service.jobs = [
        {"id": f"job-{index}", "state": "completed", "transcript": turns, "summary": "s" * 4000}
        for index in range(40)
    ]
    status = json.loads(request(control)[2])
    assert len(status["jobs"]) == 30
    assert all("transcript" not in job and job["transcript_count"] == 60 for job in status["jobs"])
    assert len(status["jobs"][0]["summary"]) == 2000
    assert status["jobs"][0]["summary_truncated"] is True
    first = json.loads(request(control, "/v1/job", {"job_id": "job-0"})[2])
    assert first["transcript"] == turns[:20]
    assert first["next_offset"] == 20
    last = json.loads(request(control, "/v1/job", {"job_id": "job-0", "offset": 50})[2])
    assert last["transcript"] == turns[50:]
    assert last["next_offset"] is None


@pytest.mark.parametrize(
    "data",
    [
        {"offset": 0},
        {"job_id": "job-0", "offset": -1},
        {"job_id": "job-0", "limit": 51},
        {"job_id": "job-0", "limit": True},
        {"job_id": 42},
    ],
)
def test_invalid_transcript_pages_are_rejected(control, data):
    assert request(control, "/v1/job", data)[0] == 400


def test_transcript_page_has_a_byte_limit_and_always_advances(control):
    turn = {"role": "assistant", "text": "語" * 32_000}
    control.service.jobs = [{"id": "job-0", "transcript": [turn] * 20}]
    code, _, raw = request(control, "/v1/job", {"job_id": "job-0", "limit": 50})
    result = json.loads(raw)
    assert code == 200 and len(raw) < 600_000
    assert 0 < result["next_offset"] < 20


def test_control_secret_is_separate_and_persists(tmp_path):
    server = ControlServer(Service(), token_path=tmp_path / "control-token", port=0)
    other = ControlServer(Service(), token_path=tmp_path / "control-token", port=0)
    assert server.token == other.token
    assert server.token != pairing_token(tmp_path / "browser-token")
    if os.name != "nt":
        assert (tmp_path / "control-token").stat().st_mode & 0o777 == 0o600


def test_live_control_listener_retains_exclusive_port_ownership(control, tmp_path):
    other = ControlServer(Service(), port=control.port, token_path=tmp_path / "other-token")
    try:
        with pytest.raises(OSError):
            other.start()
        assert request(control)[0] == 200
    finally:
        other.stop()


@pytest.mark.parametrize(
    "origin", ["https://cliq.zoho.com", "null", "", "chrome-extension://" + "a" * 32]
)
def test_all_browser_origins_are_rejected_even_with_valid_secret(control, origin):
    assert request(control, headers={"Origin": origin})[0] == 403
    assert control.service.calls == []


@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Basic secret"])
def test_control_secret_required(control, authorization):
    assert request(control, headers={"Authorization": authorization})[0] == 401


def test_browser_pairing_token_does_not_authorize_control(control, tmp_path):
    token = pairing_token(tmp_path / "browser-token")
    assert request(control, headers={"Authorization": "Bearer " + token})[0] == 401


@pytest.mark.parametrize("host", ["localhost", "evil.test", "127.0.0.1"])
def test_exact_host_and_port_required(control, host):
    assert request(control, headers={"Host": host})[0] == 403


@pytest.mark.parametrize("header", ["Host", "Authorization", "Content-Length"])
def test_duplicate_security_headers_are_rejected(control, header):
    connection = http.client.HTTPConnection("127.0.0.1", control.port, timeout=3)
    values = {
        "Host": f"127.0.0.1:{control.port}",
        "Authorization": "Bearer " + control.token,
        "Content-Length": "2",
    }
    try:
        connection.putrequest("POST", "/v1/status", skip_host=True)
        for name, value in values.items():
            connection.putheader(name, value)
        connection.putheader(header, values[header])
        connection.putheader("Content-Type", "application/json")
        connection.endheaders(b"{}")
        assert connection.getresponse().status in (400, 401, 403)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "raw",
    [b"x" * 16385, b"[]", b"not-json", b"\xff", b""],
    ids=["oversized", "array", "not-json", "non-utf8", "empty"],
)
def test_request_body_is_bounded_and_must_be_a_json_object(control, raw):
    assert request(control, raw=raw)[0] in (400, 413)


def test_transfer_encoding_and_non_json_content_type_rejected(control):
    assert request(control, headers={"Transfer-Encoding": "chunked"})[0] == 403
    assert request(control, headers={"Content-Type": "text/plain"})[0] == 415


def test_short_body_cannot_trigger_a_call(control):
    body = json.dumps({"chat_id": "42", "objective": "Audio test"}).encode()
    with socket.create_connection(("127.0.0.1", control.port), timeout=3) as connection:
        connection.sendall(
            (
                f"POST /v1/call HTTP/1.1\r\nHost: 127.0.0.1:{control.port}\r\n"
                f"Authorization: Bearer {control.token}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body) + 10}\r\n\r\n"
            ).encode()
            + body
        )
        connection.shutdown(socket.SHUT_WR)
        response = connection.recv(4096)
    assert b"400" in response.split(b"\r\n")[0]
    assert control.service.calls == []


def test_disabled_listener_cannot_execute_a_previously_partial_request(control):
    body = json.dumps({"chat_id": "42", "objective": "Audio test"}).encode()
    with socket.create_connection(("127.0.0.1", control.port), timeout=3) as connection:
        connection.sendall(
            (
                f"POST /v1/call HTTP/1.1\r\nHost: 127.0.0.1:{control.port}\r\n"
                f"Authorization: Bearer {control.token}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n"
            ).encode()
            + body[:1]
        )
        deadline = time.monotonic() + 1
        while control.server._slots._value == 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert control.server._slots._value == 3
        control.stop()
        control.start()
        connection.sendall(body[1:])
        response = connection.recv(4096)
    assert b"503" in response.split(b"\r\n")[0]
    assert control.service.calls == []
    assert request(control)[0] == 200


def test_invalid_operations_and_fields_have_no_side_effect(control):
    assert request(control, "/v1/anything")[0] == 404
    assert (
        request(control, "/v1/call", {"chat_id": "42", "objective": "Test", "url": "bad"})[0] == 400
    )
    assert request(control, "/v1/schedule", {"chat_id": "42"})[0] == 400
    assert request(control, "/v1/cancel", {})[0] == 400
    assert control.service.calls == []


@pytest.mark.parametrize("exception", [ValueError, TypeError, KeyError, OSError, RuntimeError])
def test_error_responses_and_logs_do_not_expose_sensitive_exception_text(
    control, capsys, exception
):
    control.service.failure = exception("private-token private-contact private-objective")
    status, _, body = request(control, "/v1/call", {"chat_id": "42", "objective": "Audio test"})
    assert status in (400, 503)
    assert b"private-" not in body
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_stalled_request_does_not_block_status_and_stop_closes_port(control):
    with socket.create_connection(("127.0.0.1", control.port), timeout=3) as connection:
        connection.sendall(b"POST /v1/status HTTP/1.1\r\n")
        assert request(control)[0] == 200
    port = control.port
    control.stop()
    control.stop()
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=1):
        pass
