"""Token-authenticated loopback control for local MCP clients, separate from Chrome."""

import hmac
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler

from voiceloop.browser_bridge import _Server, pairing_token
from voiceloop.config import data_directory

CONTROL_PORT = 49322


def compact_job(job):
    """Keep status useful and bounded as transcript history grows."""
    fields = (
        "id",
        "target_id",
        "target_name",
        "provider",
        "profile_id",
        "state",
        "created_at",
        "scheduled_at",
        "started_at",
        "ended_at",
        "direction",
        "delivery_status",
        "error",
    )
    result = {name: job[name] for name in fields if name in job}
    for name in ("objective", "summary"):
        value = str(job.get(name, ""))
        result[name] = value[:2000]
        if len(value) > 2000:
            result[name + "_truncated"] = True
    result["transcript_count"] = len(job.get("transcript", []))
    return result


def job_page(service, data):
    if set(data) - {"job_id", "offset", "limit"} or "job_id" not in data:
        raise ValueError("Expected job_id and optional offset and limit.")
    job_id, offset, limit = data["job_id"], data.get("offset", 0), data.get("limit", 20)
    if not isinstance(job_id, str) or not 1 <= len(job_id) <= 128:
        raise ValueError("Invalid job ID.")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Invalid transcript page.")
    job = service.store.get(job_id)
    transcript = job.get("transcript", [])
    result = compact_job(job)
    result["transcript"] = []
    size = 0
    for item in transcript[offset : offset + limit]:
        item_size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if item_size > 512 * 1024:
            raise ValueError("A transcript entry is too large to return through MCP.")
        if size + item_size > 512 * 1024:
            break
        result["transcript"].append(item)
        size += item_size
    end = min(len(transcript), offset + len(result["transcript"]))
    result["offset"] = offset
    result["next_offset"] = end if end < len(transcript) else None
    return result


class ControlServer:
    def __init__(self, service, *, port=CONTROL_PORT, token_path=None):
        self.service = service
        self.token = pairing_token(token_path or data_directory() / "assistant-control-token")
        self.port = port
        self.server = None
        self._lock = threading.RLock()

    def start(self):
        with self._lock:
            self._start()

    def _start(self):
        if self.server:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _reply(self, code, value):
                body = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.close_connection = True
                if (
                    self.client_address[0] != "127.0.0.1"
                    or self.headers.get_all("Host") != [f"127.0.0.1:{owner.port}"]
                    or self.headers.get("Origin") is not None
                    or self.headers.get("Transfer-Encoding") is not None
                ):
                    self._reply(403, {"error": "Only local MCP clients are allowed."})
                    return
                authorization = self.headers.get_all("Authorization", [])
                if len(authorization) != 1 or not hmac.compare_digest(
                    authorization[0], "Bearer " + owner.token
                ):
                    self._reply(401, {"error": "Invalid local control token."})
                    return
                try:
                    content_types = self.headers.get_all("Content-Type", [])
                    if (
                        len(content_types) != 1
                        or content_types[0].split(";", 1)[0].strip().lower() != "application/json"
                    ):
                        self._reply(415, {"error": "Send one application/json Content-Type."})
                        return
                    lengths = self.headers.get_all("Content-Length", [])
                    if len(lengths) != 1 or not 0 < int(lengths[0]) <= 16384:
                        raise ValueError("Invalid request size.")
                    raw = self.rfile.read(int(lengths[0]))
                    if len(raw) != int(lengths[0]):
                        raise ValueError("Incomplete request body.")
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("Expected an object.")
                    with owner._lock:
                        # A handler accepted by a closed listener must never
                        # issue a delayed call against a restarted service.
                        if owner.server is not self.server:
                            self._reply(503, {"error": "The local control listener stopped."})
                            return
                        if self.path == "/v1/status":
                            if data:
                                raise ValueError("Status does not accept arguments.")
                            result = owner.service.snapshot()
                            result["jobs"] = [compact_job(j) for j in result.get("jobs", [])[:30]]
                            result["targets"] = [
                                {"id": t.id, "name": t.name, "url": t.url, "enabled": t.enabled}
                                for t in owner.service.config.targets
                            ]
                        elif self.path == "/v1/job":
                            result = job_page(owner.service, data)
                        elif self.path == "/v1/call":
                            if set(data) != {"chat_id", "objective"}:
                                raise ValueError("Expected chat_id and objective.")
                            result = owner.service.trigger(data["chat_id"], data["objective"])
                        elif self.path == "/v1/schedule":
                            if set(data) != {"chat_id", "objective", "when"}:
                                raise ValueError("Expected chat_id, objective and when.")
                            result = owner.service.schedule(
                                data["chat_id"],
                                data["objective"],
                                datetime.fromisoformat(data["when"]),
                            )
                        elif self.path == "/v1/cancel":
                            if set(data) != {"job_id"}:
                                raise ValueError("Expected job_id.")
                            owner.service.cancel(data["job_id"])
                            result = {"cancelled": True}
                        else:
                            self._reply(404, {"error": "Unknown control operation."})
                            return
                    self._reply(200, result)
                except (ValueError, TypeError, KeyError):
                    self._reply(
                        400,
                        {
                            "error": (
                                "Invalid request or call policy does not permit this action. "
                                "Check Voice Loop."
                            )
                        },
                    )
                except (OSError, RuntimeError):
                    self._reply(503, {"error": "Voice Loop is not ready. Check the desktop app."})

        self.server = _Server(("127.0.0.1", self.port), None)
        self.server.RequestHandlerClass = Handler
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        with self._lock:
            server = self.server
            self.server = None
        if server:
            server.shutdown()
            server.server_close()
