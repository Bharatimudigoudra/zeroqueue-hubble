"""Real-handoff mechanics without calling Intercom."""
import hashlib
import hmac
import json


def _event(event_id="evt-1", author_type="admin", body="I can help now."):
    return {"id": event_id, "topic": "conversation.admin.replied",
            "data": {"item": {"id": "ic-convo-1", "conversation_message": {
                "id": f"part-{event_id}", "author": {"type": author_type},
                "body": f"<p>{body}</p>"}}}}


def _signed(client, payload, secret):
    raw = json.dumps(payload).encode()
    signature = "sha1=" + hmac.new(secret.encode(), raw, hashlib.sha1).hexdigest()
    return client.post("/api/webhooks/intercom", content=raw,
                       headers={"X-Hub-Signature": signature})


def test_webhook_requires_configured_secret(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "INTERCOM_WEBHOOK_SECRET", "")
    assert client.post("/api/webhooks/intercom", content=b"{}").status_code == 503


def test_bad_webhook_signature_is_rejected(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "INTERCOM_WEBHOOK_SECRET", "secret")
    response = client.post("/api/webhooks/intercom", content=b"{}",
                           headers={"X-Hub-Signature": "sha1=wrong"})
    assert response.status_code == 401


def test_webhook_dedupes_and_human_reply_returns_to_browser(client, monkeypatch, tmp_path):
    from app import config
    from app.services import handoff_store
    monkeypatch.setattr(config, "INTERCOM_WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(config, "STATE_DB_PATH", str(tmp_path / "state.db"))
    handoff_store.link("browser-session", "ic-convo-1")
    payload = _event()
    first = _signed(client, payload, "secret")
    second = _signed(client, payload, "secret")
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate_ignored"
    replies = client.get("/api/human-replies/browser-session").json()["replies"]
    assert [item["body"] for item in replies] == ["I can help now."]


def test_low_confidence_copy_is_honest_when_intercom_is_off(client):
    body = client.post("/api/chat", data={
        "session_id": "honest-copy", "message": "Can you reset my Netflix password?"
    }).json()
    assert body["status"] == "handoff"
    assert body["handoff_confirmed"] is False
    assert "marked this conversation for human review" in body["answer"]
    assert "not connected" in body["answer"]
