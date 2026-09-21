"""Brand scoping for the local retrieval fallback."""
from app.services import confidence, moss_service, pipeline
from app.services.chunking import Chunk


def _chunk(chunk_id: str, brand: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        title=brand,
        text=f"{brand} - support: voucher invalid code help",
        section="Support",
        section_kind="support",
        brand_key=brand.lower().replace(" ", "-"),
    )


def test_confirmed_brand_limits_local_fallback_before_scoring(monkeypatch):
    monkeypatch.setattr(moss_service, "_MOSS_READY", False)
    monkeypatch.setattr(moss_service, "_INDEX", [
        _chunk("amazon", "Amazon shopping"),
        _chunk("ikea", "IKEA"),
        _chunk("luzo", "Luzo"),
    ])

    result = moss_service.search(
        "voucher invalid code help", top_k=10, brand="Amazon shopping")

    assert result["passages"]
    assert {chunk.title for chunk in result["passages"]} == {"Amazon shopping"}


def test_no_confirmed_brand_keeps_global_local_search(monkeypatch):
    monkeypatch.setattr(moss_service, "_MOSS_READY", False)
    monkeypatch.setattr(moss_service, "_INDEX", [
        _chunk("amazon", "Amazon shopping"),
        _chunk("ikea", "IKEA"),
    ])

    result = moss_service.search("voucher invalid code help", top_k=10)

    assert {chunk.title for chunk in result["passages"]} == {
        "Amazon shopping", "IKEA"}


def test_ocr_brand_is_passed_to_retrieval(monkeypatch):
    seen = {}
    amazon = _chunk("amazon", "Amazon shopping")

    def fake_search(query, top_k=3, brand=""):
        seen["query"] = query
        seen["brand"] = brand
        return {"passages": [amazon], "retrieval_ms": 0.1,
                "provider": "local_fallback"}

    pipeline.reset_all()
    monkeypatch.setattr(moss_service, "search", fake_search)
    monkeypatch.setattr(moss_service, "brand_names", lambda: ["Amazon shopping", "IKEA"])

    pipeline.run_pipeline(
        "ocr-brand-scope",
        "What should I check?",
        "Amazon shopping voucher. The claim code is invalid.",
    )

    assert seen["brand"] == "Amazon shopping"
    assert "Amazon shopping" in seen["query"]


def _intent_chunk(chunk_id: str, section: str, text: str) -> Chunk:
    return Chunk(
        id=chunk_id, title="Amazon shopping", text=text, section=section,
        section_kind="test", brand_key="amazon",
    )


def test_redeem_intent_outranks_ocr_noise_and_answers(monkeypatch):
    monkeypatch.setattr(moss_service, "_MOSS_READY", False)
    monkeypatch.setattr(moss_service, "_INDEX", [
        _intent_chunk("terms", "Terms and conditions",
                      "Voucher limits, cash rules, business marketplace restrictions"),
        _intent_chunk("redeem", "How to redeem (app)",
                      "Open Amazon Pay, choose Gift Card, enter the code and add it"),
    ])

    result = moss_service.search(
        "What should I check, and how do I redeem it correctly? "
        "Attachment text (OCR): IKEA outlet max fashion receipt invalid random words",
        brand="Amazon shopping",
    )

    assert result["passages"][0].id == "redeem"
    assert confidence.band(result["passages"]) != "low"


def test_uncovered_brand_intent_stays_low_confidence(monkeypatch):
    monkeypatch.setattr(moss_service, "_MOSS_READY", False)
    monkeypatch.setattr(moss_service, "_INDEX", [
        _intent_chunk("redeem", "How to redeem (app)",
                      "Open Amazon Pay, choose Gift Card, enter the code"),
    ])

    result = moss_service.search(
        "Can I change the delivery address after dispatch?",
        brand="Amazon shopping",
    )

    assert confidence.band(result["passages"]) == "low"
