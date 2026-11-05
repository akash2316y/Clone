"""Text for /cmd and /commands."""
from clone.ui import sc

USER = [
    ("/start", "open the bot / open a file link"),
    ("/getvideo", "get a random video"),
    ("/myplan", "your premium status (main bot)"),
    ("/clone &lt;token&gt;", "create your own bot (main bot)"),
    ("/cmd", "this list"),
]
OWNER = [
    ("/myclone", "dashboard: users, files, links + quick toggles"),
    ("/settings", "force-sub, shortener, captions, auto-delete, branding, db channel"),
    ("/genlink", "send many files, store them in your db channel, get one link"),
    ("/cancel", "cancel a pending input"),
]
ADMIN = [
    ("/addadmin &lt;id&gt;", "add admin (owner only)"),
    ("/deladmin &lt;id&gt;", "remove admin (owner only)"),
    ("/addban &lt;id&gt;", "ban a user system-wide"),
    ("/delban &lt;id&gt;", "unban a user"),
    ("/addpremium &lt;id&gt; &lt;time&gt;", "grant premium, e.g. 30d, 12h, 1mo"),
    ("/rempremium &lt;id&gt;", "revoke premium"),
    ("/predetails &lt;id&gt;", "plan, expiry, perks, clones"),
    ("/ownerpanel", "clone engine ON/OFF, limits, manage clones (owner)"),
    ("/batch /genlink /broadcast /users /status", "existing admin tools"),
]


def _block(title: str, rows, note: str = "") -> str:
    lines = "\n".join(f"<code>{c}</code> — {sc(d)}" for c, d in rows)
    return f"<b>{sc(title)}</b>{(' ' + sc(note)) if note else ''}\n<blockquote>{lines}</blockquote>"


def commands_text(where: str) -> str:
    admin_note = "(main bot)" if where == "clone" else ""
    return "\n\n".join([
        f"<b>📖 {sc('command index')}</b>",
        _block("👤 users", USER),
        _block("🤖 clone owners", OWNER, "(inside your clone)" if where == "clone" else "(inside your clone bot)"),
        _block("🛡 admins", ADMIN, admin_note),
    ])
