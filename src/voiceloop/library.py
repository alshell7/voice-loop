"""Searchable local contacts and a cached, paginated manifest library."""

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from voiceloop.config import atomic_json, data_directory

TOOLS = ("Zoho Cliq", "Google Meet", "Microsoft Teams", "Zoom", "Phone", "Other")


def clean_tag(value: str) -> str:
    return " ".join(str(value).split())[:120]


class Contacts:
    def __init__(self, path: Path | None = None):
        self.path = path or data_directory() / "contacts.json"

    def names(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            values = data.get("contacts", []) if isinstance(data, dict) else []
            return sorted(
                {clean_tag(n) for n in values if isinstance(n, str) and n.strip()}, key=str.casefold
            )
        except (OSError, ValueError):
            return []

    def remember(self, value: str) -> str:
        value = clean_tag(value)
        if not value:
            return ""
        names = self.names()
        existing = next((n for n in names if n.casefold() == value.casefold()), None)
        if existing:
            return existing
        atomic_json(self.path, {"contacts": sorted([*names, value], key=str.casefold)})
        return value


@dataclass
class Session:
    directory: Path
    info: dict
    status: str

    @property
    def metadata(self):
        value = self.info.get("metadata", {})
        return value if isinstance(value, dict) else {}

    @property
    def transcribed(self):
        return (self.directory / "transcript.json").is_file()


@dataclass
class Page:
    items: list[Session]
    total: int
    number: int
    pages: int


def audio_parts(directory: Path, manifest: dict) -> list[Path]:
    directory = directory.resolve()
    result = []
    for part in manifest.get("parts", []):
        path = (directory / part["file"]).resolve()
        if path.parent != directory or path.suffix.lower() != ".wav":
            raise ValueError("Audio parts must be WAV files inside this session.")
        if not path.is_file():
            raise ValueError("A recording file is missing. Restore it before continuing.")
        result.append(path)
    return result


class SessionLibrary:
    def __init__(self):
        self.cache = {}

    def scan(self, root: Path, active: Path | None = None) -> list[Session]:
        found, seen = [], set()
        root = root.resolve()
        for path in root.glob("*/session.json"):
            try:
                if path.resolve().parent.parent != root:
                    continue
                seen.add(path)
                signature = (path.stat().st_mtime_ns, path.stat().st_size)
                old = self.cache.get(path)
                if old is None or old[0] != signature:
                    info = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(info, dict) or info.get("schema_version") != 1:
                        continue
                    self.cache[path] = (signature, info)
                info = self.cache[path][1]
                status = str(info.get("status", "unknown"))
                if status == "recording" and path.parent != active:
                    status = "unfinished"
                found.append(Session(path.parent, info, status))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        self.cache = {p: value for p, value in self.cache.items() if p in seen}
        return sorted(
            found, key=lambda s: str(s.info.get("started_at", s.directory.name)), reverse=True
        )

    def query(
        self,
        root: Path,
        *,
        text="",
        tool="",
        contact="",
        state="",
        days=0,
        page=1,
        page_size=8,
        active=None,
    ) -> Page:
        entries = self.scan(root, active)
        search, contact = text.casefold().strip(), contact.casefold().strip()
        after = datetime.now(UTC) - timedelta(days=days) if days else None
        matching = []
        for session in entries:
            meta = session.metadata
            if tool and meta.get("tool") != tool:
                continue
            if contact and contact not in str(meta.get("contact", "")).casefold():
                continue
            if state == "transcribed" and not session.transcribed:
                continue
            if state == "not_transcribed" and session.transcribed:
                continue
            if state not in ("", "transcribed", "not_transcribed") and session.status != state:
                continue
            if after:
                try:
                    started = datetime.fromisoformat(session.info["started_at"])
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=UTC)
                    if started < after:
                        continue
                except (ValueError, KeyError, TypeError):
                    continue
            haystack = " ".join(
                str(value)
                for value in (
                    meta.get("contact", ""),
                    meta.get("tool", ""),
                    session.info.get("started_at", ""),
                    session.directory.name,
                )
            ).casefold()
            if search and search not in haystack:
                continue
            matching.append(session)
        page_size = max(1, min(100, int(page_size)))
        pages = max(1, math.ceil(len(matching) / page_size))
        page = max(1, min(pages, int(page)))
        return Page(matching[(page - 1) * page_size : page * page_size], len(matching), page, pages)


def update_metadata(directory: Path, *, tool: str, contact: str) -> None:
    path = directory / "session.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") == "recording":
        raise ValueError("Finish the session before changing its saved tags.")
    data["metadata"] = {"tool": clean_tag(tool), "contact": clean_tag(contact)}
    atomic_json(path, data)
    transcript_path = directory / "transcript.json"
    if transcript_path.exists():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        transcript["metadata"] = data["metadata"]
        atomic_json(transcript_path, transcript)
        from voiceloop.transcript_html import save_html

        save_html(directory)
