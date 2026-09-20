"""Chunking rules, pinned against the real data quirks."""
from app.services.chunking import brand_to_chunks, split_long_text

SAMPLE = {
    "rank": 2,
    "brand_name": "Amazon shopping",
    "brand_key": "amazon",
    "source_url": "https://offers.myhubble.money/buy-gift-card/amazon",
    "category": "E-commerce",
    "category_id": "ONE_STOP_SHOPS",
    "discount_percentage": 1.5,
    "about": "Amazon Shopping provides a vast selection of products.",
    "validity": ["Comes with 1 year validity."],
    "highlights": None,                      # null on 98/100 brands
    "tips": None,
    "how_to_redeem": [
        {"mode": "App", "steps": ["Download the Amazon App", "Add the voucher"]},
        {"mode": "ONLINE", "steps": ["Shop on amazon.in"]},
    ],
    "restrictions": ["Not eligible on Amazon Business marketplace."],
    "terms_and_conditions": "Para one.\n\nPara two.\n\nPara three.",
    "faqs": [{"question": "What is the validity?", "answer": "One year."}],
    "where_to_use": {"online_deeplink": "https://www.amazon.in/"},
    "balance_check_available": None,
}


def test_null_and_empty_fields_never_produce_chunks():
    chunks = brand_to_chunks(SAMPLE)
    assert chunks
    for c in chunks:
        assert c.text.strip()
        assert "null" not in c.text.lower()
        assert "undefined" not in c.text
    assert not any(c.section_kind == "highlights" for c in chunks)
    assert not any(c.section_kind == "tips" for c in chunks)


def test_redeem_modes_are_normalized_to_lowercase():
    kinds = [c.section_kind for c in brand_to_chunks(SAMPLE)]
    assert any(k.startswith("redeem-app") for k in kinds)
    assert any(k.startswith("redeem-online") for k in kinds)
    assert not any("ONLINE" in k for k in kinds)


def test_every_chunk_is_self_contained_and_carries_metadata():
    for c in brand_to_chunks(SAMPLE):
        assert c.text.startswith("Amazon shopping - ")
        assert c.safe_url == SAMPLE["source_url"]
        assert c.title == "Amazon shopping"
        assert c.category == "E-commerce"


def test_faqs_become_one_chunk_per_pair():
    faqs = [c for c in brand_to_chunks(SAMPLE) if c.section_kind.startswith("faq-")]
    assert len(faqs) == 1
    assert "What is the validity?" in faqs[0].text
    assert "One year." in faqs[0].text


def test_empty_faqs_and_missing_about_are_skipped_not_errored():
    bare = {"brand_name": "Bare", "brand_key": "bare", "rank": 99,
            "faqs": [], "about": None, "validity": [], "restrictions": [],
            "how_to_redeem": [], "terms_and_conditions": ""}
    assert brand_to_chunks(bare) == []


def test_long_terms_text_splits_with_paragraph_overlap():
    long_text = "\n\n".join(f"Paragraph {i + 1} " + "x" * 120 for i in range(30))
    parts = split_long_text(long_text, 600)
    assert len(parts) > 1
    for p in parts:
        assert len(p) <= 900            # overlap may exceed max slightly
    for prev, cur in zip(parts, parts[1:]):
        assert prev.split("\n")[-1] in cur      # shared overlap paragraph


def test_moss_metadata_values_are_strings():
    from app.services.moss_service import _metadata

    chunk = brand_to_chunks(SAMPLE)[0]
    metadata = _metadata(chunk)

    assert metadata
    assert all(isinstance(value, str) for value in metadata.values())
    assert metadata["rank"] == str(chunk.rank)
    assert metadata["discount_percentage"] == str(chunk.discount_percentage)
