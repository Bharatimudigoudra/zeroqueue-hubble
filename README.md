# ZeroQueue + Hubble KB

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-one%20service-deepgreen.svg)](https://fastapi.tiangolo.com/)
[![Retrieval](https://img.shields.io/badge/Retrieval-Moss%20hybrid-deepgreen.svg)](https://github.com/usemoss/moss)
[![Tests](https://img.shields.io/badge/Tests-64%20passing-brightgreen.svg)](test/)
[![Docker](https://img.shields.io/badge/Docker-one%20container-blue.svg)](Dockerfile)
[![Deploy](https://img.shields.io/badge/Deploy-Render%20free%20tier-purple.svg)](https://zeroqueue-hubble.onrender.com)

[Live demo](https://zeroqueue-hubble.onrender.com) · [Agent console](https://zeroqueue-hubble.onrender.com/agent) · [API contract](docs/api-contract.md) · [Health check](https://zeroqueue-hubble.onrender.com/health)

---

## Problem Statement

A platform like Hubble Money operates across a large number of brands, and every brand has its own rules - redemption steps, validity, restrictions, online and offline usage, terms and conditions. The information needed to answer a customer's question already exists, scattered across brand pages, product pages, FAQs and T&Cs.

The problem is not the absence of information. The problem is access - the customer needs the right piece of information at the exact moment they need it. And when an issue cannot be answered automatically, they need a fast path to a human.

Support work comes in two types. Information resolution - the business already knows the answer ("How do I redeem?", "Is this valid online?") - should be automated. Exception resolution - errors, failed vouchers, anything needing judgment - should reach a human quickly.

---

ZeroQueue is an AI support copilot for gift-card help desks. A customer asks a question in plain language or uploads a voucher screenshot, and the app answers only from a grounded knowledge base - 100 brands, 875 retrieval chunks - with citations and a live confidence score. When the knowledge base has no real answer, it says so and hands the chat to a human through Intercom instead of guessing.

A confident wrong answer is the biggest risk in support automation, and gift cards sit next to real money. ZeroQueue's rule: the customer gets a cited correct answer or a human - never a hallucination. Retrieval, answers, handoff, and the agent console all run in one FastAPI service, so a single Docker container is the whole product.

## Quickstart

**Before you start:** Docker Desktop, or Python 3.10+ with a conda/venv environment. Copy `.env.example` to `.env` first - the demo works offline with `MOCK_MODE=true`, no keys needed.

### Docker (one container, the whole product)

```bash
docker compose up --build
```

Open `http://localhost:8000`. Ask: `How do I redeem an Amazon gift card?`

### Plain Python

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Try the demo flow

1. Ask `How do I redeem an Amazon gift card?` - cited answer, Moss Trace shows retrieval time and confidence.
2. Attach a voucher screenshot - OCR reads the real error, the answer quotes it.
3. Ask something the KB does not cover - honest "no entry" answer, one-click handoff to a human.
4. Open `/agent` - the escalated chat is there with the transcript and the customer's image. Reply, and it lands back in the customer's chat.

## Why ZeroQueue?

**Most support bots retrieve the nearest chunk and let the LLM smooth over the gap. "Nearest" is often the wrong brand, the wrong error, the wrong answer.**

ZeroQueue gates every answer on relevance: retrieved passages must actually cover the question's terms, or the app hands off honestly. Unclear issues get a clarifying question first, and the brand pins to the conversation so follow-ups stay scoped. The result is a support bot a payments-adjacent product can trust in front of customers.

### Measured in the product (Moss Trace panel, live deployment)

| Signal | Value |
|--------|-------|
| Retrieval latency | 0.5 - 3 ms per question |
| Full answer (retrieval + grounded wording) | about 1 second |
| Knowledge base | 100 brands, 875 chunks |
| Wrong-topic answers after the relevance gate | 0 (handoff instead) |

## Features

- **Grounded answers with citations** - every answer quotes real KB passages; sources and confidence shown live in the Moss Trace panel
- **Moss hybrid retrieval** - the official Python SDK, hybrid search with `alpha=0.6` over the `hubble-gift-cards` index, loaded once at startup ([`usemoss/moss`](https://github.com/usemoss/moss))
- **Relevance gate** - passages must cover the question's terms or the app hands off instead of quoting a mismatched FAQ
- **Screenshot OCR answers** - free local Tesseract reads error screenshots; the answer quotes the exact error value (like `VOUCHER CODE IS INVALID`) and skips labels
- **Clarifying questions with brand pin** - vague issues get one targeted question; the brand sticks to the conversation and re-pins instantly when the customer corrects it
- **Honest human handoff via Intercom** - real conversation with transcript and evidence note; the AI pauses for that chat only, and the pause notice shows once
- **Agent console at `/agent`** - escalated chats with full transcript and the customer's actual image; one-click reply lands back in the customer's chat; auto-refreshes every 5 seconds without touching a half-written reply
- **Clean attachment display** - the customer chat shows the image itself plus one small note line, never a wall of OCR text
- **Plain-sentence answers** - no fake numbering; numbered steps only for real sequences like redeem instructions
- **Fresh-session refresh** - a page refresh always starts a clean AI chat; the reset button wipes the conversation server-side on demand
- **Local-first fallback** - if Moss or LLM credentials fail, the app logs it and keeps answering with the local scorer; the product never breaks mid-demo
- **One-container deploy** - FastAPI serves frontend, retrieval, handoff, and console; Render free tier auto-deploys on `git push` to `main`

## Architecture

```text
Browser (chat UI + agent console)
        |
        | same FastAPI service
        +--> HTML + CSS + JavaScript (no build step, no Node.js)
        +--> /api/chat  /api/handoff  /api/agent/*  /api/webhooks/intercom
                 |
                 +--> Hubble JSON: 100 brands -> 875 chunks
                 +--> Moss hybrid retrieval -> relevance gate
                 +--> confidence -> cited answer  |  honest handoff -> Intercom
                 +--> LLM wording (any OpenAI-compatible endpoint) when MOCK_MODE=false
```

## Project structure

```text
app/
├── main.py                  # FastAPI app: page serving + all API routes
├── api_agent.py             # Agent console API (/api/agent/...)
├── api_intercom.py          # Signed Intercom webhook receiver
├── config.py                # All environment configuration
├── adapters/
│   └── intercom.py          # Intercom API calls
├── services/
│   ├── pipeline.py          # Orchestration: clarify -> retrieve -> answer/handoff
│   ├── moss_service.py      # Moss index build + hybrid search + local fallback
│   ├── answer_service.py    # Grounded answers, relevance gate, citations, LLM call
│   ├── clarification.py     # Brand/error clarification, typo tolerance
│   ├── confidence.py        # Confidence bands from retrieval scores
│   ├── attachment_service.py# OCR (Tesseract) + upload storage
│   ├── escalation.py        # Handoff decisions
│   ├── intercom_handoff.py  # Create + assign Intercom conversations
│   ├── agent_console.py     # Console reads, suggested replies, approve-send
│   └── handoff_store.py     # Session mapping, dedupe, human replies (SQLite)
├── static/
│   ├── index.html           # Customer chat page
│   ├── app.js               # Chat logic + Moss Trace panel
│   ├── agent.html + agent.js# Agent console
│   └── styles.css           # Shared styling
data/
└── hubble-gift-cards-top100.json   # The 100-brand knowledge base
test/                        # 64 tests: API, retrieval, clarification, handoff, console
scripts/                     # Backend runner + retrieval benchmark
docs/                        # API contract, integration status, latency notes
Dockerfile + docker-compose.yml     # The whole product in one container
```

## Configuration

Copy `.env.example` to `.env`. Keep `.env` private - never push it, never put real keys in `.env.example`, GitHub, or screenshots.

| Variable | What it does |
|----------|--------------|
| `MOCK_MODE` | `true` = offline grounded answers; `false` = LLM writes the final wording |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | Any OpenAI-compatible chat endpoint. For a free Groq key: `LLM_BASE_URL=https://api.groq.com/openai/v1` |
| `MOSS_PROJECT_ID` / `MOSS_PROJECT_KEY` / `MOSS_INDEX_NAME` | The live Moss index (`hubble-gift-cards`) |
| `INTERCOM_ACCESS_TOKEN` / `INTERCOM_WEBHOOK_SECRET` / `INTERCOM_ADMIN_ID` / `INTERCOM_TEAM_ID` | The live human-handoff inbox |
| `AGENT_CONSOLE_KEY` | Optional password for `/agent` - set it before sharing a deployed URL |

## API

| Route | Purpose |
|-------|---------|
| `POST /api/chat` | One customer message (+ optional file) - returns answer, status, citations, trace |
| `POST /api/agent/chat` | Alias of `/api/chat` for external frontends |
| `POST /api/handoff` | Explicit "talk to a human" |
| `POST /api/reset` | Wipe a conversation server-side (fresh AI chat) |
| `GET /api/transcript/{session_id}` | Read a stored conversation |
| `GET /api/human-replies/{session_id}` | Poll human replies for a paused chat |
| `GET /api/trace/{session_id}` | The Moss Trace data behind the panel |
| `GET /health` | Service, database, KB, retrieval, and Intercom status |
| `GET /agent` + `/api/agent/*` | The agent console and its API |
| `POST /api/webhooks/intercom` | Signed webhook: human replies reach the customer's chat |

The full request/response contract lives in [`docs/api-contract.md`](docs/api-contract.md).

## Testing

```bash
pytest test -q
```

64 tests cover the chat API, retrieval, the relevance gate, clarification and brand re-pinning, attachments and OCR, handoff, the agent console, and webhook dedupe. CI runs them on every push.

## Deployment

The live demo runs on Render's free tier as one Docker container. Render watches the GitHub repo - every `git push` to `main` rebuilds and redeploys automatically. After a deploy, check `/health`: `status` and `database` must be `ok`, and `retrieval.provider` must be `moss`. The Intercom webhook on the live deployment points at the Render URL; for local webhook testing, expose the local server with `ngrok http 8000` and use that URL instead.

## Adding more knowledge bases

Drop another `.json` file with the same `{"brands": [...]}` shape into `data/` and restart (or rebuild the Docker image). Every brand file merges into one retrieval index; keep each `brand_key` unique. `POST /api/ingest` replaces the in-memory index until restart for a temporary live refresh. `/health` shows the new `kb_brands` and `kb_chunks` counts. A malformed file is reported at startup, never silently ignored.

## Built with

FastAPI · [Moss](https://github.com/usemoss/moss) (hybrid retrieval) · Intercom (human handoff) · Tesseract OCR · Docker · Render