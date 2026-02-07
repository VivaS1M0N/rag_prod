import re
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"

def _headers(api_token: str) -> Dict[str, str]:
    # ClickUp uses the token in the Authorization header (either personal token or OAuth token).
    return {
        "Authorization": api_token,
        "Accept": "application/json",
    }

def extract_list_id(value: str) -> Optional[str]:
    """Extract a ClickUp list_id from a URL or return the value if it looks like an ID."""
    if not value:
        return None
    v = value.strip()

    # Common list url patterns include "/li/<list_id>" or "list/<list_id>".
    m = re.search(r"/li/(\d+)", v)
    if m:
        return m.group(1)

    m = re.search(r"list/(\d+)", v)
    if m:
        return m.group(1)

    # If it's only digits, assume it's the list_id
    if re.fullmatch(r"\d+", v):
        return v

    return None

def get_list_member_emails(api_token: str, list_id: str, timeout_s: int = 20) -> Set[str]:
    """Return a set of member emails that have *explicit* access to a list.

    This uses: GET /list/{list_id}/member
    """
    url = f"{CLICKUP_API_BASE}/list/{list_id}/member"
    resp = requests.get(url, headers=_headers(api_token), timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json()

    emails: Set[str] = set()

    # Response shape (seen in official Postman examples) often is:
    # { "members": [ { "id": 123, "username": "...", "email": "...", ... }, ... ] }
    for m in data.get("members", []) or []:
        if isinstance(m, dict):
            email = m.get("email") or (m.get("user") or {}).get("email")
            if isinstance(email, str) and "@" in email:
                emails.add(email.strip().lower())

    return emails

def get_tasks_from_list(
    api_token: str,
    list_id: str,
    include_closed: bool = True,
    include_markdown_description: bool = True,
    page: int = 0,
    timeout_s: int = 30,
) -> Dict[str, Any]:
    """Fetch tasks from a ClickUp list."""
    url = f"{CLICKUP_API_BASE}/list/{list_id}/task"
    params = {
        "include_closed": str(include_closed).lower(),
        "include_markdown_description": str(include_markdown_description).lower(),
        "page": page,
    }
    resp = requests.get(url, headers=_headers(api_token), params=params, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()

def update_task(
    api_token: str,
    task_id: str,
    payload: Dict[str, Any],
    timeout_s: int = 20,
) -> Dict[str, Any]:
    """Update a ClickUp task using PUT /task/{task_id}."""
    url = f"{CLICKUP_API_BASE}/task/{task_id}"
    resp = requests.put(url, headers={**_headers(api_token), "Content-Type": "application/json"}, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()
