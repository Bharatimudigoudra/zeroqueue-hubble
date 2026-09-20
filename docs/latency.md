# Retrieval latency benchmark

Status: waiting for Moss email verification and project credentials.

The benchmark script is ready at `backend/scripts/benchmark_retrieval.py`. It runs 15 fixed questions through the loaded Moss index and the previous local keyword scorer, then replaces this file with measured p50/p95 retrieval-only latency. It stops if `retrieval.provider` is not `moss`, preventing fallback numbers from being presented as Moss results.
