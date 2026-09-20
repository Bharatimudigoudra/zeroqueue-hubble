"""Chunking: one brand object -> small, self-contained chunks.

THE CORE DESIGN DECISION: semantic per-section chunks, not blind
fixed-size splits. A brand yields one chunk per populated section:
  about | discount | validity | highlights | tips | restrictions |
  redeem-<mode> (one per redeem mode) | faq-<n> (one per FAQ pair) |
  terms-p<n>  (terms_and_conditions split by paragraph - it is the only
  field that can exceed a sane chunk size, up to ~8000 chars)

Every chunk carries the brand name inside its text ("Amazon shopping -
how to redeem (online): ...") so a retrieved chunk makes sense alone,
and metadata (brand_key, category, section, source_url, rank, discount)
so results can be filtered and cited.

Data quirks this file defends against (measured on the real 100-brand
file): about is null on 51/100 brands, highlights on 98/100, tips on 22,
faqs can be an empty list, redeem mode casing is inconsistent
(Offline/OFFLINE/online/App/Website). Null or empty fields are SKIPPED -
the text "null" never enters a chunk.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

TERMS_CHUNK_CHARS = 1200   # terms paragraphs are packed up to this
TERMS_OVERLAP_PARAS = 1    # paragraphs repeated between terms chunks


@dataclass
class Chunk:
    id: str                 # stable id, e.g. "amazon#faq-1"
    title: str              # brand name - the retrieval "title"
    section: str            # human label, e.g. "How to redeem (online)"
    section_kind: str       # machine label, e.g. "redeem-online"
    text: str               # self-contained passage text
    brand_key: str = ""
    category: str = ""
    safe_url: str = ""      # public catalog page - safe to cite
    rank: int = 0
    discount_percentage: float = 0.0
    score: float = 0.0      # filled by retrieval, 0 until then


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _as_list(v) -> List[str]:
    if not isinstance(v, list):
        return []
    return [x for x in v if isinstance(x, str) and x.strip()]


def split_long_text(text: str, max_chars: int = TERMS_CHUNK_CHARS) -> List[str]:
    """Split a long string into paragraph-packed chunks with overlap."""
    paras = [p for p in (_clean(x) for x in str(text).split("\n")) if p]
    if not paras:
        return []
    chunks, buf, size = [], [], 0
    for p in paras:
        if size + len(p) > max_chars and buf:
            chunks.append("\n".join(buf))
            buf = buf[-TERMS_OVERLAP_PARAS:]          # overlap
            size = sum(len(x) for x in buf)
        buf.append(p)
        size += len(p)
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def brand_to_chunks(brand: dict) -> List[Chunk]:
    """Turn one brand record into chunks."""
    name = _clean(brand.get("brand_name")) or "Unknown brand"
    key = brand.get("brand_key") or re.sub(r"[^a-z0-9]+", "-", name.lower())
    base = dict(
        title=name,
        brand_key=key,
        category=_clean(brand.get("category")),
        safe_url=brand.get("source_url") or "",
        rank=int(brand.get("rank") or 0),
        discount_percentage=float(brand.get("discount_percentage") or 0),
    )
    chunks: List[Chunk] = []

    def push(kind: str, label: str, body: str) -> None:
        text = _clean(body)
        if not text:
            return                 # skip null/empty sections entirely
        chunks.append(Chunk(
            id=f"{key}#{kind}:{len(chunks)}", section=label,
            section_kind=kind, text=f"{name} - {label}: {text}", **base))

    if _clean(brand.get("about")):
        push("about", "About", brand["about"])
    if brand.get("discount_percentage"):
        push("discount", "Discount",
             f"Buy this gift card at {brand['discount_percentage']}% off on Hubble.")

    validity = _as_list(brand.get("validity"))
    if validity:
        push("validity", "Validity", " ".join(validity))

    highlights = _as_list(brand.get("highlights"))
    if highlights:
        push("highlights", "Highlights", " ".join(highlights))

    tips = _as_list(brand.get("tips"))
    if tips:
        push("tips", "Tips", " ".join(tips))

    for r in brand.get("how_to_redeem") or []:
        if not isinstance(r, dict):
            continue
        # The source data uses Offline/OFFLINE/online/App/Website - normalize.
        mode = _clean(r.get("mode")).lower() or "unspecified"
        steps = _as_list(r.get("steps"))
        if steps:
            push(f"redeem-{mode}", f"How to redeem ({mode})",
                 " ".join(f"{i + 1}. {s}" for i, s in enumerate(steps)))

    restrictions = _as_list(brand.get("restrictions"))
    if restrictions:
        push("restrictions", "Restrictions", " ".join(restrictions))

    if _clean(brand.get("terms_and_conditions")):
        parts = split_long_text(brand["terms_and_conditions"])
        for i, part in enumerate(parts, start=1):
            push(f"terms-p{i}",
                 f"Terms and conditions (part {i} of {len(parts)})", part)

    for i, f in enumerate(brand.get("faqs") or [], start=1):
        if not isinstance(f, dict):
            continue
        q, a = _clean(f.get("question")), _clean(f.get("answer"))
        if q and a:
            push(f"faq-{i}", f"FAQ: {q}", f"{q} {a}")

    return chunks


def kb_to_chunks(kb: dict) -> List[Chunk]:
    """Chunk a whole KB file body ({ "brands": [...] })."""
    brands = kb.get("brands") if isinstance(kb, dict) else None
    if not isinstance(brands, list):
        return []
    return [c for b in brands for c in brand_to_chunks(b)]
