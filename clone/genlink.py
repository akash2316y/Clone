"""
/genlink inside a clone bot (clone OWNER only).

Same flow as the main bot's /genlink: the owner sends any number of messages, every one is
copied into the clone's OWN db channel (set in /myclone -> db channel), and "Generate Link"
turns them into one link. Buttons: Generate Link | Cancel | Pause (Resume).

Nothing is ever written to the main bot's db channel from here.
"""
import asyncio
from typing import Dict, Tuple

from pyrogram import filters
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from clone import ctx, panels
from clone.ui import esc, sc

# (clone_id, owner_id) -> {"ids": [], "paused": bool, "panel": Message|None, "lock": Lock, "gen": int, "ch": int}
_S: Dict[Tuple[int, int], dict] = {}


def has_session(clone_id: int, uid: int) -> bool:
    return (clone_id, uid) in _S


def _text(s: dict) -> str:
    if s["paused"]:
        return (f"<b>⏸ Paused</b>\n\nStored Messages: <b>{len(s['ids'])}</b>\n\n"
                "<i>Messages are not stored right now. Tap Resume and send again.</i>")
    return (f"Stored Messages: <b>{len(s['ids'])}</b>\n\n"
            "<i>Want to add more messages? Just send them here!</i>\n\n"
            "<blockquote><i>✨You can now send multiple messages at once.</i></blockquote>")


def _markup(s: dict) -> Markup:
    toggle = Btn("Resume", callback_data="gl_resume") if s["paused"] else Btn("Pause", callback_data="gl_pause")
    return Markup([
        [Btn("Generate Link", callback_data="gl_gen")],
        [Btn("Cancel", callback_data="gl_cancel"), toggle],
    ])


async def _send_panel(client, chat_id: int, s: dict):
    old = s.get("panel")
    if old:
        try:
            await old.delete()
        except Exception:
            pass
    s["panel"] = await client.send_message(chat_id, _text(s), reply_markup=_markup(s))


async def _refresh_later(client, chat_id: int, key, s: dict, gen: int):
    await asyncio.sleep(1.5)                      # debounce: one panel after the last message
    if _S.get(key) is not s or s["gen"] != gen:
        return
    try:
        await _send_panel(client, chat_id, s)
    except Exception:
        pass


# ------------------------------------------------------------------ handlers
async def on_genlink(client, message):
    clone = await ctx.manager.store.get(client.clone_id)
    uid = message.from_user.id
    if not clone or uid != clone["owner_id"]:
        return await message.reply_text(sc("<b>🔒 only the owner of this clone can use /genlink.</b>"), quote=True)
    ch = int(clone["settings"].get("db_channel") or 0)
    if not ch:
        return await message.reply_text(
            sc("<b>🗄 set your db channel first.</b>\n<blockquote>open /myclone → db channel, add this bot as admin "
               "in your channel and connect it. then send /genlink again.</blockquote>"), quote=True)
    key = (client.clone_id, uid)
    s = _S.get(key)
    if not s or s["ch"] != ch:
        s = {"ids": [], "paused": False, "panel": None, "lock": asyncio.Lock(), "gen": 0, "ch": ch}
        _S[key] = s
    s["paused"] = False
    s["gen"] += 1
    await _send_panel(client, message.chat.id, s)


async def _collecting(_, client, message):
    if not message.from_user or message.service:
        return False
    s = _S.get((client.clone_id, message.from_user.id))
    if not s or s["paused"]:
        return False
    if message.text and message.text.startswith("/"):
        return False
    return True


collecting = filters.create(_collecting)


async def on_collect(client, message):
    key = (client.clone_id, message.from_user.id)
    s = _S.get(key)
    if not s:
        return
    async with s["lock"]:
        if s["paused"] or _S.get(key) is not s:
            return
        try:
            sent = await message.copy(s["ch"], disable_notification=True)
            s["ids"].append(sent.id)
        except Exception as e:
            await message.reply_text(
                f"❌ Failed to store this message:\n<code>{esc(str(e))}</code>\n"
                "<i>Make sure this bot is admin in your db channel (post + delete rights).</i>", quote=True)
            message.stop_propagation()
        s["gen"] += 1
        gen = s["gen"]
    asyncio.create_task(_refresh_later(client, message.chat.id, key, s, gen))
    message.stop_propagation()


async def on_cb(client, query):
    from clone.engine import b64_encode            # lazy: engine imports this module
    uid = query.from_user.id
    key = (client.clone_id, uid)
    action = query.data[3:]
    s = _S.get(key)
    if not s:
        await query.answer("Session expired. Send /genlink again.", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
        return query.stop_propagation()

    if action in ("pause", "resume"):
        s["paused"] = action == "pause"
        s["gen"] += 1
        await query.message.edit_text(_text(s), reply_markup=_markup(s))
        await query.answer("Paused" if s["paused"] else "Resumed")

    elif action == "cancel":
        async with s["lock"]:
            _S.pop(key, None)
            ids = list(s["ids"])
        for i in range(0, len(ids), 100):
            try:
                await client.delete_messages(s["ch"], ids[i:i + 100])
            except Exception:
                pass
        await query.message.edit_text("<b>❌ Cancelled.</b>\n<blockquote>Stored messages were discarded.</blockquote>")
        await query.answer("Cancelled")

    elif action == "gen":
        async with s["lock"]:
            ids = list(s["ids"])
            if not ids:
                await query.answer("Send some messages first!", show_alert=True)
                query.stop_propagation()
            _S.pop(key, None)
        clone = await ctx.manager.store.get(client.clone_id)
        first, last, mult = min(ids), max(ids), abs(s["ch"])
        raw = f"get-{first * mult}" if first == last else f"get-{first * mult}-{last * mult}"
        link = f"https://t.me/{clone['username']}?start={b64_encode(raw)}"
        try:
            await query.message.delete()
        except Exception:
            pass
        await client.send_message(
            query.message.chat.id,
            f"<blockquote><b>Here Is Your Link:</b></blockquote>\n\n{link}",
            reply_markup=Markup([[Btn("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]]),
            disable_web_page_preview=True)
        await query.answer("Link generated")
    query.stop_propagation()


def register(client):
    add = client.add_handler
    priv = filters.private
    add(MessageHandler(on_genlink, filters.command("genlink") & priv))
    add(MessageHandler(on_collect, priv & collecting & ~panels.has_pending), group=-1)
    add(CallbackQueryHandler(on_cb, filters.regex(r"^gl_(gen|cancel|pause|resume)$")), group=-1)
