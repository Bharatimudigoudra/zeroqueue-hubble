"""Brand scoping for the local retrieval fallback."""
from app.services import moss_service, pipeline
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
