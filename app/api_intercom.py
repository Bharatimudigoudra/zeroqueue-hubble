"""Intercom webhook: verify, dedupe, ingest customer/admin messages."""
import hashlib
import hmac
import html
import json
import re

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app import config
from app.adapters import intercom
from app.services import handoff_store, pipeline

router = APIRouter()


def verify_signature(raw: bytes, header: str) -> bool:
    digest = hmac.new(config.INTERCOM_WEBHOOK_SECRET.encode(), raw,
                      hashlib.sha1).hexdigest()
    return hmac.compare_digest(f"sha1={digest}", header or "")


def clean_body(value: str) -> str:
    """Turn Intercom's safe HTML into readable plain text."""
    text = value or ""
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*li\b[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*/\s*li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*/\s*(?:p|div)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*(?:p|div)\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))

    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


@router.post("/api/webhooks/intercom")
async def receive(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    if not config.INTERCOM_WEBHOOK_SECRET:
        return JSONResponse({"status": "webhook_not_configured"}, status_code=503)
    if not verify_signature(raw, request.headers.get("X-Hub-Signature", "")):
        return JSONResponse({"status": "invalid_signature"}, status_code=401)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"status": "bad_json"}, status_code=400)
    event_id = str(payload.get("id") or "")
    if not handoff_store.first_event(event_id):
        return {"status": "duplicate_ignored"}
    background_tasks.add_task(process_event, payload)
    return {"status": "accepted"}


def process_event(payload: dict):
    topic = str(payload.get("topic") or "")
    # Only reply topics may surface in the browser. Assignment, notes, closes,
    # and other conversation events can contain admin-authored parts too.
    if topic not in {"conversation.admin.replied", "conversation.operator.replied"}:
        return
    item = payload.get("data", {}).get("item", {})
    conversation_id = str(item.get("id") or "")
    session_id = handoff_store.session_for(conversation_id)
    if not session_id:
        return  # not a browser-session conversation owned by this app
    # The new reply is the LAST conversation part. conversation_message is
    # always the message that STARTED the conversation, so reading it here
    # would mistake every admin reply for the customer's original question
    # and the reply would never reach the customer chat.
    parts = (item.get("conversation_parts") or {}).get("conversation_parts") or []
    message = parts[-1] if parts else (item.get("conversation_message") or {})
    author = message.get("author") or {}
    body = clean_body(message.get("body", ""))
    if not body:
        return
    author_type = str(author.get("type") or "")
    is_admin_reply = topic == "conversation.admin.replied" and author_type == "admin"
    # Intercom workflows, Fin, and Operator emit operator.replied. Depending on
    # the automation, their author can be represented as bot, admin, or team;
    # the topic is the stable signal that this is an outbound reply.
    is_operator_reply = (topic == "conversation.operator.replied"
                         and author_type in {"bot", "admin", "team"})
    if is_admin_reply or is_operator_reply:
        handoff_store.save_human_reply(
            session_id, str(message.get("id") or payload.get("id") or ""), body)
        return
    if author_type not in ("user", "lead", "contact"):
        return
    result = pipeline.run_pipeline(session_id, body)
    if result["status"] in ("answered", "clarifying"):
        intercom.reply(conversation_id, result["answer"])
