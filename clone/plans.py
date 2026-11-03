"""Tier rules and clone validity maths. Pure functions, no I/O."""
import time
from typing import Optional, Tuple

from config import FREE_FSUB_LIMIT, PREMIUM_FSUB_LIMIT

DAY = 86400


def compute_validity(created_at: float, free_days: int, premium_expiry: Optional[float],
                     now: Optional[float] = None) -> Tuple[str, Optional[float], bool]:
    """
    Returns (plan, valid_until, expired).

    plan         'premium' while the owner's premium is active, else 'free'
    valid_until  None = never expires. Free clones live `free_days` after creation
                 (0 = unlimited). Premium can only extend that window, never shorten it.
    """
    now = now or time.time()
    plan = "premium" if premium_expiry and premium_expiry > now else "free"
    if free_days <= 0:
        return plan, None, False
    valid_until = created_at + free_days * DAY
    if premium_expiry:
        valid_until = max(valid_until, premium_expiry)
    return plan, valid_until, now > valid_until


def limits(plan: str) -> dict:
    premium = plan == "premium"
    return {
        "fsub_limit": PREMIUM_FSUB_LIMIT if premium else FREE_FSUB_LIMIT,
        "custom_shortener": premium,
        "custom_caption": premium,
        "custom_start": premium,
        "branding_optional": premium,
    }


PERKS_PREMIUM = [
    "Custom /start message & image",
    "Custom file captions",
    "Your own URL shortener (earn from ads)",
    "Up to {n} force-sub channels",
    "Remove bot branding",
    "No ads/verification on any clone",
]
PERKS_FREE = [
    "{n} force-sub channel",
    "Auto-delete, protect content, user logs",
    "Bot branding footer is mandatory",
]
