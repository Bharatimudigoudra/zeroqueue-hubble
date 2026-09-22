"""Builds the grounded answer from retrieved chunks.

MOCK_MODE (default): no LLM call. The answer is quoted from the top
chunk with explicit citations. This keeps the system fully offline and
makes the citation contract visible.

REAL BUILD: set MOCK_MODE=false and LLM_API_KEY in .env; then the
chunks, source ids and rules go to the Groq model and it must answer
ONLY from them. If the Groq call fails (outage, retired model, bad
key), we fall back to the quote - a live demo must never die on a 404.
"""
import logging
import re
from typing import List, Optional, Tuple

import httpx

from app import config
from app.services.chunking import Chunk

log = logging.getLogger("zeroqueue.answer")

PROMPT_TEMPLATE = """You are ZeroQueue, a customer-support assistant for Hubble gift cards.

Rules:
- Answer ONLY using the retrieved passages below. If they do not contain
  the answer, say you do not have a reliable answer and offer a human.
- If the customer message includes "Attachment text (OCR)", treat it as
  something the customer showed you (a photo, screenshot, or receipt)
  and use it together with the passages - e.g. match a brand name or
  order number from it against the passage.
- If the customer message or the OCR shows an error (for example a voucher
  code being rejected), address that error FIRST: say what to check using
  only the passages. If no passage covers that exact error, say so honestly
  and offer the human handoff - never invent a cause or a fix.
- Then answer the how-to question from the passages.
- Keep it short: direct answer, then one next step.
- End with a "Sources:" line listing the [n] labels you actually used.

Customer question:
{question}

Retrieved passages:
{passages}"""

# The LLM is told to end with its own "Sources:" line, and we append the
# canonical citation line ourselves - strip the model's line first or the
# customer sees "Sources: ... Sources: ..." (lesson from ZeroQueue).
_SOURCES_TAIL = re.compile(r"\s*sources\s*:.*\Z", re.IGNORECASE | re.DOTALL)


def make_citations(passages: List[Chunk]) -> List[dict]:
    """At most 3 citations, labelled like: [1] Amazon shopping - Validity."""
    return [{"label": f"[{i}] {p.title} - {p.section}",
             "url": p.safe_url or None}
            for i, p in enumerate(passages[:3], start=1)]


def _chunk_body(chunk: Chunk, limit: int = 400) -> str:
    """Chunk text without the repeated 'Brand - Section:' heading."""
    body = " ".join(chunk.text.split())
    repeated_heading = f"{chunk.title} - {chunk.section}:"
    if body.lower().startswith(repeated_heading.lower()):
        body = body[len(repeated_heading):].strip()
    return body[:limit]


def quote_issue_answer(passages: List[Chunk], error_line: str) -> str:
    """MOCK answer for a reported error: honest about KB coverage, then the
    grounded checks and the how-to steps, then the human handoff offer."""
    redeem = next((p for p in passages if p.section_kind.startswith("redeem")), None)
    rules = next((p for p in passages
                  if p.section_kind in ("restrictions", "terms-p1", "validity")), None)
    brand = (redeem or rules or passages[0]).title
    parts = [
        (f'Your image shows: "{error_line}". The support knowledge base does '
         "not have an entry for this exact error, so I cannot say why the "
         "code was rejected."),
    ]
    if rules:
        parts.append(f"What to check from the {brand} rules: "
                     f"{_chunk_body(rules, 260)}")
    if redeem:
        parts.append(f"To redeem correctly: {_chunk_body(redeem, 400)}")
    parts.append("If the code still shows invalid after these checks, say "
                 "\"human\" and a teammate will take over.")
    return "\n\n".join(parts)


def quote_chunk(passages: List[Chunk]) -> str:
    """Quote the strongest chunk without repeating its brand and section."""
    top = passages[0]
    body = " ".join(top.text.split())
    repeated_heading = f"{top.title} - {top.section}:"
    if body.lower().startswith(repeated_heading.lower()):
        body = body[len(repeated_heading):].strip()
    body = body[:400]
    return (f"{body}\n\n"
            f"Next step: if this does not solve it, say \"human\" and "
            f"a teammate will take over.")


def grounded_answer(query: str, passages: List[Chunk]) -> str:
    blocks = "\n\n".join(
        f"[{i}] {p.title} - {p.section}\n{p.text}"
        for i, p in enumerate(passages, 1))
    prompt = (PROMPT_TEMPLATE
              .replace("{question}", query)
              .replace("{passages}", blocks))
    resp = httpx.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
        json={"model": config.LLM_MODEL,
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def build_answer(query: str, passages: List[Chunk],
                 error_line: str = "") -> Tuple[str, List[dict]]:
    citations = make_citations(passages)
    if not config.MOCK_MODE and config.LLM_API_KEY:
        try:
            text = grounded_answer(query, passages)
            text = _SOURCES_TAIL.sub("", text).rstrip()
        except Exception:
            log.exception("LLM answer failed - falling back to chunk quote")
            text = (quote_issue_answer(passages, error_line) if error_line
                    else quote_chunk(passages))
    else:
        text = (quote_issue_answer(passages, error_line) if error_line
                else quote_chunk(passages))
    # Citations stay in the response and Moss Trace panel. Keep the customer
    # answer itself focused on the answer instead of repeating source labels.
    return text, citations
