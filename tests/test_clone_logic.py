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


class OwnChannelLinkTests(unittest.TestCase):
    CH = abs(int(os.environ["CHANNEL_ID"]))
    OWN = -1005550001111

    def enc(self, ids, ch):
        return main_bot_encode("get-" + "-".join(str(i * abs(ch)) for i in ids))

    def test_own_channel_link(self):
        raw = engine.b64_decode(self.enc((3, 6), self.OWN))
        self.assertEqual(engine.parse_link_src(raw, self.OWN), ("get", [3, 4, 5, 6], "own"))

    def test_central_link_still_works_in_clone_with_own_channel(self):
        raw = engine.b64_decode(self.enc((9,), -self.CH))
        self.assertEqual(engine.parse_link_src(raw, self.OWN), ("get", [9], "central"))

    def test_own_link_not_served_without_matching_channel(self):
        raw = engine.b64_decode(self.enc((3, 6), self.OWN))
        self.assertEqual(engine.parse_link_src(raw, 0)[0], None)                     # clone has no db channel
        self.assertEqual(engine.parse_link_src(raw, -1007770002222)[0], None)        # another clone's channel

    def test_b64_roundtrip(self):
        self.assertEqual(engine.b64_decode(engine.b64_encode("get-123-456")), "get-123-456")


class CloneGenlinkFlowTests(unittest.TestCase):
    """Fake Telegram objects: owner sends 3 messages, taps Generate Link -> one range link in the OWN channel."""
    OWN = -1005550001111

    def run_flow(self, owner=True, ch=OWN):
        from clone import ctx, genlink
        genlink._S.clear()
        clone = {"_id": 7, "owner_id": 500, "username": "MyClone", "settings": {"db_channel": ch}}
        ctx.manager = SimpleNamespace(store=SimpleNamespace(get=lambda cid: _aw(clone)))
        out = {"copied": [], "sent": [], "replies": []}
        counter = iter(range(100, 200))

        class Msg:
            def __init__(self, uid, text="hi"):
                self.from_user = SimpleNamespace(id=uid)
                self.chat = SimpleNamespace(id=uid)
                self.service, self.text = False, text
            async def copy(self, to, **kw):
                out["copied"].append(to)
                return SimpleNamespace(id=next(counter))
            async def reply_text(self, t, **kw):
                out["replies"].append(t)
            def stop_propagation(self):
                raise _Stop()

        class _Stop(Exception):
            pass

        class Client:
            clone_id = 7
            async def send_message(self, chat_id, text, **kw):
                out["sent"].append(text)
                return SimpleNamespace(delete=lambda: _aw(None))
            async def delete_messages(self, *a, **k):
                out.setdefault("deleted", []).append(a)

        class Query:
            def __init__(self, uid, data):
                self.from_user, self.data = SimpleNamespace(id=uid), data
                self.message = SimpleNamespace(chat=SimpleNamespace(id=uid), delete=lambda: _aw(None),
                                               edit_text=lambda *a, **k: _aw(None))
            async def answer(self, *a, **k):
                out.setdefault("answers", []).append(a)
            def stop_propagation(self):
                raise _Stop()

        async def go():
            uid = 500 if owner else 600
            c = Client()
            await genlink.on_genlink(c, Msg(uid, "/genlink"))
            for _ in range(3):
                try:
                    await genlink.on_collect(c, Msg(uid))
                except _Stop:
                    pass
            await asyncio.sleep(1.7)                  # debounce -> a single panel
            try:
                await genlink.on_cb(c, Query(uid, "gl_gen"))
            except _Stop:
                pass
        asyncio.run(go())
        return out

    def test_owner_flow_builds_one_link_from_own_channel(self):
        out = self.run_flow()
        self.assertEqual(out["copied"], [self.OWN] * 3)
        link = [t for t in out["sent"] if "Here Is Your Link" in t][0]
        payload = link.split("?start=")[1].strip()
        self.assertEqual(engine.parse_link_src(engine.b64_decode(payload), self.OWN), ("get", [100, 101, 102], "own"))
        self.assertEqual(len([t for t in out["sent"] if t.startswith("Stored Messages")]), 2)  # intro(0) + one debounced panel

    def test_not_owner_and_no_channel(self):
        self.assertEqual(self.run_flow(owner=False)["copied"], [])
        self.assertEqual(self.run_flow(ch=0)["copied"], [])


def _aw(v):
    async def f():
        return v
    return f()


class StartButtonsTests(unittest.TestCase):
    def view(self, skip_ads, uid=900, plan="free", branding=True):
        from unittest import mock
        from clone import ctx
        ctx.manager = SimpleNamespace(main=SimpleNamespace(username="MainBot"))
        clone = {"_id": 7, "owner_id": 500, "username": "MyClone", "settings": store.default_settings()}
        clone["settings"]["branding"] = branding
        u = SimpleNamespace(id=uid, first_name="A", username=None, mention="A")
        with mock.patch.object(engine, "InlineKeyboardButton", lambda t, **kw: (t, kw)), \
             mock.patch.object(engine, "InlineKeyboardMarkup", lambda rows: rows), \
             mock.patch.object(engine, "limits", lambda plan: {"custom_start": False}):
            return engine.start_view(clone, plan, u, skip_ads)[1]

    def test_non_premium_user_gets_all_four_buttons(self):
        rows = self.view(False)
        self.assertEqual(len(rows[0]), 2)                                  # help | about
        urls = [b[1]["url"] for r in rows[1:] for b in r]
        self.assertEqual(len(urls), 2)
        self.assertIn("https://t.me/MainBot?start=clone", urls)

    def test_premium_user_only_help_and_about(self):
        rows = self.view(True)
        self.assertEqual([b[1]["callback_data"] for b in rows[0]], ["cl|help", "cl|about"])
        self.assertEqual(len(rows), 1)

    def test_premium_clone_with_branding_off_hides_main_buttons(self):
        rows = self.view(False, plan="premium", branding=False)
        self.assertEqual(len(rows), 1)

    def test_premium_clone_with_branding_on_still_shows_all(self):
        self.assertEqual(len(self.view(False, plan="premium", branding=True)), 3)

    def test_free_clone_cannot_hide_buttons(self):
        self.assertEqual(len(self.view(False, plan="free", branding=False)), 3)

    def test_clone_about_page_has_every_line(self):
        txt = engine.render_about("My <Bot>", "Main Bot", "<a href='tg://user?id=5'>Admin</a>")
        self.assertIn("My &lt;Bot&gt;", txt)                                # name is escaped
        self.assertIn("ᴄʟᴏɴᴇ ᴏꜰ:</b> Main Bot", txt)
        self.assertIn("ᴍʏ ᴏᴡɴᴇʀ:</b> <a href='tg://user?id=5'>Admin</a>", txt)
        self.assertIn(">UnknownBotz</a>", txt)
        self.assertIn(">UnknownBotzChat</a>", txt)
        self.assertIn("ᴠᴇʀsɪᴏɴ:</b> 1.0", txt)
        self.assertNotIn("{", txt)                                          # no placeholder left behind
        self.assertEqual(txt.count("<b>"), txt.count("</b>"))               # well-formed HTML
        self.assertLessEqual(len(txt), 1024)                                # fits a photo caption

    def test_main_about_page_has_no_clone_of_line(self):
        txt = engine.render_about_main("Owner Bot", "<a href='tg://user?id=1'>Boss</a>")
        self.assertIn("ᴍʏ ɴᴀᴍᴇ:</b> Owner Bot", txt)
        self.assertIn("ᴍʏ ᴏᴡɴᴇʀ:</b> <a href='tg://user?id=1'>Boss</a>", txt)
        self.assertNotIn("ᴄʟᴏɴᴇ ᴏꜰ", txt)
        self.assertNotIn("{", txt)

    def test_bot_name_that_looks_like_a_placeholder_is_not_expanded(self):
        txt = engine.render_about("{owner}", "{version}", "OWNER")
        self.assertIn("ᴍʏ ɴᴀᴍᴇ:</b> {owner}", txt)
        self.assertIn("ᴄʟᴏɴᴇ ᴏꜰ:</b> {version}", txt)

    def test_owner_keeps_settings_button(self):
        rows = self.view(True, uid=500)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0][0][1]["callback_data"].startswith("cs|7|s"))


class InPlaceEditTests(unittest.TestCase):
    """Help / About / Back must edit the message they sit on and never send a new one."""
    class Msg:
        def __init__(self, photo):
            self.photo = photo
            self.chat = SimpleNamespace(id=1)
            self.calls = []
        async def edit_caption(self, text, reply_markup=None):
            self.calls.append("edit_caption")
        async def edit_text(self, text, reply_markup=None, disable_web_page_preview=None):
            self.calls.append("edit_text")
        async def delete(self):
            self.calls.append("delete")

    class Cli:
        def __init__(self):
            self.sent = []
        async def send_photo(self, *a, **k):
            self.sent.append("photo")
        async def send_message(self, *a, **k):
            self.sent.append("text")

    def setUp(self):
        # pyrogram is a MagicMock in these offline tests - give `except MessageNotModified` a real class
        from unittest import mock
        p = mock.patch.object(engine, "MessageNotModified", type("MessageNotModified", (Exception,), {}))
        p.start()
        self.addCleanup(p.stop)

    def go(self, photo, text="hi", pic="http://pic"):
        msg, cli = self.Msg(photo), self.Cli()
        run(engine._show(cli, SimpleNamespace(message=msg), text, None, pic))
        return msg.calls, cli.sent

    def test_photo_start_page_is_edited_via_caption(self):
        self.assertEqual(self.go(photo=object()), (["edit_caption"], []))

    def test_photo_page_stays_a_photo_even_without_pic(self):
        self.assertEqual(self.go(photo=object(), pic=None), (["edit_caption"], []))

    def test_text_start_page_is_edited_as_text(self):
        self.assertEqual(self.go(photo=None), (["edit_text"], []))

    def test_edit_failure_falls_back_to_one_new_message(self):
        class Bad(self.Msg):
            async def edit_caption(self, *a, **k):
                raise RuntimeError("MEDIA_CAPTION_TOO_LONG")
        msg, cli = Bad(object()), self.Cli()
        run(engine._show(cli, SimpleNamespace(message=msg), "x" * 2000, None, "http://pic"))
        self.assertEqual((msg.calls, cli.sent), (["delete"], ["text"]))


class CaptionFitTests(unittest.TestCase):
    def test_help_and_commands_fit_a_photo_caption(self):
        import re as _re
        from clone.cmdlist import commands_text
        for t in (engine.help_text(), commands_text("clone"), commands_text("main")):
            self.assertLessEqual(len(_re.sub(r"<[^>]+>", "", t)), 1024)


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
