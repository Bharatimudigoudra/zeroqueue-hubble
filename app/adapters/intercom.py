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


def _contact_identity(contact: Dict[str, Any]) -> Dict[str, str]:
    """Keep the Intercom contact id together with its API role."""
    contact_id = str(contact["id"])
    role = str(contact.get("role") or "lead")
    if role not in {"lead", "user"}:
        raise ValueError(f"Unsupported Intercom contact role: {role}")
    return {"id": contact_id, "role": role}


def create_contact(external_id: str,
                   name: str = "ZeroQueue web visitor") -> Dict[str, str]:
    body = {"role": "lead", "external_id": external_id, "name": name}
    try:
        return _contact_identity(_post("/contacts", body))
    except httpx.HTTPStatusError as exc:
        # A repeated session may already exist. Search by its stable external id.
        if exc.response.status_code != 409:
            raise
        result = _post("/contacts/search", {"query": {"field": "external_id",
                                                        "operator": "=",
                                                        "value": external_id}})
        return _contact_identity(result["data"][0])


def create_conversation(contact: Dict[str, str], body: str) -> str:
    # Intercom's create-conversation endpoint requires the contact's actual
    # role (lead or user), not the generic Contact model type.
    result = _post("/conversations", {
        "from": {"type": contact["role"], "id": contact["id"]},
        "body": body,
        "message_type": "inapp",
    })
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
