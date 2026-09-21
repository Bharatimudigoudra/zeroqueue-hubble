# ZeroQueue + Hubble KB - all Python

> **Current integration status:** the Python UI, clarification flow, Moss SDK path, local retrieval fallback, and Intercom handoff code are included. Moss is waiting for the account-confirmation email before a real key/benchmark can be completed. Intercom requires Bharati's private local `.env` plus the ngrok/webhook setup below before the live workspace test. The ZIP contains placeholders only. See `docs\integration-status.md`.

ZeroQueue is now one Python service and one Docker image. FastAPI serves both the chat page and the existing Hubble gift-card API. The backend still loads 100 brands into 875 retrieval chunks and keeps the same retrieval, citations, confidence, attachment, and human-handoff flow.

## Simple architecture

```text
Browser: http://localhost:8000
        |
        | same FastAPI service
        +--> HTML + CSS + JavaScript chat screen
        +--> /api/chat and /api/handoff
                 |
                 +--> Hubble JSON: 100 brands -> 875 chunks
                 +--> Moss-ready retrieval -> confidence -> cited answer or handoff
                 +--> LLM wording when MOCK_MODE=false
```

The browser JavaScript sends the question to `/api/chat` on the same address. There is no Node.js, Next.js, npm, frontend build step, or second container.

## Files you should know

- `app\main.py` - starts FastAPI, serves the page, and keeps all API routes.
- `app\static\index.html` - the visible chat page structure.
- `app\static\styles.css` - colors, spacing, message bubbles, mobile layout.
- `app\static\app.js` - sends questions and attachments to FastAPI, then displays answers and Moss Trace.
- `app\services\` - the existing retrieval, answer, confidence, handoff, and attachment logic.
- `data\hubble-gift-cards-top100.json` - the 100-brand knowledge base.
- `requirements.txt` - complete minimal Python dependencies.
- `docker-compose.yml` - starts only the one Python service.

## Run on Windows with Docker Desktop

1. If your old folder has a `.env`, copy that file somewhere safe first.
2. Delete the old `zeroqueue-hubble` folder.
3. Extract this ZIP in `E:\Hackathons`, creating one fresh `E:\Hackathons\zeroqueue-hubble` folder. Do not paste it over the old Next.js copy.
4. Copy your saved `.env` into the fresh `zeroqueue-hubble` folder. If you do not have one, copy `.env.example` and rename the copy to `.env`.

Open Docker Desktop and wait until it says the engine is running. Open Anaconda Prompt in the extracted `zeroqueue-hubble` folder, then run:

```powershell
conda activate GenAI
```

```powershell
docker compose down

docker compose build --no-cache

docker compose up
```

Open `http://localhost:8000`. Stop with `Ctrl+C`.

Docker installs the Python packages from `requirements.txt`; conda does not need to install them for the Docker run.

## Run directly with Python instead of Docker

From the project folder:

```powershell
conda activate GenAI
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open `http://localhost:8000`.

## Environment

Copy `.env.example` to `.env` if your old `.env` is not already available locally. Keep `.env` private and never push it to GitHub.

- `MOCK_MODE=true` - local grounded answers, no external API call.
- `MOCK_MODE=false` - the LLM writes the final wording using `LLM_API_KEY` (old `GROQ_API_KEY` still works).
- `MOSS_API_KEY` and `MOSS_INDEX_NAME` - reserved for the real Moss integration seam.

## Test

```powershell
conda activate GenAI
python -m pip install -r requirements.txt
pytest test -q
```

With the app running, ask: `How do I redeem an Amazon gift card?` The answer should include sources, and Moss Trace should show retrieval time, confidence, and the sources used.

## One-line explanation for the demo

"FastAPI serves the HTML, CSS, and JavaScript frontend as static files, and that JavaScript calls the chat routes in the same Python app. The existing retrieval and answer pipeline stays unchanged, so one container now runs the complete product."

## Real Moss retrieval

The app uses the official Python `moss` SDK. At startup it turns the existing Hubble chunks into Moss documents, creates or updates `hubble-gift-cards`, and loads that index into memory. Each question then uses Moss hybrid search with `alpha=0.6`. The result is converted back to the existing `Chunk` shape, so the answer, citation, confidence, handoff, API, and UI code do not change.

If Moss credentials are absent or startup fails, the app logs the reason and uses the previous local keyword scorer. Check `http://localhost:8000/health`: `retrieval.provider` must be `moss` for a real Moss demo. `local_fallback` means the demo is working but Moss is not active.

Required `.env` values:

```text
MOSS_PROJECT_ID=copy_from_moss_portal
MOSS_PROJECT_KEY=copy_the_once_visible_key
MOSS_INDEX_NAME=hubble-gift-cards
```

Never put the real Project Key in `.env.example`, GitHub, screenshots, or chat.

After Moss is active, run the retrieval-only benchmark:

```powershell
python scripts\benchmark_retrieval.py
```

It compares 15 questions against Moss and the previous scorer, calculates p50/p95, writes `docs\latency.md`, and refuses to publish local-fallback timings as Moss timings.

## Clarifying unclear support issues

For a message such as `My voucher is not working`, the pipeline does not retrieve a generic answer. It first asks which brand the voucher is for and what exact error is visible. The next customer message is joined to the original issue, then the normal Moss retrieval, citation, confidence, and handoff flow runs. This rule is in `app\services\clarification.py`; it is deterministic, easy to explain, and uses no extra model call. Answers stay friendly and professional without emojis.

## Real Intercom human handoff

The built-in chat creates a real Intercom conversation only when a handoff is needed. It sends the recent transcript, adds an internal note with confidence, handoff reason, and sources already checked, then assigns the conversation to the Support team. The AI pauses for that browser session. Human admin replies arriving through the signed Intercom webhook are stored and shown back in the same browser chat by a small five-second poll.

If Intercom is not configured or its API rejects the handoff, the UI does not claim success. It says the AI is paused and the conversation is only marked for review.

The customer endpoint also answers on its work-plan alias `POST /api/agent/chat`, and the full request/response contract for every route lives in `docs\api-contract.md`.

## Agent console (/agent)

Open `/agent` on the same server for the support-agent side. The console lists every escalated conversation with its handoff reason, shows the full transcript, and generates the AI's suggested answer for the latest customer message - editable before anything is sent. "Approve & send" posts the reply to the linked Intercom conversation as an admin comment, so it lands in the customer's chat like any human reply (and appears there immediately, with webhook dedupe preventing a double bubble). "Internal note" posts an Intercom note the customer never sees. If a conversation predates the Intercom link, the console runs the normal handoff creation first. The AI backend stays untouched: the console only reads pipeline state and calls the same services.

The console API is open by default for the local demo. Set `AGENT_CONSOLE_KEY` in `.env` before sharing a deployed URL; the page then asks for the key once and remembers it in the browser.

Private `.env` values needed:

```text
INTERCOM_ACCESS_TOKEN=rotated_token_from_intercom
INTERCOM_WEBHOOK_SECRET=secret_shown_for_the_webhook
INTERCOM_ADMIN_ID=11610928
INTERCOM_TEAM_ID=11621027
```

Do not put the token or webhook secret in `.env.example`, GitHub, chat, screenshots, or the ZIP. The ZIP contains placeholders only.

### Demo setup with ngrok

1. Start the one Python app: `docker compose up --build`.
2. In a second terminal run: `ngrok http 8000`.
3. Copy ngrok's HTTPS URL.
4. In Intercom webhook settings use: `https://YOUR-NGROK-URL/api/webhooks/intercom`.
5. Subscribe to customer/user conversation events and admin reply events. Copy the webhook signing secret into the private `.env`, then restart the app.
6. Check `http://localhost:8000/health`. `intercom_configured` must be `true`.
7. In the built-in chat, trigger handoff. Confirm a conversation appears in the Support inbox with the transcript and internal evidence note. Reply from Intercom and confirm the reply appears in the built-in chat.

The code is split into easy pieces: `adapters/intercom.py` makes API calls, `services/intercom_handoff.py` creates and assigns handoffs, `api_intercom.py` verifies and receives webhooks, and `services/handoff_store.py` keeps session mapping, event dedupe, and human replies in a small SQLite file.

### Brand typo handling during clarification

The clarification step remembers partial answers. If a customer first gives only a brand, it acknowledges that brand and asks only for the missing error. Brand names are normalized and compared with Python's built-in text similarity, so a clear typo such as `amezon` maps to the canonical KB brand `Amazon shopping`. The rule is deterministic and has no extra model call.

## Adding more knowledge bases

The app now loads every `.json` file inside `data\` at startup and merges all of their `brands` arrays into one retrieval index. The existing Hubble file stays where it is. To add another knowledge base:

1. Create a new file such as `data\new-store-gift-cards.json`.
2. Use the same top-level shape:

```json
{
  "brands": [
    {
      "brand_name": "Example Brand",
      "brand_key": "example-brand",
      "source_url": "https://example.com/public-policy",
      "validity": ["Valid for 12 months."],
      "restrictions": ["Cannot be exchanged for cash."],
      "how_to_redeem": [
        {"mode": "online", "steps": ["Open checkout.", "Enter the voucher code."]}
      ],
      "faqs": []
    }
  ]
}
```

3. Keep each `brand_key` unique across all files so document IDs do not collide.
4. Direct Python run: stop the server and start `scripts\run_backend.bat` again. The restart reloads every JSON file.
5. Docker run: run `docker compose down`, then `docker compose up --build`. Rebuilding is required because the JSON files are copied into the image.
6. Open `/health` and check that `kb_brands` and `kb_chunks` increased. Ask one question that only the new file can answer and check its citation.

`POST /api/ingest` still accepts one complete `{ "brands": [...] }` body and replaces the currently loaded in-memory index until restart. Use it for a temporary live refresh. For a durable knowledge base, save the JSON under `data\` and restart or rebuild as described above.

Startup is intentionally strict: a malformed JSON file or a file without a `brands` array is reported instead of being silently ignored.