"""Small Intercom API adapter. Secrets come only from environment variables."""
import logging
from typing import Any, Dict

import httpx

from app import config

log = logging.getLogger("zeroqueue.intercom")


def configured() -> bool:
    return all((config.INTERCOM_ACCESS_TOKEN, config.INTERCOM_ADMIN_ID,
                config.INTERCOM_TEAM_ID))


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {config.INTERCOM_ACCESS_TOKEN}",
            "Content-Type": "application/json", "Intercom-Version": "2.11"}


def _post(path: str, body: dict) -> Dict[str, Any]:
    response = httpx.post(f"{config.INTERCOM_API_BASE}{path}", headers=_headers(),
                          json=body, timeout=30)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        # Log the failing operation, not request headers or payloads. This gives
        # Render enough detail to diagnose permissions/IDs without exposing tokens.
        response_excerpt = " ".join(response.text.split())[:500]
        log.error("Intercom POST %s failed with HTTP %s: %s",
                  path, response.status_code, response_excerpt or "(empty response)")
        raise
    return response.json()


def create_contact(external_id: str, name: str = "ZeroQueue web visitor") -> str:
    body = {"role": "lead", "external_id": external_id, "name": name}
    try:
        return _post("/contacts", body)["id"]
    except httpx.HTTPStatusError as exc:
        # A repeated session may already exist. Search by its stable external id.
        if exc.response.status_code != 409:
            raise
        result = _post("/contacts/search", {"query": {"field": "external_id",
                                                        "operator": "=",
                                                        "value": external_id}})
        return result["data"][0]["id"]


def create_conversation(contact_id: str, body: str) -> str:
    result = _post("/conversations", {"from": {"type": "contact", "id": contact_id},
                                       "body": body, "message_type": "inapp"})
    return str(result["conversation_id"])


def reply(conversation_id: str, text: str) -> Dict[str, Any]:
    return _post(f"/conversations/{conversation_id}/reply",
                 {"message_type": "comment", "type": "admin",
                  "admin_id": config.INTERCOM_ADMIN_ID, "body": text})


def add_note(conversation_id: str, note: str) -> Dict[str, Any]:
    return _post(f"/conversations/{conversation_id}/reply",
                 {"message_type": "note", "type": "admin",
                  "admin_id": config.INTERCOM_ADMIN_ID, "body": note})


def assign(conversation_id: str) -> Dict[str, Any]:
    return _post(f"/conversations/{conversation_id}/parts",
                 {"message_type": "assignment", "type": "team",
                  "admin_id": config.INTERCOM_ADMIN_ID,
                  "assignee_id": config.INTERCOM_TEAM_ID})
