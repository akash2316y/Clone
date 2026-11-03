"""Encrypt bot tokens / API keys before they go into MongoDB."""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from config import CLONE_ENCRYPTION_KEY, TG_BOT_TOKEN

_fernet = None


def _get() -> Fernet:
    global _fernet
    if _fernet is None:
        raw = CLONE_ENCRYPTION_KEY
        try:
            _fernet = Fernet(raw.encode())
        except Exception:
            if raw:
                logging.warning("CLONE_ENCRYPTION_KEY is not a valid Fernet key; deriving one from it.")
            else:
                logging.warning(
                    "CLONE_ENCRYPTION_KEY not set; deriving a key from TG_BOT_TOKEN. "
                    "Set CLONE_ENCRYPTION_KEY, or clone tokens become unreadable if the main token changes."
                )
            digest = hashlib.sha256((raw or TG_BOT_TOKEN).encode()).digest()
            _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def enc(value: str) -> str:
    return _get().encrypt(value.encode()).decode() if value else ""


def dec(value: str) -> str:
    if not value:
        return ""
    try:
        return _get().decrypt(value.encode()).decode()
    except InvalidToken:
        logging.error("Could not decrypt a stored secret (encryption key changed?)")
        return ""
