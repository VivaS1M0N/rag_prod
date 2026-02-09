import re
from typing import Any, Dict, Optional, Set

import requests

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"


class ClickUpAPIError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text or ""


def _headers(api_token: str) -> Dict[str, str]:
    # ClickUp uses the token in the Authorization header (either personal token or OAuth token).
    return {
        "Authorization": api_token,
        "Accept": "application/json",
    }


def _raise_for_status(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        # Include a small snippet to make debugging easier without leaking too much.
        snippet = (resp.text or "")[:800]
        raise ClickUpAPIError(
            message=f"ClickUp API error {resp.status_code}: {snippet}",
            status_code=resp.status_code,
            response_text=resp.text or "",
        ) from e


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

    Uses: GET /list/{list_id}/member
    """
    url = f"{CLICKUP_API_BASE}/list/{list_id}/member"
    try:
        resp = requests.get(url, headers=_headers(api_token), timeout=timeout_s)
    except requests.RequestException as e:
        raise ClickUpAPIError(f"ClickUp request failed: {e}") from e

    _raise_for_status(resp)
    data = resp.json()

    emails: Set[str] = set()

    # Response often:
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
    include_markdown_description: bool = False,
    page: int = 0,
    timeout_s: int = 30,
) -> Dict[str, Any]:
    """Fetch tasks from a ClickUp list.

    Notes:
    - ClickUp paginates results. You can request additional pages by incrementing `page`.
    - To keep payload smaller, we default `include_markdown_description=False`.
    """
    url = f"{CLICKUP_API_BASE}/list/{list_id}/task"
    params = {
        "include_closed": str(include_closed).lower(),
        "include_markdown_description": str(include_markdown_description).lower(),
        "page": page,
    }
    try:
        resp = requests.get(url, headers=_headers(api_token), params=params, timeout=timeout_s)
    except requests.RequestException as e:
        raise ClickUpAPIError(f"ClickUp request failed: {e}") from e

    _raise_for_status(resp)
    return resp.json()


def update_task(
    api_token: str,
    task_id: str,
    payload: Dict[str, Any],
    timeout_s: int = 20,
) -> Dict[str, Any]:
    """Update a ClickUp task using PUT /task/{task_id}."""
    url = f"{CLICKUP_API_BASE}/task/{task_id}"
    headers = {**_headers(api_token), "Content-Type": "application/json"}
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=timeout_s)
    except requests.RequestException as e:
        raise ClickUpAPIError(f"ClickUp request failed: {e}") from e

    _raise_for_status(resp)
    return resp.json()
