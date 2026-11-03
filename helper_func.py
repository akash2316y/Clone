#(©)Codexbotz
import binascii
from pyrogram import filters, Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant
from pyrogram.errors import RPCError, Forbidden, UserIsBlocked, PeerIdInvalid
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait
from shortzy import Shortzy
import requests
import re, io, qrcode, urllib.parse, unicodedata, asyncio, time, base64, json, math
import random, logging, os, uuid, aiohttp, string
from datetime import datetime
from database.database import *
from plugins.FORMATS import *
from config import *
import pytz
from math import ceil
from datetime import datetime, timezone as dt_timezone
from database.database import db  
from typing import Optional, Tuple, Dict, Any

#=============================================================================================================================================================================
# -------------------- HELPER FUNCTIONS FOR USER VERIFICATION IN DIFFERENT CASES -------------------- 
#=============================================================================================================================================================================


PREMIUM_USERS_PER_PAGE = 5 
SHORTNER_IMAGE = "https://telegra.ph/file/8aaf4df8c138c6685dcee-05d3b183d4978ec347.jpg"


# Global registry for scheduled expiry tasks
SCHEDULED_EXPIRY_TASKS: Dict[int, Tuple[datetime, asyncio.Task]] = {}
SCHEDULE_LOCK = asyncio.Lock()
# -----------------------------

# Store temporary data for callback handling
temp_data = {}

async def fetch_user_info(client: Client, user_id: int):
    try:
        user = await client.get_users(user_id)
        return f"{user.first_name} {user.last_name or ''}".strip()
    except Exception as e:
        logging.error(f"Failed to fetch user info for {user_id}: {e}")
        return None

def parse_duration(duration: str):
    """Parse duration into a timedelta object."""
    time_map = {
        "min": "minutes",
        "hour": "hours",
        "day": "days",
        "week": "weeks",
        "month": "days",
        "year": "days"
    }
    try:
        value = int(''.join(filter(str.isdigit, duration)))  # Extract numeric value
        unit = ''.join(filter(str.isalpha, duration))  # Extract unit

        if unit not in time_map or value <= 0:
            raise ValueError("Invalid duration.")

        multiplier = 30 if unit == "month" else 365 if unit == "year" else 1
        kwargs = {time_map[unit]: value * multiplier} if unit in ["month", "year"] else {time_map[unit]: value}

        return timedelta(**kwargs)
    except Exception:
        raise ValueError("Invalid duration format. Use formats like 1day, 2weeks, etc.")

async def check_payment_status(order_id: str):
    api_url = f"https://pay-rho-seven.vercel.app/?mid={MERCHANT_ID}&oid={order_id}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("STATUS") == "TXN_SUCCESS"
        except:
            return False
    return False
 #-----------------------------------------------------------------------------#

def _to_aware_dt(raw) -> datetime | None:
    if raw is None:
        return None

    # datetime
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return INDIA_TZ.localize(raw)
        return raw.astimezone(INDIA_TZ)

    # epoch seconds / ms
    if isinstance(raw, (int, float)):
        # Heuristic: treat >1e12 as milliseconds
        if raw > 1e12:
            raw /= 1000.0
        return datetime.fromtimestamp(raw, INDIA_TZ)

    # ISO string
    if isinstance(raw, str):
        try:
            # try fromisoformat first
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return INDIA_TZ.localize(dt)
            return dt.astimezone(INDIA_TZ)
        except Exception:
            pass
        # fallback: common formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d %b %Y %H:%M"):
            try:
                dt = datetime.strptime(raw, fmt)
                return INDIA_TZ.localize(dt)
            except Exception:
                continue
    return None

async def _schedule_or_replace_expiry_task(client, user_id: int, expiry_dt: datetime, OWNER_ID: int):
    """Create or replace an expiry notification task for a user."""
    async with SCHEDULE_LOCK:
        existing = SCHEDULED_EXPIRY_TASKS.get(user_id)

        # If there is an existing task for the exact same expiry and it's still running, skip.
        if existing:
            old_expiry, old_task = existing
            if old_expiry == expiry_dt and not old_task.done():
                logging.info(f"[dedupe] Task already scheduled for user {user_id} at {expiry_dt} — skipping.")
                return

            # If expiry changed or task finished, cancel/cleanup the old one.
            if old_task and not old_task.done():
                old_task.cancel()
                logging.info(f"[dedupe] Replaced existing task for user {user_id} ({old_expiry} → {expiry_dt}).")

        # Create the new task and register it
        task = asyncio.create_task(
            schedule_expiry_notifications(client=client, user_id=user_id, expiry_time=expiry_dt, OWNER_ID=OWNER_ID),
            name=f"expiry:{user_id}:{int(expiry_dt.timestamp())}"
        )
        SCHEDULED_EXPIRY_TASKS[user_id] = (expiry_dt, task)

async def schedule_expiry_notifications(client: Client, user_id: int, expiry_time: datetime, OWNER_ID: int):
    """Schedule notifications for premium expiry and notify the owner."""
    try:
        now = datetime.now(INDIA_TZ)
        one_hour_before = expiry_time - timedelta(hours=1)
        expiry_delay = (expiry_time - now).total_seconds()
        one_hour_delay = (one_hour_before - now).total_seconds()

        # Notify 1 hour before expiry
        if one_hour_delay > 0:
            await asyncio.sleep(one_hour_delay)
            if await db.is_premium(user_id):
                try:
                    await client.send_message(
                        user_id,
                        (
                            "<b>››⚠️ Reminder:</b> Your premium membership will expire in <b>1 hour</b>.\n\n"
                            f"<blockquote>To renew your premium membership, please <a href='{ADMIN_LINK}'>Contact Our Admins</a>.</blockquote>"
                        ),
                        disable_web_page_preview=True
                    )
                    logging.info(f"1-hour expiry reminder sent to user {user_id}")
                except Exception as e:
                    logging.error(f"Failed to send 1-hour expiry reminder to user {user_id}: {e}")

        # Notify on expiry
        if expiry_delay > 0:
            now = datetime.now(INDIA_TZ)
            remaining = (expiry_time - now).total_seconds()
            if remaining > 0:
                await asyncio.sleep(remaining)

        # On expiry
        if await db.is_premium(user_id):
            await db.remove_premium(user_id)
        try:
            await client.send_message(
                user_id,
                (
                    "❗ <b>›› Your premium membership has expired.</b>\n\n"
                    f"<blockquote>Renew your premium membership to continue enjoying the benefits. "
                    f"<a href='{ADMIN_LINK}'>Contact Our Admins</a>.</blockquote>"
                ),
                disable_web_page_preview=True
            )
            logging.info(f"Expiry notification sent to user {user_id}")

            # Notify the owner
            await client.send_message(
                OWNER_ID,
                (
                    f"⚠️ <b>Premium Expired</b>\n\n"
                    f"• <b>User ID:</b> <code>{user_id}</code>\n"
                    f"• <b>Expired On:</b> {expiry_time.strftime('%d %b %Y %H:%M')}\n\n"
                    f"<i>Consider reaching out to offer renewal options.</i>"
                ),
                disable_web_page_preview=True
            )
            logging.info(f"Owner notified about user {user_id}'s expiry")
        except Exception as e:
            logging.error(f"Failed to send expiry notification to user {user_id} or OWNER: {e}")

    except asyncio.CancelledError:
        logging.info(f"[dedupe] Expiry task cancelled for user {user_id} ({expiry_time}).")
        raise
    finally:
        async with SCHEDULE_LOCK:
            current = SCHEDULED_EXPIRY_TASKS.get(user_id)
            if current and current[0] == expiry_time and current[1] is asyncio.current_task():
                SCHEDULED_EXPIRY_TASKS.pop(user_id, None)


async def schedule_all_premium_expiries(client, OWNER_ID: int):
    premium_users = await db.get_premium_users()
    if not premium_users:
        #logging.info("No premium users found to schedule.")
        return

    normalized: list[tuple[int, object]] = []

    if isinstance(premium_users, dict):
        for user_id, meta in premium_users.items():
            expiry_raw = None
            if isinstance(meta, dict):
                expiry_raw = meta.get("expiry") or meta.get("expires_at") or meta.get("expiry_time")
            else:
                expiry_raw = meta
            normalized.append((int(user_id), expiry_raw))
    elif isinstance(premium_users, (list, tuple, set)):
        for user_id in premium_users:
            try:
                expiry_raw = await db.get_premium_expiry(int(user_id))
            except Exception:
                expiry_raw = None
            normalized.append((int(user_id), expiry_raw))
    else:
        logging.warning("Unexpected premium_users type; nothing scheduled.")
        return

    now = datetime.now(INDIA_TZ)

    for user_id, expiry_raw in normalized:
        expiry_dt = _to_aware_dt(expiry_raw)
        if not expiry_dt:
            logging.warning(f"User {user_id}: missing/invalid expiry; skipping schedule.")
            continue
        if expiry_dt <= now:
            # Optional: notify immediately or just skip
            logging.info(f"User {user_id}: expiry {expiry_dt} is in the past; skipping schedule.")
            continue

        await _schedule_or_replace_expiry_task(client, user_id, expiry_dt, OWNER_ID)
        logging.info(f"Scheduled expiry tasks for user {user_id} at {expiry_dt.strftime('%d %b %Y %H:%M')} IST")


# Show page function
current_page = {}

def _to_utc_aware(dt: datetime) -> datetime | None:
    """Normalize datetime to UTC-aware. Treat naive as UTC-naive."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # stored as UTC-naive → make it UTC-aware
        return dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc)


async def show_premium_page(client, chat_id, premium_users, message_id=None):
    page = current_page.get(chat_id, 1)
    now_utc = datetime.now(dt_timezone.utc)
    current_time_ist = datetime.now(INDIA_TZ).strftime('%Y-%m-%d %I:%M:%S %p')

    total_pages = max(1, ceil(len(premium_users) / PREMIUM_USERS_PER_PAGE))
    start_idx = (page - 1) * PREMIUM_USERS_PER_PAGE
    end_idx = start_idx + PREMIUM_USERS_PER_PAGE

    # Buttons
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data=f"prem_prev_{page}"))
    if end_idx < len(premium_users):
        buttons.append(InlineKeyboardButton("ɴᴇxᴛ ➡️", callback_data=f"prem_next_{page}"))
    nav_buttons = [buttons] if buttons else []
    nav_buttons.append([
        InlineKeyboardButton("🔄 ʀᴇғʀᴇsʜ", callback_data="prem_refresh"),
        InlineKeyboardButton("📊 sᴛᴀᴛs", callback_data="prem_stats")
    ])
    reply_markup = InlineKeyboardMarkup(nav_buttons)

    header = f"<b>📋 ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs ({page}/{total_pages})</b>\n<code>━━━━━━━━━━━━━━━━</code>\n\n"

    # Build list
    items = list(premium_users.items())[start_idx:end_idx]
    user_rows = []

    for idx, (user_id, expiry_time) in enumerate(items, start_idx + 1):
        # Normalize expiry to UTC-aware for math
        exp_utc = _to_utc_aware(expiry_time)
        if not isinstance(exp_utc, datetime):
            # skip bad rows gracefully
            user_name = await fetch_user_info(client, user_id) or "ᴜɴᴋɴᴏᴡɴ"
            user_rows.append(
                f"<b>{idx}. {user_name}</b>\n"
                f"<code>   ├ ɪᴅ: {user_id}</code>\n"
                f"<code>   └ ɴᴏ ᴠᴀʟɪᴅ ᴇxᴘɪʀʏ</code>\n"
            )
            continue

        # IST string for display
        exp_ist = exp_utc.astimezone(INDIA_TZ)
        expiry_str = exp_ist.strftime('%d %b %Y')

        remaining_days = (exp_utc - now_utc).days  # math done in UTC-aware

        status = (
            "🔴 <i><b>ᴇxᴘɪʀɪɴɢ!</b></i>" if remaining_days <= 3
            else "🟡 <i><b>sᴏᴏɴ</b></i>" if remaining_days <= 7
            else "🟢 <i><b>ᴀᴄᴛɪᴠᴇ</b></i>"
        )
        if remaining_days < 0:
            status = "⚫ <i><b>ᴇxᴘɪʀᴇᴅ</b></i>"

        user_name = await fetch_user_info(client, user_id) or "ᴜɴᴋɴᴏᴡɴ"
        user_rows.append(
            f"<b>{idx}. {user_name}</b>\n"
            f"<code>   ├ ɪᴅ: {user_id}</code>\n"
            f"<code>   ├ ᴇxᴘɪʀʏ: {expiry_str} (IST)</code>\n"
            f"<code>   └ sᴛᴀᴛᴜs: {status} ({remaining_days}ᴅ ʟᴇғᴛ)</code>\n"
        )

    if not user_rows:
        user_rows = ["<i>No premium users on this page.</i>"]

    footer = f"\n<code>━━━━━━━━━━━━━━━━</code>\n<i>ᴜᴘᴅᴀᴛᴇᴅ: {current_time_ist}</i>"

    text = header + "\n".join(user_rows) + footer

    # Send or edit
    try:
        if message_id:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            return
    except Exception:
        pass

    await client.send_message(
        chat_id,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )

INDIA_TZ = pytz.timezone("Asia/Kolkata")
now = datetime.now(INDIA_TZ)

# --- Extract price + duration automatically ---
def extract_upi_plans(text: str):
    # Normalize fancy unicode to plain ASCII-ish and lowercase
    normalized = ''.join(
        c for c in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(c)
    ).lower()

    pattern = re.compile(
        r"(?:^|\n)\s*(?:››\s*)?"
        r"(?P<num>\d+)\s*(?P<unit>day|days|month|months|year|years)?\s*"
        r"[:\-–—]\s*₹?\s*(?P<price>\d+)",
        re.IGNORECASE
    )

    plans = {}
    order = []
    for i, m in enumerate(pattern.finditer(normalized), start=1):
        num = int(m.group("num"))
        unit = m.group("unit")
        price = m.group("price").strip()

        if not unit:
            # If unit missing (e.g., "1 : ₹20"), treat as 1 day
            unit = "day" if num == 1 else "days"

        # Normalize duration string ("1 day", "7 days", "1 month", "3 months", "1 year", "6 months", etc.)
        unit = unit.lower()
        # singular/plural fix
        if num == 1:
            if unit.endswith("s"):
                unit = unit[:-1]
        else:
            if not unit.endswith("s"):
                unit = unit + "s"

        duration_str = f"{num} {unit}"

        key = f"plan_{i}"
        plans[key] = {"duration": duration_str, "price": price}
        order.append(key)

    # preserve discovery order
    plans["_order"] = order
    return plans

def parse_durationss(duration_str: str) -> timedelta:
    s = duration_str.lower().strip()

    if "unlimited" in s or "lifetime" in s:
        return timedelta(days=3650) 
    match = re.search(
        r"(\d+)\s*(day|days|d|week|weeks|w|month|months|mo|mon|year|years|yr|y)?",
        s
    )
    if not match:
        return timedelta(days=10)

    value = int(match.group(1))
    unit = match.group(2) or "day"  # default to days if no unit given

    # Normalize unit and map to days
    if unit in ("day", "days", "d"):
        return timedelta(days=value)
    elif unit in ("week", "weeks", "w"):
        return timedelta(weeks=value)
    elif unit in ("month", "months", "mo", "mon"):
        # Approximate month as 30 days
        return timedelta(days=value * 30)
    elif unit in ("year", "years", "yr", "y"):
        # Approximate year as 365 days
        return timedelta(days=value * 365)

    # Safety fallback
    return timedelta(days=10)
                    
def txn_id():
    t = datetime.now().strftime("%Y%m%d%H%M%S")
    u = uuid.uuid4().hex[:6].upper()
    return f"TRX{t}{u}"

def make_qr(amt, tr):
    url = f"upi://pay?pa={BUSINESS_UPI}&pn=Rogger&am={amt}&cu=INR&tr={tr}&tn=Payment"
    img = qrcode.make(url)
    img.save("upi.png")


# If you already defined these helpers in your callback file, you can remove them here.


async def get_shortener_cfg():
    """Fetch shortener config safely with defaults."""
    try:
        enabled = bool(await db.get_shortener_enabled())
    except Exception:
        enabled = False

    try:
        url = await db.get_shortener_url()
    except Exception:
        url = ""

    try:
        api = await db.get_shortener_api()
    except Exception:
        api = ""

    return {
        "enabled": enabled,
        "url": url or "",
        "api": api or "",
    }

async def shortener_caption(cfg: dict) -> str:
    status_text = "Enabled ✅" if cfg["enabled"] else "Disabled ❌"
    masked_api = "•••••" if cfg["api"] else "—"
    site_text = cfg["url"] or "—"

    return (
        "🔗 <b>Shortener Settings</b>\n\n"
        f"Status: <b>{status_text}</b>\n"
        f"Site: <code>{site_text}</code>\n"
        f"API: <code>{masked_api}</code>\n\n"
        "Use the options below to configure."
    )

async def shortener_kb(cfg: dict) -> InlineKeyboardMarkup:
    toggle_text = "🟢 Disable Shortener" if cfg["enabled"] else "🔴 Enable Shortener"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_text, callback_data="shortener_toggle")],
        [InlineKeyboardButton('Set Site 🌐', callback_data='set_shortener_details')],
        [
            InlineKeyboardButton('Settings ⚙️', callback_data='shortener_settings'),
            InlineKeyboardButton('🔄 Refresh', callback_data='set_shortener'),
        ],
        [
            InlineKeyboardButton('Set Verified Time ⏱', callback_data='set_verify_time'),
            InlineKeyboardButton('Set Tutorial Video 🎥', callback_data='set_tut_video'),
        ],
        [InlineKeyboardButton('Close ✖️', callback_data='close')],
    ])

async def refresh_shortener_panel(msg: Message):
    """Edit the same message (caption + markup) in place."""
    cfg = await get_shortener_cfg()
    try:
        await msg.edit_caption(
            caption=await shortener_caption(cfg),
            reply_markup=await shortener_kb(cfg),
        )
    except Exception:
        
        try:
            await msg.edit_reply_markup(await shortener_kb(cfg))
        except Exception:
            pass



# used for checking banned user
async def check_banUser(filter, client, update):
    try:
        user_id = update.from_user.id
        return await db.ban_user_exist(user_id)
    except: #Exception as e:
        #print(f"!Error on check_banUser(): {e}")
        return False


#used for cheking if a user is admin ~Owner also treated as admin level
async def check_admin(filter, client, update):
    try:
        user_id = update.from_user.id       
        return any([user_id == OWNER_ID, await db.admin_exist(user_id)])
    except Exception as e:
        print(f"! Exception in check_admin: {e}")
        return False


# Check user subscription in Channels (optimized)
async def is_subscribed(client, update):
    Channel_ids = await db.get_all_channels()

    if not Channel_ids:
        return True

    user_id = update.from_user.id

    # Owner & admins bypass
    if user_id == OWNER_ID or await db.admin_exist(user_id):
        return True

    # Single channel check
    if len(Channel_ids) == 1:
        return await is_userJoin(client, user_id, Channel_ids[0])

    # Multiple channels → concurrent check
    tasks = [
        is_userJoin(client, user_id, channel_id)
        for channel_id in Channel_ids
        if channel_id
    ]
    results = await asyncio.gather(*tasks)

    return all(results)

#Chcek user subscription by specifying channel id and user id
async def is_userJoin(client, user_id, channel_id):
    #REQFSUB = await db.get_request_forcesub()
    try:
        member = await client.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}

    except UserNotParticipant:
        if await db.get_request_forcesub(): #and await privateChannel(client, channel_id):
                return await db.reqSent_user_exist(channel_id, user_id)

        return False

    except Exception as e:
        print(f"!Error on is_userJoin(): {e}")
        return False
#=============================================================================================================================================================================

async def encode(string: str) -> str:
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    base64_string = base64_bytes.decode("ascii").strip("=")
    return base64_string

async def decode(base64_string: str) -> str:
    try:
        base64_string = base64_string.strip()  # Strip any extraneous whitespace
        # Validate string length for proper padding
        if len(base64_string) % 4 == 1:
            raise ValueError("Invalid base64-encoded string length")
        
        # Ensure proper padding
        padding = '=' * (-len(base64_string) % 4)
        base64_string += padding
        base64_bytes = base64_string.encode("ascii")
        # Decode the base64 string
        string_bytes = base64.urlsafe_b64decode(base64_bytes)
        # Convert bytes to string
        string = string_bytes.decode("ascii")
        return string
    except (binascii.Error, ValueError) as e:
        # Handle decoding errors
        print(f"Failed to decode base64 string: {e}")
        return None
async def get_messages(client, message_ids):
    messages = []
    total_messages = 0
    while total_messages != len(message_ids):
        temb_ids = message_ids[total_messages:total_messages+200]
        try:
            msgs = await client.get_messages(
                chat_id=client.db_channel.id,
                message_ids=temb_ids
            )
        except FloodWait as e:
            await asyncio.sleep(e.x)
            msgs = await client.get_messages(
                chat_id=client.db_channel.id,
                message_ids=temb_ids
            )
        except:
            pass
        total_messages += len(temb_ids)
        messages.extend(msgs)
    return messages

async def get_message_id(client, message):
    if message.forward_from_chat:
        if message.forward_from_chat.id == client.db_channel.id:
            return message.forward_from_message_id
        else:
            return 0
    elif message.forward_sender_name:
        return 0
    elif message.text:
        pattern = "https://t.me/(?:c/)?(.*)/(\d+)"
        matches = re.match(pattern,message.text)
        if not matches:
            return 0
        channel_id = matches.group(1)
        msg_id = int(matches.group(2))
        if channel_id.isdigit():
            if f"-100{channel_id}" == str(client.db_channel.id):
                return msg_id
        else:
            if channel_id == client.db_channel.username:
                return msg_id
    else:
        return 0



default_verify = {
    'is_verified': False,
    'verified_time': 0,
    'verify_token': "",
    'link': ""
}

async def get_verify_status(user_id):
    return await db.get_verify_status(user_id)

async def get_shortlink(link):
    # Fetch shortener details from the database
    shortener_url = await db.get_shortener_url()
    shortener_api = await db.get_shortener_api()

    # Validate shortener details
    if not shortener_url or not shortener_api:
        logging.error("Shortener URL or API key is missing.")
        raise ValueError("Shortener details are not configured.")

    # Log the shortener URL and long URL for debugging
    logging.info(f"Using shortener URL: {shortener_url}")
    logging.info(f"Original Link: {link}")

    try:
        # Clean the URL to be used as base_site in Shortzy
        cleaned_url = shortener_url.replace("https://", "").replace("http://", "").rstrip("/")

        # Initialize Shortzy without altering the shortener_url
        shortzy = Shortzy(api_key=shortener_api, base_site=cleaned_url)
        short_link = await shortzy.convert(link)
        return short_link
    except Exception as e:
        logging.error(f"Error using Shortzy: {e}")
        raise

def get_exp_time(seconds: int) -> str:
    periods = [('ᴅᴀʏs', 86400), ('ʜᴏᴜʀs', 3600), ('ᴍɪɴs', 60), ('sᴇᴄs', 1)]
    result = ''
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f'{int(period_value)}{period_name} '
    return result.strip() if result else "0sᴇᴄs"



def get_readable_time(seconds: int) -> str:
    count = 0
    up_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", "days"]
    while count < 4:
        count += 1
        remainder, result = divmod(seconds, 60) if count < 3 else divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        time_list.append(int(result))
        seconds = int(remainder)
    hmm = len(time_list)
    for x in range(hmm):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4:
        up_time += f"{time_list.pop()}, "
    time_list.reverse()
    up_time += ":".join(time_list)
    return up_time

#----------------------------------------------------------------------------------------------------------------------------------------------------------------------------

async def fileSettings(getfunc, setfunc=None, delfunc=False):
    btn_mode, txt_mode, pic_mode = '❌', off_txt, off_pic
    del_btn_mode = 'Eɴᴀʙʟᴇ Mᴏᴅᴇ ✅'
    try:
        if not setfunc:
            if await getfunc():
                txt_mode = on_txt
                btn_mode = '✅'
                del_btn_mode = 'Dɪsᴀʙʟᴇ Mᴏᴅᴇ ❌'

            return txt_mode, (del_btn_mode if delfunc else btn_mode)

        else:
            if await getfunc():
                await setfunc(False)
            else:
                await setfunc(True)
                pic_mode, txt_mode = on_pic, on_txt
                btn_mode = '✅'
                del_btn_mode = 'Dɪsᴀʙʟᴇ Mᴏᴅᴇ ❌'

            return pic_mode, txt_mode, (del_btn_mode if delfunc else btn_mode)

    except Exception as e:
        print(
            f"Error occured at [fileSettings(getfunc, setfunc=None, delfunc=False)] : {e}")

# Provide or Make Button by takiing required modes and data


def buttonStatus(pc_data: str, hc_data: str, cb_data: str) -> list:
    button = [
        [
            InlineKeyboardButton(
                f'Pʀᴏᴛᴇᴄᴛ Cᴏɴᴛᴇɴᴛ: {pc_data}', callback_data='pc'),
            InlineKeyboardButton(
                f'Hɪᴅᴇ Cᴀᴘᴛɪᴏɴ: {hc_data}', callback_data='hc')
        ],
        [
            InlineKeyboardButton(
                f'Cʜᴀɴɴᴇʟ Bᴜᴛᴛᴏɴ: {cb_data}', callback_data='cb'),
            InlineKeyboardButton(f'◈ Sᴇᴛ Bᴜᴛᴛᴏɴ ➪', callback_data='setcb')
        ],
        [
            InlineKeyboardButton('🔄 Rᴇғʀᴇsʜ', callback_data='files_cmd'),
            InlineKeyboardButton('Cʟᴏsᴇ ✖️', callback_data='close')
        ],
    ]
    return button

# Verify user, if he/she is admin or owner before processing the query...


async def authoUser(query, id, owner_only=False):
    if not owner_only:
        if not any([id == OWNER_ID, await db.admin_exist(id)]):
            await query.answer("❌ Yᴏᴜ ᴀʀᴇ ɴᴏᴛ Aᴅᴍɪɴ !", show_alert=True)
            return False
        return True
    else:
        if id != OWNER_ID:
            await query.answer("❌ Yᴏᴜ ᴀʀᴇ ɴᴏᴛ Oᴡɴᴇʀ !", show_alert=True)
            return False
        return True


def time_to_seconds(val: int, unit: str) -> int:
    unit = (unit or "days").lower()
    if unit in ("s", "sec", "secs", "second", "seconds"):
        return int(val)
    if unit in ("m", "min", "mins", "minute", "minutes"):
        return int(val) * 60
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return int(val) * 60 * 60
    if unit in ("d", "day", "days"):
        return int(val) * 24 * 60 * 60
    if unit in ("w", "week", "weeks"):
        return int(val) * 7 * 24 * 60 * 60
    if unit in ("mo", "mon", "month", "months"):
        return int(val) * 30 * 24 * 60 * 60  # normalized month = 30 days
    if unit in ("y", "yr", "year", "years"):
        return int(val) * 365 * 24 * 60 * 60
    return int(val) * 24 * 60 * 60  # default days



#----------------------------------------------------------------------------------------------------------------------------------------------------------------------------


subscribed = filters.create(is_subscribed)
is_admin = filters.create(check_admin)
banUser = filters.create(check_banUser)
