"""Admin log (system-wide) and user log (per clone) helpers. Always best-effort."""
import logging
from typing import Optional

from config import ADMIN_LOG_CHANNEL

_main = None


def set_main(client):
    global _main
    _main = client


async def admin_log(text: str):
    """System-wide events go to ADMIN_LOG_CHANNEL, sent by the MAIN bot."""
    if not _main or not ADMIN_LOG_CHANNEL:
        return
    try:
        await _main.send_message(ADMIN_LOG_CHANNEL, text, disable_web_page_preview=True)
    except Exception as e:
        logging.warning(f"admin_log failed: {e}")


async def user_log(client, clone: dict, text: str):
    """Per-clone log channel chosen by the clone owner (sent by the clone bot)."""
    ch: Optional[int] = (clone.get("settings") or {}).get("user_log_channel")
    if not ch:
        return
    try:
        await client.send_message(ch, text, disable_web_page_preview=True)
    except Exception as e:
        logging.warning(f"user_log failed for clone {clone.get('_id')}: {e}")
