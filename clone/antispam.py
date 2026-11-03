"""
Flood protection shared by the main bot and every clone.

Escalation per user:  warnings  ->  temp-ban (grows each time)  ->  permanent system-wide ban.
Registered as a group=-2 handler, so it runs before any command and can swallow the update.
"""
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

from config import (OWNER_ID, SPAM_MAX_MSGS, SPAM_PERMBAN_AFTER, SPAM_TEMPBAN_SECS,
                    SPAM_WARNINGS, SPAM_WINDOW)
from clone import logs
from clone.ui import esc, sc, tpl


@dataclass
class Verdict:
    kind: str            # ok | warn | tempban | permban | blocked
    notify: bool = False
    seconds: int = 0
    left: int = 0


class RateLimiter:
    def __init__(self, max_msgs=SPAM_MAX_MSGS, window=SPAM_WINDOW, warnings=SPAM_WARNINGS,
                 tempban_secs=SPAM_TEMPBAN_SECS, permban_after=SPAM_PERMBAN_AFTER):
        self.max_msgs, self.window, self.warnings = max_msgs, window, warnings
        self.tempban_secs, self.permban_after = tempban_secs, permban_after
        self.hits: Dict[int, Deque[float]] = {}
        self.strikes: Dict[int, int] = {}
        self.banned_until: Dict[int, float] = {}
        self.ban_count: Dict[int, int] = {}

    def check(self, uid: int, now: Optional[float] = None) -> Verdict:
        now = now if now is not None else time.time()

        until = self.banned_until.get(uid)
        if until:
            if now < until:
                return Verdict("blocked", notify=False, left=int(until - now))
            del self.banned_until[uid]

        q = self.hits.setdefault(uid, deque())
        q.append(now)
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) <= self.max_msgs:
            return Verdict("ok")

        # violation
        q.clear()
        self.strikes[uid] = self.strikes.get(uid, 0) + 1
        if self.strikes[uid] <= self.warnings:
            return Verdict("warn", notify=True)

        self.strikes[uid] = 0
        self.ban_count[uid] = self.ban_count.get(uid, 0) + 1
        if self.ban_count[uid] >= self.permban_after:
            return Verdict("permban", notify=True)
        secs = self.tempban_secs * self.ban_count[uid]
        self.banned_until[uid] = now + secs
        return Verdict("tempban", notify=True, seconds=secs)

    def forget(self, uid: int):
        for d in (self.hits, self.strikes, self.banned_until, self.ban_count):
            d.pop(uid, None)

    def cleanup(self, now: Optional[float] = None):
        now = now if now is not None else time.time()
        for uid in [u for u, q in self.hits.items() if not q or now - q[-1] > self.window * 4]:
            self.hits.pop(uid, None)


limiter = RateLimiter()


class _TTL:
    def __init__(self, ttl: float):
        self.ttl, self.data = ttl, {}

    def get(self, key) -> Tuple[bool, object]:
        hit = self.data.get(key)
        if hit and hit[1] > time.time():
            return True, hit[0]
        return False, None

    def put(self, key, value):
        if len(self.data) > 20000:
            self.data.clear()
        self.data[key] = (value, time.time() + self.ttl)

    def drop(self, key):
        self.data.pop(key, None)


_admin_cache = _TTL(60)
_ban_cache = _TTL(30)
_ban_notice = _TTL(60)


def invalidate(uid: int):
    """Call after changing admin/ban state so the gate sees it immediately."""
    _admin_cache.drop(uid)
    _ban_cache.drop(uid)
    limiter.forget(uid)


async def is_exempt(uid: int) -> bool:
    if uid == OWNER_ID:
        return True
    hit, val = _admin_cache.get(uid)
    if hit:
        return bool(val)
    from database.database import db
    try:
        val = await db.admin_exist(uid)
    except Exception:
        val = False
    _admin_cache.put(uid, val)
    return bool(val)


async def is_banned(uid: int) -> bool:
    hit, val = _ban_cache.get(uid)
    if hit:
        return bool(val)
    from database.database import db
    try:
        val = await db.ban_user_exist(uid)
    except Exception:
        val = False
    _ban_cache.put(uid, val)
    return bool(val)


async def _say(update, text: str):
    try:
        if hasattr(update, "answer") and not hasattr(update, "reply_text"):   # CallbackQuery
            await update.answer(text, show_alert=True)
        else:
            await update.reply_text(text, quote=True)
    except Exception:
        pass


async def gate(client, update):
    """System-wide ban check + flood protection. Handler for messages and callbacks."""
    user = getattr(update, "from_user", None)
    if not user or user.is_bot:
        return
    uid = user.id
    if await is_exempt(uid):
        return

    if await is_banned(uid):
        seen, _ = _ban_notice.get(uid)
        if not seen:
            _ban_notice.put(uid, True)
            await _say(update, sc("<b>🚫 you are banned from using this bot.</b>"))
        update.stop_propagation()
        return

    v = limiter.check(uid)
    if v.kind == "ok":
        return

    if v.kind == "warn":
        await _say(update, sc("<b>⚠️ slow down! you are sending too fast. keep spamming and you will be banned.</b>"))
    elif v.kind == "tempban":
        mins = max(v.seconds // 60, 1)
        await _say(update, sc(f"<b>⏳ spam detected. you are blocked for {mins} min.</b>"))
        await logs.admin_log(tpl("<b>🛡 auto temp-ban</b>\nuser: <code>{id}</code> ({name})\nduration: {m} min\nvia: @{via}",
                                 id=uid, name=esc(user.first_name or ""), m=mins, via=esc(getattr(client, "username", "") or "main")))
    elif v.kind == "permban":
        from database.database import db
        try:
            await db.add_ban_user(uid)
        except Exception as e:
            logging.error(f"auto-ban failed: {e}")
        _ban_cache.drop(uid)
        await _say(update, sc("<b>🚫 you have been permanently banned for spamming.</b>"))
        await logs.admin_log(tpl("<b>🚫 auto permanent ban</b>\nuser: <code>{id}</code> ({name})\nvia: @{via}\nundo with /delban {id}",
                                 id=uid, name=esc(user.first_name or ""), via=esc(getattr(client, "username", "") or "main")))
    update.stop_propagation()
