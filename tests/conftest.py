"""Keep desktop unit tests away from the user's assistant settings and call journal."""

import pytest


@pytest.fixture(autouse=True)
def isolated_assistant_data(tmp_path, monkeypatch):
    monkeypatch.setattr("voiceloop.assistant.data_directory", lambda: tmp_path / "assistant-app")
