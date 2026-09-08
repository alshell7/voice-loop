"""Small authenticated loopback HTTP bridge for the Voice Loop Chrome extension."""

import hmac
import json
import os
import queue
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from voiceloop.call_detection import CallEvent
from voiceloop.config import data_directory

BRIDGE_PORT = 49321
MAX_BODY = 16 * 1024
_EXTENSION_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")


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
            self.path not in {"/v1/health", "/v1/events"}
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
        if self.path != "/v1/events":
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
            event = CallEvent.from_payload(json.loads(body))
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


BridgeServer = BrowserBridge
