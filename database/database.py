


import time
import pymongo, os
import motor
import motor.motor_asyncio
from config import DB_URI, DB_NAME
from pymongo import ReturnDocument
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from pytz import timezone, UTC

INDIA_TZ = timezone("Asia/Kolkata")

def _to_india_tz(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        # treat as UTC then convert to IST
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(INDIA_TZ)

def _ensure_india_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return INDIA_TZ.localize(dt)
    return dt.astimezone(INDIA_TZ)


dbclient = pymongo.MongoClient(DB_URI)
database = dbclient[DB_NAME]

logging.basicConfig(level=logging.INFO)

collection = database['premium-users']

default_verify = {
    'is_verified': False,
    'verified_time': 0,
    'verify_token': "",
    'link': ""
}

def new_user(id):
    return {
        '_id': id,
        'verify_status': {
            'is_verified': False,
            'verified_time': "",
            'verify_token': "",
            'link': ""
        }
    }



class Rohit:

    def __init__(self, DB_URI, DB_NAME):
        self.dbclient = motor.motor_asyncio.AsyncIOMotorClient(DB_URI)
        self.database = self.dbclient[DB_NAME]

        self.channel_data = self.database['channels']
        self.post_channel_data = self.database['post_channels']
        self.admins_data = self.database['admins']
        self.user_data = self.database['users']
        self.banned_user_data = self.database['banned_user']
        self.autho_user_data = self.database['autho_user']
        self.shortener_data = self.database['shortener']
        self.settings_data = self.database['settings']
        self.free_data = self.database['free']
        self.for_data = self.database['for']
        self.login_data = self.database['login']
        
        self.auto_delete_data = self.database['auto_delete']
        self.hide_caption_data = self.database['hide_caption']
        self.protect_content_data = self.database['protect_content']
        self.channel_button_data = self.database['channel_button']

        self.settings_data = self.database['settings']
        self.del_timer_data = self.database['del_timer']
        self.channel_button_link_data = self.database['channelButton_link']

        self.rqst_fsub_data = self.database['request_forcesub']
        self.rqst_fsub_Channel_data = self.database['request_forcesub_channel']
        self.store_reqLink_data = self.database['store_reqLink']
        self.videos_collection = self.database["vids"]
        self.users_collection = self.database["user_subs"] 
        self.premium_user = self.database["premium"]
        

# === Free usage config ===
    async def get_free_enabled(self) -> bool:
        doc = await self.settings_data.find_one({"_id": "free_usage"}) or {}
        return bool(doc.get("enabled", False))

    async def set_free_enabled(self, enabled: bool):
        await self.settings_data.update_one(
            {"_id": "free_usage"},
            {"$set": {"enabled": bool(enabled)}},
            upsert=True
        )

    async def get_free_limit(self) -> int:
        doc = await self.settings_data.find_one({"_id": "free_usage"}) or {}
        return int(doc.get("limit", 3))

    async def set_free_limit(self, n: int):
        await self.settings_data.update_one(
            {"_id": "free_usage"},
            {"$set": {"limit": int(n)}},
            upsert=True
        )

# === Per-user counters ===
    async def get_user_free_used(self, user_id: int) -> int:
        doc = await self.user_data.find_one({"_id": user_id}) or {}
        return int(doc.get("free_used", 0))

    async def increment_user_free_used(self, user_id: int, amount: int = 1):
        await self.user_data.update_one(
            {"_id": user_id},
            {"$inc": {"free_used": int(amount)}},
            upsert=True
        )

    async def reset_user_free_used(self, user_id: int):
        await self.user_data.update_one(
            {"_id": user_id},
            {"$set": {"free_used": 0}},
            upsert=True
        )               

    async def reset_all_user_free_used(self):
        try:
            result = await self.user_data.update_many(
                {},   
                {"$set": {"free_used": 0}}
            )
            return result.modified_count 
        except Exception as e:
            logging.error(f"Error resetting all free usage: {e}")
            return 0



 # =========================
    # PREMIUM USER MANAGEMENT
    # =========================

    async def is_premium(self, user_id: int) -> bool:
        user = await self.premium_user.find_one({'_id': user_id})
        if not user:
            return False

        now = datetime.now(INDIA_TZ)
        expiry_time = _to_india_tz(user.get('expiry_time'))

        if expiry_time and now > expiry_time:
            await self.remove_premium(user_id)
            return False
        return bool(expiry_time)  # treat as premium only if we actually have an expiry

    async def add_premium(self, user_id: int, expiry_time: datetime):
        expiry_time = _ensure_india_aware(expiry_time)
        await self.premium_user.update_one(
            {'_id': user_id},
            {'$set': {'expiry_time': expiry_time}},
            upsert=True
        )

    async def get_premium_users(self) -> Dict[int, Optional[datetime]]:
        users = await self.premium_user.find().to_list(length=None)
        return {doc['_id']: _to_india_tz(doc.get('expiry_time')) for doc in users}

    async def remove_premium(self, user_id: int):
        await self.premium_user.delete_one({'_id': user_id})

    async def remove_all_premium(self):
        await self.premium_user.delete_many({})

    async def add_premium_duration(self, user_id: int, seconds: int) -> datetime:
        doc = await self.premium_user.find_one({'_id': user_id})
        now = datetime.now(INDIA_TZ)
        current_expiry = _to_india_tz(doc.get('expiry_time')) if doc else None

        base = current_expiry if (current_expiry and current_expiry > now) else now
        new_expiry = base + timedelta(seconds=int(seconds))

        await self.add_premium(user_id, new_expiry)  # stores tz-aware
        return new_expiry

    async def get_premium_expiry(self, user_id: int) -> Optional[datetime]:
        doc = await self.premium_user.find_one({'_id': user_id}, {'expiry_time': 1, '_id': 0})
        return _to_india_tz(doc.get('expiry_time')) if doc else None

    async def update_premium_expiry(self, user_id: int, expiry_time: datetime) -> None:
        expiry_time = _ensure_india_aware(expiry_time)
        await self.premium_user.update_one(
            {'_id': user_id},
            {'$set': {'expiry_time': expiry_time}},
            upsert=True
        )


# ================== LINK CACHE ==================

    async def get_cached_video(self, url: str):
        return await self.videos_collection.find_one({"url": url})

    async def save_cached_video(self, url: str, message_ids: list, titles: list, sizes: list):
        await self.videos_collection.update_one(
            {"url": url},
            {
                "$set": {
                    "url": url,
                    "message_ids": message_ids,
                    "titles": titles,
                    "sizes": sizes,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # Shortener Token
    async def set_shortener_url(self, url):
        try:
        # Check if an active shortener exists
            existing = await self.shortener_data.find_one({"active": True})
            if existing:
            # Update the URL of the existing active shortener
                await self.shortener_data.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"shortener_url": url, "updated_at": datetime.utcnow()}}
                )
            else:
            # Insert a new active shortener with the given URL
                await self.shortener_data.insert_one({
                    "shortener_url": url,
                    "api_key": None,
                    "active": True,
                    "created_at": datetime.utcnow()
                })
            return True
        except Exception as e:
            logging.error(f"Error setting shortener URL: {e}")
            return False

    async def set_shortener_api(self, api):
        try:
        # Check if an active shortener exists
            existing = await self.shortener_data.find_one({"active": True})
            if existing:
            # Update the API key of the existing active shortener
                await self.shortener_data.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"api_key": api, "updated_at": datetime.utcnow()}}
                )
            else:
            # Insert a new active shortener with the given API key
                await self.shortener_data.insert_one({
                    "shortener_url": None,
                    "api_key": api,
                    "active": True,
                    "created_at": datetime.utcnow()
                })
            return True
        except Exception as e:
            logging.error(f"Error setting shortener API key: {e}")
            return False

    async def get_shortener_url(self):
        try:
        # Retrieve the shortener URL of the active shortener
            shortener = await self.shortener_data.find_one({"active": True}, {"_id": 0, "shortener_url": 1})
            return shortener.get("shortener_url") if shortener else None
        except Exception as e:
            logging.error(f"Error fetching shortener URL: {e}")
            return None

    async def get_shortener_api(self):
        try:
        # Retrieve the API key of the active shortener
            shortener = await self.shortener_data.find_one({"active": True}, {"_id": 0, "api_key": 1})
            return shortener.get("api_key") if shortener else None
        except Exception as e:
            logging.error(f"Error fetching shortener API key: {e}")
            return None


    async def deactivate_shortener(self):
        try:
            # Deactivate all active shorteners
            await self.shortener_data.update_many({"active": True}, {"$set": {"active": False}})
            return True
        except Exception as e:
            logging.error(f"Error deactivating shorteners: {e}")
            return False

    # Protect Mode Settings (MUTUALLY EXCLUSIVE to Shortener Mode)
    async def get_protect_mode(self) -> bool:
        doc = await self.settings_data.find_one({"_id": "protect_mode"}) or {}
        return bool(doc.get("value", False))

    async def set_protect_mode(self, value: bool):
        await self.settings_data.update_one(
            {"_id": "protect_mode"},
            {"$set": {"value": bool(value)}},
            upsert=True
        )
        if value:
            await self.set_shortener_mode(False)

    async def get_shortener_mode(self) -> bool:
        doc = await self.settings_data.find_one({"_id": "shortener_mode"})
        if doc is None:
            protect_active = await self.get_protect_mode()
            return not protect_active
        return bool(doc.get("value", False))

    async def set_shortener_mode(self, value: bool):
        await self.settings_data.update_one(
            {"_id": "shortener_mode"},
            {"$set": {"value": bool(value)}},
            upsert=True
        )
        if value:
            await self.settings_data.update_one(
                {"_id": "protect_mode"},
                {"$set": {"value": False}},
                upsert=True
            )

    async def get_protect_api_url(self) -> str:
        doc = await self.settings_data.find_one({"_id": "protect_api_url"}) or {}
        return doc.get("value", "")

    async def set_protect_api_url(self, value: str):
        await self.settings_data.update_one(
            {"_id": "protect_api_url"},
            {"$set": {"value": value.strip()}},
            upsert=True
        )

    # Verified Time & Tutorial Video
    async def set_verified_time(self, verified_time: int):
        try:
            await self.settings_data.update_one(
                {"_id": "verified_time"},
                {"$set": {"verified_time": verified_time}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error updating verified time: {e}")
            return False

    async def get_verified_time(self):
        try:
            settings = await self.settings_data.find_one({"_id": "verified_time"})
            return settings.get("verified_time", 86400) if settings else 86400
        except Exception as e:
            logging.error(f"Error fetching verified time: {e}")
            return 86400

    async def set_tut_video(self, video_url: str):
        try:
            await self.settings_data.update_one(
                {"_id": "tutorial_video"},
                {"$set": {"tutorial_video_url": video_url}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error updating tutorial video URL: {e}")
            return False

    async def get_tut_video(self):
        try:
            settings = await self.settings_data.find_one({"_id": "tutorial_video"})
            return settings.get("tutorial_video_url", None) if settings else None
        except Exception as e:
            logging.error(f"Error fetching tutorial video URL: {e}")
            return None



    # USER MANAGEMENT
    async def present_user(self, user_id: int):
        found = await self.user_data.find_one({'_id': user_id})
        return bool(found)

    async def add_user(self, user_id: int):
        await self.user_data.insert_one({'_id': user_id})
        return

    async def full_userbase(self):
        user_docs = await self.user_data.find().to_list(length=None)
        user_ids = [doc['_id'] for doc in user_docs]
        return user_ids

    async def del_user(self, user_id: int):
        await self.user_data.delete_one({'_id': user_id})
        return

    # Update shortener settings for a user
    async def update_shortener(self, user_id: int, site: str, api_key: str):
        """
        Update the shortener site and API key for a user.
        """
        await self.shortener_data.update_one(
            {'_id': user_id},
            {'$set': {'site': site, 'api': api_key}},
            upsert=True  # Create a new document if one doesn't exist
        )

    # Enable or disable shortener functionality for a user
    async def toggle_shortener(self, user_id: int, enable: bool):
        """
        Enable or disable the shortener functionality for a user.
        """
        await self.shortener_data.update_one(
            {'_id': user_id},
            {'$set': {'enabled': enable}},
            upsert=True  # Create a new document if one doesn't exist
        )

    # Fetch the shortener settings for a user
    async def fetch_shortener(self, user_id: int):
        """
        Fetch the shortener settings for a user.
        Returns a dictionary or None if no settings are found.
        """
        user = await self.shortener_data.find_one({'_id': user_id})
        if user:
            return {
                'site': user.get('site'),
                'api': user.get('api'),
                'enabled': user.get('enabled', False)
            }
        return None


    # VERIFICATION MANAGEMENT
    async def db_verify_status(self, user_id):
        user = await self.user_data.find_one({'_id': user_id})
        if user:
            return user.get('verify_status', default_verify)
        return default_verify

    async def db_update_verify_status(self, user_id, verify):
        await self.user_data.update_one({'_id': user_id}, {'$set': {'verify_status': verify}})

    async def get_verify_status(self, user_id):
        verify = await self.db_verify_status(user_id)
        return verify

    async def update_verify_status(self, user_id, verify_token="", is_verified=False, verified_time=0, link=""):
        current = await self.db_verify_status(user_id)
        current['verify_token'] = verify_token
        current['is_verified'] = is_verified
        current['verified_time'] = verified_time
        current['link'] = link
        await self.db_update_verify_status(user_id, current)

    # CHANNEL BUTTON SETTINGS
    async def set_channel_button_link(self, button_name: str, button_link: str):
        await self.channel_button_link_data.delete_many({})  # Remove all existing documents
        await self.channel_button_link_data.insert_one({'button_name': button_name, 'button_link': button_link}) # Insert the new document

    async def get_channel_button_link(self):
        data = await self.channel_button_link_data.find_one({})
        if data:
            return data.get('button_name'), data.get('button_link')
        return ' Channel', 'https://t.me/Javpostr'


    # DELETE TIMER SETTINGS
    async def set_del_timer(self, value: int):        
        existing = await self.del_timer_data.find_one({})
        if existing:
            await self.del_timer_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.del_timer_data.insert_one({'value': value})

    async def get_del_timer(self):
        data = await self.del_timer_data.find_one({})
        if data:
            return data.get('value', 600)
        return 600

    # SET BOOLEAN VALUES FOR DIFFERENT SETTINGS

    async def set_auto_delete(self, value: bool):
        existing = await self.auto_delete_data.find_one({})
        if existing:
            await self.auto_delete_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.auto_delete_data.insert_one({'value': value})

    async def set_hide_caption(self, value: bool):
        existing = await self.hide_caption_data.find_one({})
        if existing:
            await self.hide_caption_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.hide_caption_data.insert_one({'value': value})

    async def set_protect_content(self, value: bool):
        existing = await self.protect_content_data.find_one({})
        if existing:
            await self.protect_content_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.protect_content_data.insert_one({'value': value})

    async def set_channel_button(self, value: bool):
        existing = await self.channel_button_data.find_one({})
        if existing:
            await self.channel_button_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.channel_button_data.insert_one({'value': value})

    async def set_request_forcesub(self, value: bool):
        existing = await self.rqst_fsub_data.find_one({})
        if existing:
            await self.rqst_fsub_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.rqst_fsub_data.insert_one({'value': value})


    # GET BOOLEAN VALUES FOR DIFFERENT SETTINGS        

    async def get_auto_delete(self):
        data = await self.auto_delete_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    async def get_hide_caption(self):
        data = await self.hide_caption_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    async def get_protect_content(self):
        data = await self.protect_content_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    async def get_channel_button(self):
        data = await self.channel_button_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    async def get_request_forcesub(self):
        data = await self.rqst_fsub_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    # CHANNEL MANAGEMENT
    async def channel_exist(self, channel_id: int):
        found = await self.channel_data.find_one({'_id': channel_id})
        return bool(found)

    async def add_channel(self, channel_id: int):
        if not await self.channel_exist(channel_id):
            await self.channel_data.insert_one({'_id': channel_id})
            return

    async def del_channel(self, channel_id: int):
        if await self.channel_exist(channel_id):
            await self.channel_data.delete_one({'_id': channel_id})
            return

    async def get_all_channels(self):
        channel_docs = await self.channel_data.find().to_list(length=None)
        channel_ids = [doc['_id'] for doc in channel_docs]
        return channel_ids

    # POST CHANNEL MANAGEMENT (channel(s) where /plink publishes batch-link posts)
    async def post_channel_exist(self, channel_id: int):
        found = await self.post_channel_data.find_one({'_id': channel_id})
        return bool(found)

    async def add_post_channel(self, channel_id: int):
        if not await self.post_channel_exist(channel_id):
            await self.post_channel_data.insert_one({'_id': channel_id})
            return

    async def del_post_channel(self, channel_id: int):
        if await self.post_channel_exist(channel_id):
            await self.post_channel_data.delete_one({'_id': channel_id})
            return

    async def get_all_post_channels(self):
        channel_docs = await self.post_channel_data.find().to_list(length=None)
        channel_ids = [doc['_id'] for doc in channel_docs]
        return channel_ids

    # ADMIN USER MANAGEMENT
    async def admin_exist(self, admin_id: int):
        found = await self.admins_data.find_one({'_id': admin_id})
        return bool(found)

    async def add_admin(self, admin_id: int):
        if not await self.admin_exist(admin_id):
            await self.admins_data.insert_one({'_id': admin_id})
            return

    async def del_admin(self, admin_id: int):
        if await self.admin_exist(admin_id):
            await self.admins_data.delete_one({'_id': admin_id})
            return

    async def get_all_admins(self):
        users_docs = await self.admins_data.find().to_list(length=None)
        user_ids = [doc['_id'] for doc in users_docs]
        return user_ids


    # BAN USER MANAGEMENT
    async def ban_user_exist(self, user_id: int):
        found = await self.banned_user_data.find_one({'_id': user_id})
        return bool(found)

    async def add_ban_user(self, user_id: int):
        if not await self.ban_user_exist(user_id):
            await self.banned_user_data.insert_one({'_id': user_id})
            return

    async def del_ban_user(self, user_id: int):
        if await self.ban_user_exist(user_id):
            await self.banned_user_data.delete_one({'_id': user_id})
            return

    async def get_ban_users(self):
        users_docs = await self.banned_user_data.find().to_list(length=None)
        user_ids = [doc['_id'] for doc in users_docs]
        return user_ids


    # REQUEST FORCE-SUB MANAGEMENT

    # Initialize a channel with an empty user_ids array (acting as a set)
    async def add_reqChannel(self, channel_id: int):
        await self.rqst_fsub_Channel_data.update_one(
            {'_id': channel_id}, 
            {'$setOnInsert': {'user_ids': []}},  # Start with an empty array to represent the set
            upsert=True  # Insert the document if it doesn't exist
        )

    # Set the request_forcesub mode for a specific channel
    async def set_request_forcesub_channel(self, channel_id: int, fsub_mode: bool):
        await self.rqst_fsub_Channel_data.update_one(
        {'_id': channel_id},
        {'$set': {'fsub_mode': fsub_mode}},
        upsert=True
    )

    # Method 1: Add user to the channel set
    async def reqSent_user(self, channel_id: int, user_id: int):
        # Add the user to the set of users for a specific channel
        await self.rqst_fsub_Channel_data.update_one(
            {'_id': channel_id}, 
            {'$addToSet': {'user_ids': user_id}}, 
            upsert=True
        )

    # Method 2: Remove a user from the channel set
    async def del_reqSent_user(self, channel_id: int, user_id: int):
        # Remove the user from the set of users for the channel
        await self.rqst_fsub_Channel_data.update_one(
            {'_id': channel_id}, 
            {'$pull': {'user_ids': user_id}}
        )

    # Clear the user set (user_ids array) for a specific channel
    async def clear_reqSent_user(self, channel_id: int):
        if await self.reqChannel_exist(channel_id):
            await self.rqst_fsub_Channel_data.update_one(
                {'_id': channel_id}, 
                {'$set': {'user_ids': []}}  # Reset user_ids to an empty array
            )

    # Method 3: Check if a user exists in the channel set
    async def reqSent_user_exist(self, channel_id: int, user_id: int):
        # Check if the user exists in the set of the channel's users
        found = await self.rqst_fsub_Channel_data.find_one(
            {'_id': channel_id, 'user_ids': user_id}
        )
        return bool(found)

    # Method 4: Remove a channel and its set of users
    async def del_reqChannel(self, channel_id: int):
        # Delete the entire channel's user set
        await self.rqst_fsub_Channel_data.delete_one({'_id': channel_id})

    # Method 5: Check if a channel exists
    async def reqChannel_exist(self, channel_id: int):
        # Check if the channel exists
        found = await self.rqst_fsub_Channel_data.find_one({'_id': channel_id})
        return bool(found)

    # Method 6: Get all users from a channel's set
    async def get_reqSent_user(self, channel_id: int):
        # Retrieve the list of users for a specific channel
        data = await self.rqst_fsub_Channel_data.find_one({'_id': channel_id})
        if data:
            return data.get('user_ids', [])
        return []

    # Method 7: Get all available channel IDs
    async def get_reqChannel(self):
        # Retrieve all channel IDs
        channel_docs = await self.rqst_fsub_Channel_data.find().to_list(length=None)
        channel_ids = [doc['_id'] for doc in channel_docs]
        return channel_ids


    # Get all available channel IDs in store_reqLink_data
    async def get_reqLink_channels(self):
        # Retrieve all documents from store_reqLink_data
        channel_docs = await self.store_reqLink_data.find().to_list(length=None)
        # Extract the channel IDs from the documents
        channel_ids = [doc['_id'] for doc in channel_docs]
        return channel_ids

    # Get the stored link for a specific channel
    async def get_stored_reqLink(self, channel_id: int):
        # Retrieve the stored link for a specific channel_id from store_reqLink_data
        data = await self.store_reqLink_data.find_one({'_id': channel_id})
        if data:
            return data.get('link')
        return None

    # Set (or update) the stored link for a specific channel
    async def store_reqLink(self, channel_id: int, link: str):
        # Insert or update the link for the channel_id in store_reqLink_data
        await self.store_reqLink_data.update_one(
            {'_id': channel_id}, 
            {'$set': {'link': link}}, 
            upsert=True
        )

    # Delete the stored link and the channel from store_reqLink_data
    async def del_stored_reqLink(self, channel_id: int):
        # Delete the document with the channel_id in store_reqLink_data
        await self.store_reqLink_data.delete_one({'_id': channel_id})

    
    # **Get Free Usage Settings**
    async def get_free_settings(self):
        settings = await self.free_data.find_one({"_id": "free_usage"})
        if not settings:
            settings = {"limit": 5, "enabled": True}
            await self.free_data.insert_one({"_id": "free_usage", **settings})
        return settings

    # **Update Free Usage Settings**
    async def update_free_settings(self, limit=None, enabled=None):
        updates = {}
        if limit is not None:
            updates["limit"] = limit
        if enabled is not None:
            updates["enabled"] = enabled
        if updates:
            await self.free_data.update_one({"_id": "free_usage"}, {"$set": updates}, upsert=True)

    # **Set Free Limit**
    async def set_free_limit(self, limit: int):
        try:
            await self.free_data.update_one(
                {"_id": "free_usage"},  # Standardized ID
                {"$set": {"limit": limit}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error updating limit: {e}")
            return False

    # **Check User's Free Usage**
    async def check_free_usage(self, user_id):
        try:
        # Fetch user data from the database
            data = await self.free_data.find_one({"user_id": user_id})

            if not data:
                return 0  # If no data exists, assume count is 0 (new user)

        # Ensure the count is properly retrieved
            usage_count = int(data.get("count", 0))  # Default to 0 if missing
            return usage_count  # Return actual usage count
        except Exception as e:
            logging.error(f"Error checking free usage for user {user_id}: {e}")
            return 0  # Default to 0 if an error occurs


    # ---------------------------
    # 🎬 Video Management
    # ---------------------------
    async def video_exists(self, file_id: str):
        return await self.videos_collection.find_one({"file_id": file_id})

    async def insert_videos(self, video_list: list):
        if video_list:
            return await self.videos_collection.insert_many(video_list)

    async def get_videos(self):
        cursor = self.videos_collection.find({})
        return await cursor.to_list(length=None)


    # ---------------------------
    # 👤 User Subscription Management
    # ---------------------------
    async def get_user(self, user_id: int):
        return await self.users_collection.find_one({"user_id": user_id})

    async def create_user(self, user_id: int, daily_limit: int, last_access: str, subscription="free"):
        return await self.users_collection.insert_one({
            "user_id": user_id,
            "subscription": subscription,
            "subscription_expiry": None,
            "daily_limit": daily_limit,
            "last_access": last_access
        })

    async def update_user(self, user_id: int, data: dict):
        return await self.users_collection.update_one({"user_id": user_id}, {"$set": data})

    async def decrement_daily_limit(self, user_id: int):
        return await self.users_collection.update_one({"user_id": user_id}, {"$inc": {"daily_limit": -1}})

    
db = Rohit(DB_URI, DB_NAME)

        

