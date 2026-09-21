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


def quote_chunk(passages: List[Chunk]) -> str:
    """Quote the strongest chunk directly. Honest and deterministic."""
    top = passages[0]
    body = " ".join(top.text.split())[:400]
    return (f"Based on our {top.title} information ({top.section}): {body}\n\n"
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


def build_answer(query: str, passages: List[Chunk]) -> Tuple[str, List[dict]]:
    citations = make_citations(passages)
    if not config.MOCK_MODE and config.LLM_API_KEY:
        try:
            text = grounded_answer(query, passages)
            text = _SOURCES_TAIL.sub("", text).rstrip()
        except Exception:
            log.exception("LLM answer failed - falling back to chunk quote")
            text = quote_chunk(passages)
    else:
        text = quote_chunk(passages)
    source_line = "  ".join(c["label"] for c in citations)
    return f"{text}\n\nSources: {source_line}", citations