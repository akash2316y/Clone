"""URL shortener call for clones, with SSRF protection (domains are chosen by clone owners)."""
import asyncio
import ipaddress
import logging
import re
import socket
from typing import Optional

import aiohttp

_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def clean_domain(raw: str) -> str:
    d = (raw or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0].split(":")[0]
    return d


async def is_public_domain(domain: str) -> bool:
    """Syntactically valid hostname that resolves only to public IPs."""
    if not _DOMAIN.match(domain):
        return False
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
    except Exception:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False
    return bool(infos)


async def shorten(domain: str, api_key: str, url: str) -> Optional[str]:
    """Standard `https://<domain>/api?api=KEY&url=URL` shortener. None on any failure."""
    if not (domain and api_key and await is_public_domain(domain)):
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(f"https://{domain}/api", params={"api": api_key, "url": url},
                             allow_redirects=False) as r:
                data = await r.json(content_type=None)
        link = data.get("shortenedUrl") or data.get("shortened_url") or data.get("short_url")
        if link and str(link).startswith(("http://", "https://")):
            return link
    except Exception as e:
        logging.warning(f"shortener {domain} failed: {e}")
    return None
