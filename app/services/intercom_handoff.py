"""Create one real Intercom conversation for a browser session handoff."""
import html
import logging

from app.adapters import intercom
from app.services import answer_service, handoff_store

log = logging.getLogger("zeroqueue.handoff")


def send(session_id: str, customer_text: str, reason: str, band: str,
         passages: list, transcript: list) -> dict:
    if not intercom.configured():
        return {"confirmed": False, "reason": "intercom_not_configured"}
    try:
        conversation_id = handoff_store.conversation_for(session_id)
        transcript_text = "\n".join(
            f"{item['role'].title()}: {item['text']}" for item in transcript[-12:])
        if not conversation_id:
            contact_id = intercom.create_contact(f"zeroqueue-{session_id}")
            opening = ("ZeroQueue web handoff\n\n" + transcript_text).strip()
            conversation_id = intercom.create_conversation(contact_id, opening)
            handoff_store.link(session_id, conversation_id)
        citations = answer_service.make_citations(passages or [])
        source_text = "\n".join(f"- {c['label']}: {c.get('url') or 'no URL'}"
                                for c in citations) or "- No reliable source"
        note = (f"Handoff reason: {reason}\nConfidence: {band}\n"
                f"Latest customer message: {customer_text}\n\n"
                f"Sources checked:\n{source_text}")
        intercom.add_note(conversation_id, html.escape(note).replace("\n", "<br>"))
        intercom.assign(conversation_id)
        return {"confirmed": True, "conversation_id": conversation_id}
    except Exception as exc:
        log.exception("Intercom handoff failed")
        return {"confirmed": False, "reason": f"{type(exc).__name__}"}
