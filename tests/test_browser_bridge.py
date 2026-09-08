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
