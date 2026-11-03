import asyncio
import base64
import logging
import os
import random
import re
import string as _string
import time
from pyrogram import Client, filters, __version__
from pyrogram.enums import ParseMode, ChatAction
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from plugins.autoDelete import auto_del_notification, delete_message
from bot import Bot
from config import *
from helper_func import *
from database.database import *
from config import *
from plugins.FORMATS import *
from plugins.link_generator import _create_masked_link
from pyrogram.errors.exceptions.bad_request_400 import PeerIdInvalid
from datetime import datetime, timedelta
from pytz import timezone


# Enable logging
logging.basicConfig(level=logging.INFO)
IST = timezone('Asia/Kolkata')
#today = str(datetime.date.today())


@Bot.on_message(filters.command('start') & filters.private)
async def start_command(client: Client, message: Message):
    id = message.from_user.id

    # Default initialization
    AUTO_DEL = False
    DEL_TIMER = 0
    HIDE_CAPTION = False
    CHNL_BTN = None
    PROTECT_MODE = False
    last_message = None
    messages = []

    VERIFY_EXPIRE = await db.get_verified_time()  # Fetch verification expiration time
    logging.info(f"Received /start command from user ID: {id}")

    # Check and add user to the database if not present
    if not await db.present_user(id):
        try:
            await db.add_user(id)
        except Exception as e:
            logging.error(f"Error adding user: {e}")
            return

    text = message.text
    verify_status = await db.get_verify_status(id)

    # Handle expired verification
    if (
        verify_status['is_verified'] and
        VERIFY_EXPIRE is not None and
        VERIFY_EXPIRE < (time.time() - verify_status['verified_time'])
    ):
        await db.update_verify_status(id, is_verified=False)

    is_premium = await db.is_premium(id)

    logging.info(f"Verify status: {verify_status}")
    logging.info(f"Is premium: {is_premium}")

        # Handle token verification
    if "verify_" in message.text:
        _, token = message.text.split("_", 1)
        if verify_status['verify_token'] != token:
            return await message.reply("⚠️ Yᴏᴜʀ ᴛᴏᴋᴇɴ ɪs ɪɴᴠᴀʟɪᴅ ᴏʀ ᴇxᴘɪʀᴇᴅ. Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ᴡɪᴛʜ /start.")
        await db.update_verify_status(id, is_verified=True, verified_time=time.time())
        pending_link = verify_status.get("link", "")
        if pending_link:
            # Redirect user to their original file automatically
            await message.reply(
                f"✅ Yᴏᴜʀ ᴛᴏᴋᴇɴ ʜᴀs ʙᴇᴇɴ ᴠᴇʀɪғɪᴇᴅ! Fᴇᴛᴄʜɪɴɢ ʏᴏᴜʀ ғɪʟᴇ...",
                quote=True
            )
            # Redirect by re-constructing the /start call with the pending base64 link
            fake_message = message
            fake_message.text = f"/start {pending_link}"
            try:
                fake_message.command = ["start", pending_link]
            except Exception:
                pass
            # Directly decode and process the pending link
            pending_string = await decode(pending_link)
            if pending_string and pending_string.startswith("get"):
                argument = pending_string.split("-")
                if len(argument) == 3:
                    try:
                        start_id = int(int(argument[1]) / abs(client.db_channel.id))
                        end_id = int(int(argument[2]) / abs(client.db_channel.id))
                    except Exception:
                        return
                    ids = range(start_id, end_id + 1) if start_id <= end_id else range(start_id, end_id - 1, -1)
                elif len(argument) == 2:
                    try:
                        ids = [int(int(argument[1]) / abs(client.db_channel.id))]
                    except Exception:
                        return
                else:
                    return

                temp_msg = await message.reply("Please wait...")
                try:
                    messages = await get_messages(client, ids)
                except Exception:
                    await message.reply_text("Something went wrong..!")
                    return
                await temp_msg.delete()

                AUTO_DEL, DEL_TIMER, HIDE_CAPTION, CHNL_BTN, PROTECT_MODE = await asyncio.gather(
                    db.get_auto_delete(), db.get_del_timer(), db.get_hide_caption(),
                    db.get_channel_button(), db.get_protect_content()
                )
                if CHNL_BTN:
                    button_name, button_link = await db.get_channel_button_link()

                last_message = None
                for idx, msg in enumerate(messages):
                    original_caption = msg.caption.html if msg.caption else ""
                    caption = (
                        f"{CUSTOM_CAPTION}"
                        if CUSTOM_CAPTION else original_caption
                    )
                    if HIDE_CAPTION and (msg.document or msg.audio or msg.video or msg.photo):
                        caption += f"\n\n{CUSTOM_CAPTION}"
                    reply_markup = InlineKeyboardMarkup(
                        [[InlineKeyboardButton(text=button_name, url=button_link)]]
                    ) if CHNL_BTN else msg.reply_markup
                    try:
                        copied_msg = await msg.copy(
                            chat_id=id, caption=caption, parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup, protect_content=PROTECT_MODE
                        )
                        if AUTO_DEL:
                            asyncio.create_task(delete_message(copied_msg, DEL_TIMER))
                            if idx == len(messages) - 1:
                                last_message = copied_msg
                    except FloodWait as e:
                        await asyncio.sleep(e.x)
                        copied_msg = await msg.copy(
                            chat_id=id, caption=caption, parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup, protect_content=PROTECT_MODE
                        )
                        if AUTO_DEL:
                            asyncio.create_task(delete_message(copied_msg, DEL_TIMER))
                            if idx == len(messages) - 1:
                                last_message = copied_msg

                if AUTO_DEL and last_message:
                    asyncio.create_task(auto_del_notification(client.username, last_message, DEL_TIMER, pending_link))
        else:
            await message.reply(
                f"✅ Yᴏᴜʀ ᴛᴏᴋᴇɴ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssғᴜʟʟʏ ᴠᴇʀɪғɪᴇᴅ ᴀɴᴅ ɪs ᴠᴀʟɪᴅ ғᴏʀ {get_exp_time(VERIFY_EXPIRE)}.",
                reply_markup=PREMIUM_BUTTON,
                protect_content=False,
                quote=True
            )
        return  # Always return after handling verify — never fall through to base64 decode

    try:
        base64_string = text.split(" ", 1)[1]
    except IndexError:
        base64_string = None

    if base64_string:
        string = await decode(base64_string)

        if not string:
            return  # invalid / malformed base64 param — silently ignore

        # Handle premium content
        if string.startswith("premium"):
            if not is_premium:
                return await message.reply(
                    f"𝗕𝘂𝘆 𝗽𝗿𝗲𝗺𝗶𝘂𝗺 𝘁𝗼 𝗮𝗰𝗰𝗲𝘀𝘀 𝘁𝗵𝗶𝘀 𝗰𝗼𝗻𝘁𝗲𝗻𝘁.\𝗻𝗧𝗼 𝗯𝘂𝘆, 𝗰𝗼𝗻𝘁𝗮𝗰𝘁 @{OWNER_TAG}",
                    reply_markup=PREMIUM_BUTTON2
                )

            argument = string.split("-")
            if len(argument) == 3:
                try:
                    start = int(int(argument[1]) / abs(client.db_channel.id))
                    end = int(int(argument[2]) / abs(client.db_channel.id))
                except:
                    return
                ids = range(start, end + 1) if start <= end else range(start, end - 1, -1)
            elif len(argument) == 2:
                try:
                    ids = [int(int(argument[1]) / abs(client.db_channel.id))]
                except:
                    return
            else:
                return

            temp_msg = await message.reply("Please wait...")
            try:
                messages = await get_messages(client, ids)
            except:
                await message.reply_text("Something went wrong..!")
                return
            await temp_msg.delete()

            AUTO_DEL, DEL_TIMER, HIDE_CAPTION, CHNL_BTN, PROTECT_MODE = await asyncio.gather(
                db.get_auto_delete(), db.get_del_timer(), db.get_hide_caption(),
                db.get_channel_button(), db.get_protect_content()
            )

            if CHNL_BTN:
                button_name, button_link = await db.get_channel_button_link()

            for idx, msg in enumerate(messages):
                original_caption = msg.caption.html if msg.caption else ""
                caption = (
                    f"{CUSTOM_CAPTION}"
                    #f"{original_caption}\n\n{CUSTOM_CAPTION}"
                    if CUSTOM_CAPTION else original_caption
                )
                if HIDE_CAPTION and (msg.document or msg.audio or msg.video or msg.photo):
                    caption += f"\n\n{CUSTOM_CAPTION}"

                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text=button_name, url=button_link)]]
                ) if CHNL_BTN else msg.reply_markup

                try:
                    copied_msg = await msg.copy(
                        chat_id=id, caption=caption, parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup, protect_content=PROTECT_MODE
                    )
                    if AUTO_DEL:
                        asyncio.create_task(delete_message(copied_msg, DEL_TIMER))
                        if idx == len(messages) - 1:
                            last_message = copied_msg

                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    copied_msg = await msg.copy(
                        chat_id=id, caption=caption, parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup, protect_content=PROTECT_MODE
                    )
                    await asyncio.sleep(0.1)

                    if AUTO_DEL:
                        asyncio.create_task(delete_message(copied_msg, DEL_TIMER))
                        if idx == len(messages) - 1:
                            last_message = copied_msg

            if AUTO_DEL and last_message:
                asyncio.create_task(auto_del_notification(client.username, last_message, DEL_TIMER, message.command[1]))

        # Handle content fetching with ads
        elif string.startswith("get"):
            is_premium_user = await db.is_premium(id)
            is_admin_user = any([id == OWNER_ID, await db.admin_exist(id)])

            if not is_admin_user and not is_premium_user:
                protect_mode = await db.get_protect_mode()
                shortener_mode = await db.get_shortener_mode()

                if protect_mode or shortener_mode:
                    verify_status = await db.get_verify_status(id)
                    VERIFY_EXPIRE = await db.get_verified_time()

                    # Handle expired verification
                    if verify_status["is_verified"] and VERIFY_EXPIRE:
                        if VERIFY_EXPIRE < (time.time() - verify_status["verified_time"]):
                            await db.update_verify_status(id, is_verified=False)
                            verify_status["is_verified"] = False

                    # If not verified, check free limits
                    if not verify_status["is_verified"]:
                        free_enabled = await db.get_free_enabled()
                        free_limit = await db.get_free_limit()
                        free_count = await db.get_user_free_used(id)

                        if free_enabled and free_count < free_limit:
                            await db.increment_user_free_used(id)
                        else:
                            # User has exhausted free slots and is not verified -> show verify screen
                            token = ''.join(random.choices(_string.ascii_letters + _string.digits, k=10))
                            direct_verify_link = f"https://t.me/{client.username}?start=verify_{token}"
                            await db.update_verify_status(id, verify_token=token, verified_time=time.time(), link=base64_string)

                            if protect_mode:
                                verify_link = await _create_masked_link(direct_verify_link)
                            else:
                                verify_link = await get_shortlink(direct_verify_link)

                            tut_vid = await db.get_tut_video()
                            btn = [[InlineKeyboardButton("• ᴠᴇʀɪғʏ •", url=verify_link)]]
                            if tut_vid:
                                btn[0].append(InlineKeyboardButton("• ʜᴏᴡ ᴛᴏ ᴠᴇʀɪғʏ •", url=tut_vid))
                            btn.append([InlineKeyboardButton("• ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", callback_data="buy_prem")])

                            return await message.reply_photo(
                                photo=START_PIC,
                                caption=(
                                    f"<b>❌ Yᴏᴜʀ ᴀᴅs ᴛᴏᴋᴇɴ ɪs ᴇxᴘɪʀᴇᴅ ᴏʀ ɪɴᴠᴀʟɪᴅ.</b>\n"
                                    f"<blockquote>Pʟᴇᴀsᴇ ᴠᴇʀɪғʏ ᴛᴏ ᴀᴄᴄᴇss ᴛʜᴇ ғɪʟᴇs.</blockquote>\n\n"
                                    f"<b>⏱️ Tᴏᴋᴇɴ Tɪᴍᴇᴏᴜᴛ: {get_exp_time(VERIFY_EXPIRE)}</b>"
                                ),
                                reply_markup=InlineKeyboardMarkup(btn)
                            )

            argument = string.split("-")
            if len(argument) == 3:
                try:
                    start = int(int(argument[1]) / abs(client.db_channel.id))
                    end = int(int(argument[2]) / abs(client.db_channel.id))
                except:
                    return
                ids = range(start, end + 1) if start <= end else range(start, end - 1, -1)
            elif len(argument) == 2:
                try:
                    ids = [int(int(argument[1]) / abs(client.db_channel.id))]
                except:
                    return
            else:
                return

            temp_msg = await message.reply("Please wait...")
            try:
                messages = await get_messages(client, ids)
            except:
                await message.reply_text("Something went wrong..!")
                return
            await temp_msg.delete()

            AUTO_DEL, DEL_TIMER, HIDE_CAPTION, CHNL_BTN, PROTECT_MODE = await asyncio.gather(
                db.get_auto_delete(), db.get_del_timer(), db.get_hide_caption(),
                db.get_channel_button(), db.get_protect_content()
            )

            if CHNL_BTN:
                button_name, button_link = await db.get_channel_button_link()

            for idx, msg in enumerate(messages):
                original_caption = msg.caption.html if msg.caption else ""
                caption = (
                    f"{CUSTOM_CAPTION}"
                    #f"{original_caption}\n\n{CUSTOM_CAPTION}"
                    if CUSTOM_CAPTION else original_caption
                )
                if HIDE_CAPTION and (msg.document or msg.audio or msg.video or msg.photo):
                    caption += f"\n\n{CUSTOM_CAPTION}"

                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text=button_name, url=button_link)]]
                ) if CHNL_BTN else msg.reply_markup

                try:
                    copied_msg = await msg.copy(
                        chat_id=id, caption=caption, parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup, protect_content=PROTECT_MODE
                    )
                    if AUTO_DEL:
                        asyncio.create_task(delete_message(copied_msg, DEL_TIMER))
                        if idx == len(messages) - 1:
                            last_message = copied_msg

                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    copied_msg = await msg.copy(
                        chat_id=id, caption=caption, parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup, protect_content=PROTECT_MODE
                    )
                    await asyncio.sleep(0.1)

                    if AUTO_DEL:
                        asyncio.create_task(delete_message(copied_msg, DEL_TIMER))
                        if idx == len(messages) - 1:
                            last_message = copied_msg

            if AUTO_DEL and last_message:
                asyncio.create_task(auto_del_notification(client.username, last_message, DEL_TIMER, message.command[1]))

    else:
        # Inline keyboard
        inline_kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton('𝖴𝗉𝖽𝖺𝗍𝖾s', url='https://t.me/Bhabhijilive')
                ]
            ]
        )

        # Send welcome photo with inline keyboard
        await message.reply_photo(
            photo=START_PIC,
            caption=START_MSG.format(
                first=message.from_user.first_name,
                last=message.from_user.last_name or '',
                username=None if not message.from_user.username else '@' + message.from_user.username,
                mention=message.from_user.mention,
                id=message.from_user.id
            ),
            reply_markup=inline_kb,
        )


#=====================================================================================##



@Bot.on_message(filters.regex("Get Video 🍒"))
async def on_get_video(client: Client, message: Message):
    user_id = message.from_user.id
    await get_video(client, message)


@Bot.on_message(filters.command("getvideo") & filters.private)
async def on_getvideo_cmd(client: Client, message: Message):
    await get_video(client, message)


# --- Store Videos from Channel ---
async def store_videos(app: Client):
    full, part = divmod(len(VIDEOS_RANGE), 200)
    all_videos = []

    for i in range(full):
        ids = VIDEOS_RANGE[i * 11470: (i + 1) * 11470]
        if not ids:  # ⚡ skip empty
            continue
        messages = await try_until_get(app.get_messages(CHANNEL_ID, message_ids=ids))
        for msg in messages:
            if msg and msg.video:
                file_id = msg.video.file_id
                msg_id = msg.id
                exists = await db.video_exists(file_id)
                if not exists:
                    all_videos.append({"file_id": file_id, "msg_id": msg_id})

    remaining_ids = VIDEOS_RANGE[full * 11470:]
    if remaining_ids:  # ⚡ skip empty
        remaining_messages = await try_until_get(
            app.get_messages(CHANNEL_ID, message_ids=remaining_ids)
        )
        for msg in remaining_messages:
            if msg and msg.video:
                file_id = msg.video.file_id
                msg_id = msg.id
                exists = await db.video_exists(file_id)
                if not exists:
                    all_videos.append({"file_id": file_id, "msg_id": msg_id})

    if all_videos:
        await db.insert_videos(all_videos)

# --- Send Random Video (sends the file directly, no link) ---
async def send_random_video(client: Client, chat_id, user_id, protect=True):
    #await store_videos(client)
    vids = await db.get_videos()
    if not vids:
        await store_videos(client)
        vids = await db.get_videos()

    if not vids:
        return await client.send_message(chat_id, "No videos available right now.")

    # Pick random video
    random_video = random.choice(vids)

    # Try to get msg_id
    msg_id = random_video.get("msg_id")
    if not msg_id:
        return await client.send_message(chat_id, "❌ message id missing.")

    try:
        msg = await client.get_messages(CHANNEL_ID, int(msg_id))
    except:
        msg = None

    if not msg:
        return await client.send_message(chat_id, "❌ msg missing")

    # Send the actual video straight to the user — no link, no button
    try:
        await msg.copy(chat_id, protect_content=protect)
    except Exception as e:
        print(f"Could not send video: {e}")
        await client.send_message(chat_id, "❌ Cᴏᴜʟᴅ ɴᴏᴛ sᴇɴᴅ ᴠɪᴅᴇᴏ, ᴛʀʏ ᴀɢᴀɪɴ.")

# --- Safe Fetch Wrapper ---
async def try_until_get(func):
    try:
        result = await func
        return result if result else []
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await try_until_get(func)
    except Exception as e:
        print(f'Cannot get videos: {e}')
        return []


# --- Video Access Control ---
async def get_video(client: Client, message: Message):
    from pytz import timezone
    ist = timezone("Asia/Kolkata")

    user_id = message.from_user.id
    current_time = datetime.now(ist)

    # ================= PREMIUM CHECK =================
    is_premium = await db.is_premium(user_id)

    if is_premium:
        expiry = await db.get_premium_expiry(user_id)  # MUST be async

        if expiry:
            expiry_time = expiry.astimezone(ist)
            if current_time > expiry_time:
                # Auto downgrade
                await db.remove_premium(user_id)
                is_premium = False

        if is_premium:
            return await send_random_video(
                client,
                message.chat.id,
                user_id,
                protect=False
            )

    # ================= FREE USER FLOW =================
    free_enabled = await db.get_free_enabled()
    free_limit = await db.get_free_limit()
    free_count = await db.get_user_free_used(user_id)

    if not free_enabled:
        return await message.reply_text(
            "🚫 Free plan disabled.\n\nUpgrade to Premium 🍒",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("• Buy Premium •", callback_data="buy_prem")]]
            ),
            quote=True
        )

    remaining = free_limit - free_count

    if remaining <= 0:
        return await message.reply_text(
            f"🍒 Daily free limit ({free_limit}) reached.\n\nUpgrade to Premium!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("• Buy Premium •", callback_data="buy_prem")]]
            ),
            quote=True
        )

    if remaining == 1:
        await message.reply_text(
            "⚠️ This is your LAST free video today!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("• Buy Premium •", callback_data="buy_prem")]]
            ),
            quote=True
        )

    # Deduct free usage
    await db.increment_user_free_used(user_id)

    # Send video
    await send_random_video(
        client,
        message.chat.id,
        user_id,
        protect=True
    )

#=====================================================================================##

WAIT_MSG = """"<b>Processing ...</b>"""

REPLY_ERROR = """<code>Use this command as a replay to any telegram message with out any spaces.</code>"""

#=====================================================================================##


# Global cache for chat data to reduce API calls
chat_data_cache = {}

async def not_joined(client: Client, message: Message):
    temp = await message.reply(f"<b>??</b>")

    user_id = message.from_user.id

    REQFSUB = await db.get_request_forcesub()
    buttons = []
    count = 0

    try:
        for total, chat_id in enumerate(await db.get_all_channels(), start=1):
            await message.reply_chat_action(ChatAction.PLAYING)

            # Show the join button of non-subscribed Channels.....
            if not await is_userJoin(client, user_id, chat_id):
                try:
                    # Check if chat data is in cache
                    if chat_id in chat_data_cache:
                        data = chat_data_cache[chat_id]  # Get data from cache
                    else:
                        data = await client.get_chat(chat_id)  # Fetch from API
                        chat_data_cache[chat_id] = data  # Store in cache

                    cname = data.title

                    # Handle private channels and links
                    if REQFSUB and not data.username: 
                        link = await db.get_stored_reqLink(chat_id)
                        await db.add_reqChannel(chat_id)

                        if not link:
                            link = (await client.create_chat_invite_link(chat_id=chat_id, creates_join_request=True)).invite_link
                            await db.store_reqLink(chat_id, link)
                    else:
                        link = data.invite_link

                    # Add button for the chat
                    buttons.append([InlineKeyboardButton(text=cname, url=link)])
                    count += 1
                    await temp.edit(f"<b>{'! ' * count}</b>")

                except Exception as e:
                    print(f"Can't Export Channel Name and Link..., Please Check If the Bot is admin in the FORCE SUB CHANNELS:\nProvided Force sub Channel:- {chat_id}")
                    return await temp.edit(f"<b><i>! Eʀʀᴏʀ, Cᴏɴᴛᴀᴄᴛ ᴅᴇᴠᴇʟᴏᴘᴇʀ ᴛᴏ sᴏʟᴠᴇ ᴛʜᴇ ɪssᴜᴇs @AlwaysToHelpBot</i></b>\n<blockquote expandable><b>Rᴇᴀsᴏɴ:</b> {e}</blockquote>")

        await message.reply_photo(
            photo=FORCE_PIC,
            caption=FORCE_MSG.format(
                first=message.from_user.first_name,
                last=message.from_user.last_name,
                username=None if not message.from_user.username else '@' + message.from_user.username,
                mention=message.from_user.mention,
                id=message.from_user.id
            ),
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        print(f"Error: {e}")  # Print the error message for debugging
        # Optionally, send an error message to the user or handle further actions here
        await temp.edit(f"<b><i>! Eʀʀᴏʀ, Cᴏɴᴛᴀᴄᴛ ᴅᴇᴠᴇʟᴏᴘᴇʀ ᴛᴏ sᴏʟᴠᴇ ᴛʜᴇ ɪssᴜᴇs @AlwaysToHelpBot</i></b>\n<blockquote expandable><b>Rᴇᴀsᴏɴ:</b> {e}</blockquote>")


@Bot.on_message(filters.command('users') & filters.private & is_admin)
async def get_users(client: Bot, message: Message):
    msg = await client.send_message(chat_id=message.chat.id, text=WAIT_MSG)
    users = await db.full_userbase()
    await msg.edit(f"{len(users)} users are using this bot")


@Bot.on_message(filters.command('status') & filters.private & is_admin)
async def info(client: Bot, message: Message):   
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("• Close •", callback_data="close")]]
    )

    # Measure ping
    start_time = time.time()
    temp_msg = await message.reply(
        "<b><i>Processing...</i></b>", 
        quote=True, 
        parse_mode=ParseMode.HTML
    )
    end_time = time.time()
    ping_time = (end_time - start_time) * 1000

    # User count
    users = await db.full_userbase()

    # Uptime
    now = datetime.now(pytz.utc)   
    delta = now - client.uptime
    bottime = get_readable_time(int(delta.total_seconds()))

    # Edit message with final status
    await temp_msg.edit(
        f"<b>Users: {len(users)}\n\n"
        f"Uptime: {bottime}\n\n"
        f"Ping: {ping_time:.2f} ms</b>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

#--------------------------------------------------------------[[ADMIN COMMANDS]]---------------------------------------------------------------------------#
# Handler for the /cancel command
cancel_lock = asyncio.Lock()
is_canceled = False


@Bot.on_message(filters.command('cancel') & filters.private & is_admin)
async def cancel_broadcast(client: Bot, message: Message):
    global is_canceled
    async with cancel_lock:
        is_canceled = True

@Bot.on_message(filters.private & filters.command('broadcast') & is_admin)
async def broadcast(client: Bot, message: Message):
    global is_canceled
    args = message.text.split()[1:]

    if not message.reply_to_message:
        msg = await message.reply(
            "Reply to a message to broadcast.\n\nUsage examples:\n"
            "`/broadcast normal`\n"
            "`/broadcast pin`\n"
            "`/broadcast delete 30`\n"
            "`/broadcast pin delete 30`\n"
            "`/broadcast silent`\n"
        )
        await asyncio.sleep(8)
        return await msg.delete()

    # Defaults
    do_pin = False
    do_delete = False
    duration = 0
    silent = False
    mode_text = []

    i = 0
    while i < len(args):
        arg = args[i].lower()
        if arg == "pin":
            do_pin = True
            mode_text.append("PIN")
        elif arg == "delete":
            do_delete = True
            try:
                duration = int(args[i + 1])
                i += 1
            except (IndexError, ValueError):
                return await message.reply("<b>Provide valid duration for delete mode.</b>\nUsage: `/broadcast delete 30`")
            mode_text.append(f"DELETE({duration}s)")
        elif arg == "silent":
            silent = True
            mode_text.append("SILENT")
        else:
            mode_text.append(arg.upper())
        i += 1

    if not mode_text:
        mode_text.append("NORMAL")

    # Reset cancel flag
    async with cancel_lock:
        is_canceled = False

    query = await db.full_userbase()
    broadcast_msg = message.reply_to_message
    total = len(query)
    successful = blocked = deleted = unsuccessful = 0

    pls_wait = await message.reply(f"<i>Broadcasting in <b>{' + '.join(mode_text)}</b> mode...</i>")

    bar_length = 20
    progress_bar = ''
    last_update_percentage = 0
    update_interval = 0.05  # 5%

    for i, chat_id in enumerate(query, start=1):
        async with cancel_lock:
            if is_canceled:
                await pls_wait.edit(f"›› BROADCAST ({' + '.join(mode_text)}) CANCELED ❌")
                return

        try:
            sent_msg = await broadcast_msg.copy(chat_id, disable_notification=silent)

            if do_pin:
                await client.pin_chat_message(chat_id, sent_msg.id, both_sides=True)
            if do_delete:
                asyncio.create_task(auto_delete(sent_msg, duration))

            successful += 1
        except FloodWait as e:
            await asyncio.sleep(e.x)
            try:
                sent_msg = await broadcast_msg.copy(chat_id, disable_notification=silent)
                if do_pin:
                    await client.pin_chat_message(chat_id, sent_msg.id, both_sides=True)
                if do_delete:
                    asyncio.create_task(auto_delete(sent_msg, duration))
                successful += 1
            except:
                unsuccessful += 1
        except UserIsBlocked:
            await db.del_user(chat_id)
            blocked += 1
        except InputUserDeactivated:
            await db.del_user(chat_id)
            deleted += 1
        except:
            unsuccessful += 1
            await db.del_user(chat_id)

        # Progress
        percent_complete = i / total
        if percent_complete - last_update_percentage >= update_interval or last_update_percentage == 0:
            num_blocks = int(percent_complete * bar_length)
            progress_bar = "●" * num_blocks + "○" * (bar_length - num_blocks)
            status_update = f"""<b>›› BROADCAST ({' + '.join(mode_text)}) IN PROGRESS...

<blockquote>⏳:</b> [{progress_bar}] <code>{percent_complete:.0%}</code></blockquote>

<b>›› Total Users: <code>{total}</code>
›› Successful: <code>{successful}</code>
›› Blocked: <code>{blocked}</code>
›› Deleted: <code>{deleted}</code>
›› Unsuccessful: <code>{unsuccessful}</code></b>

<i>➪ To stop broadcasting click: <b>/cancel</b></i>"""
            await pls_wait.edit(status_update)
            last_update_percentage = percent_complete

    # Final status
    final_status = f"""<b>›› BROADCAST ({' + '.join(mode_text)}) COMPLETED ✅

<blockquote>Dᴏɴᴇ:</b> [{progress_bar}] {percent_complete:.0%}</blockquote>

<b>›› Total Users: <code>{total}</code>
›› Successful: <code>{successful}</code>
›› Blocked: <code>{blocked}</code>
›› Deleted: <code>{deleted}</code>
›› Unsuccessful: <code>{unsuccessful}</code></b>"""
    return await pls_wait.edit(final_status)


# helper for delete mode
async def auto_delete(sent_msg, duration):
    await asyncio.sleep(duration)
    try:
        await sent_msg.delete()
    except:
        pass





@Bot.on_message(filters.command('forcesub') & filters.private & ~banUser)
async def fsub_commands(client: Client, message: Message):
    button = [[InlineKeyboardButton("Cʟᴏsᴇ ✖️", callback_data="close")]]
    await message.reply(text=FSUB_CMD_TXT, reply_markup=InlineKeyboardMarkup(button), quote=True)


@Bot.on_message(filters.command('help') & filters.private & ~banUser)
async def help(client: Client, message: Message):
    buttons = [
        [
            InlineKeyboardButton("🤖 Oᴡɴᴇʀ", url="https://t.me/AlwaysToHelpBot"), 
            InlineKeyboardButton("🥰 Dᴇᴠᴇʟᴏᴘᴇʀ", url="https://t.me/AlwaysToHelpBot")
        ]
    ]
    
    try:
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo = FORCE_PIC,
            caption = HELP_TEXT.format(
                first = message.from_user.first_name,
                last = message.from_user.last_name,
                username = None if not message.from_user.username else '@' + message.from_user.username,
                mention = message.from_user.mention,
                id = message.from_user.id
            ),
            reply_markup = reply_markup#,
            #message_effect_id = 5046509860389126442 #🎉
        )
    except Exception as e:
        return await message.reply(f"<b><i>! Eʀʀᴏʀ, Cᴏɴᴛᴀᴄᴛ ᴅᴇᴠᴇʟᴏᴘᴇʀ ᴛᴏ sᴏʟᴠᴇ ᴛʜᴇ ɪssᴜᴇs @AlwaysToHelpBot</i></b>\n<blockquote expandable><b>Rᴇᴀsᴏɴ:</b> {e}</blockquote>")

@Bot.on_message(filters.command('short') & filters.private & is_admin)
async def shorten_link_command(client, message):
    id = message.from_user.id

    try:
        # Prompt the user to send the link to be shortened
        set_msg = await client.ask(
            chat_id=id,
            text="<b><blockquote>⏳ Sᴇɴᴅ ᴀ ʟɪɴᴋ ᴛᴏ ʙᴇ sʜᴏʀᴛᴇɴᴇᴅ</blockquote>\n\nFᴏʀ ᴇxᴀᴍᴘʟᴇ: <code>https://example.com/long_url</code></b>",
            timeout=60
        )

        # Validate the user input for a valid URL
        original_url = set_msg.text.strip()

        if original_url.startswith("http") and "://" in original_url:
            try:
                # Call the get_shortlink function
                short_link = await get_shortlink(original_url)

                # Inform the user about the shortened link
                await set_msg.reply(f"<b>🔗 Lɪɴᴋ Cᴏɴᴠᴇʀᴛᴇᴅ Sᴜᴄᴄᴇssғᴜʟʟʏ ✅</b>\n\n<blockquote>🔗 Sʜᴏʀᴛᴇɴᴇᴅ Lɪɴᴋ: <code>{short_link}</code></blockquote>")
            except ValueError as ve:
                # If shortener details are missing
                await set_msg.reply(f"<b>❌ Error: {ve}</b>")
            except Exception as e:
                # Handle errors during the shortening process
                await set_msg.reply(f"<b>❌ Error while shortening the link:\n<code>{e}</code></b>")
        else:
            # If the URL is invalid, prompt the user to try again
            await set_msg.reply("<b>❌ Invalid URL. Please send a valid link that starts with 'http'.</b>")

    except asyncio.TimeoutError:
        # Handle timeout exceptions
        await client.send_message(
            id,
            text="<b>⏳ Tɪᴍᴇᴏᴜᴛ. Yᴏᴜ ᴛᴏᴏᴋ ᴛᴏᴏ ʟᴏɴɢ ᴛᴏ ʀᴇsᴘᴏɴᴅ. Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>",
            disable_notification=True
        )
        print(f"! Timeout occurred for user ID {id} while processing '/shorten' command.")

    except Exception as e:
        # Handle any other exceptions
        await client.send_message(
            id,
            text=f"<b>❌ Aɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ:\n<code>{e}</code></b>",
            disable_notification=True
        )
        print(f"! Error occurred on '/short' command: {e}")


