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
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


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
    item = payload.get("data", {}).get("item", {})
    conversation_id = str(item.get("id") or "")
    session_id = handoff_store.session_for(conversation_id)
    if not session_id:
        return  # not a browser-session conversation owned by this app
    message = item.get("conversation_message") or item.get("conversation_parts", {}).get("conversation_parts", [{}])[-1]
    author = message.get("author") or {}
    body = clean_body(message.get("body", ""))
    if not body:
        return
    author_type = author.get("type", "")
    if author_type == "admin":
        handoff_store.save_human_reply(session_id, str(message.get("id") or payload.get("id") or ""), body)
        return
    if author_type not in ("user", "lead", "contact"):
        return
    result = pipeline.run_pipeline(session_id, body)
    if result["status"] in ("answered", "clarifying"):
        intercom.reply(conversation_id, result["answer"])
