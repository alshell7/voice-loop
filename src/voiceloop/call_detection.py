"""Validated browser events and an audio-independent call lifecycle controller.

The controller requests actions; only the desktop UI can start or stop audio.
Browser call IDs never confer ownership of a session started manually.
"""

import math
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import urlsplit

PROVIDERS = {"zoho_cliq": "Zoho Cliq", "google_meet": "Google Meet"}
STATES = {"ringing", "dialing", "connected", "ended"}
DIRECTIONS = {"incoming", "outgoing", "unknown"}
MAX_EVENT_AGE = 120
HEARTBEAT_TIMEOUT = 45
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _text(value, name: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Invalid {name}.")
    value = value.strip()
    if (required and not value) or any(ord(char) < 32 for char in value):
        raise ValueError(f"Invalid {name}.")
    return value


@dataclass(frozen=True)
class CallEvent:
    event_id: str
    call_id: str
    provider: str
    state: str
    direction: str
    contact_name: str
    contact_email: str
    title: str
    url: str
    timestamp: float

    @property
    def tool_name(self) -> str:
        return PROVIDERS[self.provider]

    @property
    def display_name(self) -> str:
        return self.contact_name or self.title or self.tool_name

    @classmethod
    def from_payload(cls, payload: dict, *, now: float | None = None) -> "CallEvent":
        """Parse protocol v1; timestamps must be timezone-aware ISO 8601."""
        if not isinstance(payload, dict) or type(payload.get("version")) is not int:
            raise ValueError("Expected a versioned event object.")
        if payload["version"] != 1:
            raise ValueError("Unsupported event version.")
        event_id = _text(payload.get("event_id"), "event ID", 128, required=True)
        call_id = _text(payload.get("call_id"), "call ID", 128, required=True)
        if not _ID.fullmatch(event_id) or not _ID.fullmatch(call_id):
            raise ValueError("Invalid event or call ID.")
        provider, state, direction = (
            payload.get("provider"),
            payload.get("state"),
            payload.get("direction", "unknown"),
        )
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise ValueError("Unsupported call provider.")
        if not isinstance(state, str) or state not in STATES:
            raise ValueError("Unsupported call state.")
        if not isinstance(direction, str) or direction not in DIRECTIONS:
            raise ValueError("Unsupported call direction.")
        contact = payload.get("contact", {})
        if not isinstance(contact, dict):
            raise ValueError("Invalid contact.")
        name = _text(contact.get("name", ""), "contact name", 256)
        email = _text(contact.get("email", ""), "contact email", 320)
        title = _text(payload.get("title", ""), "meeting title", 512)
        url = _text(payload.get("url", ""), "meeting URL", 2048)
        if url:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Meeting URLs must use HTTPS.")
            host = parsed.hostname
            if provider == "google_meet" and host != "meet.google.com":
                raise ValueError("Unexpected Google Meet hostname.")
            if provider == "zoho_cliq" and not re.fullmatch(
                r"cliq\.zoho\.(?:com|eu|in|com\.au|jp|ca|com\.cn|sa)", host
            ):
                raise ValueError("Unexpected Zoho Cliq hostname.")
        raw_timestamp = _text(payload.get("timestamp"), "timestamp", 64, required=True)
        try:
            parsed_timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            if parsed_timestamp.tzinfo is None:
                raise ValueError("Missing timestamp timezone.")
            timestamp = parsed_timestamp.timestamp()
        except (ValueError, OverflowError, OSError) as error:
            raise ValueError("Invalid event timestamp.") from error
        age = (time.time() if now is None else now) - timestamp
        if not math.isfinite(timestamp) or age > MAX_EVENT_AGE or age < -30:
            raise ValueError("Event timestamp is stale or in the future.")
        return cls(
            event_id, call_id, provider, state, direction, name, email, title, url, timestamp
        )


@dataclass(frozen=True)
class CallAction:
    kind: str
    event: CallEvent | None
    message: str = ""


@dataclass
class _TrackedCall:
    event: CallEvent
    last_seen: float
    suppressed: bool = False
    prompted: bool = False


class CallController:
    """A single recording owner with bounded duplicate and ended-call memory.

    ``start_recording`` reserves ownership immediately, including audio startup.
    Report startup failure with ``recording_failed``. Device-switch restarts must
    retain this controller; report explicit user stops with ``session_stopped``.
    All methods run on the desktop thread. ``now`` is monotonic, for testing.
    """

    def __init__(self, auto_record: bool = False, heartbeat_timeout: float = HEARTBEAT_TIMEOUT):
        self.auto_record = auto_record
        self.heartbeat_timeout = heartbeat_timeout
        self._calls: OrderedDict[tuple[str, str], _TrackedCall] = OrderedDict()
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._active: tuple[str, str] | None = None
        self._owned: tuple[str, str] | None = None

    @property
    def active_event(self) -> CallEvent | None:
        call = self._calls.get(self._active)
        return call.event if call else None

    @property
    def owned_call_id(self) -> str | None:
        return self._owned[1] if self._owned else None

    def _feedback(self, event: CallEvent) -> CallAction:
        state = {
            "ringing": "Incoming call",
            "dialing": "Calling",
            "connected": "Call connected",
            "ended": "Call ended",
        }[event.state]
        return CallAction("feedback", event, f"{state} · {event.display_name}")

    def _finish(self, key, message: str | None = None) -> list[CallAction]:
        call = self._calls[key]
        call.event = replace(call.event, state="ended")
        actions = []
        if call.prompted:
            actions.append(CallAction("dismiss_prompt", call.event))
            call.prompted = False
        if self._owned == key:
            self._owned = None
            actions.append(CallAction("stop_recording", call.event))
        if self._active == key:
            self._active = None
            actions.append(
                CallAction("feedback", call.event, message)
                if message
                else self._feedback(call.event)
            )
        return actions

    def handle(
        self, event: CallEvent, *, session_active: bool = False, now: float | None = None
    ) -> list[CallAction]:
        now = time.monotonic() if now is None else now
        if event.event_id in self._seen:
            return []
        self._seen[event.event_id] = None
        if len(self._seen) > 1024:
            self._seen.popitem(last=False)
        key = (event.provider, event.call_id)
        call = self._calls.get(key)
        if call and (call.event.state == "ended" or event.timestamp < call.event.timestamp):
            return []
        if call and call.event.state == "connected" and event.state in {"ringing", "dialing"}:
            return []
        old = call.event if call else None
        if call is None:
            # Never evict a live call to admit an unbounded stream of new IDs.
            if len(self._calls) >= 64:
                removable = next(
                    (k for k, v in self._calls.items() if v.event.state == "ended"), None
                )
                if removable is None:
                    return []
                del self._calls[removable]
            call = self._calls[key] = _TrackedCall(event, now)
        call.event, call.last_seen = event, now
        if event.state == "ended":
            return self._finish(key)
        if self._active is None:
            self._active = key
        # Parallel tabs/calls cannot take over the foreground call or session.
        if self._active != key:
            return []
        changed = old is None or (old.state, old.contact_name, old.title, old.direction) != (
            event.state,
            event.contact_name,
            event.title,
            event.direction,
        )
        actions = [self._feedback(event)] if changed else []
        if event.state != "connected" or call.suppressed or self._owned == key or call.prompted:
            return actions
        if session_active or self._owned is not None:
            call.suppressed = True
            actions.append(
                CallAction("feedback", event, "Call detected · your current session continues")
            )
        elif self.auto_record:
            self._owned = key
            actions.append(CallAction("start_recording", event))
        else:
            call.prompted = True
            actions.append(CallAction("prompt_record", event))
        return actions

    def respond(
        self, call_id: str, accepted: bool, *, session_active: bool = False
    ) -> list[CallAction]:
        key = self._active
        call = self._calls.get(key)
        if not call or call.event.call_id != call_id or not call.prompted:
            return []
        call.prompted = False
        actions = [CallAction("dismiss_prompt", call.event)]
        if not accepted or session_active or call.event.state != "connected" or self._owned:
            call.suppressed = True
            actions.append(CallAction("feedback", call.event, "Call connected · recording skipped"))
            return actions
        self._owned = key
        actions.append(CallAction("start_recording", call.event))
        return actions

    def session_stopped(self, manual: bool = True) -> list[CallAction]:
        key = self._owned or self._active
        self._owned = None
        call = self._calls.get(key)
        if not call or call.event.state == "ended":
            return []
        call.suppressed = True
        actions = []
        if call.prompted:
            call.prompted = False
            actions.append(CallAction("dismiss_prompt", call.event))
        message = (
            "Call connected · recording stopped"
            if manual and call.event.state == "connected"
            else "Call detected · recording skipped"
            if manual
            else "Call recording finished"
        )
        actions.append(CallAction("feedback", call.event, message))
        return actions

    def recording_failed(self, call_id: str) -> list[CallAction]:
        if self.owned_call_id != call_id:
            return []
        actions = self.session_stopped(manual=False)
        return [replace(a, message="Call connected · recording could not start") for a in actions]

    def tick(self, *, now: float | None = None) -> list[CallAction]:
        now = time.monotonic() if now is None else now
        actions = []
        for key, call in list(self._calls.items()):
            if call.event.state != "ended" and now - call.last_seen >= self.heartbeat_timeout:
                message = (
                    "Chrome connection lost · recording stopped"
                    if self._owned == key
                    else "Browser call updates stopped"
                )
                actions.extend(self._finish(key, message))
            elif call.event.state == "ended" and now - call.last_seen > 600:
                del self._calls[key]
        return actions

    def reset(self) -> list[CallAction]:
        actions = []
        for key, call in list(self._calls.items()):
            if call.event.state != "ended":
                actions.extend(self._finish(key))
        self._calls.clear()
        self._seen.clear()
        self._active = self._owned = None
        return actions
