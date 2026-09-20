"""Chunking dry-run:  python scripts/ingest.py [path-to-kb.json]
Loads a KB file, chunks it, and prints what the index will hold - use
this to eyeball chunk quality before starting the server. The server
itself loads data/hubble-gift-cards-top100.json automatically at boot.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

from app.services import moss_service                     # noqa: E402
from app.services.chunking import kb_to_chunks            # noqa: E402

file = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    Path(__file__).resolve().parents[1] / "data" / "hubble-gift-cards-top100.json")
kb = json.loads(file.read_text(encoding="utf-8"))
chunks = kb_to_chunks(kb)
brands = len(kb.get("brands") or [])
print(f"file:   {file}")
print(f"brands: {brands}")
print(f"chunks: {len(chunks)} (avg {len(chunks) / max(brands, 1):.1f} per brand)")

by_kind = {}
for c in chunks:
    kind = c.section_kind.split("-")[0]
    by_kind[kind] = by_kind.get(kind, 0) + 1
print("by section kind:", by_kind)

print("\nsample chunks:")
for c in chunks[:3]:
    print(f"  [{c.id}] {c.section}\n    {c.text[:140]}...")

# quick retrieval sanity check against the freshly built index
moss_service.load_from_kb(kb)
for q in ["how do I redeem an amazon gift card?",
          "what is the validity of a zepto voucher?",
          "can I exchange the card for cash?"]:
    r = moss_service.search(q)
    print(f"\nQ: {q}  ({r['retrieval_ms']} ms)")
    for p in r["passages"]:
        print(f"   {p.score:.3f}  {p.title} - {p.section}")
