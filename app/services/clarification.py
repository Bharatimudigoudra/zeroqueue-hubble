"""Deterministic clarification for under-specified voucher problems.

Brand matching first normalizes punctuation/case, then uses Python's built-in
sequence similarity. That keeps common typos such as "amezon" explainable and
avoids another model call.
"""
import re
from difflib import SequenceMatcher
from typing import List, Optional

_ISSUE = re.compile(
    r"\b(not working|doesn'?t work|didn'?t work|failed|failing|can'?t redeem|"
    r"cannot redeem|unable to redeem|invalid|declined|rejected|error|problem|issue)\b",
    re.IGNORECASE,
)
_ERROR_DETAIL = re.compile(
    r"\b(invalid|expired|already used|declined|rejected|not activated|"
    r"not applicable|limit exceeded|technical error|error\s*[:#-]?\s*[a-z0-9-]+)\b",
    re.IGNORECASE,
)
_STOP = {"my", "voucher", "gift", "card", "is", "not", "working", "the", "for",
         "brand", "says", "say", "it", "code", "error", "message"}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def find_brand(message: str, brand_names: List[str]) -> Optional[str]:
    """Return the canonical KB brand for an exact or clear fuzzy match."""
    words = [word for word in re.findall(r"[a-z0-9]+", (message or "").lower())
             if word not in _STOP and len(word) >= 3]
    candidates = words + ["".join(words)]
    best_name, best_score = None, 0.0
    for name in brand_names:
        canonical = _normalize(name)
        if not canonical:
            continue
        aliases = {canonical}
        first = _normalize(name.split()[0])
        if len(first) >= 3:
            aliases.add(first)
        for candidate in candidates:
            normalized = _normalize(candidate)
            if not normalized:
                continue
            if normalized in aliases:
                return name
            score = max(SequenceMatcher(None, normalized, alias).ratio()
                        for alias in aliases)
            if score > best_score:
                best_name, best_score = name, score
    return best_name if best_score >= 0.72 else None


def has_issue(message: str) -> bool:
    return bool(_ISSUE.search(message or ""))


def has_error(message: str) -> bool:
    return bool(_ERROR_DETAIL.search(message or ""))


def question(brand: Optional[str], need_error: bool) -> str:
    if not brand and need_error:
        return ("I can help with that. Which brand is the voucher for, and what "
                "exact error or message do you see when you try to use it?")
    if not brand:
        return "Which brand is the voucher for?"
    return f"Got it - {brand}. What exact error or message do you see?"
