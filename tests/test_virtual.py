import json

import pytest

from voiceloop import virtual


def prepare(monkeypatch, existing, fail_at=None):
    calls = []
    monkeypatch.setattr(virtual.sys, "platform", "linux")
    monkeypatch.setattr(virtual.shutil, "which", lambda _: "/usr/bin/pactl")

    def pactl(*args):
        calls.append(args)
        if args[0] == "--format=json":
            return json.dumps(existing)
        if args[0] == "load-module":
            if len([c for c in calls if c[0] == "load-module"]) == fail_at:
                raise RuntimeError("server failure")
            return str(len(calls))
        return ""

    monkeypatch.setattr(virtual, "_pactl", pactl)
    return calls


def test_virtual_setup_creates_three_modules(monkeypatch):
    calls = prepare(monkeypatch, [])
    assert len(virtual.ensure_linux_devices()) == 3
    assert len([c for c in calls if c[0] == "load-module"]) == 3


def test_virtual_setup_is_idempotent(monkeypatch):
    existing = [{"name": m[0], "argument": " ".join(m[1:])} for m in virtual.MODULES]
    calls = prepare(monkeypatch, existing)
    assert virtual.ensure_linux_devices() == []
    assert len(calls) == 1


def test_partial_failure_rolls_back_only_new_modules_in_reverse(monkeypatch):
    calls = prepare(monkeypatch, [], fail_at=3)
    with pytest.raises(RuntimeError, match="server failure"):
        virtual.ensure_linux_devices()
    assert calls[-2:] == [("unload-module", "3"), ("unload-module", "2")]


def test_setup_on_unsupported_platform_is_clear(monkeypatch):
    monkeypatch.setattr(virtual.sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="requires Linux"):
        virtual.ensure_linux_devices()
