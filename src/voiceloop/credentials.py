"""OpenAI credentials stay in the operating system credential store."""

import os
import sys

SERVICE = "VoiceLoop"
ACCOUNT = "OpenAI API key"


def _backend():
    # Explicit backends prevent a third-party plaintext fallback being selected.
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring

        return Keyring()
    from keyring.backends.SecretService import Keyring

    return Keyring()


def normalize_key(value: str) -> str:
    value = value.strip().replace("\\_", "_")
    if not value or any(c.isspace() for c in value):
        raise ValueError("Enter a valid API key without spaces.")
    return value


def get_key() -> str:
    environment = os.environ.get("OPENAI_API_KEY", "")
    if environment:
        return normalize_key(environment)
    try:
        return _backend().get_password(SERVICE, ACCOUNT) or ""
    except Exception as exc:
        raise RuntimeError(
            "Cannot unlock the system credential store. "
            "Unlock it or use OPENAI_API_KEY for this launch."
        ) from exc


def save_key(value: str) -> None:
    value = normalize_key(value)
    try:
        _backend().set_password(SERVICE, ACCOUNT, value)
    except Exception as exc:
        raise RuntimeError(
            "Could not save the key in the system credential store. No plaintext copy was saved."
        ) from exc


def delete_key() -> None:
    try:
        backend = _backend()
        if backend.get_password(SERVICE, ACCOUNT):
            backend.delete_password(SERVICE, ACCOUNT)
    except Exception as exc:
        raise RuntimeError(
            "Could not remove the stored key. Unlock your credential store."
        ) from exc
