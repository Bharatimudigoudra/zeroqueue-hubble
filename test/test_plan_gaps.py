"""Work-plan gap closures: /api/agent/chat alias and Intercom GET retrieval."""


def test_agent_chat_alias_behaves_exactly_like_chat(client):
    direct = client.post("/api/chat", data={
        "session_id": "alias-direct",
        "message": "How do I redeem an Amazon gift card?"}).json()
    alias = client.post("/api/agent/chat", data={
        "session_id": "alias-via-agent",
        "message": "How do I redeem an Amazon gift card?"}).json()
    assert alias["status"] == direct["status"] == "answered"
    assert alias["answer"] == direct["answer"]
    assert alias["citations"] == direct["citations"]


def test_agent_chat_alias_keeps_validation(client):
    assert client.post("/api/agent/chat", data={
        "session_id": "alias-empty", "message": ""}).status_code == 400


def test_get_conversation_uses_intercom_get_contract(monkeypatch):
    from app.adapters import intercom
    calls = []
    monkeypatch.setattr(intercom, "_get",
                        lambda path: calls.append(path) or {"state": "open"})
    result = intercom.get_conversation("ic-123")
    assert calls == ["/conversations/ic-123"]
    assert result["state"] == "open"


def test_console_detail_shows_live_intercom_state(client, monkeypatch, tmp_path):
    from app import config
    from app.adapters import intercom
    from app.services import handoff_store
    monkeypatch.setattr(config, "STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(config, "INTERCOM_ACCESS_TOKEN", "token")
    monkeypatch.setattr(config, "INTERCOM_ADMIN_ID", "admin-1")
    monkeypatch.setattr(config, "INTERCOM_TEAM_ID", "team-1")
    monkeypatch.setattr(intercom, "_post", lambda path, body: {"id": "p-1"})
    monkeypatch.setattr(intercom, "_get",
                        lambda path: {"id": "ic-77", "state": "open", "open": True})

    client.post("/api/chat", data={
        "session_id": "console-snapshot", "message": "Can you reset my Netflix password?"})
    handoff_store.link("console-snapshot", "ic-77")

    detail = client.get("/api/agent/conversations/console-snapshot").json()
    assert detail["intercom_conversation"] == {
        "conversation_id": "ic-77", "state": "open", "open": True}


def test_console_detail_offline_has_no_intercom_snapshot(client):
    client.post("/api/chat", data={
        "session_id": "console-no-snap", "message": "Can you reset my Netflix password?"})
    detail = client.get("/api/agent/conversations/console-no-snap").json()
    assert detail["intercom_conversation"] is None
