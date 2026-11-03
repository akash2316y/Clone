#Javpostr | @rohit_1888 on Tg
import asyncio
import logging, pyrogram.utils
from aiohttp import web
import pyromod.listen
from pyrogram import Client
from pyrogram.enums import ParseMode
import sys
from datetime import datetime
import pytz
from config import *
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from database.database import db
from helper_func import schedule_all_premium_expiries

load_dotenv(".env")

# Silence Logs
logging.getLogger("apscheduler").setLevel(logging.WARNING)

pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

def get_indian_time():
    ist = pytz.timezone("Asia/Kolkata")
    return datetime.now(ist)



async def web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    return web_app



routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("Codeflix_Bots")


class Bot(Client):
    def __init__(self):
        super().__init__(
            name="Bot",
            api_hash=API_HASH,
            api_id=APP_ID,
            plugins={"root": "plugins"},
            workers=TG_BOT_WORKERS,
            bot_token=TG_BOT_TOKEN
        )
        self.LOGGER = LOGGER
        self.IST = pytz.timezone("Asia/Kolkata")
        self.scheduler = AsyncIOScheduler(timezone=self.IST)

    async def _purge_expired_premium(self):
        now_ist = get_indian_time()
        expired_users = await db.premium_user.find(
            {'expiry_time': {'$lte': now_ist}}
        ).to_list(None)

        for user in expired_users:
            user_id = user['_id']
            await db.premium_user.delete_one({'_id': user_id})

        return len(expired_users)

    async def _reset_free_usage_daily(self):
        try:
            count = await db.reset_all_user_free_used()
            #logging.info(f"[FREE-RESET] Reset free_used=0 for {count} users.")
            # Optional owner ping:
            # await self.send_message(OWNER_ID, f"🧹 Daily free reset done: {count} users.")
        except Exception as e:
            logging.error(f"[FREE-RESET] Failed to reset free usage: {e}")

    def _start_schedulers(self):
        self.scheduler.add_job(
            self._purge_expired_premium,                     
            trigger=IntervalTrigger(seconds=4, timezone=self.IST),
            id="purge_expired_premium",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=2,
            max_instances=1
        )

        # Schedule premium expiry notifications every 40 seconds
        self.scheduler.add_job(
            schedule_all_premium_expiries,          
            trigger=IntervalTrigger(seconds=40, timezone=self.IST),
            id="schedule_expiry_notifications",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=20,
            max_instances=1,
            kwargs={"client": self, "OWNER_ID": OWNER_ID}  
        )

        # 🧹 Daily reset of free usage at 12 AM Indian 
        self.scheduler.add_job(
            self._reset_free_usage_daily,
            trigger=CronTrigger(hour=0, minute=0, timezone=self.IST),  # every day 00:00 IST
            id="reset_free_usage_daily",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,  # 1 hour
            max_instances=1
        )

        # If you prefer a 24h interval instead of midnight reset, use this:
        # self.scheduler.add_job(
        #     self._reset_free_usage_daily,
        #     trigger=IntervalTrigger(hours=24, timezone=self.IST),
        #     id="reset_free_usage_daily",
        #     replace_existing=True,
        #     coalesce=True,
        #     misfire_grace_time=3600,
        #     max_instances=1
        # )

        if not self.scheduler.running:
            self.scheduler.start()

    async def start(self):
        await super().start()
        usr_bot_me = await self.get_me()
        self.uptime = get_indian_time()

        try:
            db_channel = await self.get_chat(CHANNEL_ID)
            self.db_channel = db_channel
        except Exception as e:
            self.LOGGER(__name__).warning(e)
            self.LOGGER(__name__).warning(
                f"Make sure bot is Admin in DB Channel, current CHANNEL_ID: {CHANNEL_ID}"
            )
            sys.exit()

        self.set_parse_mode(ParseMode.HTML)
        self.username = usr_bot_me.username

        # Start scheduler and tasks
        self._start_schedulers()

        # Start Web Server
        web_runner = web.AppRunner(await web_server())
        await web_runner.setup()
        await web.TCPSite(web_runner, "0.0.0.0", PORT).start()

        # Clone engine: boots every saved clone + health monitor, expiry and auto-delete jobs
        from clone.manager import CloneManager
        self.clones = CloneManager(self)
        await self.clones.start()

        try:
            await self.send_message(
                OWNER_ID,
                text=f"<b><blockquote>🤖 Bot Restarted</blockquote></b>"
            )
        except Exception:
            pass

    async def stop(self, *args):
        if getattr(self, "clones", None):
            await self.clones.stop()
        if self.scheduler and self.scheduler.running:
            await asyncio.to_thread(self.scheduler.shutdown, wait=False)
        await super().stop()

    def run(self):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.start())
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(self.stop())
