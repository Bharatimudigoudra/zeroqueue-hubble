"""Agent console service: review AI answers and reply through Intercom.

Read-only on the AI pipeline: the console can ask for a suggested answer,
but only the agent's explicit approve action sends anything to the customer.
The AI backend (intent, retrieval, KB, decision engine) stays independent -
the console is another channel on top of the same services, not a rewrite.
"""
import html
import logging
from typing import List, Optional

from app.adapters import intercom
from app.services import (answer_service, confidence, handoff_store,
                          intercom_handoff, moss_service, pipeline)

log = logging.getLogger("zeroqueue.agent_console")

# Messages that mark an action rather than a real customer question.
_PLACEHOLDER_CUSTOMER_TEXTS = {"(handoff button)"}


def list_conversations() -> dict:
    return {"conversations": pipeline.handoff_sessions(),
            "intercom_configured": intercom.configured()}


def _intercom_snapshot(session_id: str) -> Optional[dict]:
    """Live Intercom state for the linked conversation, when reachable."""
    if not intercom.configured():
        return None
    conversation_id = handoff_store.conversation_for(session_id)
    if not conversation_id:
        return None
    try:
        result = intercom.get_conversation(conversation_id)
        return {"conversation_id": conversation_id,
                "state": result.get("state"),
                "open": result.get("open")}
    except Exception as exc:
        log.warning("Intercom conversation fetch failed: %s", type(exc).__name__)
        return {"conversation_id": conversation_id,
                "state": None, "open": None,
                "error": type(exc).__name__}


def conversation_detail(session_id: str) -> Optional[dict]:
    transcript = pipeline.transcript_for(session_id)
    if transcript is None:
        return None
    summary = next((s for s in pipeline.handoff_sessions()
                    if s["session_id"] == session_id), None)
    return {
        "session_id": session_id,
        "messages": transcript,
        "handoff_reason": (summary or {}).get("handoff_reason"),
        "confidence_band": (summary or {}).get("confidence_band"),
        "intercom_linked": bool(handoff_store.conversation_for(session_id)),
        "intercom_configured": intercom.configured(),
        "intercom_conversation": _intercom_snapshot(session_id),
        "suggestion": suggest_answer(session_id, transcript),
    }


def suggest_answer(session_id: str,
                   transcript: Optional[List[dict]] = None) -> dict:
    """The AI's draft answer for the latest customer message. Never sends."""
    if transcript is None:
        transcript = pipeline.transcript_for(session_id) or []
    latest = next((m["text"] for m in reversed(transcript)
                   if m["role"] == "customer" and m["text"].strip()
                   and m["text"] not in _PLACEHOLDER_CUSTOMER_TEXTS), "")
    if not latest:
        return {"answer": "", "citations": [], "confidence_band": None}
    passages = moss_service.search(latest)["passages"]
    if not passages:
        return {"answer": "", "citations": [],
                "confidence_band": confidence.band(passages)}
    answer, citations = answer_service.build_answer(latest, passages)
    return {"answer": answer, "citations": citations,
            "confidence_band": confidence.band(passages)}


def _ensure_conversation(session_id: str, transcript: list) -> Optional[str]:
    """Reuse the linked Intercom conversation, or run the normal handoff."""
    conversation_id = handoff_store.conversation_for(session_id)
    if conversation_id:
        return conversation_id
    latest = next((m["text"] for m in reversed(transcript)
                   if m["role"] == "customer"), "(no customer message)")
    result = intercom_handoff.send(session_id, latest, "agent_console",
                                   "unknown", [], transcript)
    return result.get("conversation_id") if result.get("confirmed") else None


def approve_reply(session_id: str, body: str) -> dict:
    """Send the agent-approved reply to the customer through Intercom."""
    transcript = pipeline.transcript_for(session_id)
    if transcript is None:
        return {"sent": False, "reason": "unknown_session"}
    if not intercom.configured():
        return {"sent": False, "reason": "intercom_not_configured"}
    try:
        conversation_id = _ensure_conversation(session_id, transcript)
        if not conversation_id:
            return {"sent": False, "reason": "conversation_create_failed"}
        result = intercom.reply(conversation_id,
                                html.escape(body).replace("\n", "<br>"))
        # Intercom sends the approved reply back through its webhook. That is
        # the one place where human replies are saved for the customer chat.
        # Saving here as well creates a second row because Intercom's reply
        # response and webhook can use different IDs for the same message.
        return {"sent": True, "conversation_id": conversation_id,
                "part_id": str(result.get("id") or "")}
    except Exception as exc:
        log.exception("Agent console reply failed")
        return {"sent": False, "reason": type(exc).__name__}


def add_internal_note(session_id: str, body: str) -> dict:
    """Post an internal Intercom note. Internal only: never shown to the
    customer, so it is not stored in human_replies."""
    transcript = pipeline.transcript_for(session_id)
    if transcript is None:
        return {"sent": False, "reason": "unknown_session"}
    if not intercom.configured():
        return {"sent": False, "reason": "intercom_not_configured"}
    try:
        conversation_id = _ensure_conversation(session_id, transcript)
        if not conversation_id:
            return {"sent": False, "reason": "conversation_create_failed"}
        intercom.add_note(conversation_id,
                          html.escape(body).replace("\n", "<br>"))
        return {"sent": True, "conversation_id": conversation_id}
    except Exception as exc:
        log.exception("Agent console note failed")
        return {"sent": False, "reason": type(exc).__name__}