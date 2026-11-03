"""
CloneManager: owns every running clone Client in the main bot's event loop.

Background jobs
  health_pass    watchdog: starts missing clones, probes running ones, auto-restarts, alerts the bot owner
  expiry_pass    pauses clones whose plan ended, warns 24h before, resumes them when renewed
  deletion_pass  executes the persisted auto-delete queue
"""
import asyncio
import html
import logging
import re
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import aiohttp
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import (API_HASH, APP_ID, HEALTH_INTERVAL, HEALTH_MAX_RESTARTS, OWNER_ID)
from database.database import db
from clone import ctx, engine, logs
from clone.crypto import dec, enc
from clone.plans import compute_validity
from clone.relay import Relay
from clone.store import (ACTIVE, BANNED, CRASHED, EXPIRED, INVALID, PAUSED, CloneStore)
from clone.ui import esc, fmt_ts, sc, tpl

TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
RESTART_WINDOW = 600
PLAN_TTL = 20


@dataclass
class Runtime:
    client: Client
    started: float = field(default_factory=time.time)
    fails: int = 0
    restarts: List[float] = field(default_factory=list)


def find_token(text: str) -> Optional[str]:
    m = TOKEN_RE.search(text or "")
    return m.group(0) if m else None


def _is_dead_token(err: str) -> bool:
    e = err.upper()
    return any(k in e for k in ("ACCESS_TOKEN_INVALID", "ACCESSTOKENINVALID", "AUTH_KEY_UNREGISTERED",
                                "AUTHKEYUNREGISTERED", "USER_DEACTIVATED", "401"))


class CloneManager:
    def __init__(self, main_client):
        self.main = main_client
        self.store = CloneStore(db.database)
        self.relay = Relay(main_client, self.store)
        self.rt: Dict[int, Runtime] = {}
        self.cfg: Dict[str, object] = {"allow_cloning": True, "max_clones": 1, "free_days": 30}
        self._tasks: List[asyncio.Task] = []
        self._locks = defaultdict(asyncio.Lock)
        self._plan_cache: Dict[int, Tuple[float, tuple]] = {}
        self._boot_fails = defaultdict(int)

    # ================================================================ lifecycle
    async def start(self):
        ctx.set_manager(self)
        logs.set_main(self.main)
        self.cfg = await self.store.get_global()
        self._tasks = [
            asyncio.create_task(self._boot_all()),
            asyncio.create_task(self._loop(self.health_pass, HEALTH_INTERVAL)),
            asyncio.create_task(self._loop(self.expiry_pass, 60)),
            asyncio.create_task(self._loop(self.deletion_pass, 15)),
        ]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*(self._stop_client(cid) for cid in list(self.rt)), return_exceptions=True)

    async def _loop(self, fn, interval: int):
        await asyncio.sleep(interval)
        while True:
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.error(f"clone job {fn.__name__} failed:\n{traceback.format_exc()}")
            await asyncio.sleep(interval)

    async def _boot_all(self):
        if not self.cfg["allow_cloning"]:
            return
        sem = asyncio.Semaphore(4)

        async def one(doc):
            async with sem:
                ok, err = await self.start_clone(doc["_id"])
                if not ok:
                    logging.warning(f"clone {doc['_id']} boot failed: {err}")

        await asyncio.gather(*(one(d) for d in await self.store.all(ACTIVE)), return_exceptions=True)

    def is_running(self, cid: int) -> bool:
        return cid in self.rt

    # ================================================================ plans
    async def plan_of(self, clone: dict) -> Tuple[str, Optional[float]]:
        hit = self._plan_cache.get(clone["_id"])
        if hit and hit[0] > time.time():
            return hit[1]
        plan, vu, _ = await self.validity(clone)
        self._plan_cache[clone["_id"]] = (time.time() + PLAN_TTL, (plan, vu))
        return plan, vu

    async def validity(self, clone: dict):
        exp = await db.get_premium_expiry(clone["owner_id"])
        return compute_validity(clone["created_at"], int(self.cfg["free_days"]), exp.timestamp() if exp else None)

    def invalidate_plans(self):
        self._plan_cache.clear()

    # ================================================================ start / stop one clone
    def _build(self, doc: dict) -> Client:
        token = dec(doc["token"])
        if not token:
            raise ValueError("ACCESS_TOKEN_INVALID (stored token unreadable)")
        c = Client(name=f"clone_{doc['_id']}", api_id=APP_ID, api_hash=API_HASH, bot_token=token,
                   in_memory=True, workers=4)
        c.set_parse_mode(ParseMode.HTML)
        c.clone_id = doc["_id"]
        c.username = doc.get("username", "")
        return c

    async def start_clone(self, cid: int) -> Tuple[bool, str]:
        async with self._locks[cid]:
            if cid in self.rt:
                return True, ""
            if not self.cfg["allow_cloning"]:
                return False, "cloning is turned off"
            doc = await self.store.get(cid)
            if not doc:
                return False, "clone not found"
            client = None
            try:
                client = self._build(doc)
                await engine.register(client)
                await asyncio.wait_for(client.start(), 90)
                me = await client.get_me()
                client.username = me.username
                await engine.set_menu(client)
                self.rt[cid] = Runtime(client)
                self._boot_fails.pop(cid, None)
                return True, ""
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                if client:
                    try:
                        await asyncio.wait_for(client.stop(), 10)
                    except Exception:
                        pass
                if _is_dead_token(err):
                    await self._mark(doc, INVALID, "token revoked or invalid", notify_owner=True)
                return False, err

    async def _stop_client(self, cid: int):
        rt = self.rt.pop(cid, None)
        if not rt:
            return
        try:
            await asyncio.wait_for(rt.client.stop(), 20)
        except Exception as e:
            logging.warning(f"clone {cid} stop: {e}")
            try:
                await rt.client.disconnect()
            except Exception:
                pass

    # ================================================================ status changes
    async def _notify(self, user_id: int, text: str):
        try:
            await self.main.send_message(user_id, text, disable_web_page_preview=True)
        except Exception as e:
            logging.info(f"notify {user_id} failed: {e}")

    async def _mark(self, doc: dict, status: str, reason: str, notify_owner: bool = False):
        await self._stop_client(doc["_id"])
        await self.store.update(doc["_id"], {"status": status})
        await logs.admin_log(tpl("<b>⏸ clone {st}</b>\n@{u} (<code>{id}</code>)\nowner: <code>{o}</code>\nreason: {r}",
                                 st=status, u=doc["username"], id=doc["_id"], o=doc["owner_id"], r=esc(reason)))
        if notify_owner:
            await self._notify(doc["owner_id"], tpl("<b>⚠️ your clone @{u} was {st}.</b>\n<blockquote>{r}</blockquote>",
                                                    u=doc["username"], st=status, r=esc(reason)))

    async def pause(self, cid: int, status: str = PAUSED, reason: str = "paused", notify_owner: bool = False):
        doc = await self.store.get(cid)
        if doc:
            await self._mark(doc, status, reason, notify_owner)

    async def resume(self, cid: int) -> Tuple[bool, str]:
        doc = await self.store.get(cid)
        if not doc:
            return False, "clone not found"
        if not self.cfg["allow_cloning"]:
            return False, "cloning is turned off by the owner"
        if await db.ban_user_exist(doc["owner_id"]):
            return False, "owner is banned"
        _, _, expired = await self.validity(doc)
        if expired:
            return False, "plan expired. renew premium to resume"
        await self.store.update(cid, {"status": ACTIVE, "warned": False})
        self._boot_fails.pop(cid, None)
        ok, err = await self.start_clone(cid)
        if ok:
            await logs.admin_log(tpl("<b>▶️ clone resumed</b>\n@{u} (<code>{id}</code>)", u=doc["username"], id=cid))
        return ok, err

    async def restart(self, cid: int) -> Tuple[bool, str]:
        await self._stop_client(cid)
        return await self.start_clone(cid)

    async def delete(self, cid: int, by: int):
        doc = await self.store.get(cid)
        await self._stop_client(cid)
        await self.store.delete(cid)
        if doc:
            await logs.admin_log(tpl("<b>🗑 clone deleted</b>\n@{u} (<code>{id}</code>)\nowner: <code>{o}</code>\nby: <code>{by}</code>",
                                     u=doc["username"], id=cid, o=doc["owner_id"], by=by))

    async def pause_owner_clones(self, owner_id: int, status: str, reason: str):
        for d in await self.store.by_owner(owner_id):
            if d["status"] == ACTIVE:
                await self._mark(d, status, reason, notify_owner=True)

    async def resume_owner_clones(self, owner_id: int, only_status: Optional[str] = None):
        for d in await self.store.by_owner(owner_id):
            if only_status is None or d["status"] == only_status:
                if d["status"] != ACTIVE:
                    await self.resume(d["_id"])

    async def set_cfg(self, **fields):
        self.cfg.update(fields)
        await self.store.set_global(**fields)
        self.invalidate_plans()
        if "allow_cloning" in fields:
            if fields["allow_cloning"]:
                asyncio.create_task(self._boot_all())
            else:
                await asyncio.gather(*(self._stop_client(c) for c in list(self.rt)), return_exceptions=True)
        if "free_days" in fields:
            asyncio.create_task(self.expiry_pass())

    # ================================================================ creating clones
    async def create_clone(self, owner_id: int, token: str, privileged: bool) -> Tuple[bool, object]:
        """Returns (True, clone_doc) or (False, user-facing error text)."""
        if not self.cfg["allow_cloning"]:
            return False, "cloning is currently turned off."
        if not TOKEN_RE.fullmatch(token or ""):
            return False, "that doesn't look like a bot token."
        if not privileged:
            used, cap = await self.store.count_by_owner(owner_id), int(self.cfg["max_clones"])
            if used >= cap:
                return False, f"clone limit reached ({used}/{cap})."
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                async with s.get(f"https://api.telegram.org/bot{token}/getMe") as r:
                    data = await r.json(content_type=None)
        except Exception:
            return False, "couldn't reach Telegram to verify the token, try again."
        if not data.get("ok"):
            return False, "Telegram rejected that token (revoked or wrong)."
        info = data["result"]
        bot_id = int(info["id"])
        if bot_id == (await self.main.get_me()).id:
            return False, "you can't clone the main bot."
        if await self.store.get(bot_id):
            return False, "that bot is already registered as a clone."
        doc = await self.store.create(bot_id, owner_id, enc(token), info.get("username", ""), info.get("first_name", ""))
        ok, err = await self.start_clone(bot_id)
        if not ok:
            await self.store.delete(bot_id)
            return False, f"couldn't start the bot: {esc(err)[:200]}"
        await logs.admin_log(tpl("<b>🆕 clone created</b>\n@{u} (<code>{id}</code>)\nowner: <code>{o}</code>",
                                 u=info.get("username", ""), id=bot_id, o=owner_id))
        return True, doc

    # ================================================================ expiry
    async def expiry_pass(self, owner_id: Optional[int] = None):
        self.invalidate_plans()
        now = time.time()
        for doc in await self.store.all():
            if owner_id and doc["owner_id"] != owner_id:
                continue
            if doc["status"] not in (ACTIVE, EXPIRED):
                continue
            plan, vu, expired = await self.validity(doc)
            if doc["status"] == ACTIVE and expired:
                await self._mark(doc, EXPIRED, "plan expired", notify_owner=False)
                await self._notify(doc["owner_id"], tpl(
                    "<b>⏰ your clone @{u} has expired and was paused.</b>\n<blockquote>renew premium to resume it automatically.</blockquote>",
                    u=doc["username"]))
            elif doc["status"] == EXPIRED and not expired:
                ok, err = await self.resume(doc["_id"])
                if ok:
                    await self._notify(doc["owner_id"], tpl("<b>✅ plan renewed. your clone @{u} is running again.</b>", u=doc["username"]))
            elif doc["status"] == ACTIVE:
                soon = bool(vu) and vu - now < 86400
                if soon and not doc.get("warned"):
                    await self.store.update(doc["_id"], {"warned": True})
                    await self._notify(doc["owner_id"], tpl(
                        "<b>⏳ your clone @{u} expires on {d}.</b>\n<blockquote>renew premium to keep it running.</blockquote>",
                        u=doc["username"], d=fmt_ts(vu)))
                elif not soon and doc.get("warned"):
                    await self.store.update(doc["_id"], {"warned": False})

    # ================================================================ health monitor
    async def _probe(self, rt: Runtime) -> Optional[str]:
        """None if healthy, else an error description (with traceback when there is one)."""
        try:
            if not rt.client.is_connected:
                return "client is disconnected"
            await asyncio.wait_for(rt.client.get_me(), 20)
            return None
        except asyncio.TimeoutError:
            return "get_me() timed out after 20s (unresponsive)"
        except Exception:
            return traceback.format_exc()

    async def health_pass(self):
        if not self.cfg["allow_cloning"]:
            return
        # 1) ACTIVE clones that are not running (failed boot): retry a few times, then flag as crashed
        for doc in await self.store.all(ACTIVE):
            cid = doc["_id"]
            if cid in self.rt:
                continue
            ok, err = await self.start_clone(cid)
            if ok:
                continue
            doc = await self.store.get(cid)
            if not doc or doc["status"] != ACTIVE:
                continue
            self._boot_fails[cid] += 1
            if self._boot_fails[cid] >= HEALTH_MAX_RESTARTS:
                await self._alert(doc, f"failed to start {self._boot_fails[cid]} times", err, "marked as crashed")
                await self._mark(doc, CRASHED, "failed to start repeatedly", notify_owner=True)

        # 2) probe the running ones concurrently
        sem = asyncio.Semaphore(10)

        async def check(cid: int, rt: Runtime):
            async with sem:
                err = await self._probe(rt)
            if err is None:
                rt.fails = 0
                return
            rt.fails += 1
            if _is_dead_token(err):
                doc = await self.store.get(cid)
                if doc:
                    await self._alert(doc, "token revoked", err, "marked invalid")
                    await self._mark(doc, INVALID, "the bot token was revoked. create the clone again with a new token.", notify_owner=True)
                return
            if rt.fails >= 2:
                await self._auto_restart(cid, rt, err)

        await asyncio.gather(*(check(c, r) for c, r in list(self.rt.items())), return_exceptions=True)

    async def _auto_restart(self, cid: int, rt: Runtime, err: str):
        doc = await self.store.get(cid)
        if not doc:
            await self._stop_client(cid)
            return
        now = time.time()
        history = [t for t in rt.restarts if now - t < RESTART_WINDOW]
        if len(history) >= HEALTH_MAX_RESTARTS:
            await self._alert(doc, f"crash loop ({len(history)} restarts in {RESTART_WINDOW // 60} min)", err, "marked as crashed, needs manual resume")
            await self._mark(doc, CRASHED, "crash loop detected", notify_owner=True)
            return
        await self._stop_client(cid)
        ok, start_err = await self.start_clone(cid)
        if ok:
            self.rt[cid].restarts = history + [now]
        await self._alert(doc, "unresponsive / crashed", err,
                          f"auto-restart #{len(history) + 1}: {'✅ back online' if ok else '❌ failed: ' + start_err[:150]}")

    async def _alert(self, doc: dict, headline: str, err: str, action: str):
        trace = html.escape(err.strip()[-2500:])
        text = (f"<b>🚨 clone crash alert</b>\n<b>bot:</b> @{esc(doc['username'])} (<code>{doc['_id']}</code>)\n"
                f"<b>owner:</b> <code>{doc['owner_id']}</code>\n<b>issue:</b> {esc(headline)}\n"
                f"<b>action:</b> {esc(action)}\n\n<pre>{trace}</pre>")
        await self._notify(OWNER_ID, text)
        await logs.admin_log(text)

    # ================================================================ persisted auto-delete
    async def deletion_pass(self):
        for d in await self.store.due_deletions(time.time()):
            rt = self.rt.get(d["clone_id"])
            if not rt:
                if not await self.store.clones.find_one({"_id": d["clone_id"]}, {"_id": 1}):
                    await self.store.drop_deletion(d["_id"])
                continue                       # clone paused: delete once it runs again
            try:
                await rt.client.delete_messages(d["chat_id"], d["msg_ids"])
            except FloodWait:
                continue
            except Exception as e:
                logging.info(f"auto-delete skipped: {e}")
            if d.get("notice_id"):
                try:
                    kb = None
                    if d.get("payload"):
                        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                            sc("♻️ get again"), url=f"https://t.me/{rt.client.username}?start={d['payload']}")]])
                    await rt.client.edit_message_text(d["chat_id"], d["notice_id"], sc("<b>🗑 the files were deleted.</b>"), reply_markup=kb)
                except Exception:
                    pass
            await self.store.drop_deletion(d["_id"])

    # ================================================================ owner panel stats
    async def counts(self) -> Dict[str, int]:
        docs = await self.store.all()
        out = {"total": len(docs), "running": len(self.rt)}
        for st in (ACTIVE, PAUSED, EXPIRED, CRASHED, INVALID, BANNED):
            out[st] = sum(1 for d in docs if d["status"] == st)
        return out
