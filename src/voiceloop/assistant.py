"""Local AI call coordinator: policy, scheduling, audio ownership and delivery."""

import copy
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from voiceloop.assistant_config import AssistantSettings
from voiceloop.assistant_store import TERMINAL, AssistantStore
from voiceloop.config import atomic_json, data_directory
from voiceloop.credentials import get_key


def utc_now():
    return datetime.now(UTC)


class AssistantService:
    def __init__(
        self,
        *,
        bridge_provider,
        audio_factory,
        audio_busy=lambda: False,
        audio_ready=lambda: True,
        config=None,
        directory=None,
        recordings=None,
        key_provider=get_key,
        worker_factory=None,
        summary_factory=None,
        now=utc_now,
    ):
        self.directory = Path(directory or data_directory())
        self.config_path = self.directory / "assistant.json"
        self.config = config or AssistantSettings.load(self.config_path)
        self.store = AssistantStore(self.directory / "assistant-jobs.sqlite3")
        self.recordings = recordings or (lambda: self.directory / "recordings")
        self.bridge_provider, self.audio_factory = bridge_provider, audio_factory
        self.audio_busy, self.key_provider = audio_busy, key_provider
        self.audio_ready = audio_ready
        self.worker_factory, self.summary_factory = worker_factory, summary_factory
        self.now = now
        self.lock = threading.RLock()
        self.runtime_enabled = False
        self.worker = None
        self.active_id = ""
        self.deadline = 0.0
        self.last_seen = 0.0
        self._seen_calls = set()
        self._live_calls = {}
        self._ended_calls = set()
        self._summaries = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voiceloop-summary")
        self._closed = False
        self._shutting_down = False
        self._shutdown_jobs = set()
        self.status = "AI Assistant is off"

    @property
    def active(self):
        return bool(self.active_id)

    def save_config(self, config):
        with self.lock:
            config.save(self.config_path)
            self.config = copy.deepcopy(config)
            if self.active_id and not config.enabled:
                self.cancel(self.active_id)
            if not config.enabled or not config.busy_fallback_enabled:
                for job in self.store.list():
                    if (
                        job.get("delivery_kind") == "busy_fallback"
                        and job.get("delivery_status") == "sending"
                    ):
                        try:
                            outcome = self._bridge().cancel_command(job["summary_command_id"])
                            job["delivery_status"] = (
                                "disabled" if outcome == "cancelled" else "ambiguous"
                            )
                        except (ValueError, RuntimeError, OSError):
                            job["delivery_status"] = "ambiguous"
                        self.store.put(job)

    def _bridge(self):
        bridge = self.bridge_provider()
        if bridge is None or not getattr(bridge, "is_running", False):
            raise ValueError("Enable browser detection and pair the Chrome extension first.")
        return bridge

    def _profile(self):
        profiles = self._bridge().profiles()
        profiles = [p for p in profiles if "call-control-v1" in p.get("capabilities", [])]
        configured = self.config.profile_id
        if configured:
            if any(p["profile_id"] == configured for p in profiles):
                return configured
            raise ValueError("The selected Chrome profile is offline. Open Cliq in that profile.")
        if len(profiles) != 1:
            raise ValueError("Select one paired Chrome profile in AI Assistant settings.")
        return profiles[0]["profile_id"]

    def _target(self, target_id):
        matches = [t for t in self.config.targets if t.id == target_id or t.chat_id == target_id]
        if len(matches) != 1:
            raise ValueError("Choose exactly one configured chat or meeting.")
        return matches[0]

    def _permit(self, target, direction="outgoing"):
        if self._shutting_down:
            raise ValueError("Voice Loop is shutting down.")
        if not self.config.enabled:
            raise ValueError("Enable AI Assistant first.")
        if not target.enabled or target.provider not in self.config.platforms:
            raise ValueError("AI Assistant is disabled for this platform or chat.")
        if not getattr(target, "allow_" + direction):
            raise ValueError("This chat does not allow " + direction + " AI calls.")
        if not self.config.permits(self.now()):
            raise ValueError("The configured availability policy does not allow calls now.")

    def _outgoing_target(self, value, contact_name=""):
        if not isinstance(value, str) or not isinstance(contact_name, str):
            raise ValueError("Enter a chat ID or link and a contact name.")
        value = value.strip()
        existing = self.config.target(value)
        if existing:
            return existing, None
        if not re.fullmatch(r"[0-9]{1,40}", value) and "://" not in value:
            return self.config.resolve_recipient(value), None
        config = copy.deepcopy(self.config)
        target = config.make_cliq_target(contact_name.strip() or "Cliq contact", value)
        existing = config.target(target.id)
        if existing:
            if existing.url != target.url:
                raise ValueError("This chat ID is already configured for another company.")
            return existing, None
        config.targets.append(target)
        config.validate()
        return target, config

    def _new_job(self, target, objective, *, when=None, event=None, new_config=None):
        if self._shutting_down:
            raise ValueError("Voice Loop is shutting down.")
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 4000:
            raise ValueError("Enter a call objective of 1–4,000 characters.")
        jobs = self.store.list()
        if sum(j["state"] not in TERMINAL for j in jobs) >= 100:
            raise ValueError("Too many pending calls. Cancel an existing job first.")
        job = {
            "id": str(uuid.uuid4()),
            "target_id": target.id,
            "target_name": target.name,
            "chat_id": target.chat_id,
            "chat_url": target.url,
            "provider": target.provider,
            "profile_id": event.profile_id if event else self._profile(),
            "objective": objective.strip(),
            "state": "scheduled" if when else "queued",
            "created_at": self.now().isoformat(),
            "scheduled_at": (when or self.now()).isoformat(),
            "started_at": "",
            "ended_at": "",
            "direction": event.direction if event else "outgoing",
            "call_id": event.call_id if event else "",
            "participant_id": getattr(event, "participant_id", "") if event else "",
            "command_id": "",
            "action": "answer"
            if event and event.state == "ringing"
            else "assist"
            if event
            else "call",
            "transcript": [],
            "summary": "",
            "error": "",
            "delivery_status": "not_requested",
        }
        if new_config is not None:
            self.save_config(new_config)
        self.store.put(job)
        return job

    def trigger(self, target_id, objective, *, contact_name=""):
        with self.lock:
            if not self.runtime_enabled:
                raise ValueError("Open the Voice Loop desktop app first.")
            target, new_config = self._outgoing_target(target_id, contact_name)
            self._permit(target)
            if target.provider != "zoho_cliq":
                raise ValueError(
                    "Join the configured Google Meet first; instant dialing uses Cliq."
                )
            if (
                self.active
                or self.audio_busy()
                or any(j["state"] == "queued" for j in self.store.list())
            ):
                raise ValueError("Finish the current audio session or AI call first.")
            return self._new_job(target, objective, new_config=new_config)

    def schedule(self, target_id, objective, when, *, contact_name=""):
        with self.lock:
            if not isinstance(when, datetime) or when.tzinfo is None:
                raise ValueError("Schedule must include a timezone.")
            if not 0 < (when - self.now()).total_seconds() <= 366 * 86400:
                raise ValueError("Choose a future time within one year.")
            target, new_config = self._outgoing_target(target_id, contact_name)
            if not self.config.enabled or not target.enabled or not target.allow_outgoing:
                raise ValueError("Enable the assistant and outgoing calls for this chat first.")
            if target.provider != "zoho_cliq":
                raise ValueError("Scheduled outgoing calls currently use Zoho Cliq.")
            if target.provider not in self.config.platforms or not self.config.permits(when):
                raise ValueError(
                    "The platform or availability policy does not allow this scheduled call."
                )
            return self._new_job(
                target, objective, when=when.astimezone(UTC), new_config=new_config
            )

    def cancel(self, job_id):
        with self.lock:
            job = self.store.get(job_id)
            if job["state"] in TERMINAL:
                return
            if job_id == self.active_id:
                if self.worker:
                    self.worker.stop()
                self._hangup(job)
                if job.get("command_id"):
                    try:
                        outcome = self._bridge().cancel_command(job["command_id"])
                        job["command_cancelled_before_delivery"] = outcome == "cancelled"
                    except (ValueError, RuntimeError, OSError):
                        job["error"] = "Browser offline; check whether the call needs ending."
            job.update(state="cancelled", ended_at=self.now().isoformat())
            self.store.put(job)

    def _hangup(self, job):
        if not job.get("call_id") or job.get("hangup_command_id") or job.get("browser_ended"):
            return
        try:
            target = (
                {"chat_id": job["chat_id"], "chat_url": job["chat_url"]}
                if job["provider"] == "zoho_cliq"
                else {}
            )
            job["hangup_command_id"] = self._bridge().submit_command(
                "hangup",
                profile_id=job["profile_id"],
                call_id=job["call_id"],
                **target,
            )
        except (ValueError, RuntimeError, OSError):
            job["error"] = "Could not confirm hangup. End the call in Chrome."

    @staticmethod
    def _event_matches_job(event, job):
        # Command correlation discovers the initial call; it must never replace
        # an established identity with a later call from the same command.
        return (
            event.profile_id == job["profile_id"]
            and event.provider == job["provider"]
            and (not event.chat_url or event.chat_url.rstrip("/") == job["chat_url"].rstrip("/"))
            and (
                event.call_id == job["call_id"]
                if job["call_id"]
                else bool(job["command_id"]) and event.command_id == job["command_id"]
            )
        )

    def _browser_unpaired(self, event):
        """Loss of extension control does not prove that the remote call ended."""
        matched = False
        for job in self.store.list():
            if not self._event_matches_job(event, job):
                continue
            matched = True
            job["call_id"] = event.call_id
            job["browser_state"] = "disconnected"
            self._record_browser_event(job, event)
            job["browser_disconnected"] = True
            job["error"] = "Browser extension disconnected. Check and end the call in Chrome."
            if job["state"] not in TERMINAL:
                job["state"] = "failed"
            if job["id"] == self.active_id and self.worker:
                self.worker.stop()
            future = self._summaries.pop(job["id"], None)
            if future:
                future.cancel()
            if job.get("delivery_status") == "sending" and job.get("summary_command_id"):
                try:
                    outcome = self._bridge().cancel_command(job["summary_command_id"])
                    job["delivery_status"] = "disabled" if outcome == "cancelled" else "ambiguous"
                except (ValueError, RuntimeError, OSError):
                    job["delivery_status"] = "ambiguous"
            elif job.get("delivery_status") != "sent":
                job["delivery_status"] = "disabled"
            self.store.put(job)
        return matched

    def handle_event(self, event):
        with self.lock:
            if event.state == "ended" and event.event_id.startswith("unpaired-"):
                return self._browser_unpaired(event)
            identity = (event.profile_id, event.provider, event.call_id)
            if event.state == "ended":
                self._live_calls.pop(identity, None)
                if len(self._ended_calls) > 1000:
                    self._ended_calls.clear()
                self._ended_calls.add(identity)
                for old in self.store.list():
                    if (old["profile_id"], old["provider"], old["call_id"]) == identity:
                        old["browser_ended"] = True
                        self.store.put(old)
            else:
                self._live_calls[identity] = time.monotonic()
            if self.active_id:
                job = self.store.get(self.active_id)
                own = (job["profile_id"], job["provider"], job["call_id"])
                if job["state"] == "active" and event.state != "ended" and identity != own:
                    # Virtual cables are shared endpoints. Stop before another
                    # call can receive this assistant's objective or voice.
                    job["error"] = "Another browser call started; assistant audio was stopped."
                    self._hangup(job)
                    self.worker.stop()
                    self.store.put(job)
            if self._cleanup_terminal_event(event):
                return True
            if self.active_id:
                job = self.store.get(self.active_id)
                if self._event_matches_job(event, job):
                    job["call_id"] = event.call_id
                    job["browser_state"] = event.state
                    self._record_browser_event(job, event)
                    participant = getattr(event, "participant_id", "")
                    if participant:
                        job["participant_id"] = participant
                        if (
                            job["action"] == "call"
                            and event.state == "connected"
                            and event.direction == "outgoing"
                            and event.chat_url == job["chat_url"]
                        ):
                            scope = job["profile_id"] + "|" + urlsplit(job["chat_url"]).netloc
                            self.store.learn(scope, participant, job["chat_url"])
                    self.last_seen = time.monotonic()
                    self._seen_calls.add(identity)
                    if event.state == "ended":
                        job["browser_ended"] = True
                        if self.worker:
                            self.worker.stop()
                    elif event.state == "connected":
                        job["connected"] = True
                        if job["state"] == "waiting":
                            try:
                                self._validate_job(job)
                                self.worker.activate()
                                job.update(state="active", started_at=self.now().isoformat())
                            except (ValueError, RuntimeError, OSError) as exc:
                                job["error"] = str(exc)
                                self._hangup(job)
                                self.worker.stop()
                    self.store.put(job)
                    return True
            if identity in self._seen_calls:
                return True
            if (
                not self.runtime_enabled
                or self._shutting_down
                or self.active
                or self.audio_busy()
                or not event.profile_id
            ):
                return False

            incoming = event.state == "ringing" and event.direction == "incoming"
            joined = event.state == "connected" and event.provider == "google_meet"
            outgoing = event.state == "connected" and event.direction == "outgoing"
            if not (
                (incoming and self.config.auto_answer)
                or (joined and self.config.auto_assist_meet)
                or (outgoing and self.config.auto_assist_outgoing)
            ):
                return False
            resolved_url = self.event_chat_url(event)
            matches = [
                t for t in self.config.targets if t.url.rstrip("/") == resolved_url.rstrip("/")
            ]
            if len(matches) != 1:
                return False
            try:
                if self._profile() != event.profile_id:
                    return False
                self._permit(matches[0], "incoming" if incoming else "outgoing")
                job = self._new_job(matches[0], self.config.default_objective, event=event)
                job["connected"] = event.state == "connected"
                self.store.put(job)
                self._seen_calls.add(identity)
                self._prepare(job)
                return True
            except (ValueError, RuntimeError, OSError) as exc:
                self.status = str(exc)
                return False

    def _cleanup_terminal_event(self, event):
        """End a cancelled leased action even if its call identity arrives late."""
        for job in self.store.list():
            if job["state"] not in TERMINAL or not job.get("command_id"):
                continue
            if not self._event_matches_job(event, job):
                continue
            job["call_id"] = event.call_id
            job["browser_state"] = event.state
            self._record_browser_event(job, event)
            self._seen_calls.add((event.profile_id, event.provider, event.call_id))
            if event.state == "ended":
                job["browser_ended"] = True
            else:
                self._hangup(job)
            self.store.put(job)
            return True
        return False

    @staticmethod
    def _record_browser_event(job, event):
        # Keep a small identifier-free lifecycle trace. In particular, a native
        # ID replacement and an explicit remote end must remain distinguishable.
        reasons = (
            "native-handoff",
            "native-replaced",
            "ui-ended",
            "ui-absent",
            "pagehide",
            "tab-closed",
            "unpaired",
        )
        reason = next((value for value in reasons if event.event_id.startswith(value + "-")), "")
        entry = {"state": event.state, "reason": reason}
        history = job.setdefault("browser_events", [])
        if not history or any(history[-1].get(key) != value for key, value in entry.items()):
            history.append({**entry, "timestamp": event.timestamp})
            del history[:-32]
        if event.state == "ended":
            job["browser_end_reason"] = reason or "browser-ended"

    def event_chat_url(self, event):
        if event.chat_url:
            return event.chat_url
        if getattr(event, "participant_id", ""):
            scope = event.profile_id + "|" + urlsplit(event.url).netloc
            return self.store.resolve(scope, event.participant_id)
        return event.url if event.provider == "google_meet" else ""

    def recording_transcribed(self, directory):
        """Opted-in Automation consumes already transcribed browser recordings only."""
        with self.lock:
            if not self.config.automation_enabled or not self.runtime_enabled:
                return
            try:
                directory = Path(directory).resolve()
                info = json.loads((directory / "session.json").read_text(encoding="utf-8"))
                if not isinstance(info, dict):
                    return
                metadata = info.get("metadata", {})
                if not isinstance(metadata, dict):
                    return
                chat_url = metadata.get("browser_chat_url", "")
                profile = metadata.get("browser_profile_id", "")
                call_id = metadata.get("browser_call_id", "")
                if not all((chat_url, profile, call_id)):
                    return
                targets = [
                    t
                    for t in self.config.targets
                    if t.url == chat_url
                    and t.provider == "zoho_cliq"
                    and t.enabled
                    and t.send_summary
                ]
                if len(targets) != 1 or profile != self._profile():
                    return
                if metadata.get("browser_chat_id") not in (None, "", targets[0].chat_id):
                    return
                job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(directory)))
                if any(j["id"] == job_id for j in self.store.list()):
                    return
                data = json.loads((directory / "transcript.json").read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
                    return
                turns = [
                    {"role": "user", "text": str(s.get("speaker") or "Speaker") + ": " + s["text"]}
                    for s in data.get("segments", [])
                    if isinstance(s, dict) and isinstance(s.get("text"), str)
                ]
                if not turns:
                    return
                target = targets[0]
                job = {
                    "id": job_id,
                    "target_id": target.id,
                    "target_name": target.name,
                    "profile_id": profile,
                    "provider": "zoho_cliq",
                    "call_id": call_id,
                    "chat_id": target.chat_id,
                    "chat_url": chat_url,
                    "state": "completed",
                    "created_at": self.now().isoformat(),
                    "started_at": info.get("started_at", ""),
                    "ended_at": self.now().isoformat(),
                    "scheduled_at": "",
                    "objective": "Summarize the recorded call faithfully.",
                    "summary": "",
                    "transcript": turns,
                    "error": "",
                    "delivery_status": "not_requested",
                    "recording_path": str(directory),
                    "browser_ended": (profile, "zoho_cliq", call_id) in self._ended_calls,
                }
                # Recording must be closed, and no current call with this identity may exist.
                if info.get("status") != "complete":
                    return
                self.store.put(job)
                self._start_summary(job)
            except (ValueError, RuntimeError, OSError, TypeError):
                self.status = "Automation could not read this recording or verify its chat."

    def _prepare(self, job):
        from voiceloop.realtime import RealtimeConfig, RealtimeWorker

        try:
            self._validate_job(job)
            if self.audio_busy():
                raise ValueError("Another audio session is active.")
            own = (job["profile_id"], job["provider"], job["call_id"])
            if any(
                identity != own and time.monotonic() - stamp < 50
                for identity, stamp in self._live_calls.items()
            ):
                raise ValueError("Another browser call is active. Finish it first.")
            key = self.key_provider()
            if not key:
                raise ValueError("Add your OpenAI API key in Preferences first.")
            audio = self.audio_factory()
            config = RealtimeConfig(
                model=self.config.model,
                voice=self.config.voice,
                language=self.config.language,
                instructions=self.config.system_instructions,
                objective=job["objective"],
                max_duration_seconds=self.config.max_duration_seconds,
            )
            self.worker = (self.worker_factory or RealtimeWorker)(key, config, audio)
            self.active_id = job["id"]
            job["state"] = "preparing"
            self.store.put(job)
            self.deadline = time.monotonic() + 35
            self.last_seen = time.monotonic()
            self.worker.start()
        except (ValueError, RuntimeError, OSError) as exc:
            job.update(state="failed", error=str(exc), ended_at=self.now().isoformat())
            self.store.put(job)
            self.status = str(exc)
            if self.worker:
                self.worker.stop()
            self.active_id, self.worker = "", None
        except Exception:
            # A failed preflight must never stay queued and repeat on every UI tick.
            # Unexpected exception text may contain SDK or credential details.
            message = (
                "Assistant preparation failed before dialing. Check audio setup and try again."
            )
            job.update(state="failed", error=message, ended_at=self.now().isoformat())
            self.store.put(job)
            self.status = message
            if self.worker:
                self.worker.stop()
            self.active_id, self.worker = "", None

    def _validate_job(self, job):
        target = self._target(job["target_id"])
        self._permit(target, "incoming" if job["action"] == "answer" else "outgoing")
        if job["profile_id"] != self._profile() or target.url != job["chat_url"]:
            raise ValueError("Call target or Chrome profile changed; create a new call.")
        if job["action"] == "answer" and not self.config.auto_answer:
            raise ValueError("Automatic answering was disabled.")
        if job["action"] == "assist":
            allowed = (
                self.config.auto_assist_meet
                if job["provider"] == "google_meet"
                else self.config.auto_assist_outgoing
            )
            if not allowed:
                raise ValueError("Automatic call assistance was disabled.")
        if self.audio_busy():
            raise ValueError("Another audio session is active.")
        own = (job["profile_id"], job["provider"], job["call_id"])
        if any(
            identity != own and time.monotonic() - stamp < 50
            for identity, stamp in self._live_calls.items()
        ):
            raise ValueError("Another browser call is active. Finish it first.")

    def tick(self):
        with self.lock:
            if self._closed or not self.runtime_enabled:
                return
            bridge = self.bridge_provider()
            if bridge and hasattr(bridge, "drain_results"):
                for result in bridge.drain_results():
                    self._command_result(result)
            if self.active_id:
                job = self.store.get(self.active_id)
                for event in self.worker.drain_events():
                    if event["type"] == "ready" and job["state"] == "preparing":
                        try:
                            self._validate_job(job)
                            if job.get("browser_ended"):
                                self.worker.stop()
                            elif job["action"] == "assist" or job.get("connected"):
                                self.worker.activate()
                                job.update(state="active", started_at=self.now().isoformat())
                            else:
                                job["command_id"] = str(uuid.uuid4())
                                job["state"] = "waiting"
                                job["busy_fallback_requested"] = (
                                    job["action"] == "call" and self.config.busy_fallback_enabled
                                )
                                self.store.put(job)  # Journal intention before browser side effect.
                                self._bridge().submit_command(
                                    job["action"],
                                    profile_id=job["profile_id"],
                                    chat_id=job["chat_id"],
                                    chat_url=job["chat_url"],
                                    call_id=job["call_id"],
                                    participant_id=job.get("participant_id", ""),
                                    command_id=job["command_id"],
                                    ttl=30,
                                    busy_fallback=job["busy_fallback_requested"],
                                )
                                self.deadline = time.monotonic() + 60
                        except (ValueError, RuntimeError, OSError) as exc:
                            job["error"] = str(exc)
                            self.worker.stop()
                    elif event["type"] == "transcript":
                        pass  # Final ordered transcript comes from result.
                    elif event["type"] == "completed":
                        self._finish(job)
                        break
                    self.store.put(job)
                if self.active_id:
                    job = self.store.get(self.active_id)
                    expired = (
                        job["state"] in {"preparing", "waiting"}
                        and time.monotonic() > self.deadline
                    )
                    lost = job["state"] == "active" and time.monotonic() - self.last_seen > 45
                    if (
                        expired
                        or lost
                        or not self.config.enabled
                        or not getattr(bridge, "is_running", False)
                    ):
                        if not job.get("error"):
                            if not self.config.enabled:
                                job["error"] = "AI Assistant was disabled during the call."
                            elif not getattr(bridge, "is_running", False):
                                job["error"] = "Browser bridge stopped during the call."
                            elif lost:
                                job["error"] = "Browser call updates stopped for 45 seconds."
                            elif job["state"] == "preparing":
                                job["error"] = "Assistant audio preparation timed out."
                            else:
                                job["error"] = (
                                    "Call connection was not confirmed within 60 seconds."
                                )
                        self._hangup(job)
                        self.store.put(job)
                        self.worker.stop()
            self._tick_summaries()
            if not self.active and not self._shutting_down:
                pending = sorted(
                    (j for j in self.store.list() if j["state"] in {"queued", "scheduled"}),
                    key=lambda j: j["scheduled_at"],
                )
                for job in pending:
                    age = (self.now() - datetime.fromisoformat(job["scheduled_at"])).total_seconds()
                    if age < 0:
                        continue
                    if age > 120:
                        job.update(state="expired", error="Missed schedule. No late call was made.")
                        self.store.put(job)
                        continue
                    self._prepare(job)
                    break
            self.status = (
                "AI Assistant · " + self.store.get(self.active_id)["state"]
                if self.active_id
                else "Ready"
                if self.config.enabled
                else "AI Assistant is off"
            )

    def _finish(self, job, *, summarize=True):
        result = self.worker.result or {}
        job["transcript"] = result.get("transcript", [])
        job["result"] = result
        job["error"] = job["error"] or result.get("error", "")
        if job["state"] not in TERMINAL:
            if not job.get("started_at") and not job["error"]:
                job["error"] = "Call ended before the assistant could connect."
            job["state"] = "failed" if job["error"] else "completed"
        job["ended_at"] = self.now().isoformat()
        self._hangup(job)
        self.store.put(job)
        self._export(job)
        self.worker, self.active_id = None, ""
        if summarize and job["transcript"] and job.get("delivery_kind") != "busy_fallback":
            self._start_summary(job)

    def _export(self, job):
        try:
            from voiceloop.assistant_ui import render_assistant_job

            directory = Path(self.recordings()) / "AI Assistant" / job["id"]
            atomic_json(directory / "transcript.json", job)
            (directory / "transcript.html").write_text(render_assistant_job(job), encoding="utf-8")
            job["transcript_path"] = str(directory / "transcript.json")
            self.store.put(job)
        except OSError:
            job["error"] = "Transcript is in local history; could not export to the storage folder."
            self.store.put(job)

    def _start_summary(self, job):
        from voiceloop.realtime import summarize_call

        if self._shutting_down or job.get("browser_disconnected"):
            return
        try:
            target = self._target(job["target_id"])
            if not (
                self.config.automation_enabled
                and target.enabled
                and target.send_summary
                and target.provider == "zoho_cliq"
            ):
                return
            job["delivery_status"] = "generating"
            self.store.put(job)
            self._summaries[job["id"]] = self._pool.submit(
                self.summary_factory or summarize_call,
                self.key_provider(),
                job["transcript"],
                job["objective"],
                model=self.config.summary_model,
                instructions=self.config.summary_instructions,
            )
        except (ValueError, RuntimeError, OSError):
            job["delivery_status"] = "failed"
            self.store.put(job)

    def _tick_summaries(self):
        if self._shutting_down:
            return
        for job_id, future in list(self._summaries.items()):
            if not future.done():
                continue
            job = self.store.get(job_id)
            if job.get("call_id") and not job.get("browser_ended"):
                if (self.now() - datetime.fromisoformat(job["ended_at"])).total_seconds() < 60:
                    continue
                job["delivery_status"] = "failed"
                job["error"] = "Summary held because the browser did not confirm call ended."
                self.store.put(job)
                del self._summaries[job_id]
                continue
            del self._summaries[job_id]
            try:
                job["summary"] = future.result()
                target = self._target(job["target_id"])
                if not (
                    self.config.automation_enabled
                    and target.enabled
                    and target.send_summary
                    and target.url == job["chat_url"]
                    and self._profile() == job["profile_id"]
                ):
                    job["delivery_status"] = "disabled"
                else:
                    job["delivery_status"] = "sending"
                    job["summary_command_id"] = str(uuid.uuid4())
                    self.store.put(job)
                    self._bridge().submit_command(
                        "send_summary",
                        profile_id=job["profile_id"],
                        chat_id=job["chat_id"],
                        chat_url=job["chat_url"],
                        text="Voice Loop · Call summary\n" + job["summary"],
                        command_id=job["summary_command_id"],
                        ttl=60,
                    )
            except Exception:
                job["delivery_status"] = "failed"
                job["error"] = "Summary could not be delivered. It was not retried automatically."
            self.store.put(job)
            self._export(job)

    def _send_busy_fallback(self, job):
        """Send once, only after an owned call command confirms a busy recipient."""
        job.update(
            state="failed",
            browser_ended=True,
            ended_at=self.now().isoformat(),
            delivery_kind="busy_fallback",
            fallback_text=job["objective"],
            fallback_reason="Cliq confirmed the recipient is busy or on another call.",
            delivery_status="disabled",
        )
        try:
            target = self._target(job["target_id"])
            self._permit(target)
            if (
                not self.config.busy_fallback_enabled
                or target.url != job["chat_url"]
                or self._profile() != job["profile_id"]
            ):
                self.store.put(job)
                return
            job["summary_command_id"] = str(uuid.uuid4())
            job["delivery_status"] = "sending"
            self.store.put(job)  # Persist before the external message action.
            self._bridge().submit_command(
                "send_summary",
                profile_id=job["profile_id"],
                chat_id=job["chat_id"],
                chat_url=job["chat_url"],
                text=job["fallback_text"],
                command_id=job["summary_command_id"],
                ttl=60,
            )
        except (ValueError, RuntimeError, OSError):
            if job["delivery_status"] == "sending":
                job["delivery_status"] = "ambiguous"
            job["fallback_reason"] = "Busy fallback could not be confirmed; it was not retried."
        self.store.put(job)

    def _command_result(self, result):
        for job in self.store.list():
            if result["command_id"] == job.get("hangup_command_id"):
                if result["status"] == "succeeded":
                    job["browser_ended"] = True
                    self._live_calls.pop((job["profile_id"], job["provider"], job["call_id"]), None)
                else:
                    job["error"] = "Hangup was not confirmed. Check the call in Chrome."
                self.store.put(job)
                return
            if result["command_id"] == job.get("summary_command_id"):
                job["delivery_status"] = (
                    "sent" if result["status"] == "succeeded" else result["status"]
                )
                self.store.put(job)
                self._export(job)
                return
            if result["command_id"] == job.get("command_id"):
                job["command_result_status"] = result["status"]
                if (
                    result.get("code") == "recipient_busy"
                    and result["status"] == "failed"
                    and job["state"] == "waiting"
                    and job["action"] == "call"
                    and job.get("busy_fallback_requested")
                    and not job.get("call_id")
                    and not result.get("call_id")
                    and not job.get("connected")
                    and job["id"] == self.active_id
                ):
                    job["error"] = "The recipient is busy; the call was not connected."
                    self.worker.stop()
                    self._send_busy_fallback(job)
                    return
                if result.get("call_id"):
                    if job.get("call_id") and job["call_id"] != result["call_id"]:
                        # A late result cannot replace a previously observed
                        # call identity and cause a different call to be ended.
                        job["error"] = "Browser result did not match the known call. Check Chrome."
                        if job["id"] == self.active_id:
                            self.worker.stop()
                        self.store.put(job)
                        return
                    job["call_id"] = result["call_id"]
                if job["state"] in TERMINAL and job.get("call_id"):
                    self._hangup(job)
                if result["status"] != "succeeded":
                    job["error"] = result.get("detail") or "Browser could not complete the action."
                    if job["id"] == self.active_id:
                        self.worker.stop()
                self.store.put(job)
                return

    def list_jobs(self, kind=None, query="", page=1, page_size=20):
        """Search and page through the complete local job history."""
        with self.lock:
            return self.store.page(kind=kind, query=query, page=page, page_size=page_size)

    def snapshot(self):
        with self.lock:
            profiles = []
            try:
                profiles = self._bridge().profiles()
            except (ValueError, RuntimeError, OSError):
                pass
            try:
                key = bool(self.key_provider())
            except RuntimeError:
                key = False
            jobs = sorted(self.store.list(), key=lambda j: j["created_at"], reverse=True)
            return {
                "status": self.status,
                "active_id": self.active_id,
                "prerequisites": {
                    "browser": bool(profiles),
                    "key": key,
                    "audio": self.audio_ready() and not self.audio_busy(),
                },
                "profiles": profiles,
                "jobs": jobs[:200],
            }

    def begin_shutdown(self):
        """Stop new work while the UI drains final transcripts and owned hangups."""
        with self.lock:
            if self._closed or self._shutting_down:
                return
            self._shutting_down = True
            for job in self.store.list():
                if job["id"] == self.active_id:
                    self._shutdown_jobs.add(job["id"])
                    self.cancel(job["id"])
                elif not job.get("browser_ended") and (
                    job.get("command_id") or job.get("hangup_command_id")
                ):
                    stamp = job.get("ended_at") or job.get("created_at")
                    if stamp and (self.now() - datetime.fromisoformat(stamp)).total_seconds() < 120:
                        self._shutdown_jobs.add(job["id"])
                if job.get("delivery_status") == "sending" and job.get("summary_command_id"):
                    try:
                        outcome = self._bridge().cancel_command(job["summary_command_id"])
                        job["delivery_status"] = (
                            "disabled" if outcome == "cancelled" else "ambiguous"
                        )
                    except (ValueError, RuntimeError, OSError):
                        job["delivery_status"] = "ambiguous"
                    self.store.put(job)
            self.status = "AI Assistant is shutting down"

    def shutdown_ready(self):
        with self.lock:
            if self._closed:
                return True
            if self.active:
                return False
            for job_id in self._shutdown_jobs:
                job = self.store.get(job_id)
                if job.get("browser_ended"):
                    continue
                if job.get("call_id") or job.get("hangup_command_id"):
                    return False
                if job.get("command_id") and not (
                    job.get("command_cancelled_before_delivery")
                    or job.get("command_result_status") == "failed"
                ):
                    return False
            return True

    def close(self, timeout=3):
        with self.lock:
            if self._closed:
                return
            self.begin_shutdown()
            self._closed = True
            self.runtime_enabled = False
            self._pool.shutdown(wait=False, cancel_futures=True)
            # Worker only uses audio/SDK, not this journal. Close after bounded cancellation.
            if self.worker:
                self.worker.join(timeout)
                if self.worker.result is not None and self.active_id:
                    self._finish(self.store.get(self.active_id), summarize=False)
            self.store.close()
