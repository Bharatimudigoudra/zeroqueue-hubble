"""API contract: the same shapes the ZeroQueue page consumes."""


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["kb_brands"] == 100
    assert body["kb_chunks"] > 800


def test_chat_answers_with_citations_and_trace(client):
    resp = client.post("/api/chat", data={
        "session_id": "t1", "message": "how do I redeem an amazon gift card?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "answered"
    assert "Sources: [1]" in body["answer"]
    assert body["citations"][0]["label"].startswith("[1] ")
    trace = body["trace"]
    assert trace["state"] == "answered"
    assert trace["confidence_band"] in ("medium", "high")
    assert trace["source_count"] >= 1
    assert trace["retrieval_ms"] is not None and trace["total_ms"] is not None


def test_handoff_then_ai_stays_silent(client):
    resp = client.post("/api/handoff", json={"session_id": "t2"})
    assert resp.json()["status"] == "handoff"
    assert resp.json()["trace"]["state"] == "escalated"
    resp = client.post("/api/chat", data={"session_id": "t2",
                                          "message": "any discount on zepto?"})
    body = resp.json()
    assert body["status"] == "handoff"
    assert "AI is paused" in body["answer"]


def test_low_confidence_hands_off(client):
    resp = client.post("/api/chat", data={
        "session_id": "t3", "message": "zzz qqq nonexistent gibberish"})
    body = resp.json()
    assert body["status"] == "handoff"
    assert body["trace"]["handoff_reason"] == "low_confidence_no_reliable_answer"


def test_text_attachment_is_read(client):
    resp = client.post(
        "/api/chat",
        data={"session_id": "t4", "message": "where do I use this?"},
        files={"file": ("note.txt", b"Amazon voucher code ABCD-1234\n", "text/plain")})
    body = resp.json()
    assert resp.status_code == 200
    assert body["attachment_note"].startswith("Read 1 line from note.txt")


def test_unsupported_attachment_gets_honest_400(client):
    resp = client.post(
        "/api/chat",
        data={"session_id": "t5", "message": "what is this?"},
        files={"file": ("model.blend", b"binary", "application/octet-stream")})
    assert resp.status_code == 400
    assert "cannot read" in resp.json()["detail"]


def test_ingest_replaces_the_index(client):
    resp = client.post("/api/ingest", json={"brands": [{
        "rank": 1, "brand_name": "Testbrand", "brand_key": "testbrand",
        "source_url": "https://example.com", "validity": ["Valid 6 months."],
        "restrictions": [], "how_to_redeem": [], "terms_and_conditions": "",
        "faqs": []}]})
    assert resp.json() == {"status": "ingested", "brands": 1, "chunks": 1}
    resp = client.post("/api/chat", data={"session_id": "t6",
                                          "message": "testbrand validity?"})
    assert "Testbrand" in resp.json()["answer"]


def test_demo_reset_requires_secret(client):
    assert client.post("/api/demo/reset").status_code == 403
    resp = client.post("/api/demo/reset",
                       headers={"x-demo-secret": "dev-reset-secret"})
    assert resp.json() == {"status": "reset"}


def test_python_frontend_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "ZeroQueue" in response.text
    assert "/static/app.js" in response.text


def test_frontend_assets_are_served(client):
    assert client.get("/static/styles.css").status_code == 200
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert 'fetch("/api/chat"' in script.text


def test_health_reports_retrieval_provider(client):
    retrieval = client.get("/health").json()["retrieval"]
    assert retrieval["provider"] in ("moss", "local_fallback")
    assert retrieval["index"] == "hubble-gift-cards"


def test_ambiguous_voucher_issue_asks_for_brand_and_error(client):
    body = client.post("/api/chat", data={
        "session_id": "clarify-1", "message": "My voucher is not working"
    }).json()
    assert body["status"] == "clarifying"
    assert "Which brand" in body["answer"]
    assert "what exact error" in body["answer"]
    assert body["citations"] == []
    assert body["trace"]["state"] == "clarifying"
    assert body["trace"]["retrieval_ms"] is None


def test_clarifier_followup_is_combined_then_answered(client):
    first = client.post("/api/chat", data={
        "session_id": "clarify-2", "message": "My voucher is not working"
    }).json()
    assert first["status"] == "clarifying"
    second = client.post("/api/chat", data={
        "session_id": "clarify-2", "message": "Amazon says invalid code"
    }).json()
    assert second["status"] == "answered"
    assert second["citations"]
    assert second["trace"]["retrieval_ms"] is not None


def test_brand_without_error_asks_only_for_error(client):
    body = client.post("/api/chat", data={
        "session_id": "clarify-3", "message": "My Amazon voucher is not working"
    }).json()
    assert body["status"] == "clarifying"
    assert body["answer"].startswith("Got it - Amazon shopping. What exact error")
    assert "Which brand" not in body["answer"]


def test_misspelled_brand_only_followup_is_recognized_and_asks_only_error(client):
    first = client.post("/api/chat", data={
        "session_id": "clarify-typo", "message": "My voucher is not working"
    }).json()
    assert "Which brand" in first["answer"]
    second = client.post("/api/chat", data={
        "session_id": "clarify-typo", "message": "amezon"
    }).json()
    assert second["status"] == "clarifying"
    assert second["answer"] == ("Got it - Amazon shopping. What exact error or "
                                "message do you see?")
    assert "Which brand" not in second["answer"]


def test_misspelled_brand_state_is_kept_until_error_then_retrieves(client):
    client.post("/api/chat", data={
        "session_id": "clarify-typo-complete", "message": "My voucher is not working"
    })
    client.post("/api/chat", data={
        "session_id": "clarify-typo-complete", "message": "amezon"
    })
    final = client.post("/api/chat", data={
        "session_id": "clarify-typo-complete", "message": "It says invalid code"
    }).json()
    assert final["status"] == "answered"
    assert final["citations"]
    assert final["citations"][0]["label"].startswith("[1] Amazon")


def test_multiple_json_knowledge_bases_are_merged(tmp_path):
    import json
    from app.main import _read_all_kb_files
    first = {"brands": [{"brand_name": "Alpha", "brand_key": "alpha"}]}
    second = {"brands": [{"brand_name": "Beta", "brand_key": "beta"}]}
    (tmp_path / "01-alpha.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "02-beta.json").write_text(json.dumps(second), encoding="utf-8")
    merged = _read_all_kb_files(tmp_path)
    assert [brand["brand_name"] for brand in merged["brands"]] == ["Alpha", "Beta"]


def test_bad_extra_knowledge_base_fails_loudly(tmp_path):
    import json
    import pytest
    from app.main import _read_all_kb_files
    (tmp_path / "bad.json").write_text(json.dumps({"documents": []}), encoding="utf-8")
    with pytest.raises(ValueError, match='must contain a "brands" array'):
        _read_all_kb_files(tmp_path)


def test_yes_after_handoff_offer_completes_handoff(client, monkeypatch):
    from app.services import answer_service, intercom_handoff, pipeline

    pipeline.reset_all()
    monkeypatch.setattr(
        answer_service, "build_answer",
        lambda query, passages: (
            "I do not have a reliable answer. Would you like me to connect "
            "you with a support agent?\n\nSources: [1] Test",
            [{"label": "[1] Test", "url": None}],
        ),
    )
    sent = []
    monkeypatch.setattr(
        intercom_handoff, "send",
        lambda *args, **kwargs: sent.append((args, kwargs)) or
        {"confirmed": True, "conversation_id": "ic-test"},
    )

    first = client.post("/api/chat", data={
        "session_id": "handoff-offer-yes",
        "message": "How do I redeem an Amazon gift card?",
    }).json()
    assert first["status"] == "answered"
    assert "connect you with a support agent" in first["answer"]

    second = client.post("/api/chat", data={
        "session_id": "handoff-offer-yes", "message": "yes"
    }).json()
    assert second["status"] == "handoff"
    assert second["handoff_confirmed"] is True
    assert second["trace"]["handoff_reason"] == "customer_requested_human"
    assert "sent this conversation" in second["answer"]
    assert len(sent) == 1
    transcript = sent[0][0][5]
    assert {"role": "customer", "text": "yes"} in transcript


def test_no_after_handoff_offer_keeps_ai_active(client, monkeypatch):
    from app.services import answer_service, intercom_handoff, pipeline

    pipeline.reset_all()
    monkeypatch.setattr(
        answer_service, "build_answer",
        lambda query, passages: (
            "Would you like me to connect you with a support agent?", []),
    )
    monkeypatch.setattr(
        intercom_handoff, "send",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no handoff")),
    )
    client.post("/api/chat", data={
        "session_id": "handoff-offer-no",
        "message": "How do I redeem an Amazon gift card?",
    })
    second = client.post("/api/chat", data={
        "session_id": "handoff-offer-no", "message": "no thanks"
    }).json()
    assert second["status"] == "answered"
    assert "AI will stay active" in second["answer"]
