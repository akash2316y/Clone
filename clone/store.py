"""MongoDB access for the clone system. Uses the same database as the main bot."""
import time
from typing import Any, Dict, List, Optional

from config import ALLOW_CLONING, FREE_CLONE_DAYS, MAX_CLONES_PER_USER

# clone.status values
ACTIVE = "active"      # should be running
PAUSED = "paused"      # paused by its owner
EXPIRED = "expired"    # plan ended (auto-paused, resumes by itself if renewed)
CRASHED = "crashed"    # crash loop, needs a manual resume
INVALID = "invalid"    # token revoked
BANNED = "banned"      # owner is banned system-wide


def default_settings() -> Dict[str, Any]:
    return {
        "fsub": {"enabled": False, "channels": []},
        "shortener": {"enabled": False, "domain": "", "api": "", "hours": 12},
        "caption": {"enabled": False, "text": ""},
        "start": {"text": "", "pic": ""},
        "branding": True,
        "protect": False,
        "auto_delete": {"links": 0, "video": 0},   # seconds, 0 = off
        "user_log_channel": 0,
    }


def merge_settings(saved: Optional[dict]) -> Dict[str, Any]:
    """Defaults overlaid with whatever is stored (so new keys never KeyError)."""
    base = default_settings()
    for key, val in (saved or {}).items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            base[key].update(val)
        else:
            base[key] = val
    return base


class CloneStore:
    def __init__(self, database):
        self.clones = database["clones"]
        self.users = database["clone_users"]
        self.files = database["clone_file_cache"]
        self.dels = database["clone_deletions"]
        self.cfg = database["clone_owner_settings"]

    # ---------------- owner-level (global) settings ----------------
    async def get_global(self) -> Dict[str, Any]:
        doc = await self.cfg.find_one({"_id": "global"}) or {}
        return {
            "allow_cloning": doc.get("allow_cloning", ALLOW_CLONING),
            "max_clones": int(doc.get("max_clones", MAX_CLONES_PER_USER)),
            "free_days": int(doc.get("free_days", FREE_CLONE_DAYS)),
        }

    async def set_global(self, **fields):
        await self.cfg.update_one({"_id": "global"}, {"$set": fields}, upsert=True)

    # ---------------- clones ----------------
    async def create(self, bot_id: int, owner_id: int, token_enc: str, username: str, name: str) -> dict:
        doc = {
            "_id": bot_id, "owner_id": owner_id, "token": token_enc,
            "username": username, "name": name, "status": ACTIVE,
            "created_at": time.time(), "warned": False,
            "settings": default_settings(),
            "stats": {"files": 0, "links": 0, "verify_links": 0, "verified": 0},
        }
        await self.clones.insert_one(doc)
        return doc

    async def get(self, bot_id: int) -> Optional[dict]:
        doc = await self.clones.find_one({"_id": bot_id})
        if doc:
            doc["settings"] = merge_settings(doc.get("settings"))
        return doc

    async def all(self, status: Optional[str] = None) -> List[dict]:
        q = {"status": status} if status else {}
        docs = await self.clones.find(q).sort("created_at", 1).to_list(None)
        for d in docs:
            d["settings"] = merge_settings(d.get("settings"))
        return docs

    async def by_owner(self, owner_id: int) -> List[dict]:
        docs = await self.clones.find({"owner_id": owner_id}).sort("created_at", 1).to_list(None)
        for d in docs:
            d["settings"] = merge_settings(d.get("settings"))
        return docs

    async def count_by_owner(self, owner_id: int) -> int:
        return await self.clones.count_documents({"owner_id": owner_id})

    async def update(self, bot_id: int, fields: Dict[str, Any]):
        """fields may use dotted keys: {'settings.fsub.enabled': True}"""
        await self.clones.update_one({"_id": bot_id}, {"$set": fields})

    async def inc(self, bot_id: int, stat: str, n: int = 1):
        await self.clones.update_one({"_id": bot_id}, {"$inc": {f"stats.{stat}": n}})

    async def delete(self, bot_id: int):
        await self.clones.delete_one({"_id": bot_id})
        await self.users.delete_many({"clone_id": bot_id})
        await self.files.delete_many({"clone_id": bot_id})
        await self.dels.delete_many({"clone_id": bot_id})

    # ---------------- clone users ----------------
    @staticmethod
    def _uid(clone_id: int, user_id: int) -> str:
        return f"{clone_id}:{user_id}"

    async def touch_user(self, clone_id: int, user_id: int) -> bool:
        """Record activity. True if this user is new to the clone."""
        res = await self.users.update_one(
            {"_id": self._uid(clone_id, user_id)},
            {"$set": {"last_seen": time.time()},
             "$setOnInsert": {"clone_id": clone_id, "user_id": user_id, "joined": time.time(),
                              "verified_until": 0, "token": "", "token_at": 0, "pending": ""}},
            upsert=True,
        )
        return res.upserted_id is not None

    async def get_user(self, clone_id: int, user_id: int) -> dict:
        return await self.users.find_one({"_id": self._uid(clone_id, user_id)}) or {}

    async def set_user(self, clone_id: int, user_id: int, **fields):
        await self.users.update_one({"_id": self._uid(clone_id, user_id)}, {"$set": fields}, upsert=True)

    async def user_counts(self, clone_id: int, active_since: float):
        total = await self.users.count_documents({"clone_id": clone_id})
        active = await self.users.count_documents({"clone_id": clone_id, "last_seen": {"$gte": active_since}})
        return total, active

    # ---------------- file_id cache (per clone bot) ----------------
    async def get_file(self, clone_id: int, msg_id: int) -> Optional[dict]:
        return await self.files.find_one({"_id": f"{clone_id}:{msg_id}"})

    async def put_file(self, clone_id: int, msg_id: int, mtype: str, file_id: str):
        await self.files.update_one(
            {"_id": f"{clone_id}:{msg_id}"},
            {"$set": {"clone_id": clone_id, "type": mtype, "file_id": file_id}}, upsert=True)

    async def drop_file(self, clone_id: int, msg_id: int):
        await self.files.delete_one({"_id": f"{clone_id}:{msg_id}"})

    # ---------------- persisted auto-delete queue ----------------
    async def queue_delete(self, clone_id: int, chat_id: int, msg_ids: List[int], delay: int,
                           notice_id: int = 0, payload: str = ""):
        await self.dels.insert_one({
            "clone_id": clone_id, "chat_id": chat_id, "msg_ids": msg_ids,
            "due": time.time() + delay, "notice_id": notice_id, "payload": payload,
        })

    async def due_deletions(self, now: float, limit: int = 100) -> List[dict]:
        return await self.dels.find({"due": {"$lte": now}}).limit(limit).to_list(limit)

    async def drop_deletion(self, _id):
        await self.dels.delete_one({"_id": _id})
