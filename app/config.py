"""Central configuration.

Every secret or environment-specific value is read here, from environment
variables. This project has exactly ONE .env file, at the repo root. We
load it by hand (no extra package): each line is KEY=VALUE, the FIRST
occurrence of a key wins, and real environment variables win over .env.
".env" is listed in .gitignore so it is never committed. Real keys live
only in ".env" - never in code, never in chat.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]   # project root (app, data, uploads)


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, # comments. Existing env wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(REPO_ROOT / ".env")

PORT = int(os.environ.get("PORT", "8000"))

# MOCK_MODE=true (default): no external paid API calls. The Groq adapter
# is skipped and answers are quoted from the best chunk instead.
MOCK_MODE = os.environ.get("MOCK_MODE", "true").strip().lower() == "true"

CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "http://localhost:8000").split(",") if o.strip()]

# Protects POST /api/demo/reset so strangers cannot wipe the demo state.
DEMO_RESET_SECRET = os.environ.get("DEMO_RESET_SECRET", "dev-reset-secret")

# --- LLM (Groq free tier; only used when MOCK_MODE=false) ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

# --- Attachments / OCR ---
UPLOAD_DIR = REPO_ROOT / "uploads"
MAX_UPLOAD_MB = float(os.environ.get("MAX_UPLOAD_MB", "15"))
TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "").strip()

# --- Moss in-process retrieval ---
MOSS_PROJECT_ID = os.environ.get("MOSS_PROJECT_ID", "")
MOSS_PROJECT_KEY = os.environ.get("MOSS_PROJECT_KEY", "")
MOSS_INDEX_NAME = os.environ.get("MOSS_INDEX_NAME", "hubble-gift-cards")

# Intercom: real human handoff. Keep real values only in the private .env.
INTERCOM_ACCESS_TOKEN = os.environ.get("INTERCOM_ACCESS_TOKEN", "")
INTERCOM_WEBHOOK_SECRET = os.environ.get("INTERCOM_WEBHOOK_SECRET", "")
INTERCOM_API_BASE = os.environ.get("INTERCOM_API_BASE", "https://api.intercom.io")
INTERCOM_ADMIN_ID = os.environ.get("INTERCOM_ADMIN_ID", "")
INTERCOM_TEAM_ID = os.environ.get("INTERCOM_TEAM_ID", "")
STATE_DB_PATH = str(REPO_ROOT / os.environ.get("STATE_DB_FILE", "zeroqueue-state.db"))

DATA_DIR = REPO_ROOT / "data"
# Kept for scripts/tests that intentionally target the original Hubble file.
KB_FILE = DATA_DIR / "hubble-gift-cards-top100.json"

