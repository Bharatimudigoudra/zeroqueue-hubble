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


def test_clean_body_preserves_paragraphs_and_line_breaks():
    from app.api_intercom import clean_body

    body = "<p><strong>Hello</strong><br>Second line</p><p>Next paragraph</p>"

    assert clean_body(body) == "Hello\nSecond line\nNext paragraph"


def test_clean_body_turns_html_list_items_into_plain_bullets():
    from app.api_intercom import clean_body

    body = "<p>Please try:</p><ul><li>Open settings</li><li>Try again</li></ul>"

    assert clean_body(body) == "Please try:\n- Open settings\n- Try again"


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


def test_assignment_uses_intercom_parts_contract(monkeypatch):
    from app import config
    from app.adapters import intercom

    monkeypatch.setattr(config, "INTERCOM_ADMIN_ID", "admin-123")
    monkeypatch.setattr(config, "INTERCOM_TEAM_ID", "team-456")
    calls = []
    monkeypatch.setattr(
        intercom,
        "_post",
        lambda path, body: calls.append((path, body)) or {"type": "conversation_part"},
    )

    intercom.assign("conversation-789")

    assert calls == [(
        "/conversations/conversation-789/parts",
        {
            "message_type": "assignment",
            "type": "team",
            "admin_id": "admin-123",
            "assignee_id": "team-456",
        },
    )]


def test_intercom_http_error_log_names_endpoint_without_token(monkeypatch, caplog):
    import httpx
    import pytest
    from app import config
    from app.adapters import intercom

    monkeypatch.setattr(config, "INTERCOM_ACCESS_TOKEN", "never-log-this-token")
    request = httpx.Request("POST", "https://api.intercom.io/conversations/c1/parts")
    response = httpx.Response(403, request=request, text='{"error":"forbidden"}')
    monkeypatch.setattr(intercom.httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(httpx.HTTPStatusError):
        intercom.assign("c1")

    assert "/conversations/c1/parts" in caplog.text
    assert "HTTP 403" in caplog.text
    assert "never-log-this-token" not in caplog.text



def test_create_contact_preserves_role_for_conversation_from_block(monkeypatch):
    from app.adapters import intercom

    calls = []

    def fake_post(path, body):
        calls.append((path, body))
        if path == "/contacts":
            return {"type": "contact", "id": "contact-123", "role": "lead"}
        if path == "/conversations":
            return {"type": "user_message", "conversation_id": "conversation-456"}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(intercom, "_post", fake_post)
    contact = intercom.create_contact("zeroqueue-browser-session")
    conversation_id = intercom.create_conversation(contact, "ZeroQueue web handoff")

    assert contact == {"id": "contact-123", "role": "lead"}
    assert conversation_id == "conversation-456"
    assert calls[1] == (
        "/conversations",
        {
            "from": {"type": "lead", "id": "contact-123"},
            "body": "ZeroQueue web handoff",
            "message_type": "inapp",
        },
    )


def test_existing_user_search_preserves_user_role(monkeypatch):
    import httpx
    from app.adapters import intercom

    request = httpx.Request("POST", "https://api.intercom.io/contacts")
    conflict = httpx.Response(409, request=request)

    def fake_post(path, body):
        if path == "/contacts":
            raise httpx.HTTPStatusError("conflict", request=request, response=conflict)
        if path == "/contacts/search":
            return {"data": [{"id": "user-789", "role": "user"}]}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(intercom, "_post", fake_post)
    assert intercom.create_contact("existing-session") == {
        "id": "user-789", "role": "user"}



def test_operator_workflow_reply_returns_to_browser(client, monkeypatch, tmp_path):
    from app import config
    from app.services import handoff_store

    monkeypatch.setattr(config, "INTERCOM_WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(config, "STATE_DB_PATH", str(tmp_path / "operator-state.db"))
    handoff_store.link("operator-browser-session", "ic-convo-1")
    payload = _event(
        event_id="operator-event-1",
        author_type="bot",
        body="Thanks for reaching out! A human agent has been notified and will reply here shortly.",
    )
    payload["topic"] = "conversation.operator.replied"

    response = _signed(client, payload, "secret")

    assert response.json()["status"] == "accepted"
    replies = client.get(
        "/api/human-replies/operator-browser-session").json()["replies"]
    assert [item["body"] for item in replies] == [
        "Thanks for reaching out! A human agent has been notified and will reply here shortly."]


def test_non_reply_admin_event_is_not_shown_as_human_reply(client, monkeypatch, tmp_path):
    from app import config
    from app.services import handoff_store

    monkeypatch.setattr(config, "INTERCOM_WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(config, "STATE_DB_PATH", str(tmp_path / "note-state.db"))
    handoff_store.link("note-browser-session", "ic-convo-1")
    payload = _event(
        event_id="admin-note-event",
        author_type="admin",
        body="Internal note that must stay inside Intercom",
    )
    payload["topic"] = "conversation.admin.noted"

    response = _signed(client, payload, "secret")

    assert response.json()["status"] == "accepted"
    replies = client.get(
        "/api/human-replies/note-browser-session").json()["replies"]
    assert replies == []
