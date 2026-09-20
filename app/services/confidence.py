"""Evidence-based confidence. The LLM never decides its own certainty.

Rules (simple on purpose, same bands as the ZeroQueue backend):
- no passage at all            -> low
- best passage score < 0.35    -> low  (weak evidence)
- best passage score >= 0.60   -> high
- otherwise                    -> medium
"""
from typing import List

from app.services.chunking import Chunk

HIGH = 0.60
LOW = 0.35


def band(passages: List[Chunk]) -> str:
    if not passages:
        return "low"
    best = max(p.score for p in passages)
    if best < LOW:
        return "low"
    if best >= HIGH:
        return "high"
    return "medium"
