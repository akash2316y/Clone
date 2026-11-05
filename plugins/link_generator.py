import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot import Bot
from config import OWNER_ID
from pyrogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove
from asyncio import TimeoutError
from helper_func import encode, get_message_id, is_admin
from database.database import db
from plugins.FORMATS import PLINK_POST_CAPTION_TXT

@Bot.on_message(filters.private & is_admin & filters.command('batch'))
async def batch(client: Client, message: Message):
    while True:
        try:
            first_message = await client.ask(text = "Forward the First Message from DB Channel (with Quotes)..\n\nor Send the DB Channel Post Link", chat_id = message.from_user.id, filters=(filters.forwarded | (filters.text & ~filters.forwarded)), timeout=60)
        except:
            return
        f_msg_id = await get_message_id(client, first_message)
        if f_msg_id:
            break
        else:
            await first_message.reply("❌ Error\n\nthis Forwarded Post is not from my DB Channel or this Link is taken from DB Channel", quote = True)
            continue

    while True:
        try:
            second_message = await client.ask(text = "Forward the Last Message from DB Channel (with Quotes)..\nor Send the DB Channel Post link", chat_id = message.from_user.id, filters=(filters.forwarded | (filters.text & ~filters.forwarded)), timeout=60)
        except:
            return
        s_msg_id = await get_message_id(client, second_message)
        if s_msg_id:
            break
        else:
            await second_message.reply("❌ Error\n\nthis Forwarded Post is not from my DB Channel or this Link is taken from DB Channel", quote = True)
            continue


    string = f"get-{f_msg_id * abs(client.db_channel.id)}-{s_msg_id * abs(client.db_channel.id)}"
    base64_string = await encode(string)
    link = f"https://t.me/{client.username}?start={base64_string}"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]])
    await second_message.reply_text(f"<b>Here is your link</b>\n\n{link}", quote=True, reply_markup=reply_markup)


# ──────────────────────────────────────────────────────────────────────────────
#  /genlink  (OWNER ONLY)
#  Multi-message collector: jitne bhi messages bhejo sab DB channel me store honge
#  aur "Generate Link" dabane par ek single link ban jayega.
#  Buttons: Generate Link | Cancel | Pause (Pause ke baad Resume)
# ──────────────────────────────────────────────────────────────────────────────
_GL = {}  # owner_id -> {"ids": [], "paused": bool, "panel": Message|None, "lock": Lock, "gen": int}


def _gl_text(s):
    if s["paused"]:
        return (
            f"<b>⏸ Paused</b>\n\nStored Messages: <b>{len(s['ids'])}</b>\n\n"
            "<i>Abhi messages store nahi honge. Resume dabao aur phir bhejo.</i>"
        )
    return (
        f"Stored Messages: <b>{len(s['ids'])}</b>\n\n"
        "<i>Want to add more messages? Just send them here!</i>\n\n"
        "<blockquote><i>✨You can now send multiple messages at once.</i></blockquote>"
    )


def _gl_markup(s):
    toggle = (
        InlineKeyboardButton("Resume", callback_data="gl_resume")
        if s["paused"] else
        InlineKeyboardButton("Pause", callback_data="gl_pause")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Generate Link", callback_data="gl_gen")],
        [InlineKeyboardButton("Cancel", callback_data="gl_cancel"), toggle],
    ])


async def _gl_send_panel(client, chat_id, s):
    old = s.get("panel")
    if old:
        try:
            await old.delete()
        except Exception:
            pass
    s["panel"] = await client.send_message(chat_id, _gl_text(s), reply_markup=_gl_markup(s))


async def _gl_refresh_later(client, chat_id, uid, s, gen):
    # Debounce: jab tak messages aate rahenge, panel sirf last message ke baad ek baar aayega
    await asyncio.sleep(1.5)
    if _GL.get(uid) is not s or s["gen"] != gen:
        return
    try:
        await _gl_send_panel(client, chat_id, s)
    except Exception:
        pass


async def _gl_collecting(_, __, message):
    if not message.from_user or message.service:
        return False
    s = _GL.get(message.from_user.id)
    if not s or s["paused"]:
        return False
    if message.text and message.text.startswith("/"):
        return False
    return True

_gl_active = filters.create(_gl_collecting)


@Bot.on_message(filters.private & filters.user(OWNER_ID) & filters.command('genlink'))
async def link_generator(client: Client, message: Message):
    s = _GL.get(message.from_user.id)
    if not s:
        s = {"ids": [], "paused": False, "panel": None, "lock": asyncio.Lock(), "gen": 0}
        _GL[message.from_user.id] = s
    s["paused"] = False
    s["gen"] += 1
    await _gl_send_panel(client, message.chat.id, s)


@Bot.on_message(filters.private & filters.user(OWNER_ID) & _gl_active, group=-1)
async def link_generator_collect(client: Client, message: Message):
    uid = message.from_user.id
    s = _GL.get(uid)
    if not s:
        return
    async with s["lock"]:
        if s["paused"] or _GL.get(uid) is not s:
            return
        try:
            sent = await message.copy(client.db_channel.id, disable_notification=True)
            s["ids"].append(sent.id)
        except Exception as e:
            await message.reply(f"❌ Failed to store this message:\n<code>{e}</code>", quote=True)
            message.stop_propagation()
        s["gen"] += 1
        gen = s["gen"]
    asyncio.create_task(_gl_refresh_later(client, message.chat.id, uid, s, gen))
    message.stop_propagation()


@Bot.on_callback_query(filters.regex(r"^gl_(gen|cancel|pause|resume)$") & filters.user(OWNER_ID), group=-1)
async def link_generator_cb(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    action = query.data[3:]
    s = _GL.get(uid)
    if not s:
        await query.answer("Session expired. /genlink dubara bhejo.", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
        query.stop_propagation()

    if action == "pause":
        s["paused"] = True
        s["gen"] += 1
        await query.message.edit_text(_gl_text(s), reply_markup=_gl_markup(s))
        await query.answer("Paused")

    elif action == "resume":
        s["paused"] = False
        s["gen"] += 1
        await query.message.edit_text(_gl_text(s), reply_markup=_gl_markup(s))
        await query.answer("Resumed")

    elif action == "cancel":
        async with s["lock"]:
            _GL.pop(uid, None)
            ids = list(s["ids"])
        # Is session me store hue messages DB channel se hata do
        for i in range(0, len(ids), 100):
            try:
                await client.delete_messages(client.db_channel.id, ids[i:i + 100])
            except Exception:
                pass
        await query.message.edit_text("<b>❌ Cancelled.</b>\n<blockquote>Stored messages discard kar diye gaye.</blockquote>")
        await query.answer("Cancelled")

    elif action == "gen":
        async with s["lock"]:
            ids = list(s["ids"])
            if not ids:
                await query.answer("Pehle kuch messages bhejo!", show_alert=True)
                query.stop_propagation()
            _GL.pop(uid, None)

        first, last = min(ids), max(ids)
        mult = abs(client.db_channel.id)
        string = f"get-{first * mult}" if first == last else f"get-{first * mult}-{last * mult}"
        base64_string = await encode(string)
        link = f"https://t.me/{client.username}?start={base64_string}"
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]]
        )
        try:
            await query.message.delete()
        except Exception:
            pass
        await client.send_message(
            query.message.chat.id,
            f"<blockquote><b>Here Is Your Link:</b></blockquote>\n\n{link}",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        await query.answer("Link generated")

    query.stop_propagation()


@Bot.on_message(filters.private & is_admin & filters.command("batch2"))
async def custom_batch(client: Client, message: Message):
    collected = []
    STOP_KEYBOARD = ReplyKeyboardMarkup([["STOP"]], resize_keyboard=True)

    await message.reply("Send all messages you want to include in batch.\n\nPress STOP when you're done.", reply_markup=STOP_KEYBOARD)

    while True:
        try:
            user_msg = await client.ask(
                chat_id=message.chat.id,
                text="Waiting for files/messages...\nPress STOP to finish.",
                timeout=60
            )
        except asyncio.TimeoutError:
            break

        if user_msg.text and user_msg.text.strip().upper() == "STOP":
            break

        try:
            sent = await user_msg.copy(client.db_channel.id, disable_notification=True)
            collected.append(sent.id)
        except Exception as e:
            await message.reply(f"❌ Failed to store a message:\n<code>{e}</code>")
            continue

    await message.reply("✅ Batch collection complete.", reply_markup=ReplyKeyboardRemove())

    if not collected:
        await message.reply("❌ No messages were added to batch.")
        return

    start_id = collected[0] * abs(client.db_channel.id)
    end_id = collected[-1] * abs(client.db_channel.id)
    string = f"get-{start_id}-{end_id}"
    base64_string = await encode(string)
    link = f"https://t.me/{client.username}?start={base64_string}"

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]])
    await message.reply(f"<b>Here is your custom batch link:</b>\n\n{link}", reply_markup=reply_markup)


@Bot.on_message(filters.private & is_admin & filters.command("link"))
async def live_link_generator(client: Client, message: Message):
    """
    /link se live mode start hota hai.
    Jab tak /stop nahi bheja jata, jo bhi message/file forward ya
    send karoge, uska link turant (ek-ek karke) generate hoke aa jayega.
    """
    await message.reply(
        "<b>🔗 Live Link Mode Started</b>\n\n"
        "Ab jo bhi message ya file bhejoge / forward karoge, uska link "
        "turant generate ho jayega.\n\n"
        "Jab band karna ho to <code>/stop</code> bhejo.",
    )

    while True:
        try:
            user_msg = await client.ask(
                chat_id=message.chat.id,
                text="⏳ Waiting for the next message...\nSend /stop to finish.",
                timeout=3600,  # 1 hour — is loop me user apni marzi se rukta hai
            )
        except asyncio.TimeoutError:
            await message.reply("⏱ Timeout ho gaya, koi message nahi mila. Live Link Mode band ho gaya.")
            return

        # /stop se loop yahi khatam ho jayega
        if user_msg.text and user_msg.text.strip().lower() == "/stop":
            await user_msg.reply("✅ Live Link Mode stopped.")
            return

        try:
            sent = await user_msg.copy(client.db_channel.id, disable_notification=True)
        except Exception as e:
            await user_msg.reply(f"❌ Failed to store this message:\n<code>{e}</code>", quote=True)
            continue

        msg_id = sent.id * abs(client.db_channel.id)
        base64_string = await encode(f"get-{msg_id}")
        link = f"https://t.me/{client.username}?start={base64_string}"

        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]]
        )
        await user_msg.reply_text(
            f"<b>Here is your link</b>\n\n{link}",
            quote=True,
            reply_markup=reply_markup,
        )


@Bot.on_message(filters.private & is_admin & filters.command("plink"))
async def post_link_generator(client: Client, message: Message):
    """
    /plink [count]  -  sirf Admin ke liye.

    - Files maangega (jitni bhi bhejo).
    - Agar count diya ho, jaise /plink 5, to 5 file milte hi khud aage badh jayega.
    - Sab file milne ke baad, batch link banega.
    - Fir post ke liye ek image maangega (chaho to caption bhi saath bhej sakte ho).
    - Aakhir me, image + caption + batch link wala post, configured Post Channel(s) me bhej dega.
    - Post successfully hone ke 5 second baad, is poore process ke saare working messages
      (jo files/prompts bheje the) khud delete ho jayenge — sirf final result message rahega.
    """
    post_channels = await db.get_all_post_channels()
    if not post_channels:
        return await message.reply(
            "<b>❌ Kᴏɪ Pᴏsᴛ Cʜᴀɴɴᴇʟ sᴇᴛ ɴᴀʜɪ ʜᴀɪ.</b>\n"
            "<blockquote>Pᴇʜʟᴇ /settings ➜ 📢 Post Channel ➜ ➕ Add Channel sᴇ ᴇᴋ ᴄʜᴀɴɴᴇʟ ᴀᴅᴅ ᴋᴀʀᴏ.</blockquote>",
            quote=True
        )

    args = message.text.split()[1:]
    total_files = None
    if args:
        raw = args[0].strip()
        if not raw.isdigit() or int(raw) <= 0:
            return await message.reply(
                "<b>❌ Iɴᴠᴀʟɪᴅ ᴄᴏᴜɴᴛ.</b>\n"
                "<blockquote>Usᴇ: <code>/plink 5</code> — ᴀɢᴀʀ 5 ғɪʟᴇ ʙʜᴇᴊɴɪ ʜᴀɪ.\nYᴀ sɪʀғ <code>/plink</code> ᴀɢᴀʀ ᴄᴏᴜɴᴛ ᴘᴀᴛᴀ ɴᴀʜɪ.</blockquote>",
                quote=True
            )
        total_files = int(raw)

    # Track every working message from this session so the chat can be auto-cleaned once done
    cleanup_msgs = [message]

    if total_files:
        intro = await message.reply(
            f"<b>📥 Tᴏᴛᴀʟ <u>{total_files}</u> ғɪʟᴇ(s) ʙʜᴇᴊᴏ, ᴇᴋ ᴇᴋ ᴋᴀʀᴋᴇ.</b>\n<i>Rᴏᴋɴᴇ ᴋᴇ ʟɪʏᴇ /cancel ʙʜᴇᴊᴏ.</i>",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        intro = await message.reply(
            "<b>📥 Fɪʟᴇs ʙʜᴇᴊɴᴀ sʜᴜʀᴜ ᴋᴀʀᴏ.</b>\n<i>Sᴀʙ ʙʜᴇᴊ ᴄʜᴜᴋᴇ ᴋᴇ ʙᴀᴀᴅ <code>/done</code> ʙʜᴇᴊᴏ. Rᴏᴋɴᴇ ᴋᴇ ʟɪʏᴇ /cancel ʙʜᴇᴊᴏ.</i>",
            reply_markup=ReplyKeyboardMarkup([["✅ Done"], ["❌ Cancel"]], resize_keyboard=True)
        )
    cleanup_msgs.append(intro)

    collected = []
    while True:
        if total_files and len(collected) >= total_files:
            break
        try:
            user_msg = await client.ask(
                chat_id=message.chat.id,
                text=(
                    f"⏳ Fɪʟᴇ {len(collected) + 1}/{total_files} ᴋᴀ ɪɴᴛᴇᴢᴀᴀʀ..."
                    if total_files else
                    "⏳ Aɢʟɪ ғɪʟᴇ ᴋᴀ ɪɴᴛᴇᴢᴀᴀʀ... (ᴋʜᴀᴛᴍ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ /done ʙʜᴇᴊᴏ)"
                ),
                timeout=300
            )
        except asyncio.TimeoutError:
            await message.reply("⏱ Timeout ho gaya. /plink dubara try karo.", reply_markup=ReplyKeyboardRemove())
            return
        cleanup_msgs.append(getattr(user_msg, "request", None))
        cleanup_msgs.append(user_msg)

        txt = (user_msg.text or "").strip().lower()
        if txt in ("/cancel", "cancel", "❌ cancel"):
            await user_msg.reply("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
            return
        if not total_files and txt in ("/done", "done", "✅ done"):
            break

        try:
            sent = await user_msg.copy(client.db_channel.id, disable_notification=True)
            collected.append(sent.id)
        except Exception as e:
            ack = await user_msg.reply(f"❌ Yᴇ ғɪʟᴇ sᴀᴠᴇ ɴᴀʜɪ ʜᴜɪ:\n<code>{e}</code>", quote=True)
            cleanup_msgs.append(ack)
            continue

        if total_files:
            ack = await user_msg.reply(f"✅ Received {len(collected)}/{total_files}", quote=True)
        else:
            ack = await user_msg.reply(f"✅ Received ({len(collected)} ᴀʙ ᴛᴀᴋ). Aᴜʀ ʙʜᴇᴊᴏ ʏᴀ /done ᴋᴀʀᴏ.", quote=True)
        cleanup_msgs.append(ack)

    if not collected:
        await message.reply("❌ Koi file nahi mili. /plink dubara try karo.", reply_markup=ReplyKeyboardRemove())
        return

    start_id = collected[0] * abs(client.db_channel.id)
    end_id = collected[-1] * abs(client.db_channel.id)
    string = f"get-{start_id}" if len(collected) == 1 else f"get-{start_id}-{end_id}"
    base64_string = await encode(string)
    link = f"https://t.me/{client.username}?start={base64_string}"

    while True:
        try:
            img_msg = await client.ask(
                chat_id=message.chat.id,
                text=(
                    "<b>🖼 Aʙ ᴘᴏsᴛ ᴋᴇ ʟɪʏᴇ ᴇᴋ ɪᴍᴀɢᴇ ʙʜᴇᴊᴏ.</b>\n"
                    "<i>Cʜᴀʜᴏ ᴛᴏ ɪᴍᴀɢᴇ ᴋᴇ sᴀᴀᴛʜ ᴀᴘɴᴀ ᴄᴀᴘᴛɪᴏɴ ʙʜɪ ʙʜᴇᴊ sᴀᴋᴛᴇ ʜᴏ, ᴡᴀʀɴᴀ default caption ʟᴀɢ ᴊᴀʏᴇɢᴀ.\n"
                    "Rᴏᴋɴᴇ ᴋᴇ ʟɪʏᴇ /cancel ʙʜᴇᴊᴏ.</i>"
                ),
                reply_markup=ReplyKeyboardRemove(),
                timeout=300
            )
        except asyncio.TimeoutError:
            await message.reply(
                f"⏱ Timeout ho gaya, lekin tumhara batch link ready hai:\n\n{link}",
                reply_markup=ReplyKeyboardRemove(),
                disable_web_page_preview=True
            )
            return
        cleanup_msgs.append(getattr(img_msg, "request", None))
        cleanup_msgs.append(img_msg)

        if img_msg.text and img_msg.text.strip().lower() in ("/cancel", "cancel"):
            await img_msg.reply(
                f"❌ Post cancel ho gaya. Tumhara link phir bhi ready hai:\n\n{link}",
                reply_markup=ReplyKeyboardRemove(),
                disable_web_page_preview=True
            )
            return

        if img_msg.photo:
            break

        invalid_ack = await img_msg.reply("❌ Yᴇ ᴇᴋ ɪᴍᴀɢᴇ (ᴘʜᴏᴛᴏ) ɴᴀʜɪ ᴛʜᴀ. Pʟᴇᴀsᴇ ᴘʜᴏᴛᴏ ʜɪ ʙʜᴇᴊᴏ, ʏᴀ /cancel ᴋᴀʀᴏ.", quote=True)
        cleanup_msgs.append(invalid_ack)

    admin_caption = img_msg.caption.html.strip() if img_msg.caption else ""
    link_line = f"<b>Hᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪɴᴋ </b><blockquote> {link} </blockquote>"
    if admin_caption:
        caption = f"{admin_caption}\n\n{link_line}"
    else:
        caption = f"{PLINK_POST_CAPTION_TXT.format(total=len(collected))}\n\n{link_line}"

    posted, failed = [], []
    for cid in post_channels:
        try:
            await client.send_photo(chat_id=cid, photo=img_msg.photo.file_id, caption=caption)
            posted.append(cid)
        except Exception as e:
            failed.append(f"<code>{cid}</code> — {e}")

    result = (
        f"<b>✅ Bᴀᴛᴄʜ ʟɪɴᴋ ʙᴀɴ ɢᴀʏᴀ ᴀᴜʀ ᴘᴏsᴛ ʜᴏ ɢᴀʏᴀ!</b>\n\n"
        f"<blockquote>{link}</blockquote>\n\n"
        f"📦 Tᴏᴛᴀʟ Fɪʟᴇs: <b>{len(collected)}</b>\n"
        f"📢 Pᴏsᴛᴇᴅ ᴛᴏ: <b>{len(posted)}</b> ᴄʜᴀɴɴᴇʟ(s)"
    )
    if failed:
        result += "\n\n⚠️ Fᴀɪʟᴇᴅ:\n" + "\n".join(failed)
    result += "\n\n<i>🧹 Yᴇ ᴄʜᴀᴛ 5 sᴇᴄᴏɴᴅ ᴍᴇ ᴀᴜᴛᴏ-ᴄʟᴇᴀɴ ʜᴏ ᴊᴀʏᴇɢɪ...</i>"

    await img_msg.reply(result, reply_markup=ReplyKeyboardRemove(), disable_web_page_preview=True)

    # Cleanup: 5 seconds baad, is poore session ke saare working messages delete kardo
    # (final result message chhod kar)
    try:
        await asyncio.sleep(5)
        ids = list({m.id for m in cleanup_msgs if m})
        if ids:
            await client.delete_messages(chat_id=message.chat.id, message_ids=ids)
    except Exception:
        pass


import requests
from urllib.parse import urlparse, urlunparse
from config import SHORTENER_DOMAIN, SHORTENER_API_KEY, PROTECT_API_URL

async def _protect_endpoint() -> str:
    protect_api_url = await db.get_protect_api_url()
    if not protect_api_url:
        from config import PROTECT_API_URL
        protect_api_url = PROTECT_API_URL
    parsed = urlparse(protect_api_url.strip())
    path = parsed.path.rstrip("/")
    if not path:
        path = "/protect"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


async def _create_masked_link(url: str) -> str:
    shortener_domain = await db.get_shortener_url()
    shortener_api = await db.get_shortener_api()
    if not shortener_domain or not shortener_api:
        from config import SHORTENER_DOMAIN, SHORTENER_API_KEY
        shortener_domain = SHORTENER_DOMAIN
        shortener_api = SHORTENER_API_KEY

    payload = {
        "url": url,
        "shortener_domain": shortener_domain,
        "shortener_api": shortener_api,
    }

    endpoint = await _protect_endpoint()

    def call_api():
        response = requests.post(endpoint, json=payload, timeout=30)
        if response.status_code == 405 and not endpoint.rstrip("/").endswith("/protect"):
            retry_endpoint = endpoint.rstrip("/") + "/protect"
            response = requests.post(retry_endpoint, json=payload, timeout=30)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            try:
                message = response.json().get("message")
            except ValueError:
                message = response.text[:300]
            raise RuntimeError(message or str(e)) from e
        return response.json()

    data = await asyncio.to_thread(call_api)
    if data.get("status") != "success" or not data.get("url"):
        raise ValueError(data.get("message", "Protect API did not return a masked URL"))
    return data["url"]


@Bot.on_message(filters.command('mask') & filters.private & is_admin)
async def mask_link(client: Client, message: Message):
    shortener_domain = await db.get_shortener_url() or SHORTENER_DOMAIN
    shortener_api = await db.get_shortener_api() or SHORTENER_API_KEY
    if not shortener_domain or not shortener_api:
        return await message.reply_text(
            "<b>❌ Mask setup incomplete.</b>\n<blockquote>Configure Shortener Site and API key in database or env vars first.</blockquote>",
            disable_web_page_preview=True,
        )

    parts = message.text.split(maxsplit=1) if message.text else []
    target_url = parts[1].strip() if len(parts) > 1 else ""
    if not target_url and message.reply_to_message and message.reply_to_message.text:
        target_url = message.reply_to_message.text.strip()

    if not target_url.startswith(("http://", "https://")):
        return await message.reply_text(
            "<b>Usage:</b> <code>/mask link</code>",
            disable_web_page_preview=True,
        )

    status = await message.reply_text("<b>🛡️ Creating protected mask link...</b>", disable_web_page_preview=True)
    try:
        masked_url = await _create_masked_link(target_url)
    except Exception as e:
        return await status.edit_text(
            f"<b>❌ Failed to create mask link.</b>\n<blockquote>{e}</blockquote>",
            disable_web_page_preview=True,
        )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Share Mask URL", url=f"https://telegram.me/share/url?url={masked_url}")],
        [InlineKeyboardButton("🛡️ Open Protected Link", url=masked_url)],
    ])
    await status.edit_text(
        f"<b>✅ Mask Link Generated</b>\n<blockquote>{masked_url}</blockquote>",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
