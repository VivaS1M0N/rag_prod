import os
import time
import logging
from typing import Optional, Set, Dict, Any

from fastapi import Header, HTTPException

from clickup_client import get_list_member_emails

log = logging.getLogger("viva_rag.authz")


def _csv_env(name: str) -> Set[str]:
    raw = os.getenv(name, "")
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


# --- Core policy
ALLOWED_EMAIL_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "vivalandscapedesign.com").strip().lower()
ADMIN_EMAILS = _csv_env("ADMIN_EMAILS")

# --- Optional: ClickUp-based allowlist (recommended when embedding in ClickUp)
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
    """Returns a set of allowed emails based on a ClickUp List membership.

    If ClickUp gating is disabled or not configured, returns None.
    Uses an in-memory TTL cache to avoid calling ClickUp on every request.
    """
    if not (AUTH_REQUIRE_CLICKUP and CLICKUP_API_TOKEN and CLICKUP_AUTH_LIST_ID):
        return None

    now = time.time()
    cached_ts = float(_clickup_cache.get("ts", 0.0))
    if (now - cached_ts) < CLICKUP_CACHE_TTL_S and _clickup_cache.get("emails"):
        return set(_clickup_cache["emails"])

    try:
        emails = get_list_member_emails(
            api_token=CLICKUP_API_TOKEN,
            list_id=CLICKUP_AUTH_LIST_ID,
            timeout_s=20,
        )
    except Exception as e:
        # Fail-closed for security: if we cannot validate membership, deny access.
        log.exception("ClickUp allowlist fetch failed")
        raise HTTPException(
            status_code=503,
            detail=(
                "El servicio de autorización (ClickUp) no está disponible. "
                "Intenta de nuevo en unos minutos o contacta al admin."
            ),
        ) from e

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


def get_user_email(
    x_forwarded_email: Optional[str] = Header(default=None),
    x_auth_request_email: Optional[str] = Header(default=None),
) -> str:
    """FastAPI dependency to read the authenticated user email.

    Nginx injects `X-Forwarded-Email` from oauth2-proxy:
      proxy_set_header X-Forwarded-Email $email;

    oauth2-proxy may also expose `X-Auth-Request-Email` depending on config.
    """
    email = normalize_email(x_forwarded_email or x_auth_request_email or "")
    if not email:
        raise HTTPException(
            status_code=401,
            detail="No se detectó usuario autenticado.",
        )

    if not is_user_allowed(email):
        if not is_domain_allowed(email):
            raise HTTPException(
                status_code=403,
                detail=f"Solo se permite el dominio @{ALLOWED_EMAIL_DOMAIN}.",
            )
        if AUTH_REQUIRE_CLICKUP:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Tu correo no aparece en la lista autorizada de ClickUp. "
                    "Pídele a un admin que te agregue a la lista de acceso."
                ),
            )
        raise HTTPException(status_code=403, detail="Usuario no autorizado.")

    return email
