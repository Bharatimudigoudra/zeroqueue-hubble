"""Pipeline: retrieve -> confidence -> answer or hand off. Channel-neutral.

Session state lives in memory (POC level - a restart wipes it, which is
fine for a demo and keeps the project dependency-light). The shape of
every public response matches the ZeroQueue backend exactly, so the
existing web page works against this service unchanged.
"""
import time
from typing import Dict, List, Optional

from app.services import answer_service, clarification, confidence, escalation, intercom_handoff, moss_service

AI_PAUSED_REPLY = ("The AI is paused for this conversation. Human support can "
                   "review it when the live inbox is connected.")

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


def run_pipeline(session_id: str, message: str, attachment_text: str = "") -> dict:
    total_start = time.perf_counter()
    sess = _session(session_id)

    # If a human already owns this conversation, the AI stays silent.
    if sess["status"] == "handoff":
        return {"answer": AI_PAUSED_REPLY, "status": "handoff",
                "citations": [], "trace": sess["trace"]}

    # Ask for missing details without repeating facts already supplied.
    incoming = (message or "").strip()
    if incoming:
        sess["messages"].append({"role": "customer", "text": incoming})
    following_up = bool(sess.get("pending_issue"))
    issue_text = f"{sess.get('pending_issue', '')} {incoming}".strip()
    brand = sess.get("pending_brand") or clarification.find_brand(
        incoming if following_up else issue_text, moss_service.brand_names())
    error_supplied = clarification.has_error(incoming) if following_up else clarification.has_error(issue_text)
    needs_clarification = clarification.has_issue(issue_text) and (not brand or not error_supplied)
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
        sess["messages"].append({"role": "assistant", "text": clarifier})
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
    retrieval = moss_service.search((message or "").strip() or query)
    passages = retrieval["passages"]

    # 2. Evidence-based confidence + escalation decision (never the LLM's).
    band = confidence.band(passages)
    reason = escalation.decide(message or "", band)
    if reason:
        sess["status"] = "handoff"
        handoff = intercom_handoff.send(session_id, message or query, reason,
                                         band, passages, sess["messages"])
        if handoff["confirmed"]:
            ack = ("I have paused the AI and sent this conversation to our human "
                   "support inbox. A teammate can review the details and reply here.")
        else:
            ack = ("I have paused the AI and marked this conversation for human "
                   "review. The live support inbox is not connected right now.")
        if reason != "customer_requested_human":
            ack = ("I do not have a reliable answer in the support knowledge "
                   "base, so I will not guess. " + ack)
        sess["messages"].append({"role": "assistant", "text": ack})
        _record_trace(sess, retrieval["retrieval_ms"], total_start, band,
                      "escalated", passages, reason)
        return {"answer": ack, "status": "handoff", "citations": [],
                "trace": sess["trace"], "handoff_confirmed": handoff["confirmed"]}

    # 3. Grounded answer with citations.
    answer, citations = answer_service.build_answer(query, passages)
    sess["messages"].append({"role": "assistant", "text": answer})
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
    answer = (("I have paused the AI and sent this conversation to our human "
               "support inbox. A teammate can review it and reply here.")
              if handoff["confirmed"] else
              ("I have paused the AI and marked this conversation for human "
               "review. The live support inbox is not connected right now."))
    sess["messages"].append({"role": "assistant", "text": answer})
    return {"answer": answer, "status": "handoff", "citations": [],
            "trace": sess["trace"], "handoff_confirmed": handoff["confirmed"]}


def trace_for(session_id: str) -> dict:
    sess = _SESSIONS.get(session_id)
    return sess["trace"] if sess else {"state": "empty", "source_count": 0,
                                       "sources": []}


def reset_all() -> None:
    _SESSIONS.clear()
