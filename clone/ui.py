"""Small-caps typography + formatting helpers shared by every clone/admin panel."""
import re
import time
from datetime import datetime
from typing import Optional

import pytz

IST = pytz.timezone("Asia/Kolkata")

_SC = dict(zip(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ",
))
# html tags, {placeholders} and &entities; are never converted
_SKIP = re.compile(r"(<[^>]+>|\{[^}]*\}|&\w+;)")


def sc(text: str) -> str:
    """Convert text to small caps, leaving HTML tags / placeholders alone."""
    parts = _SKIP.split(text)
    for i in range(0, len(parts), 2):
        parts[i] = "".join(_SC.get(ch.lower(), ch) if ch.isascii() else ch for ch in parts[i])
    return "".join(parts)


def tpl(template: str, **kw) -> str:
    """Small-caps the template, then drop real values in (so names/usernames are never restyled)."""
    out = sc(template)
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tick(on: bool) -> str:
    return "✅" if on else "❌"


def dur(seconds: Optional[int]) -> str:
    """90 -> 1ᴍ 30s style, 0/None -> ᴏғғ."""
    if not seconds:
        return sc("off")
    seconds = int(seconds)
    out = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            out.append(f"{seconds // size}{sc(name)}")
            seconds %= size
    return " ".join(out[:2])


def fmt_ts(ts: Optional[float]) -> str:
    if not ts:
        return sc("never")
    return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y, %I:%M %p IST")


def left(ts: Optional[float], now: Optional[float] = None) -> str:
    if not ts:
        return sc("unlimited")
    secs = int(ts - (now or time.time()))
    if secs <= 0:
        return sc("expired")
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}{sc('d')} {h}{sc('h')}"
    if h:
        return f"{h}{sc('h')} {m}{sc('m')}"
    return f"{max(m, 1)}{sc('m')}"


def parse_duration(text: str) -> Optional[int]:
    """'30m' '12h' '7d' '2w' '1mo' '1y' (also long forms) -> seconds."""
    m = re.fullmatch(r"\s*(\d+)\s*([a-zA-Z]+)\s*", text or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    table = (
        (("m", "min", "mins", "minute", "minutes"), 60),
        (("h", "hr", "hrs", "hour", "hours"), 3600),
        (("d", "day", "days"), 86400),
        (("w", "week", "weeks"), 7 * 86400),
        (("mo", "month", "months"), 30 * 86400),
        (("y", "yr", "year", "years"), 365 * 86400),
    )
    for names, size in table:
        if unit in names:
            return n * size if n > 0 else None
    return None
