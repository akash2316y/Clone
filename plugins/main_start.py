"""
Main bot /start page - same look as the clone bots:
    [help] [about]  +  [create my own clone] [update channel]
Help / Commands / About / Back edit the SAME message instead of sending a new one.
/help and /cmd open that same panel (one message), so their buttons edit it in place too.

Only a plain "/start" is handled here. "/start <payload>" (file links, "/start clone") still goes to the
existing handlers, so link delivery keeps working.
"""
import logging

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from bot import Bot
from config import MAIN_START_TEXT, OWNER_ID, START_PIC, UPDATES_URL
from database.database import db
from clone import antispam
from clone.cmdlist import commands_text
from clone.engine import _show, about_text_main, back_markup, fill, help_markup, help_text, send_panel
from clone.ui import sc

log = logging.getLogger(__name__)


async def _skip_ads(uid: int) -> bool:
    """Owner / admins / premium users only get Help + About."""
    try:
        if uid == OWNER_ID or await antispam.is_exempt(uid):
            return True
        return bool(await db.is_premium(uid))
    except Exception:
        return False


async def _start_view(client, user):
    text = fill(MAIN_START_TEXT, first=user.first_name or "", mention=user.mention, id=user.id,
                username=f"@{user.username}" if user.username else "")
    rows = [[Btn(sc("❓ help"), callback_data="ms|help"), Btn(sc("ℹ️ about"), callback_data="ms|about")]]
    if not await _skip_ads(user.id):
        me_un = getattr(client, "username", "") or ""
        if me_un:
            rows.append([Btn(sc("🤖 create my own clone"), url=f"https://t.me/{me_un}?start=clone")])
        if UPDATES_URL:
            rows.append([Btn(sc("📢 update channel"), url=UPDATES_URL)])
    pic = START_PIC if START_PIC and len(text) <= 1024 else None
    return text, Markup(rows), pic


async def _register(user_id: int):
    """Keep the user in the broadcast DB (the old /start handler did this; we answer before it now)."""
    try:
        if hasattr(db, "present_user") and hasattr(db, "add_user"):
            if not await db.present_user(user_id):
                await db.add_user(user_id)
    except Exception as e:
        log.warning("couldn't register user %s: %s", user_id, e)


@Bot.on_message(filters.command("start") & filters.private & filters.regex(r"^/start(@\w+)?\s*$"), group=-1)
async def main_start(client, message):
    await _register(message.from_user.id)
    text, kb, pic = await _start_view(client, message.from_user)
    if pic:
        await message.reply_photo(pic, caption=text, reply_markup=kb, quote=True)
    else:
        await message.reply_text(text, reply_markup=kb, quote=True, disable_web_page_preview=True)
    message.stop_propagation()


@Bot.on_message(filters.command("help") & filters.private, group=-1)
async def main_help(client, message):
    """/help -> help page as a panel; its Commands / Back buttons edit this same message."""
    await send_panel(message, help_text(), help_markup("ms"), START_PIC)
    message.stop_propagation()


@Bot.on_message(filters.command(["cmd", "commands"]) & filters.private, group=-1)
async def main_cmd(client, message):
    """/cmd -> command list as a panel; Back edits this same message."""
    await send_panel(message, commands_text("main"), back_markup("ms"), START_PIC)
    message.stop_propagation()


@Bot.on_callback_query(filters.regex(r"^ms\|(help|about|back|cmd)$"), group=-1)
async def main_start_cb(client, query):
    action = query.data.split("|")[1]
    if action == "help":
        await _show(client, query, help_text(), help_markup("ms"), START_PIC)
    elif action == "cmd":
        await _show(client, query, commands_text("main"), back_markup("ms", "help"), START_PIC)
    elif action == "about":
        await _show(client, query, await about_text_main(client), back_markup("ms"), START_PIC)
    else:
        text, kb, pic = await _start_view(client, query.from_user)
        await _show(client, query, text, kb, pic)
    await query.answer()
    query.stop_propagation()
