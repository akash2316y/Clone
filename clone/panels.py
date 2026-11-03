"""
Clone owner UI: /myclone dashboard + /settings, all inline, small-caps, grid layout.

Callback data:  cs|<clone_id>|<screen>|<action>|<arg>
  screen = which view to render afterwards: d dashboard, s settings, fs/sh/ca/st/ad/lg sub-menus
"""
import logging
import time
from typing import Dict, Tuple

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from config import OWNER_ID
from clone import ctx, logs
from clone.crypto import enc
from clone.plans import limits
from clone.shortener import clean_domain, is_public_domain
from clone.ui import dur, esc, fmt_ts, left, sc, tick, tpl

PENDING_TTL = 300
_pending: Dict[Tuple[int, int], dict] = {}

PRESETS = [0, 60, 300, 600, 1800, 3600]
HOURS = [1, 6, 12, 24]
LOCK = " 🔒"


# ------------------------------------------------------------------ pending input
def clear_pending(cid: int, uid: int):
    _pending.pop((cid, uid), None)


async def _has_pending(_, client, message):
    if not message.from_user:
        return False
    p = _pending.get((client.clone_id, message.from_user.id))
    if p and p["expires"] < time.time():
        _pending.pop((client.clone_id, message.from_user.id), None)
        return False
    return bool(p)

has_pending = filters.create(_has_pending)


# ------------------------------------------------------------------ rendering
def _b(label: str, screen: str, cid: int, action: str = "show", arg: str = "") -> Btn:
    return Btn(label, callback_data=f"cs|{cid}|{screen}|{action}|{arg}")


def _toggle_rows(clone: dict, plan: str, screen: str):
    s, lim, cid = clone["settings"], limits(plan), clone["_id"]
    auto = s["auto_delete"]
    locked_sh = "" if lim["custom_shortener"] else LOCK
    locked_ca = "" if lim["custom_caption"] else LOCK
    return [
        [_b(f"{sc('force sub')} {tick(s['fsub']['enabled'])}", screen, cid, "t", "fsub"),
         _b(f"{sc('shortener')} {tick(s['shortener']['enabled'])}{locked_sh}", screen, cid, "t", "short")],
        [_b(f"{sc('caption')} {tick(s['caption']['enabled'])}{locked_ca}", screen, cid, "t", "caption"),
         _b(f"{sc('branding')} {tick(s['branding'] or plan != 'premium')}", screen, cid, "t", "brand")],
        [_b(f"{sc('protect')} {tick(s['protect'])}", screen, cid, "t", "protect"),
         _b(f"{sc('auto-del')} ⏱ {dur(auto['links'])}/{dur(auto['video'])}", "ad", cid)],
    ]


async def render(clone: dict, screen: str):
    plan, valid_until = await ctx.manager.plan_of(clone)
    s, cid, lim = clone["settings"], clone["_id"], limits(plan)
    plan_line = (f"👑 {sc('premium')}" if plan == "premium" else f"🆓 {sc('free')}") + f" • {sc('valid')}: {left(valid_until)}"
    home = [_b(sc("‹ back"), "s", cid)]
    close = Btn(sc("✖ close"), callback_data="cs|0|x|close|")

    if screen == "d":
        run = ctx.manager.is_running(cid)
        total, active = await ctx.manager.store.user_counts(cid, time.time() - 86400)
        st = clone["stats"]
        text = tpl(
            "<b>📊 clone dashboard</b>\n<blockquote>bot: @{u}\nplan: {plan}\nstatus: {status}</blockquote>\n"
            "<b>👥 active users (24h):</b> {active} / {total}\n"
            "<b>📁 processed files:</b> {files}\n"
            "<b>🔗 links processed:</b> {links}\n"
            "<b>🔐 verify links generated:</b> {vl}  (✅ {vd})\n\n"
            "<b>⚡ quick toggles</b>",
            u=clone["username"], plan=plan_line, status=("🟢 " + sc("running")) if run else "🔴 " + sc(clone["status"]),
            active=active, total=total, files=st.get("files", 0), links=st.get("links", 0),
            vl=st.get("verify_links", 0), vd=st.get("verified", 0))
        rows = _toggle_rows(clone, plan, "d") + [[_b(sc("⚙️ all settings"), "s", cid), close]]
        return text, Markup(rows)

    if screen == "s":
        text = tpl("<b>⚙️ clone settings</b>\n<blockquote>bot: @{u}\nplan: {plan}</blockquote>\n"
                   "<b>tap to toggle, open a menu to configure.</b>", u=clone["username"], plan=plan_line)
        rows = _toggle_rows(clone, plan, "s") + [
            [_b(sc("📢 force sub"), "fs", cid), _b(sc("🔗 shortener"), "sh", cid)],
            [_b(sc("📝 caption"), "ca", cid), _b(sc("🎨 start page"), "st", cid)],
            [_b(sc("🗒 user logs"), "lg", cid), _b(sc("📊 dashboard"), "d", cid)],
            [close]]
        return text, Markup(rows)

    if screen == "fs":
        chans = s["fsub"]["channels"]
        listing = "\n".join(f"• {esc(c.get('title') or c['id'])} (<code>{c['id']}</code>)" for c in chans) or sc("no channels added")
        text = tpl("<b>📢 force sub</b>\n<blockquote>limit: {n}/{m} channels\nthe bot must be admin in each channel.</blockquote>",
                   n=len(chans), m=lim["fsub_limit"]) + f"\n{listing}"
        rows = [[_b(f"🗑 {esc((c.get('title') or str(c['id']))[:24])}", "fs", cid, "fsdel", str(i))] for i, c in enumerate(chans)]
        rows.append([_b(sc("➕ add channel"), "fs", cid, "ask", "fsadd")])
        rows.append(home)
        return text, Markup(rows)

    if screen == "sh":
        sh = s["shortener"]
        api = "••••••••" if sh["api"] else sc("not set")
        note = "" if lim["custom_shortener"] else "\n" + sc("🔒 premium feature. upgrade to use your own shortener.")
        text = tpl("<b>🔗 shortener</b>\n<blockquote>domain: {d}\napi key: {api}\nverification valid for: {h}h</blockquote>",
                   d=esc(sh["domain"]) or sc("not set"), api=api, h=sh["hours"]) + note
        rows = [[_b(sc("🌐 set domain"), "sh", cid, "ask", "shdom"), _b(sc("🔑 set api key"), "sh", cid, "ask", "shapi")],
                [_b(f"{'• ' if sh['hours'] == h else ''}{h}h", "sh", cid, "hrs", str(h)) for h in HOURS],
                [_b(sc("🗑 clear"), "sh", cid, "clr", "short")], home]
        return text, Markup(rows)

    if screen == "ca":
        c = s["caption"]
        note = "" if lim["custom_caption"] else "\n" + sc("🔒 premium feature.")
        text = sc("<b>📝 custom caption</b>\n<blockquote>placeholders: {filename} {caption}\nhtml allowed. max 600 chars.</blockquote>") \
            + f"\n{c['text'] or sc('not set')}{note}"
        rows = [[_b(sc("✏️ set caption"), "ca", cid, "ask", "cap"), _b(sc("🗑 clear"), "ca", cid, "clr", "caption")], home]
        return text, Markup(rows)

    if screen == "st":
        st = s["start"]
        note = "" if lim["custom_start"] else "\n" + sc("🔒 premium feature.")
        text = sc("<b>🎨 start page</b>\n<blockquote>placeholders: {first} {mention} {id} {username}</blockquote>") \
            + f"\n{st['text'] or sc('default message')}\n{sc('image')}: {sc('custom') if st['pic'] else sc('default')}{note}"
        rows = [[_b(sc("✏️ set message"), "st", cid, "ask", "sttext"), _b(sc("🖼 set image"), "st", cid, "ask", "stpic")],
                [_b(sc("↩️ reset"), "st", cid, "clr", "start")], home]
        return text, Markup(rows)

    if screen == "ad":
        a = s["auto_delete"]
        text = sc("<b>⏱ auto-delete</b>\n<blockquote>one panel for both: shared file links and /getvideo.\n"
                  "files are deleted from the user's chat after the timer.</blockquote>")
        def row(scope: str, label: str):
            return [_b(f"{'• ' if a[scope] == p else ''}{dur(p)}", "ad", cid, "ad", f"{scope}:{p}") for p in PRESETS]
        rows = [[Btn(sc("🔗 links"), callback_data="cs|0|x|noop|")], row("links", "links")[:3], row("links", "links")[3:],
                [Btn(sc("🎬 /getvideo"), callback_data="cs|0|x|noop|")], row("video", "video")[:3], row("video", "video")[3:], home]
        return text, Markup(rows)

    if screen == "lg":
        ch = s["user_log_channel"]
        text = sc("<b>🗒 user logs</b>\n<blockquote>new users, opened links, verifications and /getvideo are posted to your channel.\n"
                  "add this bot as admin there first.</blockquote>") + f"\n{sc('channel')}: <code>{ch or sc('not set')}</code>"
        rows = [[_b(sc("➕ set channel"), "lg", cid, "ask", "lgset"), _b(sc("🗑 clear"), "lg", cid, "clr", "log")], home]
        return text, Markup(rows)

    return sc("<b>unknown view</b>"), Markup([[close]])


async def show(message, clone: dict, screen: str):
    text, markup = await render(clone, screen)
    await message.reply_text(text, reply_markup=markup, quote=True, disable_web_page_preview=True)


async def _edit(query, clone: dict, screen: str):
    text, markup = await render(clone, screen)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except MessageNotModified:
        pass


# ------------------------------------------------------------------ callbacks
PROMPTS = {
    "fsadd": "📢 send the <b>channel id</b> (e.g. -100123…), its @username, or <b>forward any post</b> from it.\nthe bot must be admin there.",
    "shdom": "🌐 send your shortener <b>domain</b>, e.g. <code>example.com</code>",
    "shapi": "🔑 send your shortener <b>api key</b>. your message will be deleted right away.",
    "cap": "📝 send the new <b>caption</b> (html ok, max 600 chars). use {filename} / {caption}.",
    "sttext": "✏️ send the new <b>start message</b> (html ok, max 700 chars).",
    "stpic": "🖼 send a <b>photo</b> to use on /start.",
    "lgset": "🗒 send the <b>channel id</b> (or forward a post). the bot must be admin there.",
}
PREMIUM_ONLY = {"shdom": "custom_shortener", "shapi": "custom_shortener", "cap": "custom_caption",
                "sttext": "custom_start", "stpic": "custom_start"}


async def on_callback(client, query):
    _, cid_s, screen, action, arg = (query.data.split("|") + ["", "", "", "", ""])[:5]
    uid = query.from_user.id
    if action == "close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return query.stop_propagation()
    if action == "noop":
        await query.answer()
        return query.stop_propagation()

    clone = await ctx.manager.store.get(int(cid_s))
    if not clone or client.clone_id != clone["_id"] or uid not in (clone["owner_id"], OWNER_ID):
        await query.answer(sc("not allowed"), show_alert=True)
        return query.stop_propagation()

    store, cid = ctx.manager.store, clone["_id"]
    plan, _ = await ctx.manager.plan_of(clone)
    lim, s = limits(plan), clone["settings"]
    alert = None

    if action == "t":
        if arg == "fsub":
            if not s["fsub"]["enabled"] and not s["fsub"]["channels"]:
                alert = "add a force-sub channel first"
            else:
                await store.update(cid, {"settings.fsub.enabled": not s["fsub"]["enabled"]})
        elif arg == "short":
            sh = s["shortener"]
            if not lim["custom_shortener"]:
                alert = "premium feature"
            elif not sh["enabled"] and not (sh["domain"] and sh["api"]):
                alert = "set a domain and api key first"
            else:
                await store.update(cid, {"settings.shortener.enabled": not sh["enabled"]})
        elif arg == "caption":
            if not lim["custom_caption"]:
                alert = "premium feature"
            elif not s["caption"]["enabled"] and not s["caption"]["text"]:
                alert = "set a caption first"
            else:
                await store.update(cid, {"settings.caption.enabled": not s["caption"]["enabled"]})
        elif arg == "brand":
            if not lim["branding_optional"]:
                alert = "branding is mandatory on the free plan"
            else:
                await store.update(cid, {"settings.branding": not s["branding"]})
        elif arg == "protect":
            await store.update(cid, {"settings.protect": not s["protect"]})
    elif action == "ad":
        scope, _, val = arg.partition(":")
        if scope in ("links", "video") and val.isdigit() and int(val) in PRESETS:
            await store.update(cid, {f"settings.auto_delete.{scope}": int(val)})
    elif action == "hrs" and arg.isdigit() and int(arg) in HOURS:
        await store.update(cid, {"settings.shortener.hours": int(arg)})
    elif action == "fsdel" and arg.isdigit():
        chans = list(s["fsub"]["channels"])
        if int(arg) < len(chans):
            chans.pop(int(arg))
            await store.update(cid, {"settings.fsub.channels": chans,
                                     "settings.fsub.enabled": bool(chans) and s["fsub"]["enabled"]})
    elif action == "clr":
        reset = {"short": {"settings.shortener.domain": "", "settings.shortener.api": "", "settings.shortener.enabled": False},
                 "caption": {"settings.caption.text": "", "settings.caption.enabled": False},
                 "start": {"settings.start.text": "", "settings.start.pic": ""},
                 "log": {"settings.user_log_channel": 0}}.get(arg)
        if reset:
            await store.update(cid, reset)
    elif action == "ask" and arg in PROMPTS:
        need = PREMIUM_ONLY.get(arg)
        if need and not lim[need]:
            alert = "premium feature"
        else:
            _pending[(cid, uid)] = {"kind": arg, "expires": time.time() + PENDING_TTL,
                                    "chat_id": query.message.chat.id, "msg_id": query.message.id, "screen": screen}
            await query.answer()
            try:
                await query.message.edit_text(
                    f"<b>{PROMPTS[arg]}</b>",
                    reply_markup=Markup([[_b(sc("✖ cancel"), screen, cid, "cancel")]]))
            except MessageNotModified:
                pass
            return query.stop_propagation()
    elif action == "cancel":
        clear_pending(cid, uid)

    if alert:
        await query.answer(sc(alert), show_alert=True)
    else:
        await query.answer()
    clone = await store.get(cid)
    await _edit(query, clone, screen)
    query.stop_propagation()


# ------------------------------------------------------------------ typed input
async def _resolve_channel(client, message):
    if message.forward_from_chat:
        return message.forward_from_chat.id
    txt = (message.text or "").strip()
    if txt.lstrip("-").isdigit():
        return int(txt)
    if txt.startswith("@"):
        return (await client.get_chat(txt)).id
    return None


async def _bot_is_admin(client, ch: int) -> bool:
    me = await client.get_chat_member(ch, "me")
    return me.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)


async def on_input(client, message):
    cid, uid = client.clone_id, message.from_user.id
    p = _pending.get((cid, uid))
    if not p:
        return
    store = ctx.manager.store
    clone = await store.get(cid)
    if not clone or uid not in (clone["owner_id"], OWNER_ID):
        return
    plan, _ = await ctx.manager.plan_of(clone)
    lim, kind, s = limits(plan), p["kind"], clone["settings"]
    text = (message.text or "").strip()
    err = None
    note = "✅ saved"

    try:
        if kind == "fsadd":
            ch = await _resolve_channel(client, message)
            if ch is None:
                err = "send a channel id, @username, or forward a post from the channel"
            elif any(c["id"] == ch for c in s["fsub"]["channels"]):
                err = "that channel is already added"
            elif len(s["fsub"]["channels"]) >= lim["fsub_limit"]:
                err = f"your plan allows {lim['fsub_limit']} force-sub channel(s)"
            elif not await _bot_is_admin(client, ch):
                err = "make this bot an admin in that channel first, then send it again"
            else:
                chat = await client.get_chat(ch)
                chans = s["fsub"]["channels"] + [{"id": ch, "title": chat.title or str(ch)}]
                await store.update(cid, {"settings.fsub.channels": chans})
                note = "✅ channel added (turn force sub on from the menu)"
        elif kind == "shdom":
            dom = clean_domain(text)
            if not await is_public_domain(dom):
                err = "that doesn't look like a valid public domain"
            else:
                await store.update(cid, {"settings.shortener.domain": dom})
        elif kind == "shapi":
            try:
                await message.delete()
            except Exception:
                pass
            if not 8 <= len(text) <= 200 or " " in text:
                err = "that doesn't look like an api key"
            else:
                await store.update(cid, {"settings.shortener.api": enc(text)})
        elif kind == "cap":
            body = message.text.html if message.text else ""
            if not body or len(body) > 600:
                err = "send text up to 600 characters"
            else:
                await store.update(cid, {"settings.caption.text": body})
        elif kind == "sttext":
            body = message.text.html if message.text else ""
            if not body or len(body) > 700:
                err = "send text up to 700 characters"
            else:
                await store.update(cid, {"settings.start.text": body})
        elif kind == "stpic":
            if not message.photo:
                err = "send a photo"
            else:
                await store.update(cid, {"settings.start.pic": message.photo.file_id})
        elif kind == "lgset":
            ch = await _resolve_channel(client, message)
            if ch is None:
                err = "send a channel id or forward a post from the channel"
            else:
                await client.send_message(ch, sc("✅ log channel connected."))
                await store.update(cid, {"settings.user_log_channel": ch})
    except Exception as e:
        logging.info(f"[clone {cid}] input '{kind}' failed: {e}")
        err = "couldn't verify that, check the bot has access and try again"

    if err:
        await message.reply_text(tpl("<b>⚠️ {e}</b>\n/cancel to stop.", e=sc(err)), quote=True)
        return
    clear_pending(cid, uid)
    clone = await store.get(cid)
    text_out, markup = await render(clone, p["screen"])
    text_out = f"<b>{sc(note)}</b>\n\n{text_out}"
    try:
        await client.edit_message_text(p["chat_id"], p["msg_id"], text_out, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await message.reply_text(text_out, reply_markup=markup, disable_web_page_preview=True)
