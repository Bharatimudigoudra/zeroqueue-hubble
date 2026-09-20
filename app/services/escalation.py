"""Decides when the bot stops and a human takes over.

Two triggers:
1. The customer explicitly asks (keyword match, case-insensitive).
2. Evidence is weak: confidence band is low, meaning the knowledge base
   cannot support a reliable answer. We never invent one.
"""
import re
from typing import Optional

PHRASES = [
    r"\bhuman\b", r"\bagent\b", r"\breal person\b", r"\bsomeone real\b",
    r"\btalk to (a |the )?(support|team|person)\b",
    r"\bnot helpful\b", r"\bdid(n't| not) help\b", r"\bthat didn't help\b",
    r"\bescalat", r"\bmanager\b",
]

_PATTERN = re.compile("|".join(PHRASES), re.IGNORECASE)


def customer_requested_human(message: str) -> bool:
    return bool(_PATTERN.search(message or ""))


def decide(message: str, confidence_band: str) -> Optional[str]:
    """Return a handoff reason, or None if the bot may answer."""
    if customer_requested_human(message):
        return "customer_requested_human"
    if confidence_band == "low":
        return "low_confidence_no_reliable_answer"
    return None
