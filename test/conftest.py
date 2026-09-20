import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

# Keep the demo-reset contract deterministic even when a developer's private
# .env overrides the local value.
os.environ["DEMO_RESET_SECRET"] = "dev-reset-secret"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
