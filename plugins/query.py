import random, asyncio, logging, time, os, qrcode, uuid, aiohttp, random, string, io, logging, math
from asyncio import sleep
import urllib.parse
from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatAction
from bot import Bot
from pyrogram import __version__
from PIL import Image
from plugins.FORMATS import *
from config import *
from pyrogram.enums import ChatAction
from plugins.autoDelete import convert_time
from database.database import db
from datetime import datetime, timedelta
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, ReplyKeyboardMarkup, ReplyKeyboardRemove#, LabeledPrice, PreCheckoutQuery  
from math import ceil
from pyrogram.errors import MessageNotModified
from helper_func import *
from plugins.premium import *
from pytz import timezone



logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)



# Example: In your message handler, handle numeric day replies:
@Client.on_message(filters.regex(r"^\d+$") & filters.private)
async def handle_custom_days(client, message):
    # --- Inputs ---
    days = int(message.text)
    if days <= 9:
        return await message.reply_text("Please enter a valid positive number MINIMUM 10days.")

    amt = days * 10
    tr = txn_id()
    user_id = message.from_user.id

    # --- Build UPI & QR ---
    upi_url = f"upi://pay?pa={BUSINESS_UPI}&pn=htkuky&am={amt}&cu=INR&tr={tr}&tn=Payment"

    qr = qrcode.make(upi_url)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)

    caption = (
        f"<b><blockquote>✦ 𝗖𝗨𝗦𝗧𝗢𝗠 𝗣𝗥𝗘𝗠𝗜𝗨𝗠 𝗣𝗟𝗔𝗡</b></blockquote>\n\n"
        f"<b><blockquote>❐ Dᴀʏꜱ:</b> {days}</blockquote>\n"
        f"<b><blockquote>❐ Aᴍᴏᴜɴᴛ:</b> ₹{amt}</blockquote>\n"
        f"<b><blockquote>❐ Tʀᴀɴsᴀᴄᴛɪᴏɴ ID:</b> <code>{tr}</code></blockquote>\n"
        f"────────────────────\n"
        f"<b><blockquote>≡ Sᴄᴀɴ ᴛʜɪs QR ᴡɪᴛʜ ᴀɴʏ UPI ᴀᴘᴘ ᴛᴏ ᴘᴀʏ.</b></blockquote>\n\n"
        f"<b><blockquote><a href='{ADMIN_LINK}'>✦ Pay ₹{amt} via UPI</a></blockquote></b>\n\n"
        f"<b><blockquote>✦ Premium will be activated automatically once payment is verified (within 5 minutes).</b></blockquote>"
    )

    sent = await message.reply_photo(
        photo=buf,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("•Sᴇɴᴅ Sᴄʀᴇᴇɴsʜᴏᴛ", url=ADMIN_LINK)],
            [InlineKeyboardButton("❌ Cancel", callback_data="close")],
            [InlineKeyboardButton("‹ Back", callback_data="buy_prem")]
        ])
    )

    

@Bot.on_callback_query()
async def cb_handler(client: Bot, query: CallbackQuery):
    data = query.data
    if data == "close":
        await query.message.delete()
        try:
            await query.message.reply_to_message.delete()
        except BaseException:
            pass

    elif data == "about":
        await query.message.edit_text(
            text=(
                f"<b>○ Updates : <a href='https://t.me/AlwaysToHelpBot'>Unknown</a>\n"
                f"○ Language : <code>Python3</code>\n"
                f"○ Library : <a href='https://docs.pyrogram.org/'>Pyrogram asyncio {__version__}</a>"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('⬅️ Bᴀᴄᴋ', callback_data='start'), InlineKeyboardButton(
                    'Cʟᴏsᴇ ✖️', callback_data='close')]
            ]),
        )

    elif data == "buy_prem":
        user = await client.get_users(OWNER_ID)
        user_link = f"https://t.me/{user.username}" if user.username else f"tg://openmessage?user_id={OWNER_ID}"
        ownername = f"<a href={user_link}>{user.first_name}</a>" if user.first_name else f"<a href={user_link}>no name !</a>"

        try:
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media="https://envs.sh/JP6.jpg",
                    caption=PREMIUM_TXT.format(
                        botname=client.name,
                        ownername=ownername
                    )
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("𝟩 𝖣𝖠𝖸𝖲", callback_data="upi_plan_7day")],
                    [
                        InlineKeyboardButton("𝟣𝟦 𝖣𝖠𝖸𝖲", callback_data="upi_plan_1"),
                        InlineKeyboardButton("𝟥𝟢 𝖣𝖠𝖸𝖲", callback_data="upi_plan_2")
                    ],
                    [
                        InlineKeyboardButton("𝟥 𝖬𝖮𝖭𝖳𝖧𝖲", callback_data="upi_plan_3"),
                        InlineKeyboardButton("𝟣 𝖸𝖤𝖠𝖱", callback_data="upi_plan_4")
                    ],
                    [InlineKeyboardButton("✦ Cᴜsᴛᴏᴍ Pʟᴀɴ ✦", callback_data="custom_plan")],
                    [InlineKeyboardButton("‹ Back", callback_data="start")]
                ])
            )
        except MessageNotModified:
            await query.answer()

    elif data.startswith("upi_plan_"):
        plan_key = data.replace("upi_plan_", "")

        # Hardcoded plan table (₹10/day rate). Edit prices/durations here as needed —
        # this no longer depends on PREMIUM_TXT / extract_upi_plans, which is what
        # was causing "Invalid plan!" whenever a button's key wasn't found there.
        PLAN_TABLE = {
            "7day": {"price": 49,   "duration": "7 days"},
            "1":    {"price": 79,  "duration": "14 days"},
            "2":    {"price": 129,  "duration": "30 days"},
            "3":    {"price": 239,  "duration": "3 months"},
            "4":    {"price": 999, "duration": "1 year"},
        }

        if plan_key not in PLAN_TABLE:
            await query.answer("⚠️ Invalid plan!", show_alert=True)
            return

        await query.message.delete()

        amt = PLAN_TABLE[plan_key]["price"]
        duration_str = PLAN_TABLE[plan_key]["duration"]
        tr = txn_id()
        print(f"Transaction ID: {tr}")
        upi_url = f"upi://pay?pa={BUSINESS_UPI}&pn=htkuky&am={amt}&cu=INR&tr={tr}&tn=Payment"
        qr = qrcode.make(upi_url)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "qr.png"  # Required so Pyrogram knows the file extension

        encoded_upi = urllib.parse.quote(upi_url, safe="")
        https_link = f"https://paypage-delta.vercel.app/pay?upi={encoded_upi}"

        caption = (
            f"<b><blockquote>✦ 𝗣𝗥𝗘𝗠𝗜𝗨𝗠 𝗣𝗔𝗬𝗠𝗘𝗡𝗧</b></blockquote>\n\n"
            f"<b><blockquote>❐ Aᴍᴏᴜɴᴛ: ₹{amt}</b></blockquote>\n"
            f"<b><blockquote>≡ Vᴀʟɪᴅɪᴛɪ: {duration_str}</b></blockquote>\n"
            f"<b><blockquote>❐ Tʀᴀɴsᴀᴄᴛɪᴏɴ ID: <code>{tr}</code></b></blockquote>\n────────────────────\n"
            f"<b><blockquote>≡ Sᴄᴀɴ ᴛʜɪs QR ᴡɪᴛʜ ᴀɴʏ UPI ᴀᴘᴘ ᴛᴏ ᴘᴀʏ.</b></blockquote>\n\n"
            f"<b><blockquote>✦ OR tap here to pay directly</b></blockquote>\n"
            f"<b><blockquote>›› Pay ₹{amt} via UPI</b></blockquote>\n\n"
            f"<b><blockquote>✦ Pʀᴇmɪᴜᴍ ᴡɪʟʟ ʙᴇ ᴀᴅᴅᴇᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ɪғ ᴘᴀɪᴅ ᴡɪᴛʜɪɴ 𝟻 ᴍɪɴᴜᴛᴇs...</b></blockquote>"
        )

        sent = await query.message.reply_photo(
            photo=buf,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("•Sᴇɴᴅ Sᴄʀᴇᴇɴsʜᴏᴛ", url=ADMIN_LINK)],
                [InlineKeyboardButton("❌ Cᴀɴᴄᴇʟ•", callback_data="close")],
                [InlineKeyboardButton("‹ Back", callback_data="buy_prem")]
            ])
        )

    elif data == "custom_plan":
        caption = CUSTOM_PLAN_TXT.format(mention=query.from_user.mention)
        user = await client.get_users(OWNER_ID)
        user_link = f"https://t.me/{user.username}" if user.username else f"tg://openmessage?user_id={OWNER_ID}"

        await query.edit_message_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✦ Pʀᴏᴄᴇᴇᴅ ᴡɪᴛʜ Bᴏᴛ", callback_data="enter_days")],
                [InlineKeyboardButton("❐ Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ", url=ADMIN_LINK)],
                [InlineKeyboardButton("‹ Back", callback_data="buy_prem")]
            ])
        )

    elif data == "enter_days":
        await query.message.reply_text(
            "Eɴᴛᴇʀ ʜᴏᴡ ᴍᴀɴʏ ᴅᴀʏs ᴏғ ᴘʀᴇᴍɪᴜᴍ ʏᴏᴜ ᴡᴀɴᴛ (e.g., <b>10</b>):\n\n"
            "💰 Rate: ₹10 per day",
            parse_mode=ParseMode.HTML
        )

    elif data == "setting":
        await query.edit_message_media(InputMediaPhoto(random.choice(PICS), "<b>Pʟᴇᴀsᴇ wᴀɪᴛ !\n\n<i>🔄 Rᴇᴛʀɪᴇᴠɪɴɢ ᴀʟʟ Sᴇᴛᴛɪɴɢs...</i></b>"))
        try:
            total_fsub = len(await db.get_all_channels())
            total_admin = len(await db.get_all_admins())
            total_ban = len(await db.get_ban_users())
            autodel_mode = 'Eɴᴀʙʟᴇ特' if await db.get_auto_delete() else 'Dɪsᴀʙʟᴇᴅ'
            protect_content = 'Eɴᴀʙʟᴇᴅ' if await db.get_protect_content() else 'Dɪsᴀʙʟᴇᴅ'
            hide_caption = 'Eɴᴀʙʟᴇᴅ' if await db.get_hide_caption() else 'Dɪsᴀʙʟᴇᴅ'
            chnl_butn = 'Eɴᴀʙʟᴇᴅ' if await db.get_channel_button() else 'DɪsᴀʙʟEᴅ'
            reqfsub = 'Eɴᴀʙʟᴇᴅ' if await db.get_request_forcesub() else 'Dɪsᴀʙʟᴇᴅ'

            await query.edit_message_media(
                InputMediaPhoto(random.choice(PICS),
                                SETTING_TXT.format(
                                    total_fsub=total_fsub,
                                    total_admin=total_admin,
                                    total_ban=total_ban,
                                    autodel_mode=autodel_mode,
                                    protect_content=protect_content,
                                    hide_caption=hide_caption,
                                    chnl_butn=chnl_butn,
                                    reqfsub=reqfsub
                )
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('⬅️ Bᴀᴄᴋ', callback_data='start'), InlineKeyboardButton(
                        'Cʟᴏsᴇ ✖️', callback_data='close')]
                ]),
            )
        except Exception as e:
            print(f"! Error Occurred on callback data = 'setting' : {e}")

    elif data == "start":
        await query.edit_message_media(
            InputMediaPhoto(random.choice(PICS),
                            START_MSG.format(
                                first=query.from_user.first_name,
                                last=query.from_user.last_name,
                                username=None if not query.from_user.username else '@' + query.from_user.username,
                                mention=query.from_user.mention,
                                id=query.from_user.id
            )
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🤖 Aʙᴏᴜᴛ ᴍᴇ', callback_data='about'), InlineKeyboardButton(
                    'Sᴇᴛᴛɪɴɢs ⚙️', callback_data='setting')]
            ]),
        )

    elif data == "files_cmd":
        if await authoUser(query, query.from_user.id):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            try:
                protect_content, pcd = await fileSettings(db.get_protect_content)
                hide_caption, hcd = await fileSettings(db.get_hide_caption)
                channel_button, cbd = await fileSettings(db.get_channel_button)
                name, link = await kingdb.get_channel_button_link()

                await query.edit_message_media(
                    InputMediaPhoto(files_cmd_pic,
                                    FILES_CMD_TXT.format(
                                        protect_content=protect_content,
                                        hide_caption=hide_caption,
                                        channel_button=channel_button,
                                        name=name,
                                        link=link
                                    )
                                    ),
                    reply_markup=InlineKeyboardMarkup(
                        buttonStatus(pcd, hcd, cbd)),
                )
            except Exception as e:
                print(f"! Error Occurred on callback data = 'files_cmd' : {e}")

    elif data == "pc":
        if await authoUser(query, query.from_user.id):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            try:
                pic, protect_content, pcd = await fileSettings(db.get_protect_content, db.set_protect_content)
                hide_caption, hcd = await fileSettings(db.get_hide_caption)
                channel_button, cbd = await fileSettings(db.get_channel_button)
                name, link = await db.get_channel_button_link()

                await query.edit_message_media(
                    InputMediaPhoto(pic,
                                    FILES_CMD_TXT.format(
                                        protect_content=protect_content,
                                        hide_caption=hide_caption,
                                        channel_button=channel_button,
                                        name=name,
                                        link=link
                                    )
                                    ),
                    reply_markup=InlineKeyboardMarkup(
                        buttonStatus(pcd, hcd, cbd))
                )
            except Exception as e:
                print(f"! Error Occurred on callback data = 'pc' : {e}")

    elif data == "hc":
        if await authoUser(query, query.from_user.id):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            try:
                protect_content, pcd = await fileSettings(db.get_protect_content)
                pic, hide_caption, hcd = await fileSettings(db.get_hide_caption, db.set_hide_caption)
                channel_button, cbd = await fileSettings(db.get_channel_button)
                name, link = await db.get_channel_button_link()

                await query.edit_message_media(
                    InputMediaPhoto(pic,
                                    FILES_CMD_TXT.format(
                                        protect_content=protect_content,
                                        hide_caption=hide_caption,
                                        channel_button=channel_button,
                                        name=name,
                                        link=link
                                    )
                                    ),
                    reply_markup=InlineKeyboardMarkup(
                        buttonStatus(pcd, hcd, cbd))
                )
            except Exception as e:
                print(f"! Error Occurred on callback data = 'hc' : {e}")

    elif data == "cb":
        if await authoUser(query, query.from_user.id):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            try:
                protect_content, pcd = await fileSettings(db.get_protect_content)
                hide_caption, hcd = await fileSettings(db.get_hide_caption)
                pic, channel_button, cbd = await fileSettings(db.get_channel_button, db.set_channel_button)
                name, link = await db.get_channel_button_link()

                await query.edit_message_media(
                    InputMediaPhoto(pic,
                                    FILES_CMD_TXT.format(
                                        protect_content=protect_content,
                                        hide_caption=hide_caption,
                                        channel_button=channel_button,
                                        name=name,
                                        link=link
                                    )
                                    ),
                    reply_markup=InlineKeyboardMarkup(
                        buttonStatus(pcd, hcd, cbd))
                )
            except Exception as e:
                print(f"! Error Occurred on callback data = 'cb' : {e}")

    elif data == "setcb":
        id = query.from_user.id
        if await authoUser(query, id):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            try:
                button_name, button_link = await db.get_channel_button_link()

                button_preview = [[InlineKeyboardButton(
                    text=button_name, url=button_link)]]
                set_msg = await client.ask(chat_id=id, text=f'<b>Tᴏ ᴄʜᴀɴɢᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴ, Pʟᴇᴀsᴇ sᴇɴᴅ ᴠᴀʟɪᴅ ᴀʀɢᴜᴍᴇɴᴛs ᴡɪᴛʜɪɴ 1 ᴍɪɴᴜᴛᴇ.\nFᴏʀ ᴇxᴀᴍᴘʟᴇ:\n<blockquote><code>Join Channel - https://t.me/Tera_Downloder</code></blockquote>\n\n<i>Bᴇʟᴏᴡ ɪs ʙᴜᴛᴛᴏɴ Pʀᴇᴠɪᴇᴡ ⬇️</i></b>', timeout=60, reply_markup=InlineKeyboardMarkup(button_preview), disable_web_page_preview=True)
                button = set_msg.text.split(' - ')

                if len(button) != 2:
                    markup = [[InlineKeyboardButton(
                        f'◈ Sᴇᴛ Cʜᴀɴɴᴇʟ Bᴜᴛᴛᴏɴ ➪', callback_data='setcb')]]
                    return await set_msg.reply("<b>Pʟᴇᴀsᴇ sᴇɴᴅ ᴠᴀʟɪᴅ ᴀʀɢᴜᴍᴇɴᴛs.\nFᴏʀ ᴇxᴀᴍᴘʟᴇ:\n<blockquote><code>Join Channel - https://t.me/AlwaysToHelpBot</code></blockquote>\n\n<i>Tʀʏ ᴀɢᴀɪɴ ʙʏ ᴄʟɪᴄᴋɪɴɢ ʙᴇʟᴏᴡ ʙᴜᴛᴛᴏɴ..</i></b>", reply_markup=InlineKeyboardMarkup(markup), disable_web_page_preview=True)

                button_name = button[0].strip()
                button_link = button[1].strip()
                button_preview = [[InlineKeyboardButton(
                    text=button_name, url=button_link)]]

                await set_msg.reply("<b><i>Aᴅᴅᴇᴅ Sᴜᴄcᴇssғᴜʟʟʏ ✅</i>\n<blockquote>Sᴇᴇ ʙᴇʟᴏᴡ ʙᴜᴛᴛᴏɴ ᴀs Pʀᴇᴠɪᴇᴡ ⬇️</blockquote></b>", reply_markup=InlineKeyboardMarkup(button_preview))
                await db.set_channel_button_link(button_name, button_link)
                return
            except Exception as e:
                try:
                    await set_msg.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ..\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>")
                    print(f"! Error Occurred on callback data = 'setcb' : {e}")
                except BaseException:
                    await client.send_message(id, text=f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ..\n<blockquote><i>Rᴇᴀsᴏɴ: 1 minute Time out ..</i></b></blockquote>", disable_notification=True)
                    print(
                        f"! Error Occurred on callback data = 'setcb' -> Rᴇᴀsᴏɴ: 1 minute Time out ..")


    elif data == 'autodel_cmd':
        if await authoUser(query, query.from_user.id, owner_only=True):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            try:
                timer = convert_time(await db.get_del_timer())
                autodel_mode, mode = await fileSettings(db.get_auto_delete, delfunc=True)

                await query.edit_message_media(
                    InputMediaPhoto(autodel_cmd_pic,
                                    AUTODEL_CMD_TXT.format(
                                        autodel_mode=autodel_mode,
                                        timer=timer
                                    )
                                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(mode, callback_data='chng_autodel'), InlineKeyboardButton(
                            '◈ Sᴇᴛ Tɪᴍᴇʀ ⏱', callback_data='set_timer')],
                        [InlineKeyboardButton('🔄 Rᴇғʀᴇsʜ', callback_data='autodel_cmd'), InlineKeyboardButton(
                            'Cʟᴏsᴇ ✖️', callback_data='close')]
                    ])
                )
            except Exception as e:
                print(
                    f"! Error Occurred on callback data = 'autodel_cmd' : {e}")

    elif data == 'chng_autodel':
        if await authoUser(query, query.from_user.id, owner_only=True):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            try:
                timer = convert_time(await db.get_del_timer())
                pic, autodel_mode, mode = await fileSettings(db.get_auto_delete, db.set_auto_delete, delfunc=True)

                await query.edit_message_media(
                    InputMediaPhoto(pic,
                                    AUTODEL_CMD_TXT.format(
                                        autodel_mode=autodel_mode,
                                        timer=timer
                                    )
                                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(mode, callback_data='chng_autodel'), InlineKeyboardButton(
                            '◈ Sᴇᴛ Tɪᴍᴇʀ ⏱', callback_data='set_timer')],
                        [InlineKeyboardButton('🔄 Rᴇғʀᴇsʜ', callback_data='autodel_cmd'), InlineKeyboardButton(
                            'Cʟᴏsᴇ ✖️', callback_data='close')]
                    ])
                )
            except Exception as e:
                print(
                    f"! Error Occurred on callback data = 'chng_autodel' : {e}")

    elif data == 'set_timer':
        id = query.from_user.id
        if await authoUser(query, id, owner_only=True):
            try:

                timer = convert_time(await db.get_del_timer())
                set_msg = await client.ask(chat_id=id, text=f'<b><blockquote>⏱ Cᴜʀʀᴇɴᴛ Tɪᴍᴇʀ: {timer}</blockquote>\n\nTᴏ ᴄʜᴀɴɢᴇ ᴛɪᴍᴇʀ, Pʟᴇᴀsᴇ sᴇɴᴅ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ ɪɴ sᴇᴄᴏɴᴅs ᴡɪᴛʜɪɴ 1 ᴍɪɴᴜᴛᴇ.\n<blockquote>Fᴏʀ ᴇxᴀᴍᴘʟᴇ: <code>300</code>, <code>600</code>, <code>900</code></b></blockquote>', timeout=60)
                del_timer = set_msg.text.split()

                if len(del_timer) == 1 and del_timer[0].isdigit():
                    DEL_TIMER = int(del_timer[0])
                    await db.set_del_timer(DEL_TIMER)
                    timer = convert_time(DEL_TIMER)
                    await set_msg.reply(f"<b><i>Aᴅᴅᴇᴅ Sᴜᴄcᴇssғᴜʟʟʏ ✅</i>\n<blockquote>⏱ Cᴜʀʀᴇɴᴛ Tɪᴍᴇʀ: {timer}</blockquote></b>")
                else:
                    markup = [[InlineKeyboardButton(
                        '◈ Sᴇᴛ Dᴇʟᴇᴛᴇ Tɪᴍᴇʀ ⏱', callback_data='set_timer')]]
                    return await set_msg.reply("<b>Pʟᴇᴀsᴇ sᴇɴᴅ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ ɪɴ sᴇᴄᴏɴᴅs.\n<blockquote>Fᴏʀ ᴇxᴀᴍᴘʟᴇ: <code>300</code>, <code>600</code>, <code>900</code></blockquote>\n\n<i>Tʀʏ ᴀɢᴀɪɴ ʙʏ ᴄʟɪᴄᴋɪɴɢ ʙᴇʟᴏᴡ ʙᴜᴛᴛᴏɴ..</i></b>", reply_markup=InlineKeyboardMarkup(markup))

            except Exception as e:
                try:
                    await set_msg.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ..\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>")
                    print(
                        f"! Error Occurred on callback data = 'set_timer' : {e}")
                except BaseException:
                    await client.send_message(id, text=f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ..\n<blockquote><i>Rᴇᴀsᴏɴ: 1 minute Time out ..</i></b></blockquote>", disable_notification=True)
                    print(
                        f"! Error Occurred on callback data = 'set_timer' -> Rᴇᴀsᴏɴ: 1 minute Time out ..")

    elif data == 'chng_req':
        if await authoUser(query, query.from_user.id, owner_only=True):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            try:
                on = off = ""
                if await db.get_request_forcesub():
                    await db.set_request_forcesub(False)
                    off = "🔴"
                    texting = off_txt
                else:
                    await db.set_request_forcesub(True)
                    on = "🟢"
                    texting = on_txt

                button = [
                    [InlineKeyboardButton(f"{on} ON", "chng_req"), InlineKeyboardButton(
                        f"{off} OFF", "chng_req")],
                    [InlineKeyboardButton(
                        "⚙️ Mᴏʀᴇ Sᴇᴛᴛɪɴɢs ⚙️", "more_settings")]
                ]
                # 🎉)
                await query.message.edit_text(text=RFSUB_CMD_TXT.format(req_mode=texting), reply_markup=InlineKeyboardMarkup(button))

            except Exception as e:
                print(f"! Error Occurred on callback data = 'chng_req' : {e}")

    elif data == 'more_settings':
        if await authoUser(query, query.from_user.id, owner_only=True):
            # await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")
            try:
                await query.message.edit_text("<b>Pʟᴇᴀsᴇ wᴀɪᴛ !\n\n<i>🔄 Rᴇᴛʀɪᴇᴠɪɴɢ ᴀʟʟ Sᴇᴛᴛɪɴɢs...</i></b>")
                LISTS = "Eᴍᴘᴛʏ Rᴇǫᴜᴇsᴛ FᴏʀᴄᴇSᴜʙ Cʜᴀɴɴᴇʟ Lɪsᴛ !?"

                REQFSUB_CHNLS = await db.get_reqChannel()
                if REQFSUB_CHNLS:
                    LISTS = ""
                    channel_name = "<i>Uɴᴀʙʟᴇ Lᴏᴀᴅ Nᴀᴍᴇ..</i>"
                    for CHNL in REQFSUB_CHNLS:
                        await query.message.reply_chat_action(ChatAction.TYPING)
                        try:
                            name = (await client.get_chat(CHNL)).title
                        except BaseException:
                            name = None
                        channel_name = name if name else channel_name

                        user = await db.get_reqSent_user(CHNL)
                        channel_users = len(user) if user else 0

                        link = await db.get_stored_reqLink(CHNL)
                        if link:
                            channel_name = f"<a href={link}>{channel_name}</a>"

                        LISTS += f"NAME: {channel_name}\n(ID: <code>{CHNL}</code>)\nUSERS: {channel_users}\n\n"

                buttons = [
                    [InlineKeyboardButton("ᴄʟᴇᴀʀ ᴜsᴇʀs", "clear_users"), InlineKeyboardButton(
                        "cʟᴇᴀʀ cʜᴀɴɴᴇʟs", "clear_chnls")],
                    [InlineKeyboardButton(
                        "♻️  Rᴇғʀᴇsʜ Sᴛᴀᴛᴜs  ♻️", "more_settings")],
                    [InlineKeyboardButton("⬅️ Bᴀᴄᴋ", "req_fsub"), InlineKeyboardButton(
                        "Cʟᴏsᴇ ✖️", "close")]
                ]
                await query.message.reply_chat_action(ChatAction.CANCEL)
                await query.message.edit_text(text=RFSUB_MS_TXT.format(reqfsub_list=LISTS.strip()), reply_markup=InlineKeyboardMarkup(buttons))

            except Exception as e:
                print(
                    f"! Error Occurred on callback data = 'more_settings' : {e}")

    elif data == 'clear_users':
        # if await authoUser(query, query.from_user.id, owner_only=True) :
        # await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")
        try:
            REQFSUB_CHNLS = await db.get_reqChannel()
            if not REQFSUB_CHNLS:
                return await query.answer("Eᴍᴘᴛʏ Rᴇǫᴜᴇsᴛ FᴏʀᴄᴇSᴜʙ Cʜᴀɴɴᴇʟ !?", show_alert=True)

            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            REQFSUB_CHNLS = list(map(str, REQFSUB_CHNLS))
            buttons = [REQFSUB_CHNLS[i:i + 2]
                       for i in range(0, len(REQFSUB_CHNLS), 2)]
            buttons.insert(0, ['CANCEL'])
            buttons.append(['DELETE ALL CHANNELS USER'])

            user_reply = await client.ask(query.from_user.id, text=CLEAR_USERS_TXT, reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True))

            if user_reply.text == 'CANCEL':
                return await user_reply.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ...</i></b>", reply_markup=ReplyKeyboardRemove())

            elif user_reply.text in REQFSUB_CHNLS:
                try:
                    await db.clear_reqSent_user(int(user_reply.text))
                    return await user_reply.reply(f"<b><blockquote>✅ Usᴇʀ Dᴀᴛᴀ Sᴜᴄᴄᴇssғᴜʟʟʏ Cʟᴇᴀʀᴇᴅ ғʀᴏᴍ Cʜᴀɴɴᴇʟ ɪᴅ: <code>{user_reply.text}</code></blockquote></b>", reply_markup=ReplyKeyboardRemove())
                except Exception as e:
                    return await user_reply.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ...\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>", reply_markup=ReplyKeyboardRemove())

            elif user_reply.text == 'DELETE ALL CHANNELS USER':
                try:
                    for CHNL in REQFSUB_CHNLS:
                        await db.clear_reqSent_user(int(CHNL))
                    return await user_reply.reply(f"<b><blockquote>✅ Usᴇʀ Dᴀᴛᴀ Sᴜᴄᴄᴇssғᴜʟʟʏ Cʟᴇᴀʀᴇᴅ ғʀᴏᴍ Aʟʟ Cʜᴀɴɴᴇʟ ɪᴅs</blockquote></b>", reply_markup=ReplyKeyboardRemove())
                except Exception as e:
                    return await user_reply.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ...\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>", reply_markup=ReplyKeyboardRemove())

            else:
                return await user_reply.reply(f"<b><blockquote>INVALID SELECTIONS</blockquote></b>", reply_markup=ReplyKeyboardRemove())

        except Exception as e:
            print(f"! Error Occurred on callback data = 'clear_users' : {e}")

    elif data == 'clear_chnls':
        # if await authoUser(query, query.from_user.id, owner_only=True)

        try:
            REQFSUB_CHNLS = await db.get_reqChannel()
            if not REQFSUB_CHNLS:
                return await query.answer("Eᴍᴘᴛʏ Rᴇǫᴜᴇsᴛ FᴏʀᴄᴇSᴜʙ Cʜᴀɴɴᴇʟ !?", show_alert=True)

            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            REQFSUB_CHNLS = list(map(str, REQFSUB_CHNLS))
            buttons = [REQFSUB_CHNLS[i:i + 2]
                       for i in range(0, len(REQFSUB_CHNLS), 2)]
            buttons.insert(0, ['CANCEL'])
            buttons.append(['DELETE ALL CHANNEL IDS'])

            user_reply = await client.ask(query.from_user.id, text=CLEAR_CHNLS_TXT, reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True))

            if user_reply.text == 'CANCEL':
                return await user_reply.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ...</i></b>", reply_markup=ReplyKeyboardRemove())

            elif user_reply.text in REQFSUB_CHNLS:
                try:
                    chnl_id = int(user_reply.text)

                    await db.del_reqChannel(chnl_id)

                    try:
                        await client.revoke_chat_invite_link(chnl_id, await db.get_stored_reqLink(chnl_id))
                    except BaseException:
                        pass

                    await db.del_stored_reqLink(chnl_id)

                    return await user_reply.reply(f"<b><blockquote><code>{user_reply.text}</code> Cʜᴀɴɴᴇʟ ɪᴅ ᴀʟᴏɴɢ ᴡɪᴛʜ ɪᴛs ᴅᴀᴛᴀ sᴜᴄᴄᴇssғᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ ✅</blockquote></b>", reply_markup=ReplyKeyboardRemove())
                except Exception as e:
                    return await user_reply.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ...\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>", reply_markup=ReplyKeyboardRemove())

            elif user_reply.text == 'DELETE ALL CHANNEL IDS':
                try:
                    for CHNL in REQFSUB_CHNLS:
                        chnl = int(CHNL)

                        await db.del_reqChannel(chnl)

                        try:
                            await client.revoke_chat_invite_link(chnl, await db.get_stored_reqLink(chnl))
                        except BaseException:
                            pass

                        await db.del_stored_reqLink(chnl)

                    return await user_reply.reply(f"<b><blockquote>Aʟʟ Cʜᴀɴɴᴇʟ ɪᴅs ᴀʟᴏɴɢ ᴡɪᴛʜ ɪᴛs ᴅᴀᴛᴀ sᴜᴄᴄᴇssғᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ ✅</blockquote></b>", reply_markup=ReplyKeyboardRemove())

                except Exception as e:
                    return await user_reply.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ...\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>", reply_markup=ReplyKeyboardRemove())

            else:
                return await user_reply.reply(f"<b><blockquote>INVALID SELECTIONS</blockquote></b>", reply_markup=ReplyKeyboardRemove())

        except Exception as e:
            print(f"! Error Occurred on callback data = 'more_settings' : {e}")

    elif data == 'clear_links':
        # if await authoUser(query, query.from_user.id, owner_only=True) :
        # await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

        try:
            REQFSUB_CHNLS = await db.get_reqLink_channels()
            if not REQFSUB_CHNLS:
                return await query.answer("Nᴏ Sᴛᴏʀᴇᴅ Rᴇǫᴜᴇsᴛ Lɪɴᴋ Aᴠᴀɪʟᴀʙʟᴇ !?", show_alert=True)

            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

            REQFSUB_CHNLS = list(map(str, REQFSUB_CHNLS))
            buttons = [REQFSUB_CHNLS[i:i + 2]
                       for i in range(0, len(REQFSUB_CHNLS), 2)]
            buttons.insert(0, ['CANCEL'])
            buttons.append(['DELETE ALL REQUEST LINKS'])

            user_reply = await client.ask(query.from_user.id, text=CLEAR_LINKS_TXT, reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True))

            if user_reply.text == 'CANCEL':
                return await user_reply.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ...</i></b>", reply_markup=ReplyKeyboardRemove())

            elif user_reply.text in REQFSUB_CHNLS:
                channel_id = int(user_reply.text)
                try:
                    try:
                        await client.revoke_chat_invite_link(channel_id, await db.get_stored_reqLink(channel_id))
                    except BaseException:
                        text = """<b>❌ Uɴᴀʙʟᴇ ᴛᴏ Rᴇᴠᴏᴋᴇ ʟɪɴᴋ !
<blockquote expandable>ɪᴅ: <code>{}</code></b>
<i>Eɪᴛʜᴇʀ ᴛʜᴇ ʙᴏᴛ ɪs ɴᴏᴛ ɪɴ ᴀʙᴏᴠᴇ ᴄʜᴀɴɴᴇʟ Oʀ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴘʀᴏᴘᴇʀ ᴀᴅᴍɪɴ ᴘᴇʀᴍɪssɪᴏɴs</i></blockquote>"""
                        return await user_reply.reply(text=text.format(channel_id), reply_markup=ReplyKeyboardRemove())

                    await db.del_stored_reqLink(channel_id)
                    return await user_reply.reply(f"<b><blockquote><code>{channel_id}</code> Cʜᴀɴɴᴇʟs Lɪɴᴋ Sᴜᴄᴄᴇssғᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ ✅</blockquote></b>", reply_markup=ReplyKeyboardRemove())

                except Exception as e:
                    return await user_reply.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ...\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>", reply_markup=ReplyKeyboardRemove())

            elif user_reply.text == 'DELETE ALL REQUEST LINKS':
                try:
                    result = ""
                    for CHNL in REQFSUB_CHNLS:
                        channel_id = int(CHNL)
                        try:
                            await client.revoke_chat_invite_link(channel_id, await db.get_stored_reqLink(channel_id))
                        except BaseException:
                            result += f"<blockquote expandable><b><code>{channel_id}</code> Uɴᴀʙʟᴇ ᴛᴏ Rᴇᴠᴏᴋᴇ ❌</b>\n<i>Eɪᴛʜᴇʀ ᴛʜᴇ ʙᴏᴛ ɪs ɴᴏᴛ ɪɴ ᴀʙᴏᴠᴇ ᴄʜᴀɴɴᴇʟ Oʀ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴘʀᴏᴘᴇʀ ᴀᴅᴍɪɴ ᴘᴇʀᴍɪssɪᴏɴs.</i></blockquote>\n"
                            continue
                        await db.del_stored_reqLink(channel_id)
                        result += f"<blockquote><b><code>{channel_id}</code> IDs Lɪɴᴋ Dᴇʟᴇᴛᴇᴅ ✅</b></blockquote>\n"

                    return await user_reply.reply(f"<b>⁉️ Oᴘᴇʀᴀᴛɪᴏɴ Rᴇsᴜʟᴛ:</b>\n{result.strip()}", reply_markup=ReplyKeyboardRemove())

                except Exception as e:
                    return await user_reply.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ...\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>", reply_markup=ReplyKeyboardRemove())

            else:
                return await user_reply.reply(f"<b><blockquote>INVALID SELECTIONS</blockquote></b>", reply_markup=ReplyKeyboardRemove())

        except Exception as e:
            print(f"! Error Occurred on callback data = 'more_settings' : {e}")

    elif data == 'req_fsub':
        # if await authoUser(query, query.from_user.id, owner_only=True) :
        await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")

        try:
            on = off = ""
            if await db.get_request_forcesub():
                on = "🟢"
                texting = on_txt
            else:
                off = "🔴"
                texting = off_txt

            button = [
                [InlineKeyboardButton(f"{on} ON", "chng_req"), InlineKeyboardButton(
                    f"{off} OFF", "chng_req")],
                [InlineKeyboardButton("⚙️ Mᴏʀᴇ Sᴇᴛᴛɪɴɢs ⚙️", "more_settings")]
            ]
            # 🎉)
            await query.message.edit_text(text=RFSUB_CMD_TXT.format(req_mode=texting), reply_markup=InlineKeyboardMarkup(button))

        except Exception as e:
            print(f"! Error Occurred on callback data = 'chng_req' : {e}")
    

    # Handle settings details
    elif data == "shortener_settings":
        if await authoUser(query, query.from_user.id, owner_only=True):
            try:
                await query.answer("💫 Fetching settings details...")

                shortener_url = await db.get_shortener_url()
                shortener_api = await db.get_shortener_api()
                protect_api = await db.get_protect_api_url()
                verified_time = await db.get_verified_time()
                tut_video = await db.get_tut_video()
                protect_mode = await db.get_protect_mode()
                shortener_mode = await db.get_shortener_mode()

                shortener_url_display = shortener_url or "Not set"
                shortener_api_display = shortener_api or "Not set"
                protect_api_display = protect_api or "Not set"
                
                shortener_status = "Enabled ✅" if shortener_mode else "Disabled ❌"
                protect_status = "Enabled ✅" if protect_mode else "Disabled ❌"
                
                verified_time_display = f"{verified_time} seconds" if verified_time else "Not set"
                tut_video_display = f"[Tutorial Video]({tut_video})" if tut_video else "Not set"

                response_text = (
                    f"⚙️ <b>Verification & Token Settings Details</b>\n\n"
                    f"🛡️ Protect Mode: <b>{protect_status}</b>\n"
                    f"🔗 Shortener Mode: <b>{shortener_status}</b>\n\n"
                    f"🌐 Shortener Site: <code>{shortener_url_display}</code>\n"
                    f"🔑 Shortener API Token: <code>{shortener_api_display}</code>\n"
                    f"🛠️ Protect API URL: <code>{protect_api_display}</code>\n"
                    f"⏱️ Verified Time Expiry: <b>{verified_time_display}</b>\n"
                    f"🎥 Tutorial Video: {tut_video_display}"
                )

                await query.message.edit_text(
                    text=response_text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔙 Back', callback_data='set_shortener')]
                    ]),
                    disable_web_page_preview=True
                )

            except Exception as e:
                logging.error(f"Error fetching settings: {e}")
                await query.message.reply(
                    f"⚠️ An error occurred: {e}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Back', callback_data='set_shortener')]])
                )


    elif data == "chng_shortener": 
        user_id = query.from_user.id
        shortener_details = await db.get_shortener()

    # Toggle the shortener status in the database
        if shortener_details:
        # Disable shortener
            await db.set_shortener("", "")
            await query.answer("Shortener Disabled ❌", show_alert=True)
        else:
        # Enable shortener, prompt for URL and API Key
            await query.answer("Shortener Enabled ✅. Please provide the Shortener URL and API Key.", show_alert=True)
            await query.message.reply("Send the Shortener URL and API Key in the format:\n`<shortener_url> <api_key>`")

    


    elif data == 'set_shortener_details':
        if await authoUser(query, query.from_user.id, owner_only=True):
            try:
                await query.answer("Please send the shortener URL within 1 minute...")
                set_msg_url = await query.message.reply(
                    "⏳ Please provide the Shortener site URL (e.g., https://example.com) within 1 minute.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Back', callback_data='set_shortener')]])
                )
                site_msg = await client.ask(
                    chat_id=query.from_user.id,
                    text="⏳ Enter Shortener site URL:",
                    timeout=60
                )

                shortener_url = site_msg.text.strip()


            # Confirm the shortener site URL
                await site_msg.reply(f"Shortener site URL set to: {shortener_url}\nNow please send the API key.")

            # Step 3: Prompt for API key
                set_msg_api = await query.message.reply(
                    "⏳ Please provide the API key for the shortener within 1 minute.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Back', callback_data='set_shortener')]])
                )

                api_msg = await client.ask(
                    chat_id=query.from_user.id,
                    text="⏳ Enter API key for the shortener:",
                    timeout=60
                )

                api_key = api_msg.text.strip()

            # Step 4: Save the shortener details in the database
                await db.set_shortener_url(shortener_url)
                await db.set_shortener_api(api_key)
            
            # Confirmation message
                await api_msg.reply(
                    "✅ Shortener details have been successfully set!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('◈ Disable Shortener ❌', callback_data='disable_shortener')],
                        [InlineKeyboardButton('Back', callback_data='set_shortener')]
                    ])
                )
            except asyncio.TimeoutError:
                await query.message.reply(
                    "⚠️ You did not provide the details in time. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Back', callback_data='set_shortener')]])
                )
            except Exception as e:
                logging.error(f"Error setting shortener details: {e}")  # This now works correctly
                await query.message.reply(
                    f"⚠️ Error occurred: {e}",
    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Back', callback_data='set_shortener')]])
    )


    elif data == "set_shortener":
        if await authoUser(query, query.from_user.id, owner_only=True):
            try:
                message = query.message

                protect_mode = await db.get_protect_mode()
                shortener_mode = await db.get_shortener_mode()

                shortener_status = "Enabled ✅" if shortener_mode else "Disabled ❌"
                protect_status = "Enabled ✅" if protect_mode else "Disabled ❌"

                mode_button = InlineKeyboardButton('Disable Shortener ❌', callback_data='disable_shortener') if shortener_mode else InlineKeyboardButton('Enable Shortener ✅', callback_data='enable_shortener')
                protect_button = InlineKeyboardButton('Disable Protect Mode 🔓', callback_data='disable_protect_mode') if protect_mode else InlineKeyboardButton('Enable Protect Mode 🛡️', callback_data='enable_protect_mode')

                await message.edit_media(
                    media=InputMediaPhoto(
                        media=START_PIC,
                        caption=SET_SHORTENER_CMD_TXT.format(shortener_status=shortener_status, protect_status=protect_status),
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [mode_button],
                        [protect_button],
                        [InlineKeyboardButton('Set Site & API key 🌐', callback_data='set_shortener_details')],
                        [InlineKeyboardButton('Set Protect API URL 🛠️', callback_data='set_protect_api_url')],
                        [
                            InlineKeyboardButton('Settings ⚙️', callback_data='shortener_settings'),
                            InlineKeyboardButton('🔄 Refresh', callback_data='set_shortener')
                        ],
                        [
                            InlineKeyboardButton('Set Verified Time ⏱', callback_data='set_verify_time'),
                            InlineKeyboardButton('Set Tutorial Video 🎥', callback_data='set_tut_video')
                        ],
                        [InlineKeyboardButton('📢 Post Channel', callback_data='post_channel_menu')],
                        [InlineKeyboardButton('Close ✖️', callback_data='close')]
                    ])
                )

            except MessageNotModified:
                await query.answer("✅ Already up to date!", show_alert=False)
            except Exception as e:
                await query.answer(f"Error: {e}", show_alert=True)

    elif data == "set_tut_video":
        id = query.from_user.id

        if await authoUser(query, id, owner_only=True):
            await query.answer("♻️ Qᴜᴇʀʏ Pʀᴏᴄᴇssɪɴɢ....")
        
            try:
            # Fetch the current tutorial video URL from the database
                current_video_url = await db.get_tut_video()

            # Prompt the user to input the new tutorial video URL
                set_msg = await client.ask(
                    chat_id=id,
                    text=f'<b><blockquote>⏳ Cᴜʀʀᴇɴᴛ Tᴜᴛᴏʀɪᴀʟ Vɪᴅᴇᴏ URL: {current_video_url if current_video_url else "Not Set"}</blockquote>\n\nTᴏ ᴄʜᴀɴɢᴇ, Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴠɪᴅᴇᴏ URL.\n<blockquote>Fᴏʀ ᴇxᴀᴍᴘʟᴇ: <code>https://youtube.com/some_video</code></b></blockquote>',
                    timeout=60
                )

            # Validate the user input for a valid URL
                video_url = set_msg.text.strip()

                if video_url.startswith("http") and "://" in video_url:
                # Save the new tutorial video URL to the database
                    await db.set_tut_video(video_url)

                # Confirm the update to the user
                    await set_msg.reply(f"<b><i>Tᴜᴛᴏʀɪᴀʟ Vɪᴅᴇᴏ URL sᴇᴛ sᴜᴄᴄᴇssғᴜʟʟʏ ✅</i>\n<blockquote>📹 Cᴜʀʀᴇɴᴛ Tᴜᴛᴏʀɪᴀʟ Vɪᴅᴇᴏ URL: {video_url}</blockquote></b>")
                else:
                # If the URL is invalid, prompt the user to try again
                    markup = [[InlineKeyboardButton(
                        '◈ Sᴇᴛ Tᴜᴛᴏʀɪᴀʟ Vɪᴅᴇᴏ URL 📹', callback_data='set_tut_video')]]
                    return await set_msg.reply(
                        "<b>Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ʟɪɴᴋ ᴛᴏ ᴀ ᴠᴀʟɪᴅ ᴠɪᴅᴇᴏ.\n<blockquote>Fᴏʀ ᴇxᴀᴍᴘʟᴇ: <code>https://youtube.com/some_video</code></blockquote>\n\n<i>Tʀʏ ᴀɢᴀɪɴ ʙʏ ᴄʟɪᴄᴋɪɴɢ ʙᴇʟᴏᴡ ʙᴜᴛᴛᴏɴ..</i></b>", reply_markup=InlineKeyboardMarkup(markup))

            except Exception as e:
                try:
                # Handle any exceptions that occur during the process
                    await set_msg.reply(f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ..\n<blockquote>Rᴇᴀsᴏɴ:</b> {e}</blockquote>")
                    print(f"! Error Occurred on callback data = 'set_tut_video' : {e}")
                except BaseException:
                # If an error occurs while sending the error message, send a timeout message
                    await client.send_message(id, text=f"<b>! Eʀʀᴏʀ Oᴄᴄᴜʀᴇᴅ..\n<blockquote><i>Rᴇᴀsᴏɴ: 1 minute Time out ..</i></b></blockquote>", disable_notification=True)
                    print(f"! Error Occurred on callback data = 'set_tut_video' -> Reason: 1 minute Time out ..")


    elif data == 'set_verify_time':
        id = query.from_user.id

        if await authoUser(query, id, owner_only=True):
            await query.answer("♻️ Processing request...")

            try:
                # Fetch the current verified time from the database
                current_verify_time = await db.get_verified_time()
                time_display = f"{current_verify_time} seconds" if current_verify_time else "Not set"

                # Prompt the user to input a new verified time
                set_msg = await client.ask(
                    chat_id=id,
                    text=(
                        f"<b><blockquote>⏱ Current Timer: {time_display}</blockquote>\n\n"
                        f"To change the timer, please send a valid number in seconds within 1 minute.\n"
                        f"<blockquote>For example: <code>300</code>, <code>600</code>, <code>900</code></blockquote></b>"
                    ),
                    timeout=60
                )

                # Validate the user input
                verify_time_input = set_msg.text.strip()
                if verify_time_input.isdigit():
                    verify_time = int(verify_time_input)

                    # Save the new verified time to the database
                    await db.set_verified_time(verify_time)
                    formatted_time = f"{verify_time} seconds"
                    
                    # Confirm the update to the user
                    await set_msg.reply(
                        f"<b><i>Timer updated successfully ✅</i>\n"
                        f"<blockquote>⏱ Current Timer: {formatted_time}</blockquote></b>"
                    )
                else:
                    # Handle invalid input
                    markup = [[InlineKeyboardButton('◈ Set Verify Timer ⏱', callback_data='set_verify_time')]]
                    return await set_msg.reply(
                        "<b>Please send a valid number in seconds.\n"
                        "<blockquote>For example: <code>300</code>, <code>600</code>, <code>900</code></blockquote>\n\n"
                        "<i>Try again by clicking the button below.</i></b>",
                        reply_markup=InlineKeyboardMarkup(markup)
                    )

            except asyncio.TimeoutError:
                # Handle timeout if user doesn't respond in time
                await client.send_message(
                    id,
                    text="<b>⚠️ Timeout occurred. You did not respond within the time limit.</b>",
                    disable_notification=True
                )
            except Exception as e:
                # Handle any other exceptions
                await client.send_message(
                    id,
                    text=f"<b>⚠️ Error occurred:\n<blockquote>{e}</blockquote></b>",
                    disable_notification=True
                )
                print(f"! Error occurred on callback data = 'set_verify_time' : {e}")



    elif data == "enable_shortener":
        await query.answer()
        await db.set_shortener_mode(True)
        await query.message.reply("Shortener Mode Enabled ✅ (Protect Mode Disabled automatically)")
        query.data = "set_shortener"
        await cb_handler(client, query)

    elif data == "disable_shortener":
        await query.answer()
        await db.set_shortener_mode(False)
        await query.message.reply("Shortener Mode Disabled ❌")
        query.data = "set_shortener"
        await cb_handler(client, query)

    elif data == "enable_protect_mode":
        await query.answer()
        await db.set_protect_mode(True)
        await query.message.reply("Protect Mode Enabled 🛡️ (Shortener Mode Disabled automatically)")
        query.data = "set_shortener"
        await cb_handler(client, query)

    elif data == "disable_protect_mode":
        await query.answer()
        await db.set_protect_mode(False)
        await db.set_shortener_mode(True)
        await query.message.reply("Protect Mode Disabled 🔓 (Shortener Mode Enabled by default)")
        query.data = "set_shortener"
        await cb_handler(client, query)

    elif data == "set_protect_api_url":
        id = query.from_user.id
        if await authoUser(query, id, owner_only=True):
            try:
                current_url = await db.get_protect_api_url()
                set_msg = await client.ask(
                    chat_id=id,
                    text=f'<b><blockquote>⏳ Current Protect API URL: {current_url or "Not Set"}</blockquote>\n\nPlease send the new Protect API URL within 1 minute.</b>',
                    timeout=60
                )
                new_url = set_msg.text.strip()
                if new_url.startswith("http"):
                    await db.set_protect_api_url(new_url)
                    await set_msg.reply(f"<b>Protect API URL set successfully ✅\n<blockquote>🛠️ URL: {new_url}</blockquote></b>")
                else:
                    return await set_msg.reply("<b>Invalid URL format. Please try again.</b>")
            except Exception as e:
                print(f"Error setting protect API: {e}")


    # ==================== POST CHANNEL SETTINGS (used by /plink) ====================

    elif data == "post_channel_menu":
        if await authoUser(query, query.from_user.id):
            try:
                await query.answer()
                channel_ids = await db.get_all_post_channels()

                if channel_ids:
                    lines = []
                    for cid in channel_ids:
                        try:
                            chat = await client.get_chat(cid)
                            title = chat.title
                        except Exception:
                            title = "Unknown / Not accessible"
                        lines.append(f"◈ {title} (<code>{cid}</code>)")
                    channel_list = "\n".join(lines)
                else:
                    channel_list = "❌ Nᴏ Pᴏsᴛ Cʜᴀɴɴᴇʟ sᴇᴛ ʏᴇᴛ."

                await query.message.edit_caption(
                    caption=POST_CHANNEL_TXT.format(channel_list=channel_list),
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton('➕ Add Channel', callback_data='add_post_channel'),
                            InlineKeyboardButton('➖ Delete Channel', callback_data='del_post_channel_menu')
                        ],
                        [InlineKeyboardButton('🔙 Back', callback_data='set_shortener')]
                    ])
                )
            except MessageNotModified:
                await query.answer()
            except Exception as e:
                print(f"! Error Occurred on callback data = 'post_channel_menu' : {e}")
                await query.answer(f"Error: {e}", show_alert=True)


    elif data == "add_post_channel":
        id = query.from_user.id
        if await authoUser(query, id, owner_only=True):
            back_markup = InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Back', callback_data='post_channel_menu')]])
            try:
                await query.answer()
                ask_msg = await client.ask(
                    chat_id=id,
                    text=(
                        "<b><blockquote>📢 Aᴅᴅ Pᴏsᴛ Cʜᴀɴɴᴇʟ</blockquote>\n\n"
                        "Fᴏʀᴡᴀʀᴅ ᴀɴʏ ᴍᴇssᴀɢᴇ ғʀᴏᴍ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ (ᴡɪᴛʜ Qᴜᴏᴛᴇs), ᴏʀ sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID / @ᴜsᴇʀɴᴀᴍᴇ, ᴡɪᴛʜɪɴ 1 ᴍɪɴᴜᴛᴇ.\n\n"
                        "<i>⚠️ Mᴀᴋᴇ sᴜʀᴇ ᴛʜᴇ ʙᴏᴛ ɪs ᴀᴅᴅᴇᴅ ᴀs ᴀᴅᴍɪɴ (ᴡɪᴛʜ ᴘᴏsᴛ ᴘᴇʀᴍɪssɪᴏɴ) ɪɴ ᴛʜᴀᴛ ᴄʜᴀɴɴᴇʟ.</i></b>"
                    ),
                    timeout=60
                )

                channel_id, channel_title = None, None
                try:
                    if ask_msg.forward_from_chat:
                        chat = ask_msg.forward_from_chat
                        channel_id, channel_title = chat.id, chat.title
                    elif ask_msg.text:
                        text = ask_msg.text.strip()
                        try:
                            lookup = int(text)
                        except ValueError:
                            lookup = text
                        chat = await client.get_chat(lookup)
                        channel_id, channel_title = chat.id, chat.title
                except Exception:
                    channel_id = None

                if not channel_id:
                    return await ask_msg.reply(
                        "<b>❌ Cʜᴀɴɴᴇʟ ᴅᴇᴛᴇᴄᴛ ɴᴀʜɪ ʜᴜᴀ.</b>\n<blockquote>Eɪᴛʜᴇʀ ᴀ ᴍᴇssᴀɢᴇ ғᴏʀᴡᴀʀᴅ ᴋᴀʀᴏ ᴜss ᴄʜᴀɴɴᴇʟ sᴇ, ʏᴀ ᴠᴀʟɪᴅ ID/username ʙʜᴇᴊᴏ, ᴀᴜʀ ᴄᴏɴғɪʀᴍ ᴋᴀʀᴏ ᴋɪ ʙᴏᴛ ᴜss ᴄʜᴀɴɴᴇʟ ᴍᴇ ᴀᴅᴍɪɴ ʜᴀɪ.</blockquote>",
                        reply_markup=back_markup
                    )

                if await db.post_channel_exist(channel_id):
                    return await ask_msg.reply(
                        f"<b>ℹ️ Yᴇ ᴄʜᴀɴɴᴇʟ ᴘᴀʜᴀʟᴇ sᴇ ʜɪ ᴀᴅᴅᴇᴅ ʜᴀɪ.</b>\n<blockquote>{channel_title} (<code>{channel_id}</code>)</blockquote>",
                        reply_markup=back_markup
                    )

                await db.add_post_channel(channel_id)
                await ask_msg.reply(
                    f"<b>✅ Pᴏsᴛ Cʜᴀɴɴᴇʟ ᴀᴅᴅᴇᴅ!</b>\n<blockquote>Nᴀᴍᴇ: {channel_title}\nID: <code>{channel_id}</code></blockquote>",
                    reply_markup=back_markup
                )

            except asyncio.TimeoutError:
                await client.send_message(id, "<b>⚠️ Timeout ho gaya. Dubara try karo.</b>", disable_notification=True, reply_markup=back_markup)
            except Exception as e:
                print(f"! Error Occurred on callback data = 'add_post_channel' : {e}")
                await client.send_message(id, f"<b>⚠️ Error occurred:\n<blockquote>{e}</blockquote></b>", disable_notification=True, reply_markup=back_markup)


    elif data == "del_post_channel_menu":
        if await authoUser(query, query.from_user.id, owner_only=True):
            try:
                await query.answer()
                channel_ids = await db.get_all_post_channels()

                if not channel_ids:
                    return await query.message.edit_caption(
                        caption="<b>❌ Dᴇʟᴇᴛᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ᴋᴏɪ Pᴏsᴛ Cʜᴀɴɴᴇʟ ɴᴀʜɪ ʜᴀɪ.</b>",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Back', callback_data='post_channel_menu')]])
                    )

                buttons = []
                for cid in channel_ids:
                    try:
                        chat = await client.get_chat(cid)
                        title = chat.title
                    except Exception:
                        title = str(cid)
                    buttons.append([InlineKeyboardButton(f"🗑 {title}", callback_data=f"delpost_{cid}")])
                buttons.append([InlineKeyboardButton('🔙 Back', callback_data='post_channel_menu')])

                await query.message.edit_caption(
                    caption="<b>➖ Dᴇʟᴇᴛᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ᴇᴋ ᴄʜᴀɴɴᴇʟ ᴄʜᴜɴᴏ:</b>",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except MessageNotModified:
                await query.answer()
            except Exception as e:
                print(f"! Error Occurred on callback data = 'del_post_channel_menu' : {e}")
                await query.answer(f"Error: {e}", show_alert=True)


    elif data.startswith("delpost_"):
        if await authoUser(query, query.from_user.id, owner_only=True):
            try:
                channel_id = int(data[len("delpost_"):])
                await db.del_post_channel(channel_id)
                await query.answer("✅ Channel removed", show_alert=False)
                query.data = "del_post_channel_menu"
                await cb_handler(client, query)
            except Exception as e:
                print(f"! Error Occurred on callback data = 'delpost_' : {e}")
                await query.answer(f"Error: {e}", show_alert=True)

    
