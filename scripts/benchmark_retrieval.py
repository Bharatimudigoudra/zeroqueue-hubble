"""Compare loaded Moss search with the original local keyword fallback.

Run after Moss credentials are in .env:
  python scripts/benchmark_retrieval.py
The script writes docs/latency.md and refuses to label fallback timings as Moss.
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402
from app.services import moss_service  # noqa: E402

QUESTIONS = [
    "How do I redeem an Amazon gift card?",
    "What is the validity of a Zepto voucher?",
    "Can I exchange a gift card for cash?",
    "Where can I use a Myntra gift card?",
    "What discount is available on Swiggy?",
    "Can I use an Apollo Pharmacy voucher online?",
    "How do I redeem a Croma gift card in a store?",
    "Does a MakeMyTrip gift card expire?",
    "Can I combine gift cards for one purchase?",
    "What happens if my order costs more than the voucher?",
    "Is the gift card refundable?",
    "Can I use a voucher during a sale?",
    "How do I add an Amazon voucher in the app?",
    "Where do I find the gift card PIN?",
    "Can an expired voucher be extended?",
]


def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def run():
    kb = json.loads(config.KB_FILE.read_text(encoding="utf-8"))
    moss_service.load_from_kb(kb)
    if moss_service.status()["provider"] != "moss":
        raise SystemExit("Moss is not ready. Add valid MOSS_PROJECT_ID and MOSS_PROJECT_KEY first.")

    moss_times, local_times, rows = [], [], []
    for question in QUESTIONS:
        result = moss_service.search(question)
        moss_times.append(result["retrieval_ms"])
        start = __import__("time").perf_counter()
        local_hits = moss_service._local_search(question, 3)
        local_ms = (__import__("time").perf_counter() - start) * 1000
        local_times.append(local_ms)
        rows.append((question, result["retrieval_ms"], local_ms,
                     result["passages"][0].title if result["passages"] else "-",
                     local_hits[0].title if local_hits else "-"))

    def summary(values):
        return round(statistics.median(values), 2), round(percentile(values, 95), 2)
    moss_p50, moss_p95 = summary(moss_times)
    local_p50, local_p95 = summary(local_times)
    lines = [
        "# Retrieval latency benchmark", "",
        f"Date: {__import__('datetime').date.today().isoformat()}",
        f"Questions: {len(QUESTIONS)}", "",
        "Measured around retrieval only. The Moss index was loaded into memory before timing; index creation, model download, answer generation, and network setup are excluded.", "",
        "| Retriever | p50 | p95 |", "|---|---:|---:|",
        f"| Moss in-process hybrid search | {moss_p50} ms | {moss_p95} ms |",
        f"| Previous local keyword scorer | {local_p50} ms | {local_p95} ms |", "",
        f"Moss sub-10ms p95 result: **{'PASS' if moss_p95 < 10 else 'NOT MET'}**", "",
        "| Question | Moss ms | Local ms | Moss top brand | Local top brand |",
        "|---|---:|---:|---|---|",
    ]
    lines += [f"| {q} | {m:.2f} | {l:.2f} | {mt} | {lt} |" for q, m, l, mt, lt in rows]
    out = Path(__file__).resolve().parents[1] / "docs" / "latency.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Moss p50={moss_p50} ms p95={moss_p95} ms")


if __name__ == "__main__":
    run()
