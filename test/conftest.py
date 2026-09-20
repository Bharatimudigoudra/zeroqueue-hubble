import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

# Isolate the test suite from a developer's private .env. These values are set
# before app.config is imported, so tests never call live Groq, Moss, or
# Intercom services and cannot depend on local credentials.
os.environ.update({
    "MOCK_MODE": "true",
    "GROQ_API_KEY": "",
    "MOSS_PROJECT_ID": "",
    "MOSS_PROJECT_KEY": "",
    "MOSS_INDEX_NAME": "hubble-gift-cards",
    "INTERCOM_ACCESS_TOKEN": "",
    "INTERCOM_WEBHOOK_SECRET": "",
    "INTERCOM_ADMIN_ID": "",
    "INTERCOM_TEAM_ID": "",
    "DEMO_RESET_SECRET": "dev-reset-secret",
    "STATE_DB_FILE": "zeroqueue-test-state.db",
})


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
