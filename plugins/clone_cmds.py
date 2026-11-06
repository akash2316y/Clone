"""
Main-bot side of the clone system:
  /clone /myclone            users create and manage their clones
  /ownerpanel                owner: clone engine ON/OFF, limits, manage every clone
  /addadmin /deladmin /addban /delban /addpremium /rempremium /predetails
  /cmd /commands             categorized command index
  + anti-spam / ban gate for the main bot itself
"""
import asyncio
import logging
import time

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from bot import Bot
from config import OWNER_ID
from database.database import db
from helper_func import is_admin
from clone import ctx, logs
from clone import antispam
from clone.cmdlist import commands_text
from clone.manager import find_token
from clone.plans import PERKS_FREE, PERKS_PREMIUM, limits
from clone.store import ACTIVE, BANNED, PAUSED
from clone.ui import esc, fmt_ts, left, parse_duration, sc, tpl

PAGE = 5
STATUS_ICON = {"active": "🟢", "paused": "⏸", "expired": "⏰", "crashed": "💥", "invalid": "🔑", "banned": "🚫"}


# ============================================================== gate (ban + anti-spam) for the main bot
@Bot.on_message(filters.private, group=-2)
async def _gate_message(client, message):
    await antispam.gate(client, message)


@Bot.on_callback_query(group=-2)
async def _gate_callback(client, query):
    await antispam.gate(client, query)


# ============================================================== helpers
def _ready(message):
    return ctx.manager is not None


async def _is_staff(uid: int) -> bool:
    return uid == OWNER_ID or await antispam.is_exempt(uid)


async def _target(message):
    """user id from '/cmd <id>' or from a replied message."""
    parts = message.text.split()
    if len(parts) > 1 and parts[1].lstrip("-").isdigit():
        return int(parts[1])
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


def _usage(text: str) -> str:
    return f"<b>{sc('usage:')}</b> <code>{text}</code>"


# ============================================================== /cmd
@Bot.on_message(filters.command(["cmd", "commands"]) & filters.private)
async def cmd_index(client, message):
    await message.reply_text(commands_text("main"), quote=True)


# ============================================================== admin management
@Bot.on_message(filters.command("addadmin") & filters.private & filters.user(OWNER_ID))
async def add_admin_cmd(client, message):
    uid = await _target(message)
    if not uid:
        return await message.reply_text(_usage("/addadmin &lt;user_id&gt;"), quote=True)
    if await db.admin_exist(uid):
        return await message.reply_text(sc("<b>already an admin.</b>"), quote=True)
    await db.add_admin(uid)
    antispam.invalidate(uid)
    await logs.admin_log(tpl("<b>➕ admin added</b>: <code>{id}</code> by <code>{by}</code>", id=uid, by=message.from_user.id))
    await message.reply_text(tpl("<b>✅ <code>{id}</code> is now an admin.</b>", id=uid), quote=True)


@Bot.on_message(filters.command("deladmin") & filters.private & filters.user(OWNER_ID))
async def del_admin_cmd(client, message):
    uid = await _target(message)
    if not uid:
        return await message.reply_text(_usage("/deladmin &lt;user_id&gt;"), quote=True)
    if not await db.admin_exist(uid):
        return await message.reply_text(sc("<b>that user is not an admin.</b>"), quote=True)
    await db.del_admin(uid)
    antispam.invalidate(uid)
    await logs.admin_log(tpl("<b>➖ admin removed</b>: <code>{id}</code> by <code>{by}</code>", id=uid, by=message.from_user.id))
    await message.reply_text(tpl("<b>✅ <code>{id}</code> is no longer an admin.</b>", id=uid), quote=True)


@Bot.on_message(filters.command("addban") & filters.private & is_admin)
async def add_ban_cmd(client, message):
    uid = await _target(message)
    if not uid:
        return await message.reply_text(_usage("/addban &lt;user_id&gt;"), quote=True)
    if await _is_staff(uid):
        return await message.reply_text(sc("<b>you can't ban the owner or an admin.</b>"), quote=True)
    if await db.ban_user_exist(uid):
        return await message.reply_text(sc("<b>already banned.</b>"), quote=True)
    await db.add_ban_user(uid)
    antispam.invalidate(uid)
    if ctx.manager:
        asyncio.create_task(ctx.manager.pause_owner_clones(uid, BANNED, "the owner of this clone was banned"))
    await logs.admin_log(tpl("<b>🚫 user banned</b>: <code>{id}</code> by <code>{by}</code>", id=uid, by=message.from_user.id))
    await message.reply_text(tpl("<b>🚫 <code>{id}</code> banned system-wide (main bot + all clones).</b>", id=uid), quote=True)


@Bot.on_message(filters.command("delban") & filters.private & is_admin)
async def del_ban_cmd(client, message):
    uid = await _target(message)
    if not uid:
        return await message.reply_text(_usage("/delban &lt;user_id&gt;"), quote=True)
    if not await db.ban_user_exist(uid):
        return await message.reply_text(sc("<b>that user is not banned.</b>"), quote=True)
    await db.del_ban_user(uid)
    antispam.invalidate(uid)
    if ctx.manager:
        asyncio.create_task(ctx.manager.resume_owner_clones(uid, only_status=BANNED))
    await logs.admin_log(tpl("<b>✅ user unbanned</b>: <code>{id}</code> by <code>{by}</code>", id=uid, by=message.from_user.id))
    await message.reply_text(tpl("<b>✅ <code>{id}</code> unbanned.</b>", id=uid), quote=True)


# ============================================================== premium management
@Bot.on_message(filters.command("addpremium") & filters.private & is_admin)
async def add_premium_cmd(client, message):
    parts = message.text.split()
    help_ = _usage("/addpremium &lt;user_id&gt; &lt;duration&gt;") + "\n" + sc("duration: 30m, 12h, 7d, 2w, 1mo, 1y")
    if len(parts) < 3 or not parts[1].lstrip("-").isdigit():
        return await message.reply_text(help_, quote=True)
    uid, secs = int(parts[1]), parse_duration(parts[2])
    if not secs:
        return await message.reply_text(help_, quote=True)
    expiry = await db.add_premium_duration(uid, secs)
    if ctx.manager:
        ctx.manager.invalidate_plans()
        asyncio.create_task(ctx.manager.expiry_pass(owner_id=uid))
    try:
        await client.send_message(uid, tpl("<b>🎉 premium activated!</b>\n<blockquote>valid until {d}</blockquote>\nsend /predetails to see your perks.",
                                           d=fmt_ts(expiry.timestamp())))
    except Exception:
        pass
    await logs.admin_log(tpl("<b>👑 premium granted</b>: <code>{id}</code> +{t} by <code>{by}</code>\nuntil {d}",
                             id=uid, t=esc(parts[2]), by=message.from_user.id, d=fmt_ts(expiry.timestamp())))
    await message.reply_text(tpl("<b>✅ premium granted to <code>{id}</code></b>\n<blockquote>expires: {d}</blockquote>",
                                 id=uid, d=fmt_ts(expiry.timestamp())), quote=True)


@Bot.on_message(filters.command("rempremium") & filters.private & is_admin)
async def rem_premium_cmd(client, message):
    uid = await _target(message)
    if not uid:
        return await message.reply_text(_usage("/rempremium &lt;user_id&gt;"), quote=True)
    if not await db.is_premium(uid):
        return await message.reply_text(sc("<b>that user has no active premium.</b>"), quote=True)
    await db.remove_premium(uid)
    if ctx.manager:
        ctx.manager.invalidate_plans()
        asyncio.create_task(ctx.manager.expiry_pass(owner_id=uid))
    await logs.admin_log(tpl("<b>👑 premium revoked</b>: <code>{id}</code> by <code>{by}</code>", id=uid, by=message.from_user.id))
    await message.reply_text(tpl("<b>✅ premium revoked for <code>{id}</code>.</b>", id=uid), quote=True)


@Bot.on_message(filters.command("predetails") & filters.private)
async def pre_details_cmd(client, message):
    caller = message.from_user.id
    uid = await _target(message)
    if uid and uid != caller and not await _is_staff(caller):
        return await message.reply_text(sc("<b>🔒 only admins can look up other users.</b>"), quote=True)
    uid = uid or caller

    exp = await db.get_premium_expiry(uid)
    ts = exp.timestamp() if exp else None
    active = bool(ts and ts > time.time())
    plan = "premium" if active else "free"

    from config import FREE_FSUB_LIMIT, PREMIUM_FSUB_LIMIT
    perks = [p.format(n=PREMIUM_FSUB_LIMIT) for p in PERKS_PREMIUM] if active else [p.format(n=FREE_FSUB_LIMIT) for p in PERKS_FREE]
    perk_txt = "\n".join(f"{'✅' if active else '•'} {sc(p)}" for p in perks)

    lines = []
    if ctx.manager:
        for c in await ctx.manager.store.by_owner(uid):
            lines.append(f"{STATUS_ICON.get(c['status'], '•')} @{c['username']} — {sc(c['status'])}")
    cap = (await ctx.manager.store.get_global())["max_clones"] if ctx.manager else 0

    text = tpl("<b>👑 premium details</b>\n<blockquote>user: <code>{id}</code>\nplan: {plan}\nexpires: {exp}\ntime left: {left}</blockquote>\n"
               "<b>perks</b>\n{perks}\n\n<b>clones</b> ({n}/{cap})\n{clones}",
               id=uid, plan=("👑 " + sc("premium")) if active else ("🆓 " + sc("free")),
               exp=fmt_ts(ts) if active else sc("n/a"), left=left(ts) if active else sc("n/a"),
               perks=perk_txt, n=len(lines), cap=cap, clones="\n".join(lines) or sc("none"))
    await message.reply_text(text, quote=True)


# ============================================================== /clone
@Bot.on_message(filters.command("start") & filters.private & filters.regex(r"^/start(@\w+)?\s+clone$"), group=-1)
async def start_clone_payload(client, message):
    """Opened from the 'Create my own clone' button inside a clone bot."""
    await clone_cmd(client, message)
    message.stop_propagation()


@Bot.on_message(filters.command("clone") & filters.private)
async def clone_cmd(client, message):
    mgr = ctx.manager
    if mgr is None:
        return await message.reply_text(sc("<b>clone engine is starting, try again in a moment.</b>"), quote=True)
    if not mgr.cfg["allow_cloning"]:
        return await message.reply_text(sc("<b>🚫 cloning is currently turned off.</b>"), quote=True)

    token = find_token(message.text)
    if not token:
        return await message.reply_text(
            sc("<b>🤖 create your own bot</b>\n<blockquote>1. open @BotFather and send /newbot\n2. copy the token it gives you\n"
               "3. send it here:</blockquote>") + "\n<code>/clone 123456:ABC-your-token</code>", quote=True)

    try:                                    # the token is a password: remove it from the chat
        await message.delete()
    except Exception:
        pass
    uid = message.from_user.id
    wait = await client.send_message(uid, sc("<b>⏳ setting up your bot...</b>"))
    ok, res = await mgr.create_clone(uid, token, privileged=await _is_staff(uid))
    if not ok:
        return await wait.edit_text(tpl("<b>❌ {e}</b>", e=sc(res) if not res.startswith("couldn't start") else esc(res)))
    await wait.edit_text(
        tpl("<b>✅ your clone is live!</b>\n<blockquote>bot: @{u}\nopen it and send /settings to configure,\n/myclone for your dashboard.</blockquote>"
            "\n<i>your token message was deleted. never share it with anyone.</i>", u=res["username"]),
        reply_markup=Markup([[Btn(sc("🤖 open my bot"), url=f"https://t.me/{res['username']}")]]))


# ============================================================== clone list / detail (users + staff)
async def _can_manage(uid: int, clone: dict) -> bool:
    return uid == clone["owner_id"] or await _is_staff(uid)


async def _clone_detail(clone: dict):
    mgr = ctx.manager
    plan, vu = await mgr.plan_of(clone)
    total, active = await mgr.store.user_counts(clone["_id"], time.time() - 86400)
    st = clone["stats"]
    running = mgr.is_running(clone["_id"])
    text = tpl("<b>🤖 @{u}</b>\n<blockquote>owner: <code>{o}</code>\nplan: {plan}  •  valid: {valid}\nstatus: {status}</blockquote>\n"
               "<b>👥</b> {active}/{total}   <b>📁</b> {files}   <b>🔗</b> {links}",
               u=clone["username"], o=clone["owner_id"],
               plan=("👑 " + sc("premium")) if plan == "premium" else ("🆓 " + sc("free")), valid=left(vu),
               status=("🟢 " + sc("running")) if running else f"{STATUS_ICON.get(clone['status'], '•')} {sc(clone['status'])}",
               active=active, total=total, files=st.get("files", 0), links=st.get("links", 0))
    cid = clone["_id"]
    toggle = Btn(sc("⏸ pause"), callback_data=f"cl|pause|{cid}") if clone["status"] == ACTIVE else Btn(sc("▶️ resume"), callback_data=f"cl|resume|{cid}")
    rows = [[toggle, Btn(sc("🔄 restart"), callback_data=f"cl|restart|{cid}")],
            [Btn(sc("🤖 open"), url=f"https://t.me/{clone['username']}"), Btn(sc("🗑 delete"), callback_data=f"cl|del|{cid}")],
            [Btn(sc("‹ back"), callback_data="cl|list|0")]]
    return text, Markup(rows)


async def _list_view(uid: int, page: int, staff_all: bool):
    mgr = ctx.manager
    clones = await mgr.store.all() if staff_all else await mgr.store.by_owner(uid)
    pages = max((len(clones) - 1) // PAGE + 1, 1)
    page = min(max(page, 0), pages - 1)
    chunk = clones[page * PAGE:(page + 1) * PAGE]
    if not clones:
        return sc("<b>you have no clones yet.\nsend /clone &lt;token&gt; to create one.</b>"), None
    head = sc("<b>🤖 all clones</b>" if staff_all else "<b>🤖 your clones</b>") + f" ({len(clones)})"
    rows = [[Btn(f"{STATUS_ICON.get(c['status'], '•')} @{c['username']}", callback_data=f"cl|view|{c['_id']}")] for c in chunk]
    nav = []
    if page > 0:
        nav.append(Btn("‹", callback_data=f"cl|{'all' if staff_all else 'list'}|{page - 1}"))
    if page < pages - 1:
        nav.append(Btn("›", callback_data=f"cl|{'all' if staff_all else 'list'}|{page + 1}"))
    if nav:
        rows.append(nav)
    return head, Markup(rows)


@Bot.on_message(filters.command("myclone") & filters.private)
async def my_clone_cmd(client, message):
    if ctx.manager is None:
        return await message.reply_text(sc("<b>clone engine is starting, try again in a moment.</b>"), quote=True)
    text, markup = await _list_view(message.from_user.id, 0, False)
    await message.reply_text(text, reply_markup=markup, quote=True)


# ============================================================== owner panel
async def _panel():
    mgr = ctx.manager
    c, cfg = await mgr.counts(), mgr.cfg
    on = cfg["allow_cloning"]
    days = cfg["free_days"]
    text = tpl("<b>👑 owner panel — clone engine</b>\n<blockquote>engine: {eng}\nmax clones / user: {m}\nfree clone validity: {d}</blockquote>\n"
               "<b>total</b> {t}  <b>running</b> {r}  <b>active</b> {a}\n<b>paused</b> {p}  <b>expired</b> {e}  <b>crashed</b> {cr}  <b>invalid</b> {i}",
               eng=("🟢 " + sc("on")) if on else ("🔴 " + sc("off")), m=cfg["max_clones"],
               d=(f"{days} " + sc("days")) if days else sc("unlimited"),
               t=c["total"], r=c["running"], a=c["active"], p=c["paused"], e=c["expired"], cr=c["crashed"], i=c["invalid"])
    rows = [
        [Btn(sc("🔴 turn engine off") if on else sc("🟢 turn engine on"), callback_data="op|toggle|0")],
        [Btn("➖", callback_data="op|max|-1"), Btn(sc(f"max clones: {cfg['max_clones']}"), callback_data="op|noop|0"), Btn("➕", callback_data="op|max|1")],
        [Btn("-7", callback_data="op|days|-7"), Btn("-1", callback_data="op|days|-1"), Btn(sc("free days"), callback_data="op|noop|0"),
         Btn("+1", callback_data="op|days|1"), Btn("+7", callback_data="op|days|7")],
        [Btn(sc("📋 all clones"), callback_data="cl|all|0"), Btn(sc("🔄 restart all"), callback_data="op|restartall|0")],
        [Btn(sc("✖ close"), callback_data="close")],
    ]
    return text, Markup(rows)


@Bot.on_message(filters.command(["ownerpanel", "opanel"]) & filters.private & filters.user(OWNER_ID))
async def owner_panel_cmd(client, message):
    if ctx.manager is None:
        return await message.reply_text(sc("<b>clone engine is starting, try again in a moment.</b>"), quote=True)
    text, markup = await _panel()
    await message.reply_text(text, reply_markup=markup, quote=True)


async def _edit(query, text, markup):
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
            logging.info(f"edit failed: {e}")


@Bot.on_callback_query(filters.regex(r"^(cl|op)\|"), group=-1)
async def clone_callbacks(client, query):
    mgr, uid = ctx.manager, query.from_user.id
    kind, action, arg = (query.data.split("|") + ["", ""])[:3]
    try:
        if mgr is None:
            return await query.answer(sc("starting up..."), show_alert=True)
        staff = await _is_staff(uid)

        # ---------- owner panel ----------
        if kind == "op":
            if uid != OWNER_ID:
                return await query.answer(sc("owner only"), show_alert=True)
            if action == "toggle":
                await mgr.set_cfg(allow_cloning=not mgr.cfg["allow_cloning"])
                await logs.admin_log(tpl("<b>⚙️ clone engine {s}</b> by <code>{by}</code>", s=sc("on" if mgr.cfg["allow_cloning"] else "off"), by=uid))
            elif action == "max":
                await mgr.set_cfg(max_clones=max(1, int(mgr.cfg["max_clones"]) + int(arg)))
            elif action == "days":
                await mgr.set_cfg(free_days=max(0, int(mgr.cfg["free_days"]) + int(arg)))
            elif action == "restartall":
                await query.answer(sc("restarting all clones..."))
                asyncio.create_task(_restart_all())
                return
            elif action == "noop":
                return await query.answer()
            await query.answer()
            return await _edit(query, *await _panel())

        # ---------- clone list / detail / actions ----------
        if action in ("list", "all"):
            await query.answer()
            return await _edit(query, *await _list_view(uid, int(arg or 0), action == "all" and staff))

        cid = int(arg)
        clone = await mgr.store.get(cid)
        if not clone:
            await query.answer(sc("clone not found"), show_alert=True)
            return await _edit(query, *await _list_view(uid, 0, staff))
        if not await _can_manage(uid, clone):
            return await query.answer(sc("not allowed"), show_alert=True)

        if action == "view":
            await query.answer()
            return await _edit(query, *await _clone_detail(clone))
        if action == "pause":
            await mgr.pause(cid, PAUSED, f"paused by {uid}")
            await query.answer(sc("paused"))
        elif action == "resume":
            ok, err = await mgr.resume(cid)
            await query.answer(sc("resumed") if ok else err[:180], show_alert=not ok)
        elif action == "restart":
            if not staff:
                return await query.answer(sc("admins only"), show_alert=True)
            ok, err = await mgr.restart(cid)
            await query.answer(sc("restarted") if ok else err[:180], show_alert=not ok)
        elif action == "del":
            await query.answer()
            return await _edit(query, tpl("<b>🗑 delete @{u}?</b>\n<blockquote>its settings, users and stats will be removed. this can't be undone.</blockquote>", u=clone["username"]),
                               Markup([[Btn(sc("yes, delete"), callback_data=f"cl|delok|{cid}"), Btn(sc("cancel"), callback_data=f"cl|view|{cid}")]]))
        elif action == "delok":
            await mgr.delete(cid, uid)
            await query.answer(sc("deleted"))
            return await _edit(query, *await _list_view(uid, 0, False))
        clone = await mgr.store.get(cid)
        await _edit(query, *await _clone_detail(clone))
    except Exception as e:
        logging.error(f"clone callback failed: {e}", exc_info=True)
        try:
            await query.answer(sc("something went wrong"), show_alert=True)
        except Exception:
            pass
    finally:
        query.stop_propagation()


async def _restart_all():
    mgr = ctx.manager
    for cid in list(mgr.rt):
        await mgr.restart(cid)
