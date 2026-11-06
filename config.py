import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

#Bot token @Botfather
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")


#Your API ID from my.telegram.org
APP_ID = int(os.environ.get("APP_ID", ""))

#Your API Hash from my.telegram.org
API_HASH = os.environ.get("API_HASH", "")

#Your db channel Id
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", ""))

LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", ""))

MIN_ID = int(os.getenv("MIN_ID", 1))
MAX_ID = int(os.getenv("MAX_ID", 81500))

VIDEOS_RANGE = list(range(MIN_ID, MAX_ID + 1))

#OWNER ID
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

#Port
PORT = os.environ.get("PORT", "3435")
DB_URI = os.environ.get("DATABASE_URL", "")
if not DB_URI:
    raise RuntimeError("DATABASE_URL is not set. Clone bot tokens are stored in this database, so use your own MongoDB URL.")
DB_NAME = os.environ.get("DATABASE_NAME", "media")



TUT_VID = os.environ.get("TUT_VID", "")

TG_BOT_WORKERS = int(os.environ.get("TG_BOT_WORKERS", "5"))

START_PIC = os.environ.get("START_PIC", "https://envs.sh/JP6.jpg")

FORCE_PIC = os.environ.get("FORCE_PIC", "https://envs.sh/JP6.jpg")

QR_PIC = os.environ.get("QR_PIC", "https://telegra.ph/file/9f072b85fcdeef6e13e19.jpg")

#Collection of pics for Bot // #Optional but atleast one pic link should be replaced if you don't want predefined links

PICS = (os.environ.get("PICS", "https://envs.sh/JP6.jpg")).split() #Required

#set your Custom Caption here, Keep None for Disable Custom Caption
CUSTOM_CAPTION = os.environ.get("CUSTOM_CAPTION", "<b>ʙʏ @Bhabhijilive</b>")


#Set true if you want Disable your Channel Posts Share button
DISABLE_CHANNEL_BUTTON = os.environ.get("True", True) == 'True'

SHORTENER_DOMAIN = os.environ.get("SHORTENER_DOMAIN", "")
SHORTENER_API_KEY = os.environ.get("SHORTENER_API_KEY", "")
PROTECT_API_URL = os.environ.get("PROTECT_API_URL", "")


#==========================(CLONE SYSTEM)====================#

def _env_int(name: str, default: int) -> int:
    """Empty / missing / invalid env var -> default (Heroku app.json passes "" for unset optionals)."""
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default

# Central storage channel. Every clone serves files from here.
# Keep it equal to CHANNEL_ID so links made by the main bot work inside clones.
OWNER_DB_CHANNEL = _env_int("OWNER_DB_CHANNEL", CHANNEL_ID)

# System-wide logs (clone created/deleted/crashed, bans, premium changes). Admins only.
ADMIN_LOG_CHANNEL = _env_int("ADMIN_LOG_CHANNEL", LOG_CHANNEL)

# Defaults. Owner Panel (/ownerpanel) overrides these at runtime and saves them in MongoDB.
ALLOW_CLONING = (os.environ.get("ALLOW_CLONING") or "True").strip().lower() == "true"
MAX_CLONES_PER_USER = _env_int("MAX_CLONES_PER_USER", 1)
FREE_CLONE_DAYS = _env_int("FREE_CLONE_DAYS", 30)   # clone is auto-paused when its plan ends; 0 = never expire (disables auto-pause)

# Tier limits
FREE_FSUB_LIMIT = _env_int("FREE_FSUB_LIMIT", 1)
PREMIUM_FSUB_LIMIT = _env_int("PREMIUM_FSUB_LIMIT", 5)

# Footer forced on every message/caption of free-tier clones
CLONE_BRANDING = os.environ.get("CLONE_BRANDING") or "<b>⚡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ @{main_username}</b>"

# Fernet key for encrypting clone tokens / shortener keys in MongoDB.
# Generate: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
CLONE_ENCRYPTION_KEY = os.environ.get("CLONE_ENCRYPTION_KEY", "")

# Anti-spam: more than SPAM_MAX_MSGS updates in SPAM_WINDOW seconds = violation.
SPAM_MAX_MSGS = _env_int("SPAM_MAX_MSGS", 6)
SPAM_WINDOW = _env_int("SPAM_WINDOW", 5)
SPAM_WARNINGS = _env_int("SPAM_WARNINGS", 2)            # warnings before a temp-ban
SPAM_TEMPBAN_SECS = _env_int("SPAM_TEMPBAN_SECS", 300)  # 1st temp-ban length (grows per repeat)
SPAM_PERMBAN_AFTER = _env_int("SPAM_PERMBAN_AFTER", 3)  # temp-bans before permanent ban

# Health monitor
HEALTH_INTERVAL = _env_int("HEALTH_INTERVAL", 45)
HEALTH_MAX_RESTARTS = _env_int("HEALTH_MAX_RESTARTS", 3)  # per 10 minutes, then marked crashed

#==========================(BUY PREMIUM)====================#

PREMIUM_BUTTON = reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("• Rᴇᴍᴏᴠᴇ Aᴅs Iɴ Oɴᴇ Cʟɪᴄᴋ •", callback_data="buy_prem")]]
)
PREMIUM_BUTTON2 = reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("• Rᴇᴍᴏᴠᴇ Aᴅs Iɴ Oɴᴇ Cʟɪᴄᴋ •", callback_data="buy_prem")]]
) 


OWNER_TAG = os.environ.get("OWNER_TAG", "@AlwaysToHelpBot")

# ---- Clone /start buttons + "About me" page (same text for every user) ----
ABOUT_OWNER_NAME = os.environ.get("ABOUT_OWNER_NAME", OWNER_TAG)           # shown as "Owner"
UPDATES_NAME = os.environ.get("UPDATES_NAME", "Updates")
UPDATES_URL = os.environ.get("UPDATES_URL", "https://t.me/AlwaysToHelpBot")  # also the "Update Channel" button
SUPPORT_NAME = os.environ.get("SUPPORT_NAME", "Support")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/AlwaysToHelpBot")
BOT_VERSION = os.environ.get("BOT_VERSION", "1.0")

#UPI ID
BUSINESS_UPI = os.environ.get("BUSINESS_UPI", "nothingcopyright@airtel")


MERCHANT_ID = os.environ.get("MERCHANT_ID", "")

#SCREENSHOT URL of ADMIN for verification of payments
ADMIN_LINK = os.environ.get("ADMIN_LINK", f"t.me/AlwaysToHelpBot")



#===================(END)========================#
LOG_FILE_NAME = "testingbot.txt"
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt='%d-%b-%y %H:%M:%S',
    handlers=[
        RotatingFileHandler(
            LOG_FILE_NAME,
            maxBytes=50000000,
            backupCount=10
        ),
        logging.StreamHandler()
    ]
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)
