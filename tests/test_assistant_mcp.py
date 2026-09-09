import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from voiceloop import assistant_mcp

TOOLS = {
    "voice_loop_status",
    "voice_loop_job",
    "voice_loop_call",
    "voice_loop_schedule",
    "voice_loop_cancel",
}


def test_real_mcp_handshake_lists_schemas_and_routes_calls():
    calls = []

    def client(operation, payload=None):
        calls.append((operation, payload))
        return {"ok": True, "state": "queued" if operation == "call" else "ready"}

    async def exercise():
        async with create_connected_server_and_client_session(
            assistant_mcp.create_server(client)
        ) as session:
            listing = await session.list_tools()
            tools = {tool.name: tool for tool in listing.tools}
            assert set(tools) == TOOLS
            assert tools["voice_loop_status"].annotations.readOnlyHint is True
            assert tools["voice_loop_job"].annotations.readOnlyHint is True
            assert tools["voice_loop_call"].annotations.idempotentHint is False
            assert tools["voice_loop_call"].annotations.openWorldHint is True
            assert set(tools["voice_loop_call"].inputSchema["required"]) == {"chat_id", "objective"}
            await session.call_tool("voice_loop_status", {})
            await session.call_tool("voice_loop_job", {"job_id": "job-1"})
            result = await session.call_tool(
                "voice_loop_call", {"chat_id": "42", "objective": "Audio test"}
            )
            assert result.isError is False
            assert json.loads(result.content[0].text)["state"] == "queued"
            await session.call_tool(
                "voice_loop_schedule",
                {"chat_id": "42", "objective": "Reminder", "when": "2026-10-01T09:00:00+05:30"},
            )
            await session.call_tool("voice_loop_cancel", {"job_id": "job-1"})

    asyncio.run(exercise())
    assert calls == [
        ("status", None),
        ("job", {"job_id": "job-1", "offset": 0, "limit": 20}),
        ("call", {"chat_id": "42", "objective": "Audio test"}),
        (
            "schedule",
            {"chat_id": "42", "objective": "Reminder", "when": "2026-10-01T09:00:00+05:30"},
        ),
        ("cancel", {"job_id": "job-1"}),
    ]


def test_mcp_invalid_tool_arguments_never_reach_desktop():
    calls = []

    async def exercise():
        async with create_connected_server_and_client_session(
            assistant_mcp.create_server(lambda *args: calls.append(args))
        ) as session:
            assert (await session.call_tool("voice_loop_call", {"chat_id": "42"})).isError
            assert (
                await session.call_tool("voice_loop_call", {"chat_id": {}, "objective": "Test"})
            ).isError
            assert (await session.call_tool("not_a_tool", {})).isError

    asyncio.run(exercise())
    assert calls == []


def test_real_stdio_entry_point_handshakes_without_loading_api_key_or_calling():
    async def exercise():
        source = Path(__file__).resolve().parents[1] / "src"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "voiceloop.assistant_mcp"],
            env={"PYTHONPATH": str(source), "PYTHONUTF8": "1"},
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                assert result.serverInfo.name == "Voice Loop"
                listing = await session.list_tools()
                assert {tool.name for tool in listing.tools} == TOOLS

    asyncio.run(exercise())


def test_request_uses_local_token_only_and_disables_proxy(monkeypatch, tmp_path):
    (tmp_path / "assistant-control-token").write_text("local-control-secret", encoding="utf-8")
    monkeypatch.setattr(assistant_mcp, "data_directory", lambda: tmp_path)
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, limit):
            captured["limit"] = limit
            return b'{"status":"idle"}'

    class Opener:
        def open(self, request, timeout):
            captured["request"], captured["timeout"] = request, timeout
            return Response()

    def opener(*handlers):
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(assistant_mcp.urllib.request, "build_opener", opener)
    assert assistant_mcp.request("status") == {"status": "idle"}
    request = captured["request"]
    assert request.full_url == "http://127.0.0.1:49322/v1/status"
    assert request.get_header("Authorization") == "Bearer local-control-secret"
    assert request.get_header("Origin") is None
    assert json.loads(request.data) == {}
    assert captured["handlers"][0].proxies == {}
    assert isinstance(captured["handlers"][1], assistant_mcp.NoRedirect)
    assert captured["timeout"] == 10


def test_redirect_never_forwards_the_control_secret(monkeypatch, tmp_path):
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            observed.append(self.path)
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            observed.append(self.path)
            self.send_response(200)
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    (tmp_path / "assistant-control-token").write_text("private-test-secret", encoding="utf-8")
    monkeypatch.setattr(assistant_mcp, "data_directory", lambda: tmp_path)
    monkeypatch.setattr(assistant_mcp, "CONTROL_PORT", server.server_port)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    try:
        with pytest.raises(RuntimeError, match="Open Voice Loop") as error:
            assistant_mcp.request("status")
        assert error.value.__suppress_context__
        assert "private-test-secret" not in str(error.value)
        assert observed == ["/v1/status"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_mcp_unavailable_desktop_error_is_generic(monkeypatch, tmp_path):
    monkeypatch.setattr(assistant_mcp, "data_directory", lambda: tmp_path / "private-directory")

    async def exercise():
        async with create_connected_server_and_client_session(
            assistant_mcp.create_server(assistant_mcp.request)
        ) as session:
            result = await session.call_tool("voice_loop_status", {})
            assert result.isError
            text = " ".join(c.text for c in result.content if c.type == "text")
            assert "Open Voice Loop" in text
            assert "private-directory" not in text

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "raw", [b"[]", b"invalid", b" " * (2 * 1024 * 1024 + 1)], ids=["array", "invalid", "oversized"]
)
def test_invalid_or_oversized_control_response_is_rejected(monkeypatch, tmp_path, raw):
    (tmp_path / "assistant-control-token").write_text("local-control-secret", encoding="utf-8")
    monkeypatch.setattr(assistant_mcp, "data_directory", lambda: tmp_path)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _limit):
            return raw

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(assistant_mcp.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(RuntimeError, match="Open Voice Loop"):
        assistant_mcp.request("status")
