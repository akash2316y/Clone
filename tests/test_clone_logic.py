"""
Offline tests for the clone engine (no Telegram, no MongoDB).

Run:  python -m unittest discover -s tests -v

Libraries that are not installed (pyrogram, motor, ...) are replaced by stubs, so the tests
only exercise our own logic. They do NOT prove the bot works against live Telegram.
"""
import asyncio
import base64
import os
import sys
import types
import unittest
import zoneinfo
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- environment the bot's config.py insists on -------------------------------------------------
os.environ.update({
    "TG_BOT_TOKEN": "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN",
    "APP_ID": "1", "API_HASH": "x", "CHANNEL_ID": "-1001234567890", "LOG_CHANNEL": "-1009999999999",
    "DATABASE_URL": "mongodb://localhost:27017", "OWNER_ID": "111",
    "CLONE_ENCRYPTION_KEY": "",   # force the derived-key path
})

# ---- stub third-party libs that are not installed -----------------------------------------------
def _stub(name, obj=None):
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = obj or MagicMock()

for mod in ("pyrogram", "pyrogram.types", "pyrogram.enums", "pyrogram.errors", "pyrogram.handlers",
            "pyrogram.filters", "motor", "motor.motor_asyncio", "pymongo", "aiohttp", "apscheduler"):
    _stub(mod)
_pytz = types.ModuleType("pytz")
_pytz.timezone = lambda n: zoneinfo.ZoneInfo(n)
_pytz.UTC = zoneinfo.ZoneInfo("UTC")
_stub("pytz", _pytz)

from clone import antispam, crypto, ctx, engine, plans, store, ui   # noqa: E402

DAY = 86400


def run(coro):
    return asyncio.run(coro)


# ================================================================== ui
class UiTests(unittest.TestCase):
    def test_small_caps_keeps_html_and_placeholders(self):
        out = ui.sc("<b>hello {name} &amp; x</b>")
        self.assertIn("<b>", out)
        self.assertIn("{name}", out)
        self.assertIn("&amp;", out)
        self.assertIn("ʜᴇʟʟᴏ", out)

    def test_tpl_does_not_restyle_values(self):
        self.assertIn("MixedCase", ui.tpl("<b>user: {n}</b>", n="MixedCase"))

    def test_parse_duration(self):
        cases = {"30m": 1800, "12h": 43200, "7d": 7 * DAY, "2w": 14 * DAY, "1mo": 30 * DAY, "1y": 365 * DAY,
                 "5 days": 5 * DAY}
        for text, secs in cases.items():
            self.assertEqual(ui.parse_duration(text), secs, text)
        for bad in ("", "abc", "0d", "10", "d", "5x", "-3d"):
            self.assertIsNone(ui.parse_duration(bad), bad)

    def test_esc(self):
        self.assertEqual(ui.esc("<a&b>"), "&lt;a&amp;b&gt;")


# ================================================================== plans / expiry
class PlanTests(unittest.TestCase):
    T0 = 1_000_000.0

    def test_free_clone_lives_free_days(self):
        plan, vu, expired = plans.compute_validity(self.T0, 30, None, now=self.T0 + 29 * DAY)
        self.assertEqual((plan, expired), ("free", False))
        self.assertEqual(vu, self.T0 + 30 * DAY)
        _, _, expired = plans.compute_validity(self.T0, 30, None, now=self.T0 + 31 * DAY)
        self.assertTrue(expired)

    def test_premium_extends_validity(self):
        prem_until = self.T0 + 90 * DAY
        plan, vu, expired = plans.compute_validity(self.T0, 30, prem_until, now=self.T0 + 60 * DAY)
        self.assertEqual((plan, vu, expired), ("premium", prem_until, False))

    def test_short_premium_never_shortens_free_window(self):
        _, vu, _ = plans.compute_validity(self.T0, 30, self.T0 + 5 * DAY, now=self.T0 + DAY)
        self.assertEqual(vu, self.T0 + 30 * DAY)

    def test_lapsed_premium_then_expired_after_window(self):
        plan, _, expired = plans.compute_validity(self.T0, 30, self.T0 + 10 * DAY, now=self.T0 + 40 * DAY)
        self.assertEqual((plan, expired), ("free", True))

    def test_zero_free_days_never_expires(self):
        plan, vu, expired = plans.compute_validity(self.T0, 0, None, now=self.T0 + 9999 * DAY)
        self.assertEqual((plan, vu, expired), ("free", None, False))

    def test_tier_limits(self):
        self.assertFalse(plans.limits("free")["custom_shortener"])
        self.assertFalse(plans.limits("free")["branding_optional"])
        self.assertTrue(plans.limits("premium")["custom_caption"])
        self.assertGreater(plans.limits("premium")["fsub_limit"], plans.limits("free")["fsub_limit"])


# ================================================================== anti-spam
class AntiSpamTests(unittest.TestCase):
    def make(self):
        return antispam.RateLimiter(max_msgs=3, window=5, warnings=2, tempban_secs=60, permban_after=3)

    def burst(self, rl, uid, t, n=4):
        v = None
        for i in range(n):
            v = rl.check(uid, now=t + i * 0.01)
        return v

    def test_normal_traffic_is_fine(self):
        rl = self.make()
        for i in range(20):
            self.assertEqual(rl.check(1, now=i * 3.0).kind, "ok")

    def test_escalation_warn_warn_tempban_then_permban(self):
        rl = self.make()
        t = 1000.0
        self.assertEqual(self.burst(rl, 1, t).kind, "warn")
        self.assertEqual(self.burst(rl, 1, t + 10).kind, "warn")
        v = self.burst(rl, 1, t + 20)
        self.assertEqual((v.kind, v.seconds), ("tempban", 60))
        self.assertEqual(rl.check(1, now=t + 30).kind, "blocked")          # still banned, silent
        t2 = t + 200                                                        # ban over
        self.burst(rl, 1, t2); self.burst(rl, 1, t2 + 10)
        v = self.burst(rl, 1, t2 + 20)
        self.assertEqual((v.kind, v.seconds), ("tempban", 120))            # grows
        t3 = t2 + 1000
        self.burst(rl, 1, t3); self.burst(rl, 1, t3 + 10)
        self.assertEqual(self.burst(rl, 1, t3 + 20).kind, "permban")

    def test_users_are_independent_and_forget_resets(self):
        rl = self.make()
        self.burst(rl, 1, 0)
        self.assertEqual(rl.check(2, now=0.5).kind, "ok")
        rl.forget(1)
        self.assertEqual(rl.check(1, now=1.0).kind, "ok")


# ================================================================== crypto
class CryptoTests(unittest.TestCase):
    def test_roundtrip_and_not_plaintext(self):
        token = "123456:ABC-secret"
        blob = crypto.enc(token)
        self.assertNotIn("secret", blob)
        self.assertEqual(crypto.dec(blob), token)

    def test_garbage_decrypts_to_empty(self):
        self.assertEqual(crypto.dec("not-a-fernet-token"), "")
        self.assertEqual(crypto.dec(""), "")
        self.assertEqual(crypto.enc(""), "")


# ================================================================== link parsing (must match main bot)
def main_bot_encode(text: str) -> str:            # same as helper_func.encode
    return base64.urlsafe_b64encode(text.encode("ascii")).decode("ascii").strip("=")


class LinkTests(unittest.TestCase):
    CH = abs(int(os.environ["CHANNEL_ID"]))

    def payload(self, *ids, kind="get"):
        return main_bot_encode(f"{kind}-" + "-".join(str(i * self.CH) for i in ids))

    def parse(self, payload):
        return engine.parse_link(engine.b64_decode(payload))

    def test_single(self):
        self.assertEqual(self.parse(self.payload(42)), ("get", [42]))

    def test_batch_forward_and_reverse(self):
        self.assertEqual(self.parse(self.payload(5, 8)), ("get", [5, 6, 7, 8]))
        self.assertEqual(self.parse(self.payload(8, 5)), ("get", [8, 7, 6, 5]))

    def test_premium_prefix(self):
        self.assertEqual(self.parse(self.payload(7, kind="premium")), ("premium", [7]))

    def test_rejects_foreign_or_broken_payloads(self):
        bad = [main_bot_encode(f"get-{12345}"),            # not a multiple of the channel id
               main_bot_encode("evil-1-2"), main_bot_encode(f"get-{self.CH}-x"),
               main_bot_encode(f"get-0"), "!!!", "", None]
        for b in bad:
            kind, ids = engine.parse_link(engine.b64_decode(b) if b else b)
            self.assertIsNone(kind, b)
            self.assertEqual(ids, [])

    def test_batch_size_cap(self):
        kind, _ = self.parse(self.payload(1, engine.MAX_BATCH + 5))
        self.assertIsNone(kind)


# ================================================================== settings merge
class StoreTests(unittest.TestCase):
    def test_merge_adds_new_keys_and_keeps_saved(self):
        saved = {"fsub": {"enabled": True}, "branding": False}
        m = store.merge_settings(saved)
        self.assertTrue(m["fsub"]["enabled"])
        self.assertEqual(m["fsub"]["channels"], [])            # default filled in
        self.assertFalse(m["branding"])
        self.assertIn("auto_delete", m)

    def test_merge_none(self):
        self.assertEqual(store.merge_settings(None), store.default_settings())


# ================================================================== engine behaviours
class FakeStore:
    def __init__(self):
        self.users, self.stats = {}, {}

    async def set_user(self, cid, uid, **f):
        self.users.setdefault((cid, uid), {}).update(f)

    async def inc(self, cid, stat, n=1):
        self.stats[stat] = self.stats.get(stat, 0) + n


class FakeMessage:
    def __init__(self, uid=5):
        self.from_user = SimpleNamespace(id=uid)
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append((text, kw))


class Caption(str):
    """Stands in for pyrogram's Str: plain text via str(), HTML via .html"""
    @property
    def html(self):
        return str(self)


def make_clone(plan_settings=None, **over):
    s = store.default_settings()
    s["shortener"].update({"enabled": True, "domain": "short.example.com", "api": crypto.enc("PLAIN-KEY-123"), "hours": 6})
    if plan_settings:
        s.update(plan_settings)
    d = {"_id": 77, "owner_id": 9, "username": "mybot", "status": "active", "created_at": 0, "settings": s}
    d.update(over)
    return d


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.fs = FakeStore()
        ctx.set_manager(SimpleNamespace(store=self.fs, main=SimpleNamespace(username="MainBot")))
        engine.logs.set_main(None)

    def test_verify_uses_decrypted_shortener_key(self):
        """Regression: the key is stored encrypted; the shortener must receive the plaintext."""
        seen = {}

        async def fake_shorten(domain, api, url):
            seen.update(domain=domain, api=api, url=url)
            return "https://short.example.com/abc"

        original, engine.shorten = engine.shorten, fake_shorten
        try:
            msg = FakeMessage()
            ok = run(engine.send_verify(SimpleNamespace(username="mybot"), msg, make_clone(), "premium", "PAYLOAD"))
        finally:
            engine.shorten = original
        self.assertTrue(ok)
        self.assertEqual(seen["api"], "PLAIN-KEY-123")
        self.assertEqual(seen["domain"], "short.example.com")
        self.assertIn("start=verify_", seen["url"])
        u = self.fs.users[(77, 5)]
        self.assertEqual(u["pending"], "PAYLOAD")
        self.assertIn(u["token"], seen["url"])

    def test_verify_fails_open_when_key_unreadable(self):
        clone = make_clone()
        clone["settings"]["shortener"]["api"] = "corrupted"
        called = []

        async def fake_shorten(*a):
            called.append(a)
            return "https://x"

        original, engine.shorten = engine.shorten, fake_shorten
        try:
            ok = run(engine.send_verify(SimpleNamespace(username="mybot"), FakeMessage(), clone, "premium", "P"))
        finally:
            engine.shorten = original
        self.assertFalse(ok)          # caller serves the file instead of blocking forever
        self.assertEqual(called, [])

    def test_shortener_only_active_for_premium(self):
        clone = make_clone()
        self.assertFalse(engine.shortener_active(clone, "free"))
        self.assertTrue(engine.shortener_active(clone, "premium"))

    def test_branding_mandatory_on_free(self):
        clone = make_clone({"branding": False})
        self.assertIn("MainBot", engine.brand_text(clone, "free"))          # cannot be switched off
        self.assertEqual(engine.brand_text(clone, "premium"), "")           # premium may

    def test_caption_has_footer_and_fits_telegram_limit(self):
        msg = SimpleNamespace(caption=Caption("y" * 1200), video=None, document=None)
        cap = engine.build_caption(make_clone(), "free", msg)
        self.assertLessEqual(len(cap), 1024)
        self.assertIn("MainBot", cap)

    def test_custom_caption_is_premium_only(self):
        settings = {"caption": {"enabled": True, "text": "CUSTOM {caption}"}}
        msg = SimpleNamespace(caption=Caption("orig"), video=None, document=None)
        self.assertTrue(engine.build_caption(make_clone(settings), "premium", msg).startswith("CUSTOM orig"))
        self.assertNotIn("CUSTOM", engine.build_caption(make_clone(settings), "free", msg))


if __name__ == "__main__":
    unittest.main(verbosity=2)
