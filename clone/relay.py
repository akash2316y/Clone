"""
Serves files from the owner's central channel through a clone bot.

A clone is a different bot, so it cannot read OWNER_DB_CHANNEL and Telegram file_ids are
bot-specific. First time a file is requested through a clone, the MAIN bot downloads it, the
CLONE uploads it, and the clone's own file_id is cached. Every later request is an instant resend.
"""
import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from collections import defaultdict
from typing import List, Optional, Tuple

from config import OWNER_DB_CHANNEL

MEDIA_TYPES = ("video", "document", "audio", "photo", "animation", "voice", "video_note", "sticker")
NO_CAPTION = ("video_note", "sticker")
TMP_ROOT = os.path.join(tempfile.gettempdir(), "clone_relay")


def media_of(msg) -> Tuple[Optional[str], object]:
    for t in MEDIA_TYPES:
        obj = getattr(msg, t, None)
        if obj:
            return t, obj
    return None, None


def filename_of(msg) -> str:
    _, obj = media_of(msg)
    return getattr(obj, "file_name", None) or ""


class Relay:
    def __init__(self, main_client, store, concurrency: int = 3):
        self.main, self.store = main_client, store
        self._locks = defaultdict(asyncio.Lock)
        self._sem = asyncio.Semaphore(concurrency)

    async def fetch(self, ids: List[int]) -> list:
        """Read posts from the central channel with the main bot."""
        out = []
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            msgs = await self.main.get_messages(OWNER_DB_CHANNEL, chunk)
            if not isinstance(msgs, list):
                msgs = [msgs]
            out.extend(m for m in msgs if m and not getattr(m, "empty", False))
        return out

    async def fetch_own(self, clone_client, channel: int, ids: List[int]) -> list:
        """Read posts from a clone owner's OWN db channel with the clone bot itself."""
        out = []
        for i in range(0, len(ids), 200):
            msgs = await clone_client.get_messages(channel, ids[i:i + 200])
            if not isinstance(msgs, list):
                msgs = [msgs]
            for m in msgs:
                if m and not getattr(m, "empty", False):
                    m._clone_own = True          # file_ids are valid for this bot: no download/upload/cache needed
                    out.append(m)
        return out

    @staticmethod
    def _kwargs(mtype: str, obj, caption: Optional[str], protect: bool, thumb=None) -> dict:
        kw = {"protect_content": protect}
        if mtype not in NO_CAPTION:
            kw["caption"] = caption or ""
        if mtype == "video":
            kw.update(duration=getattr(obj, "duration", 0), width=getattr(obj, "width", 0),
                      height=getattr(obj, "height", 0), supports_streaming=True)
            if thumb:
                kw["thumb"] = thumb
        elif mtype == "animation":
            kw.update(duration=getattr(obj, "duration", 0), width=getattr(obj, "width", 0),
                      height=getattr(obj, "height", 0))
        elif mtype == "audio":
            kw.update(duration=getattr(obj, "duration", 0), performer=getattr(obj, "performer", None),
                      title=getattr(obj, "title", None))
        elif mtype == "voice":
            kw["duration"] = getattr(obj, "duration", 0)
        elif mtype == "video_note":
            kw.update(duration=getattr(obj, "duration", 0), length=getattr(obj, "length", 240))
        elif mtype == "document" and thumb:
            kw["thumb"] = thumb
        return kw

    async def send(self, clone_client, clone_id: int, chat_id: int, msg,
                   caption: Optional[str], protect: bool = False):
        """Send one central-channel post to chat_id as the clone. Returns the sent message."""
        mtype, obj = media_of(msg)
        if not mtype:                                   # plain text post
            text = (msg.text.html if msg.text else "") or ""
            if caption:
                text = caption
            return await clone_client.send_message(chat_id, text, protect_content=protect)

        sender = getattr(clone_client, f"send_{mtype}")

        if getattr(msg, "_clone_own", False):            # own db channel: send straight by file_id
            return await sender(chat_id, obj.file_id, **self._kwargs(mtype, obj, caption, protect))

        cached = await self.store.get_file(clone_id, msg.id)
        if cached:
            try:
                return await sender(chat_id, cached["file_id"], **self._kwargs(mtype, obj, caption, protect))
            except Exception as e:
                logging.warning(f"[clone {clone_id}] cached file_id failed ({e}); re-uploading")
                await self.store.drop_file(clone_id, msg.id)

        async with self._locks[(clone_id, msg.id)]:
            cached = await self.store.get_file(clone_id, msg.id)       # filled while we waited?
            if cached:
                return await sender(chat_id, cached["file_id"], **self._kwargs(mtype, obj, caption, protect))

            async with self._sem:
                work = os.path.join(TMP_ROOT, uuid.uuid4().hex)
                os.makedirs(work, exist_ok=True)
                try:
                    path = await self.main.download_media(msg, file_name=work + os.sep)
                    thumb = None
                    thumbs = getattr(obj, "thumbs", None)
                    if thumbs and mtype in ("video", "document"):
                        try:
                            thumb = await self.main.download_media(thumbs[0].file_id, file_name=work + os.sep)
                        except Exception:
                            thumb = None
                    sent = await sender(chat_id, path, **self._kwargs(mtype, obj, caption, protect, thumb))
                    new = getattr(sent, mtype, None)
                    if new:
                        await self.store.put_file(clone_id, msg.id, mtype, new.file_id)
                    return sent
                finally:
                    shutil.rmtree(work, ignore_errors=True)
