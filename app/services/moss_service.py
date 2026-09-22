"""Moss retrieval with a local fallback.

The rest of the app calls only load_from_kb() and search(). When Moss
credentials are present, chunks are loaded into a real in-process Moss index
and every question uses Moss hybrid search. If Moss cannot start, the same
chunks remain searchable with the small local scorer so the demo still works.
"""
import asyncio
import logging
import re
import threading
import time
from dataclasses import replace
from typing import List, Tuple

from app import config
from app.services.chunking import Chunk, kb_to_chunks

log = logging.getLogger(__name__)

_STOP = {"the", "a", "an", "is", "it", "my", "i", "do", "to", "of", "and",
         "or", "for", "on", "in", "me", "can", "what", "how", "does", "are",
         "was", "were", "will", "would", "should", "could", "get", "got",
         "where", "when", "who", "whom", "whose", "which", "why",
         "this", "that", "these", "those", "there", "here", "their", "them",
         "they", "we", "you", "your", "yours", "he", "she", "his", "her",
         "its", "am", "be", "been", "being", "have", "has", "had", "did",
         "doing", "tell", "say", "says", "please", "want", "need", "know",
         "about"}


def tokenize(text: str) -> List[str]:
    out = []
    for token in re.findall(r"[a-z0-9]+", str(text).lower()):
        if token not in _STOP:
            out.append(token[:-1] if len(token) > 3 and token.endswith("s") else token)
    return out


_INDEX: List[Chunk] = []
_BY_ID = {}
_MOSS_CLIENT = None
_MOSS_READY = False
_MOSS_ERROR = "credentials_not_configured"

# The Moss SDK is async. One tiny background event loop lets the existing
# synchronous pipeline call it without changing any API route or UI code.
_LOOP = asyncio.new_event_loop()
threading.Thread(target=_LOOP.run_forever, daemon=True, name="moss-loop").start()


def _run(coroutine):
    return asyncio.run_coroutine_threadsafe(coroutine, _LOOP).result()


def _metadata(chunk: Chunk) -> dict:
    """Return Moss-compatible metadata.

    Moss 1.12.0 requires every metadata value to be a string. Chunk metadata
    also contains numeric values such as rank and discount_percentage, so
    normalize the complete mapping at the SDK boundary.
    """
    values = {
        "title": chunk.title,
        "section": chunk.section,
        "section_kind": chunk.section_kind,
        "brand_key": chunk.brand_key,
        "category": chunk.category,
        "safe_url": chunk.safe_url,
        "rank": chunk.rank,
        "discount_percentage": chunk.discount_percentage,
    }
    return {key: "" if value is None else str(value) for key, value in values.items()}


async def _prepare_moss() -> None:
    """Create/update the cloud index once, then load it into local memory."""
    global _MOSS_CLIENT, _MOSS_READY, _MOSS_ERROR
    from moss import DocumentInfo, MossClient

    client = MossClient(config.MOSS_PROJECT_ID, config.MOSS_PROJECT_KEY)
    docs = [DocumentInfo(id=c.id, text=c.text, metadata=_metadata(c)) for c in _INDEX]
    names = {item.name for item in await client.list_indexes()}
    if config.MOSS_INDEX_NAME in names:
        await client.add_docs(config.MOSS_INDEX_NAME, docs)
    else:
        await client.create_index(config.MOSS_INDEX_NAME, docs, "moss-minilm")
    await client.load_index(config.MOSS_INDEX_NAME)
    _MOSS_CLIENT, _MOSS_READY, _MOSS_ERROR = client, True, ""
    log.info("Moss index ready: %s (%d chunks)", config.MOSS_INDEX_NAME, len(docs))


def load_from_kb(kb: dict) -> Tuple[int, int]:
    """Chunk the KB, keep the local fallback, and initialize Moss if configured."""
    global _INDEX, _BY_ID, _MOSS_READY, _MOSS_ERROR
    _INDEX = kb_to_chunks(kb)
    _BY_ID = {chunk.id: chunk for chunk in _INDEX}
    _MOSS_READY = False
    brands = len(kb.get("brands") or []) if isinstance(kb, dict) else 0
    if config.MOSS_PROJECT_ID and config.MOSS_PROJECT_KEY:
        try:
            _run(_prepare_moss())
        except Exception as exc:  # fallback is deliberate for demo resilience
            _MOSS_ERROR = f"{type(exc).__name__}: {exc}"
            log.warning("Moss unavailable; using local fallback: %s", _MOSS_ERROR)
    else:
        _MOSS_ERROR = "credentials_not_configured"
    return brands, len(_INDEX)


def _local_search(query: str, top_k: int, brand: str = "") -> List[Chunk]:
    """Score local chunks, optionally limiting the candidates to one brand."""
    candidates = _INDEX
    if brand:
        wanted_brand = brand.casefold().strip()
        candidates = [
            chunk for chunk in _INDEX
            if chunk.title.casefold().strip() == wanted_brand
        ]

    # The typed question carries the customer's intent. OCR may contain dozens
    # of unrelated receipt/image words, so do not let it dilute that intent.
    typed_query = re.split(r"attachment text \(ocr\):", query,
                           maxsplit=1, flags=re.IGNORECASE)[0]
    q_terms = set(tokenize(typed_query))
    if not q_terms:
        q_terms = set(tokenize(query)[:12])

    scored = []
    if q_terms:
        for chunk in candidates:
            section_terms = set(tokenize(chunk.section))
            body_terms = set(tokenize(chunk.text))
            section_hits = len(q_terms & section_terms)
            body_hits = len(q_terms & body_terms)
            if not section_hits and not body_hits:
                continue

            # Section names are the KB's intent labels (for example "How to
            # redeem (app)"). A section match must beat incidental body noise.
            coverage = body_hits / len(q_terms)
            intent_boost = 0.35 * section_hits
            score = min(1.0, coverage + intent_boost)
            scored.append(replace(chunk, score=round(score, 3)))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]


async def _moss_search(query: str, top_k: int) -> List[Chunk]:
    from moss import QueryOptions
    result = await _MOSS_CLIENT.query(
        config.MOSS_INDEX_NAME, query, QueryOptions(top_k=top_k, alpha=0.6))
    passages = []
    for hit in result.docs:
        original = _BY_ID.get(hit.id)
        if original:
            passages.append(replace(original, score=round(float(hit.score), 3)))
    return passages


def search(query: str, top_k: int = 3, brand: str = "") -> dict:
    """Retrieve passages, scoping local fallback candidates to a known brand."""
    start = time.perf_counter()
    provider = "moss" if _MOSS_READY else "local_fallback"
    try:
        passages = (_run(_moss_search(query, top_k)) if _MOSS_READY
                    else _local_search(query, top_k, brand))
    except Exception as exc:
        log.warning("Moss query failed; using local fallback: %s", exc)
        provider = "local_fallback"
        passages = _local_search(query, top_k, brand)
    retrieval_ms = (time.perf_counter() - start) * 1000
    return {"passages": passages, "retrieval_ms": round(retrieval_ms, 1),
            "provider": provider}


def brand_policy_chunks(brand: str, kinds: Tuple[str, ...]) -> List[Chunk]:
    """Return one brand's chunks for the given section kinds, unscored.

    Keyword scoring cannot find troubleshooting material for an error the KB
    never names (for example "voucher code is invalid") - the brand's rules
    (restrictions, terms, validity) are the honest "what to check" source.
    """
    wanted = brand.casefold().strip()
    by_kind = {}
    for chunk in _INDEX:
        if (chunk.title.casefold().strip() == wanted
                and chunk.section_kind in kinds
                and chunk.section_kind not in by_kind):
            by_kind[chunk.section_kind] = chunk
    # Return in the requested kind order, not index order: restrictions and
    # terms are the "what to check" material, validity is a fallback.
    return [by_kind[kind] for kind in kinds if kind in by_kind]


def brand_names() -> List[str]:
    """Names used only to decide whether a support issue names its brand."""
    return sorted({chunk.title for chunk in _INDEX if chunk.title})


def status() -> dict:
    """Safe health details; credentials are never returned."""
    return {"provider": "moss" if _MOSS_READY else "local_fallback",
            "index": config.MOSS_INDEX_NAME, "error": _MOSS_ERROR or None}
