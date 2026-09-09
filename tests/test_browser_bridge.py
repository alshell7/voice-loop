import http.client
import json
import os
import socket
import time
from datetime import UTC, datetime

import pytest

from voiceloop.browser_bridge import MAX_BODY, BrowserBridge, pairing_token

ORIGIN = "chrome-extension://" + "a" * 32


@pytest.fixture
def bridge(tmp_path):
    instance = BrowserBridge(tmp_path / "browser-token", port=0)
    instance.start()
    yield instance
    instance.stop()


def payload():
    return {
        "version": 1,
        "event_id": "event-1",
        "call_id": "call-1",
        "provider": "google_meet",
        "state": "connected",
        "direction": "unknown",
        "contact": {},
        "title": "Team review",
        "url": "https://meet.google.com/abc-defg-hij",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def request(bridge, method="GET", path="/v1/health", body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=4)
    defaults = {"Authorization": "Bearer " + bridge.pairing_token, "Origin": ORIGIN}
    defaults.update(headers or {})
    try:
        connection.request(method, path, body=body, headers=defaults)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def post(bridge, value=None, headers=None):
    return request(
        bridge,
        "POST",
        "/v1/events",
        json.dumps(payload() if value is None else value),
        {"Content-Type": "application/json", **(headers or {})},
    )


def test_pairing_secret_is_stable_private_and_separate(tmp_path):
    path = tmp_path / "private" / "browser-pairing-token"
    token = pairing_token(path)
    assert len(token) == 43
    assert pairing_token(path) == token
    assert token not in str(path)
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    path.write_text("invalid", encoding="ascii")
    with pytest.raises(ValueError):
        pairing_token(path)


def test_authenticated_health_and_validated_event_queue(bridge):
    status, headers, data = request(bridge)
    assert status == 200
    assert json.loads(data) == {"ok": True, "version": 1, "application": "VoiceLoop"}
    assert headers["Cache-Control"] == "no-store"
    assert headers["Access-Control-Allow-Origin"] == ORIGIN
    assert post(bridge)[0] == 202
    events = bridge.drain()
    assert len(events) == 1
    assert events[0].title == "Team review"
    assert events[0].state == "connected"
    assert bridge.drain() == []


@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Basic secret"])
def test_authentication_is_required_even_from_extension(bridge, authorization):
    assert request(bridge, headers={"Authorization": authorization})[0] == 401
    assert post(bridge, headers={"Authorization": authorization})[0] == 401
    assert bridge.drain() == []


@pytest.mark.parametrize(
    "origin", ["https://cliq.zoho.com", "https://evil.test", "null", "chrome-extension://invalid"]
)
def test_webpage_origins_are_rejected_even_with_token(bridge, origin):
    assert request(bridge, headers={"Origin": origin})[0] == 403
    assert post(bridge, headers={"Origin": origin})[0] == 403
    assert bridge.drain() == []


def test_authenticated_service_worker_request_without_origin_is_supported(bridge):
    connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=2)
    try:
        connection.request(
            "GET", "/v1/health", headers={"Authorization": "Bearer " + bridge.pairing_token}
        )
        assert connection.getresponse().status == 200
    finally:
        connection.close()


def test_dns_rebinding_and_duplicate_host_are_rejected(bridge):
    assert request(bridge, headers={"Host": f"evil.test:{bridge.port}"})[0] == 403
    connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=2)
    try:
        connection.putrequest("GET", "/v1/health")
        connection.putheader("Host", f"127.0.0.1:{bridge.port}")
        connection.putheader("Authorization", "Bearer " + bridge.pairing_token)
        connection.endheaders()
        assert connection.getresponse().status == 403
    finally:
        connection.close()


def test_preflight_allows_extension_but_rejects_webpages_and_unneeded_headers(bridge):
    headers = {
        "Authorization": "",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization, content-type",
        "Access-Control-Request-Private-Network": "true",
    }
    status, response, _ = request(bridge, "OPTIONS", "/v1/events", headers=headers)
    assert status == 200
    assert response["Access-Control-Allow-Private-Network"] == "true"
    assert response["Access-Control-Allow-Origin"] == ORIGIN
    assert (
        request(bridge, "OPTIONS", "/v1/events", headers=headers | {"Origin": "https://evil.test"})[
            0
        ]
        == 403
    )
    assert (
        request(
            bridge,
            "OPTIONS",
            "/v1/events",
            headers=headers | {"Access-Control-Request-Headers": "x-unwanted"},
        )[0]
        == 403
    )


def test_body_limits_content_type_and_invalid_events_are_rejected(bridge):
    assert post(bridge, value={"version": 2})[0] == 400
    assert post(bridge, headers={"Content-Type": "text/plain"})[0] == 415
    assert (
        request(
            bridge,
            "POST",
            "/v1/events",
            "x" * (MAX_BODY + 1),
            {"Content-Type": "application/json"},
        )[0]
        == 413
    )
    assert (
        request(
            bridge,
            "POST",
            "/v1/events",
            "not json",
            {"Content-Type": "application/json"},
        )[0]
        == 400
    )
    assert post(bridge, value=payload() | {"timestamp": "2000-01-01T00:00:00Z"})[0] == 400
    assert bridge.drain() == []


def test_queue_is_bounded_and_returns_backpressure(bridge):
    for _ in range(128):
        assert post(bridge)[0] == 202
    assert post(bridge)[0] == 503
    assert len(bridge.drain(limit=500)) == 128
    assert post(bridge)[0] == 202


def test_server_binds_only_loopback_and_shuts_down_cleanly(bridge):
    assert bridge._server.server_address[0] == "127.0.0.1"
    bridge.start()
    port = bridge.port
    bridge.stop()
    bridge.stop()
    assert not bridge.is_running
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=1):
        pass
    bridge.start()
    assert request(bridge)[0] == 200


def test_a_stalled_request_does_not_block_other_clients(bridge):
    stalled = socket.create_connection(("127.0.0.1", bridge.port), timeout=2)
    try:
        stalled.sendall(b"POST /v1/events HTTP/1.1\r\n")
        started = time.monotonic()
        assert request(bridge)[0] == 200
        assert time.monotonic() - started < 1.5
    finally:
        stalled.close()


def test_request_from_stopped_server_cannot_enqueue_after_restart(bridge):
    body = json.dumps(payload()).encode()
    connection = socket.create_connection(("127.0.0.1", bridge.port), timeout=2)
    try:
        headers = (
            f"POST /v1/events HTTP/1.1\r\nHost: 127.0.0.1:{bridge.port}\r\n"
            f"Authorization: Bearer {bridge.pairing_token}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
        )
        connection.sendall(headers.encode() + body[:1])
        # Wait until this connection has been accepted before shutting down.
        deadline = time.monotonic() + 1
        while bridge._server._slots._value == 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert bridge._server._slots._value == 3
        bridge.stop()
        bridge.start()
        connection.sendall(body[1:])
        response = connection.recv(4096)
        assert b"503" in response.split(b"\r\n")[0]
        assert bridge.drain() == []
        assert post(bridge)[0] == 202
    finally:
        connection.close()


def test_tokens_and_contact_data_are_not_written_to_server_logs(bridge, capsys):
    assert post(bridge)[0] == 202
    assert post(bridge, headers={"Authorization": "Bearer sensitive-value"})[0] == 401
    output = capsys.readouterr()
    assert output.out == output.err == ""


def command_request(bridge, endpoint, value):
    status, _, body = request(
        bridge,
        "POST",
        "/v1/commands/" + endpoint,
        json.dumps(value),
        {"Content-Type": "application/json"},
    )
    return status, json.loads(body)


def poll(bridge, profile="profile-1"):
    return command_request(
        bridge,
        "poll",
        {"version": 1, "profile_id": profile, "capabilities": ["call-control-v1", "zoho_cliq"]},
    )


def queue_call(bridge, **kwargs):
    return bridge.submit_command(
        "call",
        profile_id="profile-1",
        chat_id="12345",
        chat_url="https://cliq.zoho.com/company/987/chats/12345",
        **kwargs,
    )


def test_commands_are_profile_bound_once_delivered_and_results_idempotent(bridge):
    assert poll(bridge)[0] == 200
    assert bridge.profiles()[0]["capabilities"] == ["call-control-v1", "zoho_cliq"]
    command_id = queue_call(bridge)
    assert poll(bridge, "profile-2")[1]["commands"] == []
    command = poll(bridge)[1]["commands"][0]
    assert command["command_id"] == command_id
    assert command["chat_id"] == "12345"
    assert poll(bridge)[1]["commands"] == []  # Never redial on lost response.
    result = {
        "version": 1,
        "profile_id": "profile-1",
        "command_id": command_id,
        "status": "succeeded",
        "call_id": "call-123",
        "detail": "Dialing confirmed.",
    }
    assert command_request(bridge, "result", result | {"profile_id": "profile-2"})[0] == 400
    assert command_request(bridge, "result", result)[0] == 200
    assert command_request(bridge, "result", result)[0] == 200
    results = bridge.drain_results()
    assert len(results) == 1
    assert results[0]["call_id"] == "call-123"
    assert results[0]["status"] == "succeeded"
    assert queue_call(bridge, command_id=command_id) == command_id
    assert poll(bridge)[1]["commands"] == []


def test_cancellation_prevents_undelivered_call_but_reports_leased_uncertainty(bridge):
    poll(bridge)
    first = queue_call(bridge)
    assert bridge.cancel_command(first) == "cancelled"
    assert poll(bridge)[1]["commands"] == []
    second = queue_call(bridge)
    poll(bridge)
    assert bridge.cancel_command(second) == "ambiguous"
    assert bridge.cancel_command("missing") == "unknown"
    bridge.stop()
    results = {value["command_id"]: value for value in bridge.drain_results()}
    assert results[first]["status"] == "failed"
    assert results[second]["status"] == "ambiguous"


def test_expired_lease_is_ambiguous_and_never_requeued(bridge, monkeypatch):
    poll(bridge)
    command = queue_call(bridge, ttl=1)
    poll(bridge)
    now = time.time()
    monkeypatch.setattr("voiceloop.browser_bridge.time.time", lambda: now + 2)
    assert bridge.drain_results()[0]["status"] == "ambiguous"
    assert poll(bridge)[1]["commands"] == []
    assert queue_call(bridge, command_id=command) == command


def test_commands_reject_unknown_profile_invalid_target_and_conflicting_id(bridge):
    with pytest.raises(ValueError, match="profile"):
        queue_call(bridge)
    poll(bridge)
    for target in [
        "https://cliq.zoho.com.evil.test/company/987/chats/12345",
        "https://user@cliq.zoho.com/company/987/chats/12345",
        "https://cliq.zoho.com/company/987/chats/22222",
        "https://cliq.zoho.com/company/987/chats/12345?secret=value",
    ]:
        with pytest.raises(ValueError):
            bridge.submit_command("call", profile_id="profile-1", chat_id="12345", chat_url=target)
    command = queue_call(bridge)
    with pytest.raises(ValueError, match="another action"):
        queue_call(bridge, command_id=command, text="different")
    with pytest.raises(ValueError, match="specific call"):
        bridge.submit_command("hangup", profile_id="profile-1")


def test_command_endpoint_auth_and_input_validation(bridge):
    assert (
        request(
            bridge,
            "POST",
            "/v1/commands/poll",
            "{}",
            {"Content-Type": "application/json", "Authorization": "Bearer invalid"},
        )[0]
        == 401
    )
    assert (
        command_request(
            bridge,
            "poll",
            {"version": 1, "profile_id": "profile-1", "capabilities": ["arbitrary-js"]},
        )[0]
        == 400
    )
    assert (
        command_request(
            bridge, "poll", {"version": 1, "profile_id": "profile-1", "label": "x\ninvalid"}
        )[0]
        == 400
    )


def test_optional_call_identity_is_validated_and_backward_compatible(bridge):
    event = payload() | {
        "provider": "zoho_cliq",
        "url": "https://cliq.zoho.com/",
        "profile_id": "profile-1",
        "command_id": "cmd-1",
        "chat_id": "12345",
        "chat_url": "https://cliq.zoho.com/company/987/chats/12345",
    }
    assert post(bridge, event)[0] == 202
    parsed = bridge.drain()[0]
    assert (parsed.chat_id, parsed.profile_id, parsed.command_id) == ("12345", "profile-1", "cmd-1")
    assert (
        post(bridge, event | {"chat_url": "https://cliq.zoho.eu/company/987/chats/12345"})[0] == 400
    )
    assert post(bridge, event | {"chat_id": "54321"})[0] == 400
    assert post(bridge, event | {"participant_id": "111222333"})[0] == 202
    assert bridge.drain()[0].participant_id == "111222333"
    assert post(bridge, event | {"participant_id": "caller@example.com"})[0] == 400


def test_diagnostic_terminal_id_prefixes_preserve_event_protocol(bridge):
    reasons = [
        "native-handoff",
        "native-replaced",
        "ui-ended",
        "ui-absent",
        "pagehide",
        "tab-closed",
        "tab-missing",
        "navigation",
        "unpaired",
    ]
    identifiers = [reason + "-11111111-2222-3333-4444-555555555555" for reason in reasons]
    for identifier in identifiers:
        assert post(bridge, payload() | {"event_id": identifier, "state": "ended"})[0] == 202
    assert [event.event_id for event in bridge.drain()] == identifiers
