import os
import time
from typing import Optional, Set, Dict, Any

import requests

from clickup_client import get_list_member_emails

def _csv_env(name: str) -> Set[str]:
    raw = os.getenv(name, "")
    return {x.strip().lower() for x in raw.split(",") if x.strip()}

ALLOWED_EMAIL_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "vivalandscapedesign.com").strip().lower()
ADMIN_EMAILS = _csv_env("ADMIN_EMAILS")

AUTH_REQUIRE_CLICKUP = os.getenv("AUTH_REQUIRE_CLICKUP", "false").strip().lower() == "true"
CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "").strip()
CLICKUP_AUTH_LIST_ID = os.getenv("CLICKUP_AUTH_LIST_ID", "").strip()
CLICKUP_CACHE_TTL_S = int(os.getenv("CLICKUP_CACHE_TTL_S", "300"))

_clickup_cache: Dict[str, Any] = {"ts": 0.0, "emails": set()}

def normalize_email(email: str) -> str:
    return (email or "").strip().lower()

def is_domain_allowed(email: str) -> bool:
    email = normalize_email(email)
    if not email or "@" not in email:
        return False
    if not ALLOWED_EMAIL_DOMAIN:
        return True
    return email.endswith("@" + ALLOWED_EMAIL_DOMAIN)

def is_admin(email: str) -> bool:
    email = normalize_email(email)
    return email in ADMIN_EMAILS

def _get_clickup_allowed_emails() -> Optional[Set[str]]:
    if not (AUTH_REQUIRE_CLICKUP and CLICKUP_API_TOKEN and CLICKUP_AUTH_LIST_ID):
        return None

    now = time.time()
    cached_ts = float(_clickup_cache.get("ts", 0.0))
    if (now - cached_ts) < CLICKUP_CACHE_TTL_S and _clickup_cache.get("emails"):
        return set(_clickup_cache["emails"])

    emails = get_list_member_emails(
        api_token=CLICKUP_API_TOKEN,
        list_id=CLICKUP_AUTH_LIST_ID,
        timeout_s=20,
    )
    _clickup_cache["ts"] = now
    _clickup_cache["emails"] = set(emails or [])
    return set(_clickup_cache["emails"])

def is_clickup_allowed(email: str) -> bool:
    allowed = _get_clickup_allowed_emails()
    if allowed is None:
        return True
    return normalize_email(email) in allowed

def is_user_allowed(email: str) -> bool:
    if not is_domain_allowed(email):
        return False
    if not is_clickup_allowed(email):
        return False
    return True
