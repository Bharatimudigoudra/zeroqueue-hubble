"""Hubble KB backend - FastAPI entrypoint. Run from the repo root:
    uvicorn app.main:app --port 8000        (or scripts\\run_backend.bat)

Serves the exact API contract the ZeroQueue web page speaks:
  GET  /health                  status pill (no secrets)
  POST /api/chat                one customer message (+ optional file)
  POST /api/agent/chat          documented alias of /api/chat (work plan)
  POST /api/handoff             "Talk to a human" button
  GET  /api/trace/{session_id}  the safe Moss Trace subset for the page
  POST /api/demo/reset          wipe demo state (x-demo-secret header)
  POST /api/ingest              replace the KB with a posted JSON body
  GET  /agent                   support-agent console (review + approve)
  GET  /api/agent/conversations handoff queue for the console
"""
import json

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config
from app.api_agent import router as agent_router
from app.api_intercom import router as intercom_router
from app.services import attachment_service, handoff_store, moss_service, pipeline

app = FastAPI(title="ZeroQueue + Hubble", version="1.0.0")
app.include_router(intercom_router)
app.include_router(agent_router)

# FastAPI serves the browser UI and API from one Python service.
STATIC_DIR = config.REPO_ROOT / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/agent", include_in_schema=False)
def agent_console_page():
    """Support-agent console: review AI answers, approve replies, add notes."""
    return FileResponse(STATIC_DIR / "agent.html")

# CORS stays available for optional direct API development clients.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Replaced by the boot loader / /api/ingest; exposed via /health.
KB_STATS = {"brands": 0, "chunks": 0}


class HandoffRequest(BaseModel):
    session_id: str
    reason: str = "customer_requested_human"


def _read_all_kb_files(data_dir=None) -> dict:
    """Merge every JSON knowledge base in data/ into one brands array.

    Each file must use the same simple shape: {"brands": [...]}. A bad file
    fails startup loudly instead of silently dropping knowledge.
    """
    directory = data_dir or config.DATA_DIR
    files = sorted(directory.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No JSON knowledge bases found in {directory}")
    merged = {"brands": []}
    for path in files:
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body.get("brands"), list):
            raise ValueError(f'{path.name} must contain a "brands" array')
        merged["brands"].extend(body["brands"])
    return merged


def _load_kb_files() -> None:
    """Boot: merge all data/*.json files and build one retrieval index."""
    try:
        kb = _read_all_kb_files()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Knowledge-base load failed: {exc}. POST /api/ingest to load one.")
        return
    brands, chunks = moss_service.load_from_kb(kb)
    KB_STATS.update(brands=brands, chunks=chunks)
    print(f"KB loaded from data/*.json: {brands} brands -> {chunks} chunks indexed.")


@app.on_event("startup")
def startup() -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _load_kb_files()


@app.get("/health")
def health():
    return {
        "service": "hubble-kb-backend",
        "status": "ok",
        "database": "ok",                  # in-memory index: always ok
        "mock_mode": config.MOCK_MODE,     # safe to expose: not a secret
        "ocr_provider": "tesseract",
        "kb_brands": KB_STATS["brands"],
        "kb_chunks": KB_STATS["chunks"],
        "llm_configured": bool(config.GROQ_API_KEY),
        "retrieval": moss_service.status(),
        "intercom_configured": all((config.INTERCOM_ACCESS_TOKEN, config.INTERCOM_WEBHOOK_SECRET, config.INTERCOM_ADMIN_ID, config.INTERCOM_TEAM_ID)),
    }


@app.post("/api/chat")
async def chat(session_id: str = Form(...),
               message: str = Form(""),
               file: UploadFile = File(default=None)):
    """One customer message (plus an optional text/image file)."""
    if not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required.")

    # Read the attachment first: its text becomes part of the question.
    attachment_text, attachment_note = "", None
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=400,
                                detail=f"File is over {config.MAX_UPLOAD_MB} MB.")
        try:
            attachment_text, attachment_note = attachment_service.extract(
                file.filename, data)
        except attachment_service.UnsupportedFileError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if not message.strip() and not attachment_text:
        raise HTTPException(
            status_code=400,
            detail="Send a message, or attach a file with readable text in it.")

    result = pipeline.run_pipeline(session_id, message, attachment_text)
    return {**result, "attachment_note": attachment_note}


@app.post("/api/agent/chat")
async def agent_chat_alias(session_id: str = Form(...),
                           message: str = Form(""),
                           file: UploadFile = File(default=None)):
    """Alias of /api/chat under the path named in the UI work plan."""
    return await chat(session_id=session_id, message=message, file=file)


@app.get("/api/human-replies/{session_id}")
def human_replies(session_id: str, after_id: int = 0):
    return {"replies": handoff_store.replies_after(session_id, after_id)}


@app.post("/api/handoff")
def request_handoff(req: HandoffRequest):
    """Explicit 'Talk to a human' button in the chat."""
    if not req.session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required.")
    return {**pipeline.request_handoff(req.session_id), "attachment_note": None}


@app.get("/api/trace/{session_id}")
def get_trace(session_id: str):
    return pipeline.trace_for(session_id)


@app.post("/api/demo/reset")
def demo_reset(x_demo_secret: str = Header(default="")):
    """Development/demo only: wipe session state so the demo can be re-run."""
    if not config.DEMO_RESET_SECRET or x_demo_secret != config.DEMO_RESET_SECRET:
        raise HTTPException(status_code=403, detail="invalid demo secret")
    pipeline.reset_all()
    return {"status": "reset"}


@app.post("/api/ingest")
def ingest(kb: dict):
    """Accept a full KB JSON body ({ "brands": [...] }) and re-index.
    This is how a new extraction lands without a restart."""
    if not isinstance(kb.get("brands"), list):
        raise HTTPException(
            status_code=400,
            detail='Expected the KB JSON object with a "brands" array.')
    brands, chunks = moss_service.load_from_kb(kb)
    KB_STATS.update(brands=brands, chunks=chunks)
    pipeline.reset_all()     # traces refer to the old KB - start clean
    print(f"Re-ingested via API: {brands} brands -> {chunks} chunks.")
    return {"status": "ingested", "brands": brands, "chunks": chunks}
