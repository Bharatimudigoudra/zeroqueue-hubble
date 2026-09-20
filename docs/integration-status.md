# Final integration status

## Included and verified locally

- One flattened FastAPI project serves the HTML/CSS/JavaScript UI and API on port 8000.
- The 100-brand Hubble JSON loads as 875 chunks through the local fallback.
- Every `data/*.json` file is merged at startup; malformed files fail loudly.
- Answers include citations, confidence, retrieval timing, attachment handling, and human-handoff decisions.
- Ambiguous voucher failures ask for brand and exact error before retrieval.
- Partial clarification state is preserved. A clear typo such as `amezon` maps deterministically to `Amazon shopping`.
- Intercom adapter, handoff creation, transcript/evidence note, assignment, signed webhook, dedupe, and browser reply path are implemented and covered by contract tests.
- GitHub Actions runs the full pytest suite on every push using Python 3.12.

## Moss

The official Moss Python SDK is wired behind the retrieval seam. With valid `MOSS_PROJECT_ID` and `MOSS_PROJECT_KEY`, startup creates or updates the merged knowledge index, loads it into memory, and uses Moss hybrid search. Without those credentials, `/health` reports `local_fallback` and the previous local scorer keeps the demo working.

Bharati's Moss signup was still waiting for its confirmation email when this package was built. No Project ID/key or real Moss benchmark was available. `docs/latency.md` remains marked pending. Run `scripts/benchmark_retrieval.py` only after `/health` reports `retrieval.provider` as `moss`; the script refuses to present fallback numbers as Moss.

## Intercom

Real Intercom code is present, but the live workspace round-trip was not completed in this environment because real secrets cannot be exported from the vault into a shell and the saved Intercom/Google browser login was unavailable. Local contract tests cover signature verification, dedupe, mapping, admin reply ingestion, and honest failure behavior.

For the live test, Bharati must place the current rotated Intercom token and webhook secret in her private `.env`, start the app, expose port 8000 with ngrok or HTTPS hosting, set `/api/webhooks/intercom` as the webhook endpoint, then verify: handoff appears in Support team `11621027`, the internal note has the transcript/evidence, and a human reply returns to the browser within five seconds. Until API handoff succeeds, the UI says the AI is paused and the case is marked for review rather than claiming a human received it.

## Secrets and publication

The package contains `.env.example` placeholders only. It contains no `.env`, API token, webhook secret, Moss Project Key, runtime database, or cache. Before publishing to GitHub, scan the working tree and commit history again, keep `.env` ignored, and do not upload local runtime files.
