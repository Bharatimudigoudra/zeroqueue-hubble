"""Pipeline: retrieve -> confidence -> answer or hand off. Channel-neutral.

Session state lives in memory (POC level - a restart wipes it, which is
fine for a demo and keeps the project dependency-light). The shape of
every public response matches the ZeroQueue backend exactly, so the
existing web page works against this service unchanged.
"""
import re
import time
from typing import Dict, List, Optional

from app.services import (answer_service, clarification, confidence,
                            escalation, handoff_store, intercom_handoff,
                            moss_service)


# Generic field labels a voucher template prints ABOVE the actual error
# value ("ERROR MESSAGE", "STATUS", ...). They match the error regex but
# carry no information, so they must never be quoted as the error.
_ERROR_LABELS = {"error", "errormessage", "errorcode", "errordescription",
                 "status", "message", "reason", "details"}
# Words that mark a real error statement, not a label.
_STRONG_ERROR = re.compile(
    r"invalid|expired|already used|declined|rejected|not activated|"
    r"not applicable|limit exceeded|failed|failure", re.IGNORECASE)


def _is_label_line(line: str) -> bool:
    return re.sub(r"[^a-z]", "", line.casefold()) in _ERROR_LABELS


def extract_error_line(text: str) -> str:
    """Pick the line that states the actual error, skipping field labels."""
    lines = [ln.strip().strip(".").strip()
             for ln in (text or "").splitlines() if ln.strip()]
    strong = [ln for ln in lines
              if _STRONG_ERROR.search(ln) and not _is_label_line(ln)]
    if strong:
        return strong[0]
    weak = [ln for ln in lines
            if clarification.has_error(ln) and not _is_label_line(ln)]
    return weak[0] if weak else ""

# session_id -> {"status": "open" | "handoff", "trace": {...}}
_SESSIONS: Dict[str, dict] = {}


def _session(session_id: str) -> dict:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = {
            "status": "open",
            "trace": {"state": "empty", "source_count": 0, "sources": []},
            "pending_issue": "",
            "pending_brand": "",
            "messages": [],
        }
    return _SESSIONS[session_id]


def _record_trace(sess: dict, retrieval_ms: float, total_start: float,
                  band: str, state: str, passages: list,
                  handoff_reason: Optional[str] = None) -> None:
    sess["trace"] = {
        "state": state,                       # answered | escalated | error
        "retrieval_ms": retrieval_ms,
        "total_ms": round((time.perf_counter() - total_start) * 1000, 1),
        "source_count": len(passages or []),
        "sources": answer_service.make_citations(passages or []),
        "confidence_band": band,
        "handoff_reason": handoff_reason,
    }


def run_pipeline(session_id: str, message: str, attachment_text: str = "",
                  attachment: Optional[dict] = None) -> dict:
    total_start = time.perf_counter()
    sess = _session(session_id)

    incoming = (message or "").strip()

    # If a human already owns this conversation, forward the new message to
    # that same support conversation instead of asking the AI to answer it.
    if sess["status"] == "handoff":
        forwarded_text = incoming
        if attachment_text.strip():
            forwarded_text = (f"{forwarded_text}\n\nAttachment text (OCR):\n"
                              f"{attachment_text.strip()}").strip()
        if forwarded_text or attachment:
            entry = {"role": "customer", "text": incoming}
            if attachment:
                entry["attachment"] = attachment
            sess["messages"].append(entry)
            if not forwarded_text:
                forwarded_text = (f"(customer sent an attachment: "
                                  f"{attachment.get('name', 'file')})")
            handoff = intercom_handoff.send(
                session_id, forwarded_text,
                sess["trace"].get("handoff_reason") or "human_follow_up",
                sess["trace"].get("confidence_band") or "unknown", [],
                sess["messages"],
            )
        else:
            handoff = {"confirmed": False}
        # The pause notice is shown once, when the handoff begins. Follow-up
        # customer messages while paused are still stored and forwarded to the
        # human, but no banner is repeated in the customer chat.
        return {"answer": "", "status": "handoff",
                "citations": [], "trace": sess["trace"],
                "handoff_confirmed": handoff["confirmed"]}

    # Store the current customer message before clarification or retrieval.
    # A handoff is decided later from an explicit human request or weak evidence.
    if incoming or attachment:
        entry = {"role": "customer", "text": incoming}
        if attachment:
            entry["attachment"] = attachment
        sess["messages"].append(entry)

    # Ask for missing details without repeating facts already supplied. OCR is
    # part of the customer's current context, so it must inform clarification
    # before this branch can return early without retrieval.
    current_context = incoming
    if attachment_text.strip():
        current_context = (f"{current_context} Attachment text (OCR): "
                           f"{attachment_text.strip()}").strip()
    following_up = bool(sess.get("pending_issue"))
    issue_text = f"{sess.get('pending_issue', '')} {current_context}".strip()
    # A brand sticks to the conversation once detected. Generic follow-up
    # words ("what about the refund?") must not drop the scoping - but a
    # brand explicitly typed in the CURRENT message always re-pins it.
    detected_brand = (clarification.find_brand(
        current_context, moss_service.brand_names())
        or sess.get("pending_brand")
        or clarification.find_brand(
            sess.get("pending_issue", ""), moss_service.brand_names()))
    if detected_brand:
        sess["brand"] = detected_brand
    brand = detected_brand or sess.get("brand", "")
    error_supplied = (clarification.has_error(current_context) if following_up
                      else clarification.has_error(issue_text))
    needs_clarification = (clarification.has_issue(issue_text)
                           and (not brand or not error_supplied))
    if needs_clarification:
        sess["pending_issue"] = issue_text
        sess["pending_brand"] = brand or ""
        sess["trace"] = {
            "state": "clarifying", "retrieval_ms": None, "total_ms": round(
                (time.perf_counter() - total_start) * 1000, 1),
            "source_count": 0, "sources": [], "confidence_band": None,
            "handoff_reason": None,
        }
        clarifier = clarification.question(brand, need_error=not error_supplied)
        sess["messages"].append({"role": "assistant", "text": clarifier,
                                  "kind": "clarifying"})
        return {"answer": clarifier, "status": "clarifying", "citations": [],
                "trace": sess["trace"]}
    if following_up:
        canonical_brand = brand or ""
        message = f"{sess['pending_issue']} {canonical_brand} {incoming}".strip()
        sess["pending_issue"] = ""
        sess["pending_brand"] = ""

    # Merge the typed message with whatever the attachment told us.
    query = (message or "").strip()
    if attachment_text.strip():
        query = f"{query}\n\nAttachment text (OCR):\n{attachment_text.strip()}".strip()
    if not query:
        query = "(customer sent an attachment with no readable text)"

    # 1. Retrieve (local index today, real Moss tomorrow - same signature).
    # A confirmed brand narrows the local fallback before keyword scoring.
    # This also covers brands read from attachment OCR above.
    # Wider candidate pool (8): the relevance gate below filters these down,
    # so retrieval must not cut a relevant chunk before the gate can see it.
    retrieval = moss_service.search(query, top_k=8, brand=brand or "")
    scored_passages = retrieval["passages"]
    distinctive = answer_service.distinctive_terms(query, brand)
    if distinctive and not error_supplied:
        scored_passages = answer_service.filter_relevant(
            scored_passages, distinctive)
    passages = list(scored_passages)

    # A reported error (typed or read from an attachment) needs the brand's
    # rules next to the how-to chunks. Keyword scoring cannot find them -
    # the KB never names the customer's exact error - so pull the policy
    # chunks deterministically and merge them after the scored passages.
    # Two deterministic inclusions keyword scoring cannot be trusted with:
    # - a reported error needs the brand's rules (the KB never names the
    #   customer's exact error, so scoring cannot find them);
    # - a "how do I redeem" question must surface the brand's redeem chunks
    #   (FAQ section names repeat the brand and outscore them).
    # Order is deliberate: redeem steps first, then the rules to check, then
    # whatever the scorer found.
    seen_ids = {p.id for p in passages}
    front = []
    if brand and re.search(r"\bredeem\b", current_context, re.IGNORECASE):
        for chunk in moss_service.brand_policy_chunks(
                brand, ("redeem-app", "redeem-website", "redeem-online",
                        "redeem-offline")):
            if chunk.id not in seen_ids:
                front.append(chunk)
                seen_ids.add(chunk.id)

    error_line = ""
    policy_chunks = []
    if error_supplied and brand:
        error_line = extract_error_line(current_context)
        for chunk in moss_service.brand_policy_chunks(
                brand, ("restrictions", "terms-p1", "validity")):
            if chunk.id not in seen_ids:
                policy_chunks.append(chunk)
                seen_ids.add(chunk.id)

    # "How long is it valid" must surface the brand's validity chunk - its
    # keyword score is weak ("valid" vs "validity"), so terms paragraphs
    # would otherwise bury it.
    if brand and re.search(r"\b(valid|validity|expire|expiry|expired|expires|"
                           r"duration)\b|\bhow long\b",
                           current_context, re.IGNORECASE):
        for chunk in moss_service.brand_policy_chunks(brand, ("validity",)):
            if chunk.id not in seen_ids:
                front.append(chunk)
                seen_ids.add(chunk.id)

    passages = (front + policy_chunks + passages)[:5]

    # 2. Evidence-based confidence + escalation decision (never the LLM's).
    # Confidence is judged on the SCORED passages only: the deterministic
    # redeem/policy chunks carry no retrieval score, and letting them set
    # the band would either fake confidence or fake weakness.
    band = confidence.band(scored_passages)
    # Deterministic inclusions (redeem/validity/policy) and relevance-gated
    # survivors are real evidence; exact-token scoring must not push them to
    # a false low-confidence handoff.
    if band == "low" and (front or policy_chunks
                          or (distinctive and scored_passages)):
        band = "medium"
    reason = escalation.decide(message or "", band)
    if reason:
        sess["status"] = "handoff"
        handoff = intercom_handoff.send(session_id, message or query, reason,
                                         band, passages, sess["messages"])
        if handoff["confirmed"]:
            ack = ("A human agent has been notified and will reply right here "
                   "in this chat shortly. The AI is paused while you wait.")
        else:
            ack = ("I have paused the AI and marked this conversation for human "
                   "review. The live support inbox is not connected right now.")
        if reason != "customer_requested_human":
            ack = ("I do not have a reliable answer in the support knowledge "
                   "base, so I will not guess. " + ack)
        sess["messages"].append({"role": "assistant", "text": ack, "kind": "ack"})
        _record_trace(sess, retrieval["retrieval_ms"], total_start, band,
                      "escalated", passages, reason)
        return {"answer": ack, "status": "handoff", "citations": [],
                "trace": sess["trace"], "handoff_confirmed": handoff["confirmed"]}

    # 3. Grounded answer with citations.
    answer, citations = answer_service.build_answer(query, passages,
                                                    error_line=error_line)
    sess["messages"].append({"role": "assistant", "text": answer,
                             "kind": "answer"})
    _record_trace(sess, retrieval["retrieval_ms"], total_start, band,
                  "answered", passages)
    return {"answer": answer, "status": "answered", "citations": citations,
            "trace": sess["trace"]}


def request_handoff(session_id: str) -> dict:
    sess = _session(session_id)
    sess["status"] = "handoff"
    # Mark the trace so the UI's trace panel shows the escalation, not a
    # stale "answered" from an earlier message.
    sess["trace"] = {**sess["trace"], "state": "escalated",
                     "handoff_reason": "customer_requested_human"}
    handoff = intercom_handoff.send(session_id, "(handoff button)",
                                     "customer_requested_human", "unknown", [],
                                     sess.get("messages", []))
    answer = (("A human agent has been notified and will reply right here "
               "in this chat shortly. The AI is paused while you wait.")
              if handoff["confirmed"] else
              ("I have paused the AI and marked this conversation for human "
               "review. The live support inbox is not connected right now."))
    sess["messages"].append({"role": "assistant", "text": answer,
                             "kind": "ack"})
    return {"answer": answer, "status": "handoff", "citations": [],
            "trace": sess["trace"], "handoff_confirmed": handoff["confirmed"]}


def is_handoff(session_id: str) -> bool:
    """True only while this running app has handed the chat to a human."""
    sess = _SESSIONS.get(session_id)
    return bool(sess and sess["status"] == "handoff")


def trace_for(session_id: str) -> dict:
    sess = _SESSIONS.get(session_id)
    return sess["trace"] if sess else {"state": "empty", "source_count": 0,
                                       "sources": []}


def reset_all() -> None:
    _SESSIONS.clear()


def handoff_sessions() -> List[dict]:
    """Summaries of every conversation a human now owns (agent console)."""
    summaries = []
    for session_id, sess in _SESSIONS.items():
        if sess["status"] != "handoff":
            continue
        customer_texts = [m["text"] for m in sess["messages"]
                          if m["role"] == "customer"]
        summaries.append({
            "session_id": session_id,
            "last_customer_message": customer_texts[-1] if customer_texts else "",
            "message_count": len(sess["messages"]),
            "handoff_reason": sess["trace"].get("handoff_reason"),
            "confidence_band": sess["trace"].get("confidence_band"),
        })
    return summaries


def append_human_message(session_id: str, body: str) -> None:
    """Record a human-support reply in the live transcript so a page
    refresh can restore it in order. No-op for unknown sessions."""
    sess = _SESSIONS.get(session_id)
    if sess is not None and body.strip():
        sess["messages"].append({"role": "human", "text": body.strip()})


def reset_session(session_id: str) -> None:
    """Fully clear one conversation: transcript, paused/escalated state,
    pinned brand, and its stored human replies / Intercom link. The next
    message from this session id starts a genuinely fresh AI chat."""
    _SESSIONS.pop(session_id, None)
    handoff_store.clear_session(session_id)


def transcript_for(session_id: str) -> Optional[List[dict]]:
    """The full stored transcript for one session, or None if unknown."""
    sess = _SESSIONS.get(session_id)
    return list(sess["messages"]) if sess else None
