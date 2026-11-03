from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode, ChatAction
from bot import Bot
from database.database import db
from config import *
import asyncio
from datetime import datetime, timedelta
from pytz import timezone
import logging
from helper_func import *
from math import ceil


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


@Bot.on_message(filters.command("free") & filters.private & is_admin)
async def cmd_free_toggle(client, message):
    # Usage: /free on   OR   /free off
    try:
        arg = (message.text.split(maxsplit=1)[1]).strip().lower()
    except Exception:
        return await message.reply_text("Usage: <code>/free on</code> or <code>/free off</code>", parse_mode=ParseMode.HTML)

    if arg not in ("on", "off"):
        return await message.reply_text("Usage: <code>/free on</code> or <code>/free off</code>", parse_mode=ParseMode.HTML)

    enabled = (arg == "on")
    await db.set_free_enabled(enabled)
    await message.reply_text(f"✅ Free mode set to: <b>{'ON' if enabled else 'OFF'}</b>", parse_mode=ParseMode.HTML)


@Bot.on_message(filters.command(["setfreelimit", "set_free_limit"]) & filters.private & is_admin)
async def cmd_set_free_limit(client, message):
    # Usage: /setfreelimit 3
    try:
        n = int(message.text.split(maxsplit=1)[1])
        if n < 0: raise ValueError
    except Exception:
        return await message.reply_text("Usage: <code>/setfreelimit 3</code> (non-negative integer)", parse_mode=ParseMode.HTML)

    await db.set_free_limit(n)
    await message.reply_text(f"✅ Global FREE_LIMIT set to <b>{n}</b>", parse_mode=ParseMode.HTML)



@Bot.on_message(filters.command("resetfree") & filters.private & is_admin)
async def cmd_reset_free(client, message):
    # Usage: /resetfree <user_id>  OR reply to a user message with /resetfree
    target = None
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].isdigit():
        target = int(parts[1])
    elif message.reply_to_message:
        target = message.reply_to_message.from_user.id

    if not target:
        return await message.reply_text("Usage: <code>/resetfree &lt;user_id&gt;</code> or reply to a user.", parse_mode=ParseMode.HTML)

    await db.reset_user_free_used(target)
    await message.reply_text(f"🔁 Reset free usage for <code>{target}</code>.", parse_mode=ParseMode.HTML)

# Commands
@Bot.on_message(filters.command('addpaid') & is_admin)
async def add_premium_command(client: Client, message: Message):
    if len(message.command) != 3:
        await message.reply_text(
            "❌ Incorrect format. Use:\n"
            "<code>/addpaid {user_id} {duration}</code>\n\n"
            "🕒 Examples of duration:\n"
            "- <code>1min</code>\n"
            "- <code>1hour</code>\n"
            "- <code>1day</code>\n"
            "- <code>1week</code>\n"
            "- <code>1month</code>\n"
            "- <code>1year</code>"
        )
        return

    try:
        user_id = int(message.command[1])
        duration = parse_duration(message.command[2])
        current_time_ist = datetime.now(INDIA_TZ).strftime('%Y-%m-%d %I:%M:%S %p')
        expiry_time = datetime.now(INDIA_TZ) + duration
    except ValueError as e:
        await message.reply_text(f"❌ {str(e)}")
        return

    user_name = await fetch_user_info(client, user_id)
    if not user_name:
        await message.reply_text(f"❌ Uɴᴀʙʟᴇ ᴛᴏ ғᴇᴛᴄʜ ᴜsᴇʀ ɪɴғᴏ ғᴏʀ ID {user_id}.")
        return

    if not await db.is_premium(user_id):
        await db.add_premium(user_id, expiry_time)
        await message.reply_text(
            f"✅ User <b>{user_name}</b> (ID: <code>{user_id}</code>) ʜᴀs ʙᴇᴇɴ ɢʀᴀɴᴛᴇᴅ ᴘʀᴇᴍɪᴜᴍ ғᴏʀ <b>{message.command[2]}</b>."
        )

        # Notify user about their premium activation
        try:
            await client.send_message(
                user_id,
                f"<blockquote>🎉 <b>Congratulations!</b></blockquote>\n"
                f"<blockquote>Yᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴍᴇᴍʙᴇʀsʜɪᴘ ɪs ɴᴏᴡ ᴀᴄᴛɪᴠᴇ ғᴏʀ <b>{message.command[2]}</b>. Enjoy! 🎊</blockquote>",
                disable_web_page_preview=True
            )
        except Exception as e:
            logging.warning(f"Failed to notify user {user_id}: {e}")

        # Log the admin action (PREMIUM_LOGS)
        if LOG_CHANNEL:
            try:
                admin_user = message.from_user
                log_text = (
                    f"<b><blockquote>✦ 𝗠𝗔𝗡𝗨𝗔𝗟 𝗣𝗥𝗘𝗠𝗜𝗨𝗠 𝗔𝗗𝗗𝗘𝗗 ✦</b></blockquote>\n\n"
                    f"<b><blockquote>❐  Usᴇʀ:</b> <a href='tg://user?id={user_id}'>{user_name}</a> (`{user_id}`)</b></blockquote>\n"
                    f"<b><blockquote>❐  Aᴅᴅᴇᴅ Bʏ:</b> {admin_user.mention} (`{admin_user.id}`)</b></blockquote>\n"
                    f"<b><blockquote>❐  Dᴜʀᴀᴛɪᴏɴ:</b> {message.command[2]}</b></blockquote>\n"
                    f"<b><blockquote>❐  Aᴅᴅᴇᴅ Oɴ:</b> {current_time_ist}</b></blockquote>\n\n"
                    f"<b><blockquote>❐  Pʀᴇᴍɪᴜᴍ ᴀᴄᴛɪᴠᴇ ᴛɪʟʟ <b>{expiry_time.strftime('%Y-%m-%d %H:%M:%S')}</b></blockquote>"
                )
                await client.send_message(
                    LOG_CHANNEL,
                    log_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            except Exception as e:
                print(f"[PREMIUM_LOGS] Error: {e}")

    else:
        await message.reply_text(
            f"ℹ️ User <b>{user_name}</b> (ID: <code>{user_id}</code>) is already a premium user."
        )


        
@Bot.on_message(filters.command("removepaid") & is_admin)
async def remove_premium_command(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Incorrect format. Use:\n"
                                 "<code>/removepaid {user_id} {reason}</code> or\n"
                                 "<code>/removepaid all {reason}</code>")
        return

    argument = message.command[1].lower()
    current_time_ist = datetime.now(INDIA_TZ).strftime('%Y-%m-%d %I:%M:%S %p')
    reason = "Nᴏ sᴘᴇᴄɪғɪᴄ ʀᴇᴀsᴏɴ ᴘʀᴏᴠɪᴅᴇᴅ."  

    if len(message.command) > 2:
        reason = " ".join(message.command[2:])  

    if argument == "all":
        premium_users = await db.get_premium_users()
        if not premium_users:
            await message.reply_text("ℹ️ Nᴏ ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs ғᴏᴜɴᴅ.")
            return

        # Remove all premium users
        for user_id in premium_users.keys():
            await db.remove_premium(user_id)
            try:
                await client.send_message(
                    user_id,
                    f"❗<blockquote> <b>Yᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴍᴇᴍʙᴇʀsʜɪᴘ ʜᴀs ʙᴇᴇɴ ʀᴇᴠᴏᴋᴇᴅ.</b></blockquote>\n"
                    f"<blockquote>📌 <b>Rᴇᴀsᴏɴ:</b> {reason}</blockquote>\n"
                    f"<b><blockquote><a href='{ADMIN_LINK}'>✦ 💬 Cʟɪᴄᴋ ʜᴇʀᴇ ᴛᴏ Cᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴs</a></b></blockquote>",
    disable_web_page_preview=True
                )
            except Exception as e:
                logging.warning(f"Failed to notify user {user_id}: {e}")

            # Log to PREMIUM_LOGS
            if LOG_CHANNEL:
                try:
                    log_text = (
                        f"🚫 <b>Premium Revoked</b>\n\n"
                        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
                        f"🧾 <b>Action:</b> All Users Removal\n"
                        f"📅 <b>Time:</b> {current_time_ist}\n"
                        f"📌 <b>Reason:</b> {reason}"
                    )
                    await client.send_message(LOG_CHANNEL, log_text, parse_mode=ParseMode.HTML)
                except Exception as e:
                    print(f"[PREMIUM_LOGS] Error: {e}")

        await message.reply_text(f"<blockquote>✅ Aʟʟ ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs ʜᴀᴠᴇ ʙᴇᴇɴ ʀᴇᴍᴏᴠᴇᴅ.\n\n📌 Rᴇᴀsᴏɴ: {reason}</blockquote>")

    else:
        try:
            user_id = int(argument)
        except ValueError:
            await message.reply_text("❌ Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID ғᴏʀᴍᴀᴛ ᴏʀ ᴜɴsᴜᴘᴘᴏʀᴛᴇᴅ ᴀʀɢᴜᴍᴇɴᴛ.")
            return

        user_name = await fetch_user_info(client, user_id)
        if not user_name:
            await message.reply_text(f"❌ Uɴᴀʙʟᴇ ᴛᴏ ғᴇᴛᴄʜ ᴜsᴇʀ ɪɴғᴏ ғᴏʀ ID {user_id}.")
            return

        if await db.is_premium(user_id):
            await db.remove_premium(user_id)
            await message.reply_text(
                f"✅ User <b>{user_name}</b> (ID: <code>{user_id}</code>) is no longer a premium user.\n"
                f"📌 <b>Reason:</b> {reason}"
            )
            try:
                await client.send_message(
                    user_id,
                    f"❗<blockquote> <b>Yᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴍᴇᴍʙᴇʀsʜɪᴘ ʜᴀs ʙᴇᴇɴ ʀᴇᴠᴏᴋᴇᴅ.</b></blockquote>\n"
                    f"<blockquote>📌 <b>Rᴇᴀsᴏɴ:</b> {reason}</blockquote>\n"
                    f"<b><blockquote><a href='{ADMIN_LINK}'>✦ 💬 Cʟɪᴄᴋ ʜᴇʀᴇ ᴛᴏ Cᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴs</a></b></blockquote>",
    disable_web_page_preview=True
                )
            except Exception as e:
                logging.warning(f"Failed to notify user {user_id}: {e}")

            # Log to PREMIUM_LOGS
            if LOG_CHANNEL:
                try:
                    log_text = (
                        f"🚫 <b>Premium Revoked</b>\n\n"
                        f"👤 <b>User:</b> {user_name} (<code>{user_id}</code>)\n"
                        f"🧾 <b>Action By:</b> {message.from_user.mention} (<code>{message.from_user.id}</code>)\n"
                        f"📅 <b>Time:</b> {current_time_ist}\n"
                        f"📌 <b>Reason:</b> {reason}"
                    )
                    await client.send_message(LOG_CHANNEL, log_text, parse_mode=ParseMode.HTML)
                except Exception as e:
                    print(f"[PREMIUM_LOGS] Error: {e}")

        else:
            await message.reply_text(f"ℹ️ User <b>{user_name}</b> (ID: <code>{user_id}</code>) is not a premium user.")



@Bot.on_message(filters.command('refresh') & is_admin)
async def refresh_premium_command(client: Client, message: Message):
    premium_users = await db.get_premium_users()
    for user_id in list(premium_users.keys()):
        if not await db.is_premium(user_id):  # If the user's premium has expired, remove them from the list
            await kingdb.remove_premium(user_id)
    
    await message.reply_text("<blockquote><b><i>✅ Premium users list has been refreshed!</i></b></blockquote>")

# user profile 

@Bot.on_message(filters.command("myplan") & filters.private)
async def profile_command(client: Client, message: Message):
    user_id = message.from_user.id
    user_name = message.from_user.username or "N/A"
    full_name = message.from_user.first_name + (f" {message.from_user.last_name}" if message.from_user.last_name else "")

    wait_msg = await message.reply_text("<blockquote><b>⏳ Fetching your profile...</b></blockquote>")
    await asyncio.sleep(1)
    try:
        await wait_msg.delete()
    except Exception:
        pass

    # ✅ Flags / status
    is_premium_user = await db.is_premium(user_id)

    # Free quota
    FREE_ENABLED = await db.get_free_enabled()
    FREE_LIMIT   = await db.get_free_limit()
    USER_USED    = await db.get_user_free_used(user_id)
    FREE_REMAIN  = max(0, FREE_LIMIT - USER_USED)


    # Build free usage line
    if FREE_ENABLED and (FREE_LIMIT > 0) and (not is_premium_user):
        free_line = f"\n<b>• ғʀᴇᴇ ᴜsᴀɢᴇ :</b> <code>{USER_USED}/{FREE_LIMIT}</code>  (ʀᴇᴍᴀɪɴɪɴɢ: <code>{FREE_REMAIN}</code>)"
    elif FREE_ENABLED and (FREE_LIMIT > 0) and is_premium_user:
        # Optional: hide for premium; set to "" if you don't want to show
        free_line = ""
    else:
        free_line = "\n<b>• ғʀᴇᴇ ᴜsᴀɢᴇ :</b> <i>ᴅɪsᴀʙʟᴇᴅ</i>"


    if is_premium_user:
        # Fetch expiry (assuming get_premium_users() -> {user_id: expiry_dt})
        user_map = await db.get_premium_users()
        expiry_time = user_map.get(user_id)
        expiry_text = expiry_time.strftime('%Y-%m-%d %H:%M:%S') if expiry_time else "Unknown"

        profile_photo_url = "https://graph.org/file/4d765d3c53783f6ff670d-21029256a9aeab6a6a.jpg"
        profile_text = (
            f"<b>╭───────────⭓</b>\n"
            f"<b>│ 👑 ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀ</b>\n"
            f"<b>╰───────────⭓</b>\n"
            f"<b>• ɴᴀᴍᴇ :</b> <code>{full_name}</code>\n"
            f"<b>• ᴜsᴇʀɴᴀᴍᴇ :</b> @{user_name}\n"
            f"<b>• ᴜsᴇʀ ɪᴅ :</b> <code>{user_id}</code>\n"
            f"<b>• ᴘʀᴇᴍɪᴜᴍ sᴛᴀᴛᴜs :</b> ✅ ᴀᴄᴛɪᴠᴇ\n"
            f"<b>• ᴇxᴘɪʀʏ :</b> <code>{expiry_text}</code>\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>"
            f"{free_line}"
        )

        # Buttons: extend + (optional) referral tools if enabled
        btns = [[InlineKeyboardButton("• ᴇxᴛᴇɴᴅ ᴘʀᴇᴍɪᴜᴍ •", callback_data="buy_prem")]]
        reply_markup = InlineKeyboardMarkup(btns)

    else:
        profile_photo_url = "https://graph.org/file/58fb1904a46c13c52b806-3dd429c7c3e4d76818.jpg"
        profile_text = (
            f"<b>╭───────────⭓</b>\n"
            f"<b>│ ᴘʀᴏғɪʟᴇ</b>\n"
            f"<b>╰───────────⭓</b>\n"
            f"<b>• ɴᴀᴍᴇ :</b> <code>{full_name}</code>\n"
            f"<b>• ᴜsᴇʀɴᴀᴍᴇ :</b> @{user_name}\n"
            f"<b>• ᴜsᴇʀ ɪᴅ :</b> <code>{user_id}</code>\n"
            f"<b>• ᴘʀᴇᴍɪᴜᴍ sᴛᴀᴛᴜs :</b> ❌ ɴᴏᴛ ᴀᴄᴛɪᴠᴇ\n"
            f"<b>━━━━━━━━━━━━━━━━━</b>"
            f"{free_line}"
        )

        # Buttons: Refer/Points Shop (if enabled), plus Buy Premium and Tutorial
        buttons = []
        buttons.append([InlineKeyboardButton("• ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", callback_data="buy_prem")])
        try:
           
            buttons.append([InlineKeyboardButton("• ᴛᴜᴛᴏʀɪᴀʟ ᴛᴏ ʙᴜʏ •", url=PREMIUM_TUT_VID)])
        except NameError:
            pass
        reply_markup = InlineKeyboardMarkup(buttons)

    await message.reply_photo(profile_photo_url, caption=profile_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


# Command handler
@Bot.on_message(filters.command('listpaid') & is_admin)
async def list_premium_command(client: Client, message: Message):
    premium_users = await db.get_premium_users()
    current_page[message.chat.id] = 1  # Reset to first page
    
    if not premium_users:
        await message.reply_text(
            "<b>✨ ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs ✨</b>\n\n"
            "<i>▫️ No premium users found.</i>"
        )
        return
    
    await show_premium_page(client, message.chat.id, premium_users, message.id)
