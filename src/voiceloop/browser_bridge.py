"""Small authenticated loopback HTTP bridge for the Voice Loop Chrome extension."""

import hmac
import json
import os
import queue
import re
import secrets
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from voiceloop.call_detection import CallEvent
from voiceloop.config import data_directory

BRIDGE_PORT = 49321
MAX_BODY = 16 * 1024
_EXTENSION_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_COMMAND_PATHS = {"/v1/commands/poll", "/v1/commands/result"}


def _identifier(value, name):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name}.")
    return value


def _chat_target(chat_id, chat_url):
    if not isinstance(chat_id, str) or not re.fullmatch(r"[0-9]{1,64}", chat_id):
        raise ValueError("A numeric Cliq chat ID is required.")
    if not isinstance(chat_url, str) or len(chat_url) > 2048:
        raise ValueError("Invalid Cliq chat URL.")
    parsed = urlsplit(chat_url)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(r"cliq\.zoho\.(?:com|eu|in|com\.au|jp|ca|com\.cn|sa)", parsed.netloc)
        or not re.fullmatch(rf"/company/[0-9]+/chats/{chat_id}/?", parsed.path)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("The Cliq chat URL must match the exact chat ID.")
    return chat_url.rstrip("/")


def pairing_token(path: Path) -> str:
    """Persist only a random browser-pairing secret, separate from API keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        token = secrets.token_urlsafe(32)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(token + "\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError:
        token = path.read_text(encoding="ascii").strip()
    if not _TOKEN.fullmatch(token):
        raise ValueError("Invalid browser pairing token file. Remove it to pair Chrome again.")
    if os.name != "nt":
        path.chmod(0o600)
    return token


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False
    request_queue_size = 4

    def __init__(self, address, bridge):
        self.bridge = bridge
        self._slots = threading.BoundedSemaphore(4)
        super().__init__(address, _Handler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(2)
        return request, address

    def verify_request(self, request, client_address):
        return client_address[0] == "127.0.0.1"

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # Requests contain private contact data and a pairing secret. No logging.
        pass


class _Handler(BaseHTTPRequestHandler):
    server_version = "VoiceLoop"
    sys_version = ""

    def log_message(self, format, *args):
        pass

    def _reply(self, status: int, value: dict, *, preflight: bool = False):
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        origin = self.headers.get("Origin", "")
        if _EXTENSION_ORIGIN.fullmatch(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            if preflight:
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
                if self.headers.get("Access-Control-Request-Private-Network") == "true":
                    self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _allowed(self, *, authenticate: bool = True) -> bool:
        hosts = self.headers.get_all("Host", [])
        if hosts != [f"127.0.0.1:{self.server.server_port}"]:
            self._reply(403, {"error": "Invalid loopback host."})
            return False
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and not _EXTENSION_ORIGIN.fullmatch(origins[0])):
            self._reply(403, {"error": "Only the Chrome extension may use this bridge."})
            return False
        if not authenticate:
            if not origins:
                self._reply(403, {"error": "An extension origin is required."})
                return False
            return True
        authorization = self.headers.get_all("Authorization", [])
        expected = "Bearer " + self.server.bridge.pairing_token
        if len(authorization) != 1 or not hmac.compare_digest(
            authorization[0].encode("utf-8"), expected.encode("utf-8")
        ):
            self._reply(401, {"error": "Pair Chrome with Voice Loop first."})
            return False
        return True

    def do_OPTIONS(self):
        if not self._allowed(authenticate=False):
            return
        requested_headers = {
            item.strip().lower()
            for item in self.headers.get("Access-Control-Request-Headers", "").split(",")
            if item.strip()
        }
        if (
            self.path not in {"/v1/health", "/v1/events"} | _COMMAND_PATHS
            or self.headers.get("Access-Control-Request-Method") not in {"GET", "POST"}
            or not requested_headers <= {"authorization", "content-type"}
        ):
            self._reply(403, {"error": "Unsupported preflight request."})
            return
        self._reply(200, {"ok": True}, preflight=True)

    def do_GET(self):
        if not self._allowed():
            return
        if self.path != "/v1/health":
            self._reply(404, {"error": "Unknown endpoint."})
            return
        self._reply(200, {"ok": True, "version": 1, "application": "VoiceLoop"})

    def do_POST(self):
        if not self._allowed():
            return
        if self.path not in {"/v1/events"} | _COMMAND_PATHS:
            self._reply(404, {"error": "Unknown endpoint."})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            self._reply(400, {"error": "A single Content-Length is required."})
            return
        try:
            length = int(lengths[0])
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            self._reply(413, {"error": "Event body exceeds the size limit."})
            return
        if self.headers.get_content_type() != "application/json":
            self._reply(415, {"error": "Expected application/json."})
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete body.")
            payload = json.loads(body)
            if self.path in _COMMAND_PATHS:
                result = self.server.bridge._command_request(self.path, payload, self.server)
                self._reply(200, result)
                return
            event = CallEvent.from_payload(payload)
        except (TimeoutError, ValueError, UnicodeError, RecursionError):
            self._reply(400, {"error": "Invalid or stale call event."})
            return
        try:
            accepted = self.server.bridge._enqueue(event, self.server)
        except queue.Full:
            self._reply(503, {"error": "Event queue is full. Try again shortly."})
            return
        if not accepted:
            self._reply(503, {"error": "Bridge is stopping."})
            return
        self._reply(202, {"ok": True})


class BrowserBridge:
    """No GUI or audio dependencies; drain validated events on the GUI thread."""

    def __init__(self, token_path: Path | None = None, port: int = BRIDGE_PORT):
        self._token_path = token_path or data_directory() / "browser-pairing-token"
        self._token: str | None = None
        self._port = port
        self._events: queue.Queue[CallEvent] = queue.Queue(maxsize=128)
        self._state_lock = threading.Lock()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._commands: OrderedDict[str, dict] = OrderedDict()
        self._results: list[dict] = []
        self._profiles: OrderedDict[str, dict] = OrderedDict()

    @property
    def pairing_token(self) -> str:
        if self._token is None:
            self._token = pairing_token(self._token_path)
        return self._token

    @property
    def port(self) -> int:
        return self._server.server_port if self._server else self._port

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self.is_running:
            return
        _ = self.pairing_token
        server = _Server(("127.0.0.1", self._port), self)
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="VoiceLoopBrowserBridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        with self._state_lock:
            server, self._server = self._server, None
            for record in self._commands.values():
                if not record.get("result"):
                    self._finish_command(
                        record,
                        "ambiguous" if record["leased"] else "failed",
                        "Browser bridge stopped.",
                    )
        if server:
            server.shutdown()
            server.server_close()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self.drain(limit=128)

    def _enqueue(self, event: CallEvent, server: _Server) -> bool:
        # A slow request from a previous bridge instance cannot start a call
        # after detection was disabled and enabled again.
        with self._state_lock:
            if server is not self._server:
                return False
            self._events.put_nowait(event)
            return True

    def drain(self, limit: int = 64) -> list[CallEvent]:
        events = []
        for _ in range(max(0, min(limit, 128))):
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def submit_command(
        self,
        action,
        *,
        profile_id,
        chat_id="",
        chat_url="",
        call_id="",
        participant_id="",
        text="",
        command_id=None,
        ttl=45,
    ):
        """Queue one policy-authorized action for exactly one paired profile.

        This transport grants no policy authorization itself. Callers must enforce
        enabled providers, allowed chats, working hours and session ownership.
        Commands are delivered once; a lost response never causes a second call.
        """
        if action not in {"call", "answer", "hangup", "send_summary"}:
            raise ValueError("Unsupported browser action.")
        profile_id = _identifier(profile_id, "profile ID")
        command_id = _identifier(command_id or str(uuid4()), "command ID")
        if call_id:
            _identifier(call_id, "call ID")
        if not isinstance(participant_id, str) or (
            participant_id and not re.fullmatch(r"[0-9]{1,64}", participant_id)
        ):
            raise ValueError("Invalid Cliq participant ID.")
        if action in {"answer", "hangup"} and not call_id:
            raise ValueError("A specific call ID is required.")
        if chat_id or chat_url or action in {"call", "send_summary", "answer"}:
            chat_url = _chat_target(chat_id, chat_url)
        if (
            not isinstance(text, str)
            or len(text) > 4000
            or any(ord(c) < 32 and c not in "\n\t" for c in text)
        ):
            raise ValueError("Invalid summary text.")
        if action == "send_summary" and not text.strip():
            raise ValueError("A summary is required.")
        if type(ttl) not in {int, float} or not 1 <= ttl <= 120:
            raise ValueError("Command expiry must be within 1–120 seconds.")
        with self._state_lock:
            if not self._server:
                raise ValueError("Browser bridge is not running.")
            if command_id in self._commands:
                prior = self._commands[command_id]["command"]
                if any(
                    prior[key] != value
                    for key, value in {
                        "action": action,
                        "profile_id": profile_id,
                        "chat_id": chat_id,
                        "chat_url": chat_url,
                        "call_id": call_id,
                        "participant_id": participant_id,
                        "text": text,
                    }.items()
                ):
                    raise ValueError("Command ID already belongs to another action.")
                return command_id
            self._expire_commands()
            if sum(not record.get("result") for record in self._commands.values()) >= 128:
                raise ValueError("Browser command queue is full.")
            profile = self._profiles.get(profile_id)
            if (
                not profile
                or time.time() - profile["last_seen"] > 45
                or "call-control-v1" not in profile["capabilities"]
            ):
                raise ValueError(
                    "The selected Chrome profile is not connected with call control enabled."
                )
            command = {
                "version": 1,
                "command_id": command_id,
                "profile_id": profile_id,
                "action": action,
                "provider": "zoho_cliq" if chat_url else "google_meet",
                "chat_id": chat_id,
                "chat_url": chat_url,
                "call_id": call_id,
                "participant_id": participant_id,
                "text": text,
                "expires_at": datetime.fromtimestamp(time.time() + ttl, UTC).isoformat(),
            }
            self._commands[command_id] = {"command": command, "leased": False, "result": None}
            while len(self._commands) > 512:
                old = next((key for key, value in self._commands.items() if value["result"]), None)
                if old is None:
                    break
                del self._commands[old]
        return command_id

    def cancel_command(self, command_id):
        """Return cancelled, ambiguous (already delivered), or unknown."""
        with self._state_lock:
            record = self._commands.get(command_id)
            if not record:
                return "unknown"
            if record["leased"]:
                return "ambiguous"
            if not record["result"]:
                self._finish_command(record, "failed", "Cancelled before delivery.")
            return "cancelled"

    def _finish_command(self, record, status, detail, call_id=""):
        command = record["command"]
        result = {
            key: command[key]
            for key in ("command_id", "profile_id", "action", "chat_id", "chat_url")
        }
        result.update(status=status, detail=detail, call_id=call_id or command["call_id"])
        record["result"] = result
        self._results.append(result)
        self._results = self._results[-512:]

    def _expire_commands(self):
        now = time.time()
        for record in self._commands.values():
            if (
                not record["result"]
                and datetime.fromisoformat(record["command"]["expires_at"]).timestamp() <= now
            ):
                self._finish_command(
                    record,
                    "ambiguous" if record["leased"] else "failed",
                    "Command expired; it will not be repeated.",
                )

    def profiles(self):
        with self._state_lock:
            return [
                dict(profile)
                for profile in self._profiles.values()
                if time.time() - profile["last_seen"] <= 45
            ]

    def drain_results(self):
        with self._state_lock:
            self._expire_commands()
            results, self._results = self._results, []
            return results

    def _command_request(self, path, payload, server):
        if (
            not isinstance(payload, dict)
            or type(payload.get("version")) is not int
            or payload.get("version") != 1
        ):
            raise ValueError("Invalid command protocol version.")
        profile_id = _identifier(payload.get("profile_id"), "profile ID")
        with self._state_lock:
            if server is not self._server:
                raise ValueError("Bridge is stopping.")
            self._expire_commands()
            if path == "/v1/commands/poll":
                capabilities = payload.get("capabilities", [])
                if not isinstance(capabilities, list) or any(
                    value not in {"call-control-v1", "zoho_cliq", "google_meet"}
                    for value in capabilities
                ):
                    raise ValueError("Invalid capabilities.")
                label = payload.get("label", "Chrome profile")
                if not isinstance(label, str) or len(label) > 80 or any(ord(c) < 32 for c in label):
                    raise ValueError("Invalid profile label.")
                self._profiles[profile_id] = {
                    "profile_id": profile_id,
                    "last_seen": time.time(),
                    "label": label,
                    "capabilities": capabilities,
                }
                self._profiles.move_to_end(profile_id)
                while len(self._profiles) > 16:
                    self._profiles.popitem(last=False)
                for record in self._commands.values():
                    command = record["command"]
                    if (
                        not record["result"]
                        and not record["leased"]
                        and command["profile_id"] == profile_id
                    ):
                        record["leased"] = True
                        return {"ok": True, "commands": [command]}
                return {"ok": True, "commands": []}
            command_id = _identifier(payload.get("command_id"), "command ID")
            record = self._commands.get(command_id)
            if not record or record["command"]["profile_id"] != profile_id or not record["leased"]:
                raise ValueError("Unknown command result.")
            status, detail = payload.get("status"), payload.get("detail", "")
            if (
                status not in {"succeeded", "failed", "ambiguous"}
                or not isinstance(detail, str)
                or len(detail) > 512
                or any(ord(c) < 32 for c in detail)
            ):
                raise ValueError("Invalid command result.")
            call_id = payload.get("call_id", "")
            if call_id:
                _identifier(call_id, "call ID")
            if not record["result"]:
                self._finish_command(record, status, detail, call_id)
            return {"ok": True}


BridgeServer = BrowserBridge
