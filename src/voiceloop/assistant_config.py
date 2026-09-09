"""Validated assistant policy settings. Credentials and call history live elsewhere."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from voiceloop.config import data_directory

CLIQ_HOSTS = frozenset(
    "cliq.zoho." + suffix for suffix in ("com", "eu", "in", "com.au", "jp", "ca", "com.cn", "sa")
)
PLATFORMS = ("zoho_cliq", "google_meet")
AVAILABILITY = ("any", "inside_hours", "outside_hours", "busy")
DEFAULT_INSTRUCTIONS = (
    "You are Voice Loop, a helpful AI voice assistant. Introduce yourself as an AI assistant. "
    "Keep the call brief and focused on its objective. Ask only necessary questions. "
    "Do not claim to be the account owner or invent facts, promises, or completed actions. "
    "Respect a request to stop. Once the objective is addressed, thank the person and end the call."
)
DEFAULT_SUMMARY_INSTRUCTIONS = (
    "Write a concise call summary someone can read in 10 seconds. Lead with the outcome. "
    "Include any request, decision, owner, deadline, caveat, or unresolved point that matters. "
    "Use at most 4 short bullets. Preserve uncertainty and do not invent details."
)
_SAVE_LOCK = threading.RLock()


def _text(value: object, name: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    value = value.strip()
    if (not value and not empty) or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} must contain {'0' if empty else '1'}–{limit} characters.")
    return value


def _boolean(value: object, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be enabled or disabled.")


def parse_target_url(url: str) -> tuple[str, str, str]:
    """Return (provider, stable target ID, canonical URL), accepting exact call scopes."""
    url = _text(url, "Chat or meeting URL", 1000)
    try:
        parsed = urlsplit(url)
        bad_authority = parsed.username or parsed.password or parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTPS chat or meeting link.") from exc
    if parsed.scheme != "https" or bad_authority or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTPS chat or meeting link without a query or fragment.")
    host = (parsed.hostname or "").lower()
    if host in CLIQ_HOSTS:
        match = re.fullmatch(r"/company/([0-9]{1,40})/chats/([0-9]{1,40})/?", parsed.path)
        if match:
            company, chat_id = match.groups()
            return "zoho_cliq", chat_id, f"https://{host}/company/{company}/chats/{chat_id}"
    elif host == "meet.google.com":
        match = re.fullmatch(r"/([a-z]{3}-[a-z]{4}-[a-z]{3})/?", parsed.path)
        if match:
            meeting_id = match.group(1)
            return "google_meet", meeting_id, f"https://{host}/{meeting_id}"
    raise ValueError("Use a Zoho Cliq chat link or a Google Meet meeting link.")


@dataclass
class ChatTarget:
    id: str
    name: str
    url: str
    enabled: bool = True
    allow_incoming: bool = False
    allow_outgoing: bool = True
    send_summary: bool = False

    def __post_init__(self):
        self.name = _text(self.name, "Contact name", 120)
        _, target_id, self.url = parse_target_url(self.url)
        if self.id != target_id:
            raise ValueError("Target ID must match the ID in its chat or meeting URL.")
        for name in ("enabled", "allow_incoming", "allow_outgoing", "send_summary"):
            _boolean(getattr(self, name), name)

    @classmethod
    def from_url(cls, name: str, url: str, **options) -> ChatTarget:
        _, target_id, canonical = parse_target_url(url)
        return cls(id=target_id, name=name, url=canonical, **options)

    @property
    def provider(self) -> str:
        return parse_target_url(self.url)[0]

    @property
    def chat_id(self) -> str:
        return self.id if self.provider == "zoho_cliq" else ""

    @property
    def company_id(self) -> str:
        return urlsplit(self.url).path.split("/")[2] if self.chat_id else ""


@dataclass
class AssistantSettings:
    enabled: bool = False
    model: str = "gpt-realtime"
    voice: str = "marin"
    language: str = "English"
    cliq_company_id: str = ""
    cliq_origin: str = "https://cliq.zoho.com"
    system_instructions: str = DEFAULT_INSTRUCTIONS
    default_objective: str = ""
    max_duration_seconds: int = 90
    busy: bool = False
    profile_id: str = ""
    auto_answer: bool = False
    auto_assist_outgoing: bool = False
    auto_assist_meet: bool = False
    platforms: tuple[str, ...] = ("zoho_cliq",)
    availability: str = "any"
    timezone: str = "UTC"
    work_days: tuple[int, ...] = (0, 1, 2, 3, 4)
    work_start: str = "09:00"
    work_end: str = "18:00"
    targets: list[ChatTarget] = field(default_factory=list)
    automation_enabled: bool = False
    summary_model: str = "gpt-4.1-mini"
    summary_instructions: str = DEFAULT_SUMMARY_INSTRUCTIONS

    def validate(self) -> AssistantSettings:
        self.language = _text(self.language, "Assistant language", 80)
        if any(ord(char) < 32 or ord(char) == 127 for char in self.language):
            raise ValueError("Assistant language must be a single line of text.")
        self.cliq_company_id = _text(self.cliq_company_id, "Cliq company ID", 40, empty=True)
        if self.cliq_company_id and not re.fullmatch(r"[0-9]{1,40}", self.cliq_company_id):
            raise ValueError("Cliq company ID must contain only digits.")
        origin = urlsplit(_text(self.cliq_origin, "Cliq origin", 100))
        if (
            origin.scheme != "https"
            or origin.netloc not in CLIQ_HOSTS
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
        ):
            raise ValueError("Choose a supported HTTPS Cliq regional origin without a path.")
        self.cliq_origin = "https://" + origin.netloc
        for name in (
            "enabled",
            "busy",
            "auto_answer",
            "auto_assist_outgoing",
            "auto_assist_meet",
            "automation_enabled",
        ):
            _boolean(getattr(self, name), name)
        for name in ("model", "voice", "summary_model"):
            value = _text(getattr(self, name), name.replace("_", " ").title(), 100)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", value):
                raise ValueError(f"{name.replace('_', ' ').title()} contains invalid characters.")
            setattr(self, name, value)
        self.system_instructions = _text(self.system_instructions, "System instructions", 12000)
        self.default_objective = _text(
            self.default_objective, "Default objective", 4000, empty=True
        )
        self.summary_instructions = _text(self.summary_instructions, "Summary instructions", 4000)
        self.profile_id = _text(self.profile_id, "Browser profile", 100, empty=True)
        if self.profile_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", self.profile_id):
            raise ValueError("Choose a paired browser profile.")
        if type(self.max_duration_seconds) is not int or not 15 <= self.max_duration_seconds <= 600:
            raise ValueError("Maximum call duration must be between 15 and 600 seconds.")
        if not isinstance(self.platforms, (list, tuple)) or any(
            p not in PLATFORMS for p in self.platforms
        ):
            raise ValueError("Choose supported assistant platforms.")
        self.platforms = tuple(dict.fromkeys(self.platforms))
        if self.availability not in AVAILABILITY:
            raise ValueError("Choose a valid availability policy.")
        self.timezone = _text(self.timezone, "Time zone", 100)
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                "Enter a valid IANA time zone, such as Asia/Kolkata or Europe/London."
            ) from exc
        if not isinstance(self.work_days, (list, tuple)) or any(
            type(day) is not int or day not in range(7) for day in self.work_days
        ):
            raise ValueError("Working days must be weekdays from Monday through Sunday.")
        self.work_days = tuple(sorted(set(self.work_days)))
        for name in ("work_start", "work_end"):
            if not isinstance(getattr(self, name), str) or not re.fullmatch(
                r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", getattr(self, name)
            ):
                raise ValueError("Working hours must use HH:MM in 24-hour time.")
        if self.work_start == self.work_end:
            raise ValueError("Working hours must have different start and end times.")
        if not isinstance(self.targets, list) or len(self.targets) > 200:
            raise ValueError("Configure at most 200 contacts or meetings.")
        ids = set()
        for target in self.targets:
            if not isinstance(target, ChatTarget):
                raise ValueError("Every target must be a valid contact or meeting.")
            target.__post_init__()
            if target.id in ids:
                raise ValueError("Each chat or meeting can only be configured once.")
            ids.add(target.id)
        return self

    def target(self, target_id: str) -> ChatTarget | None:
        return next((target for target in self.targets if target.id == target_id), None)

    def make_cliq_target(self, name: str, value: str, **flags) -> ChatTarget:
        value = _text(value, "Cliq chat ID or link", 1000)
        self.validate()
        if re.fullmatch(r"[0-9]{1,40}", value):
            if not self.cliq_company_id:
                raise ValueError("Configure the Cliq company ID first, or paste a full chat link.")
            value = f"{self.cliq_origin}/company/{self.cliq_company_id}/chats/{value}"
        target = ChatTarget.from_url(name, value, **flags)
        if target.provider != "zoho_cliq":
            raise ValueError("Enter a Cliq chat ID or chat link.")
        origin = "https://" + urlsplit(target.url).netloc
        if self.cliq_company_id:
            if target.company_id != self.cliq_company_id or origin != self.cliq_origin:
                raise ValueError(
                    "This link belongs to a different Cliq company or region. "
                    "Update Cliq settings first."
                )
        else:
            self.cliq_company_id, self.cliq_origin = target.company_id, origin
        return target

    def within_working_hours(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Working-hours checks require an aware date and time.")
        local = now.astimezone(ZoneInfo(self.timezone))
        clock = local.strftime("%H:%M")
        if self.work_start < self.work_end:
            return local.weekday() in self.work_days and self.work_start <= clock < self.work_end
        # Overnight windows belong to the day on which the shift starts.
        if clock >= self.work_start:
            return local.weekday() in self.work_days
        return clock < self.work_end and (local - timedelta(days=1)).weekday() in self.work_days

    def available(self, now: datetime) -> bool:
        if self.availability == "any":
            return True
        if self.availability == "busy":
            return self.busy
        inside = self.within_working_hours(now)
        return inside if self.availability == "inside_hours" else not inside

    def permits(self, now: datetime) -> bool:
        """Availability only; callers must separately enforce target and enabled policies."""
        return self.available(now)

    def to_dict(self) -> dict:
        self.validate()
        return {"version": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict) -> AssistantSettings:
        if not isinstance(data, dict) or data.get("version", 1) != 1:
            raise ValueError("Unsupported assistant settings format.")
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        if "targets" in values:
            if not isinstance(values["targets"], list):
                raise ValueError("Assistant contacts must be a list.")
            values["targets"] = [
                ChatTarget(
                    **{k: v for k, v in item.items() if k in ChatTarget.__dataclass_fields__}
                )
                if isinstance(item, dict)
                else None
                for item in values["targets"]
            ]
        if "cliq_company_id" not in data:
            scopes = {
                (t.company_id, "https://" + urlsplit(t.url).netloc)
                for t in values.get("targets", [])
                if t and t.provider == "zoho_cliq"
            }
            if len(scopes) == 1:
                values["cliq_company_id"], values["cliq_origin"] = scopes.pop()
        return cls(**values).validate()

    @classmethod
    def load(cls, path: Path | None = None) -> AssistantSettings:
        path = path or data_directory() / "assistant.json"
        try:
            if path.stat().st_size > 1_000_000:
                return cls()
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            # Corrupt or incompatible policy files must never enable automatic calls.
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or data_directory() / "assistant.json"
        data = self.to_dict()
        with _SAVE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=path.name + ".", suffix=".tmp", dir=path.parent
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
