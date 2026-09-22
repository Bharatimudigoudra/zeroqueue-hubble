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
from app.services import moss_service
from app.services.chunking import Chunk

log = logging.getLogger("zeroqueue.answer")

PROMPT_TEMPLATE = """You are ZeroQueue, a customer-support assistant for Hubble gift cards.

Rules:
- Answer ONLY using the retrieved passages below. If they do not contain
  the answer, say you do not have a reliable answer in the knowledge base.
- If the customer message includes "Attachment text (OCR)", treat it as
  something the customer showed you (a photo, screenshot, or receipt)
  and use it together with the passages - e.g. match a brand name or
  order number from it against the passage.
- If the customer message or the OCR shows an error (for example a voucher
  code being rejected), address that error FIRST: say what to check using
  only the passages. If no passage covers that exact error, say so honestly
  - never invent a cause or a fix.
- Then answer the how-to question from the passages.
- Keep it short: direct answer only. Do not add closing offers or next
  steps - escalation is handled by a separate Ask Human button.
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


def quote_issue_answer(passages: List[Chunk], error_line: str,
                       query: str = "") -> str:
    """MOCK answer for a reported error: honest about KB coverage, then the
    grounded checks and the how-to steps. The Ask Human button covers
    escalation, so no trailing handoff offer is appended."""
    redeem = next((p for p in passages if p.section_kind.startswith("redeem")), None)
    rules = next((p for p in passages
                  if p.section_kind in ("restrictions", "terms-p1", "validity")), None)
    brand = (redeem or rules or passages[0]).title
    from_image = "attachment text (ocr):" in (query or "").lower()
    shown = (f'Your image shows: "{error_line}".' if from_image
             else f'You mentioned: "{error_line}".')
    parts = [
        (f"{shown} The support knowledge base does "
         "not have an entry for this exact error, so I cannot say why the "
         "code was rejected."),
    ]
    if rules:
        checks = _best_sentence_quote([rules], query, limit=280,
                                      max_sentences=1)
        if checks:
            parts.append(f"What to check from the {brand} rules: {checks}")
    if redeem:
        parts.append(f"To redeem correctly: {_chunk_body(redeem, 400)}")
    return "\n\n".join(parts)


# Words nearly every voucher question contains. They say nothing about
# WHICH entry answers it, so the relevance gate ignores them.
_GENERIC_QUERY_TERMS = {
    "gift", "card", "voucher", "buy", "use", "using", "purchase", "get",
    "redeem", "apply", "check", "balance", "add", "online", "app",
    "website", "store", "pay", "payment", "number", "code", "send",
    "one", "two", "three", "much",
}


def typed_part(query: str) -> str:
    """The customer's typed words, without any appended OCR text."""
    return re.split(r"attachment text \(ocr\):", query or "",
                    maxsplit=1, flags=re.IGNORECASE)[0]


def distinctive_terms(query: str, brand: str = "") -> set:
    """Query terms that identify the actual question: no stop words, no
    brand name, no generic voucher vocabulary."""
    terms = set(moss_service.tokenize(typed_part(query)))
    brand_terms = set(moss_service.tokenize(brand or ""))
    return terms - brand_terms - _GENERIC_QUERY_TERMS


def term_in_text(term: str, text: str) -> bool:
    """Exact or prefix match, so 'valid' finds 'validity'."""
    for token in set(moss_service.tokenize(text)):
        if token == term:
            return True
        if len(term) >= 4 and token.startswith(term):
            return True
        if len(token) >= 4 and term.startswith(token):
            return True
    return False


def question_coverage(passage: Chunk, terms: set) -> float:
    """Share of the question's distinctive terms the passage mentions."""
    if not terms:
        return 1.0
    haystack = f"{passage.section} {passage.text}"
    hits = sum(1 for term in terms if term_in_text(term, haystack))
    return hits / len(terms)


def filter_relevant(passages: List[Chunk], terms: set) -> List[Chunk]:
    """Drop passages that answer a different question (score order kept).
    A passage survives only when it covers at least half of the question's
    distinctive terms - a one-word coincidence is not evidence."""
    if not terms:
        return list(passages)
    return [p for p in passages if question_coverage(p, terms) >= 0.5]


# Abbreviations whose period is not a sentence boundary.
_ABBREV = re.compile(r"\b(Pvt|Ltd|Mr|Mrs|Ms|Dr|Inc|No|vs|approx)\.",
                     re.IGNORECASE)
# Leftover corporate-suffix fragments after splitting ("Ltd", "Inc").
_LEADING_FRAGMENT = re.compile(r"^(ltd|pvt|private|limited|inc|llp|corp)\b\s*",
                               re.IGNORECASE)


# KB restriction/terms bullets are joined with plain spaces and mostly lack
# end punctuation, so a run-on item boundary looks like "amount Gift Cards":
# a lowercase word followed by a capitalised one (but not after and/or).
_SOFT_BOUNDARY = re.compile(r"(?<!\band )(?<!\bor )(?<=[a-z)\]]) (?=[A-Z])")


def _split_sentences(text: str) -> List[str]:
    protected = _ABBREV.sub(lambda m: m.group(1) + "\u0000", text)
    parts = re.split(r"\n+|(?<=[.!?])\s+|\s+[-•]\s+", protected)
    refined = []
    for part in parts:
        if len(part) > 240:
            refined.extend(_SOFT_BOUNDARY.split(part))
        else:
            refined.append(part)
    out = []
    for part in refined:
        part = part.replace("\u0000", ".").strip(" -•\t")
        part = _LEADING_FRAGMENT.sub("", part)
        # Drop fragments: list numbers ("2."), abbreviations, stray words.
        if len(part) < 12 or not re.search(r"[a-zA-Z]{3,}", part):
            continue
        out.append(part)
    return out


def _term_overlap(sentence: str, terms: set) -> int:
    return sum(1 for term in terms if term_in_text(term, sentence))


def _best_sentence_quote(passages: List[Chunk], query: str,
                         limit: int = 320, max_sentences: int = 2) -> str:
    """Quote only the sentence(s) that answer the question - never the
    echoed FAQ question line, never a whole legal paragraph."""
    q_terms = set(moss_service.tokenize(typed_part(query)))
    distinctive = distinctive_terms(query)
    best_chunk, best_key, best_sentences = None, (-1, -1, -1), []
    for passage in passages:
        section_hits = _term_overlap(passage.section, distinctive)
        body = _chunk_body(passage, 2000)
        sentences = [s for s in _split_sentences(body)
                     if not s.rstrip().endswith("?")]
        for sentence in sentences:
            key = (section_hits,
                   _term_overlap(sentence, distinctive),
                   _term_overlap(sentence, q_terms))
            if key > best_key:
                best_key, best_chunk = key, passage
    if not best_chunk or best_key == (0, 0, 0):
        return ""
    body = _chunk_body(best_chunk, 2000)
    sentences = [s for s in _split_sentences(body)
                 if not s.rstrip().endswith("?")]
    sentences.sort(key=lambda s: (_term_overlap(s, distinctive),
                                  _term_overlap(s, q_terms)), reverse=True)
    total = 0
    for sentence in sentences[:max_sentences]:
        if best_sentences and _term_overlap(sentence, distinctive) == 0:
            break
        if total + len(sentence) > limit and best_sentences:
            break
        best_sentences.append(sentence)
        total += len(sentence) + 1
    return " ".join(item if item.rstrip().endswith((".", "!", "?"))
                    else item.rstrip() + "."
                    for item in best_sentences)


def quote_chunk(passages: List[Chunk], query: str = "") -> str:
    """Quote the strongest chunk without repeating its brand and section."""
    top = passages[0]
    if top.section_kind.startswith("redeem"):
        # Genuine step sequences stay numbered and complete.
        return _chunk_body(top, 400)
    quote = _best_sentence_quote(passages, query)
    if quote:
        return quote
    return _chunk_body(top, 400)


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
            text = (quote_issue_answer(passages, error_line, query) if error_line
                    else quote_chunk(passages, query))
    else:
        text = (quote_issue_answer(passages, error_line, query) if error_line
                else quote_chunk(passages, query))
    # Citations stay in the response and Moss Trace panel. Keep the customer
    # answer itself focused on the answer instead of repeating source labels.
    return text, citations
