"""
Handlers that run inside every clone bot: /start, link delivery, force-sub, token verification,
/getvideo, /cmd. Settings UI lives in panels.py.
"""
import asyncio
import base64
import binascii
import logging
import random
import string
import time
from typing import List, Optional, Tuple

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import FloodWait, UserIsBlocked, UserNotParticipant
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup

from config import CLONE_BRANDING, OWNER_DB_CHANNEL, OWNER_ID, START_PIC
from clone import ctx, logs, panels
from clone.antispam import gate, is_exempt
from clone.cmdlist import commands_text
from clone.crypto import dec
from clone.plans import limits
from clone.relay import filename_of, media_of
from clone.shortener import shorten
from clone.ui import dur, esc, sc, tpl

MAX_BATCH = 500
VIDEO_PAYLOAD = "__video__"
_invite_cache = {}

DEFAULT_START = sc("<b>ʜᴇʏ {mention} ✨\n\nɪ sʜᴀʀᴇ ғɪʟᴇs ᴛʜʀᴏᴜɢʜ sᴘᴇᴄɪᴀʟ ʟɪɴᴋs. ᴏᴘᴇɴ ᴀ ʟɪɴᴋ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ғɪʟᴇs, ᴏʀ ᴜsᴇ /getvideo.</b>")


# ------------------------------------------------------------------ helpers
def fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def b64_decode(s: str) -> Optional[str]:
    try:
        s = s.strip()
        if len(s) % 4 == 1:
            return None
        return base64.urlsafe_b64decode((s + "=" * (-len(s) % 4)).encode("ascii")).decode("ascii")
    except (binascii.Error, ValueError, UnicodeError):
        return None


def parse_link(string_: Optional[str]) -> Tuple[Optional[str], List[int]]:
    """'get-<id*chan>[-<id*chan>]'  ->  ('get', [ids])  (same format the main bot generates)."""
    if not string_:
        return None, []
    parts = string_.split("-")
    if parts[0] not in ("get", "premium") or len(parts) not in (2, 3):
        return None, []
    mult = abs(OWNER_DB_CHANNEL)
    try:
        nums = [int(p) for p in parts[1:]]
        if any(n % mult for n in nums):
            return None, []
        nums = [n // mult for n in nums]
    except ValueError:
        return None, []
    if len(nums) == 1:
        ids = nums
    else:
        a, b = nums
        ids = list(range(a, b + 1)) if a <= b else list(range(a, b - 1, -1))
    if not ids or len(ids) > MAX_BATCH or min(ids) < 1:
        return None, []
    return parts[0], ids


async def current(client) -> Optional[dict]:
    return await ctx.manager.store.get(client.clone_id)


def brand_text(clone: dict, plan: str) -> str:
    """Free clones always carry the footer; premium clones may switch it off."""
    if plan == "premium" and not clone["settings"].get("branding", True):
        return ""
    return CLONE_BRANDING.replace("{main_username}", getattr(ctx.manager.main, "username", "") or "")


def branded(clone: dict, plan: str, text: str) -> str:
    b = brand_text(clone, plan)
    return f"{text}\n\n{b}" if b else text


def build_caption(clone: dict, plan: str, msg) -> str:
    s, lim = clone["settings"], limits(plan)
    orig_html = (msg.caption.html if msg.caption else "") or ""
    orig_plain = (str(msg.caption) if msg.caption else "") or ""
    brand = brand_text(clone, plan)
    room = 1024 - (len(brand) + 2 if brand else 0)

    def compose(orig: str) -> str:
        if lim["custom_caption"] and s["caption"]["enabled"] and s["caption"]["text"]:
            return fill(s["caption"]["text"], filename=esc(filename_of(msg)), caption=orig)
        return orig

    cap = compose(orig_html)
    if len(cap) > room:                       # never cut HTML mid-tag: fall back to escaped plain text
        for keep in (len(orig_plain), 500, 200, 0):
            cap = compose(esc(orig_plain[:keep]))
            if len(cap) <= room:
                break
        else:
            cap = ""
    return f"{cap}\n\n{brand}".strip() if brand else cap


async def staff_or_skip(clone: dict, uid: int) -> Tuple[bool, bool]:
    """(staff, skip_ads). staff = bot owner / admin / this clone's owner. skip_ads also covers premium users."""
    staff = uid == clone["owner_id"] or await is_exempt(uid)
    if staff:
        return True, True
    from database.database import db
    return False, await db.is_premium(uid)


def shortener_active(clone: dict, plan: str) -> bool:
    sh = clone["settings"]["shortener"]
    return bool(limits(plan)["custom_shortener"] and sh["enabled"] and sh["domain"] and sh["api"])


# ------------------------------------------------------------------ force-sub
async def _invite_link(client, ch: int) -> Optional[str]:
    key = (client.clone_id, ch)
    if key in _invite_cache:
        return _invite_cache[key]
    try:
        chat = await client.get_chat(ch)
        link = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or await client.export_chat_invite_link(ch))
    except Exception as e:
        logging.warning(f"[clone {client.clone_id}] invite link for {ch} failed: {e}")
        return None
    _invite_cache[key] = link
    return link


async def missing_fsub(client, clone: dict, uid: int) -> List[dict]:
    fs = clone["settings"]["fsub"]
    if not fs["enabled"]:
        return []
    missing = []
    for ch in fs["channels"]:
        try:
            m = await client.get_chat_member(ch["id"], uid)
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                missing.append(ch)
        except UserNotParticipant:
            missing.append(ch)
        except Exception as e:      # bot removed / not admin: don't lock users out, warn the owner
            logging.warning(f"[clone {client.clone_id}] fsub check {ch['id']} failed: {e}")
    return missing


async def send_fsub(client, message, clone, plan, missing: List[dict], payload: Optional[str]):
    rows = []
    for ch in missing:
        link = await _invite_link(client, ch["id"])
        if link:
            rows.append([InlineKeyboardButton(ch.get("title") or "Join", url=link)])
    retry = f"https://t.me/{client.username}" + (f"?start={payload}" if payload and payload != VIDEO_PAYLOAD else "")
    rows.append([InlineKeyboardButton(sc("♻️ try again"), url=retry)])
    text = branded(clone, plan, sc("<b>🔒 join the channels below to continue, then tap try again.</b>"))
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows), quote=True)


# ------------------------------------------------------------------ verification
async def send_verify(client, message, clone, plan, payload: str) -> bool:
    """True if a verify prompt was sent. False = shortener broke, caller should fail open."""
    store, uid, cid = ctx.manager.store, message.from_user.id, clone["_id"]
    sh = clone["settings"]["shortener"]
    token = "".join(random.choices(string.ascii_letters + string.digits, k=12))
    direct = f"https://t.me/{client.username}?start=verify_{token}"
    api = dec(sh["api"])                     # stored encrypted by panels.py
    url = await shorten(sh["domain"], api, direct) if api else None
    if not url:
        await logs.user_log(client, clone, sc("⚠️ shortener failed, files are being served without verification. check your domain / api key in /settings."))
        return False
    await store.set_user(cid, uid, token=token, token_at=time.time(), pending=payload)
    await store.inc(cid, "verify_links")
    hours = sh["hours"]
    text = branded(clone, plan, sc(f"<b>🔐 verification required</b>\n<blockquote>complete the short link to unlock files. valid for {hours} hour(s).</blockquote>"))
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(sc("• verify •"), url=url)]]), quote=True)
    return True


async def is_verified(clone: dict, uid: int) -> bool:
    u = await ctx.manager.store.get_user(clone["_id"], uid)
    return u.get("verified_until", 0) > time.time()


async def handle_verify(client, message, clone, plan, token: str):
    store, uid, cid = ctx.manager.store, message.from_user.id, clone["_id"]
    u = await store.get_user(cid, uid)
    if not token or not u.get("token") or u["token"] != token:
        return await message.reply_text(branded(clone, plan, sc("<b>⚠️ this verification link is invalid or already used. open your file link again.</b>")), quote=True)
    hours = clone["settings"]["shortener"]["hours"]
    pending = u.get("pending", "")
    await store.set_user(cid, uid, verified_until=time.time() + hours * 3600, token="", pending="")
    await store.inc(cid, "verified")
    await logs.user_log(client, clone, sc(f"✅ verified: <code>{uid}</code>"))
    await message.reply_text(branded(clone, plan, sc(f"<b>✅ verified! access unlocked for {hours} hour(s).</b>")), quote=True)
    if pending == VIDEO_PAYLOAD:
        await send_video(client, message, clone, plan)
    elif pending:
        await handle_payload(client, message, clone, pending)


# ------------------------------------------------------------------ delivery
async def _send_with_retry(client, chat_id, msg, caption, protect):
    relay, cid = ctx.manager.relay, client.clone_id
    for attempt in (1, 2):
        try:
            return await relay.send(client, cid, chat_id, msg, caption, protect)
        except FloodWait as e:
            await asyncio.sleep(getattr(e, "value", None) or getattr(e, "x", 5))
            if attempt == 2:
                raise


async def deliver(client, message, clone, plan, msgs: list, payload: str, scope: str):
    """Send fetched central-channel posts to the user, apply caption/branding/auto-delete."""
    store, chat_id, cid = ctx.manager.store, message.chat.id, clone["_id"]
    protect = bool(clone["settings"]["protect"])
    sent_ids = []
    for m in msgs:
        try:
            sent = await _send_with_retry(client, chat_id, m, build_caption(clone, plan, m), protect)
            if sent:
                sent_ids.append(sent.id)
        except UserIsBlocked:
            return
        except Exception as e:
            logging.error(f"[clone {cid}] send failed for msg {getattr(m, 'id', '?')}: {e}")
    if not sent_ids:
        return await message.reply_text(branded(clone, plan, sc("<b>❌ couldn't send the file, try again later.</b>")), quote=True)
    await store.inc(cid, "files", len(sent_ids))

    secs = clone["settings"]["auto_delete"].get(scope, 0)
    if secs:
        notice = await message.reply_text(
            branded(clone, plan, sc(f"<b>⚠️ these files will be deleted in {dur(secs)}. forward them somewhere safe.</b>")))
        await store.queue_delete(cid, chat_id, sent_ids, secs, notice.id, payload if payload != VIDEO_PAYLOAD else "")


async def handle_payload(client, message, clone, payload: str):
    uid, cid = message.from_user.id, clone["_id"]
    kind, ids = parse_link(b64_decode(payload))
    plan, _ = await ctx.manager.plan_of(clone)
    if not kind:
        return await message.reply_text(branded(clone, plan, sc("<b>❌ invalid or expired link.</b>")), quote=True)

    staff, skip_ads = await staff_or_skip(clone, uid)
    if kind == "premium" and not skip_ads:
        return await message.reply_text(branded(clone, plan, sc("<b>👑 this content is for premium users only.</b>")), quote=True)

    if not staff:
        miss = await missing_fsub(client, clone, uid)
        if miss:
            return await send_fsub(client, message, clone, plan, miss, payload)

    if kind == "get" and not skip_ads and shortener_active(clone, plan) and not await is_verified(clone, uid):
        if await send_verify(client, message, clone, plan, payload):
            return

    wait = await message.reply_text(sc("<b>⏳ please wait...</b>"), quote=True)
    try:
        msgs = await ctx.manager.relay.fetch(ids)
    except Exception as e:
        logging.error(f"[clone {cid}] fetch failed: {e}")
        return await wait.edit_text(sc("<b>⚠️ something went wrong, try again later.</b>"))
    try:
        await wait.delete()
    except Exception:
        pass
    if not msgs:
        return await message.reply_text(branded(clone, plan, sc("<b>❌ files not found.</b>")), quote=True)

    await ctx.manager.store.inc(cid, "links")
    await logs.user_log(client, clone, sc(f"🔗 link opened by <code>{uid}</code> ({len(msgs)} file(s))"))
    await deliver(client, message, clone, plan, msgs, payload, "links")


async def send_video(client, message, clone, plan):
    from database.database import db
    cid = clone["_id"]
    docs = await db.videos_collection.aggregate([{"$sample": {"size": 1}}]).to_list(1)
    msg_id = docs[0].get("msg_id") if docs else None
    if not msg_id:
        return await message.reply_text(branded(clone, plan, sc("<b>no videos available right now.</b>")), quote=True)
    try:
        msgs = await ctx.manager.relay.fetch([int(msg_id)])
    except Exception as e:
        logging.error(f"[clone {cid}] video fetch failed: {e}")
        msgs = []
    if not msgs:
        return await message.reply_text(branded(clone, plan, sc("<b>❌ couldn't load a video, try again.</b>")), quote=True)
    await logs.user_log(client, clone, sc(f"🎬 /getvideo by <code>{message.from_user.id}</code>"))
    await deliver(client, message, clone, plan, msgs, VIDEO_PAYLOAD, "video")


# ------------------------------------------------------------------ commands
async def on_start(client, message):
    clone = await current(client)
    if not clone:
        return
    uid, cid = message.from_user.id, clone["_id"]
    if await ctx.manager.store.touch_user(cid, uid):
        await logs.user_log(client, clone, tpl("👤 new user: <code>{id}</code> {name}", id=uid, name=esc(message.from_user.first_name or "")))
    payload = message.command[1] if len(message.command) > 1 else None
    plan, _ = await ctx.manager.plan_of(clone)

    if payload and payload.startswith("verify_"):
        return await handle_verify(client, message, clone, plan, payload[len("verify_"):])
    if payload:
        return await handle_payload(client, message, clone, payload)

    s, lim = clone["settings"], limits(plan)
    template = s["start"]["text"] if lim["custom_start"] and s["start"]["text"] else DEFAULT_START
    u = message.from_user
    text = fill(template, first=esc(u.first_name or ""), mention=u.mention, id=u.id,
                username=f"@{u.username}" if u.username else "")
    text = branded(clone, plan, text)
    kb = None
    if uid == clone["owner_id"]:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(sc("⚙️ settings"), callback_data=f"cs|{cid}|s|home")]])
    pic = s["start"]["pic"] if lim["custom_start"] and s["start"]["pic"] else START_PIC
    if pic and len(text) <= 1024:
        try:
            return await message.reply_photo(pic, caption=text, reply_markup=kb, quote=True)
        except Exception:
            pass
    await message.reply_text(text, reply_markup=kb, quote=True, disable_web_page_preview=True)


async def on_getvideo(client, message):
    clone = await current(client)
    if not clone:
        return
    uid, cid = message.from_user.id, clone["_id"]
    await ctx.manager.store.touch_user(cid, uid)
    plan, _ = await ctx.manager.plan_of(clone)
    staff, skip_ads = await staff_or_skip(clone, uid)
    if not staff:
        miss = await missing_fsub(client, clone, uid)
        if miss:
            return await send_fsub(client, message, clone, plan, miss, None)
    if not skip_ads and shortener_active(clone, plan) and not await is_verified(clone, uid):
        if await send_verify(client, message, clone, plan, VIDEO_PAYLOAD):
            return
    await send_video(client, message, clone, plan)


async def on_cmd(client, message):
    await message.reply_text(commands_text("clone"), quote=True)


async def on_myclone(client, message):
    clone = await current(client)
    if not clone or message.from_user.id not in (clone["owner_id"], OWNER_ID):
        return await message.reply_text(sc("<b>🔒 only the owner of this clone can use /myclone.</b>"), quote=True)
    await panels.show(message, clone, "d")


async def on_settings(client, message):
    clone = await current(client)
    if not clone or message.from_user.id not in (clone["owner_id"], OWNER_ID):
        return await message.reply_text(sc("<b>🔒 only the owner of this clone can use /settings.</b>"), quote=True)
    await panels.show(message, clone, "s")


async def on_cancel(client, message):
    panels.clear_pending(client.clone_id, message.from_user.id)
    await message.reply_text(sc("<b>✖️ cancelled.</b>"), quote=True)


# ------------------------------------------------------------------ wiring
async def register(client):
    add = client.add_handler
    priv = filters.private
    add(MessageHandler(gate, priv), group=-2)
    add(CallbackQueryHandler(gate), group=-2)
    add(MessageHandler(on_start, filters.command("start") & priv))
    add(MessageHandler(on_getvideo, filters.command("getvideo") & priv))
    add(MessageHandler(on_cmd, filters.command(["cmd", "commands", "help"]) & priv))
    add(MessageHandler(on_myclone, filters.command("myclone") & priv))
    add(MessageHandler(on_settings, filters.command("settings") & priv))
    add(MessageHandler(on_cancel, filters.command("cancel") & priv))
    add(CallbackQueryHandler(panels.on_callback, filters.regex(r"^cs\|")), group=-1)
    add(MessageHandler(panels.on_input, priv & ~filters.command(["start", "cancel"]) & panels.has_pending), group=1)


async def set_menu(client):
    try:
        await client.set_bot_commands([
            BotCommand("start", "Start the bot"),
            BotCommand("getvideo", "Get a random video"),
            BotCommand("cmd", "All commands"),
            BotCommand("myclone", "Clone dashboard (owner)"),
            BotCommand("settings", "Clone settings (owner)"),
        ])
    except Exception as e:
        logging.warning(f"set_bot_commands failed: {e}")
