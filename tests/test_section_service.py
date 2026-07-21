import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.section_service import SectionService
from app.services.storage import JsonStore


def _write_pack(store: JsonStore, book_id: str) -> None:
    store.save_json(book_id, "section_aliases.json", {})
    store.save_json(
        book_id,
        "section_packs/1.1.json",
        {
            "book_id": book_id,
            "section_id": "1.1",
            "resolved_section_id": "1.1",
            "parent_section_id": "1",
            "title": "Long Section",
            "page_start": 1,
            "page_end": 1,
            "section_type": "official",
            "summary": "A long section.",
            "text_blocks": [
                {"type": "paragraph", "text": "abcdefghij", "page_number": 1},
                {"type": "paragraph", "text": "klmnopqrst", "page_number": 1},
            ],
            "figures": [
                {
                    "figure_id": "1.1",
                    "caption": "Figure metadata.",
                    "page_number": 1,
                }
            ],
            "equations": [],
            "examples": [],
            "source_pages": [{"page_index": 0, "page_number": 1}],
            "previous_sections": [],
            "next_sections": [],
            "prerequisites": [],
            "warnings": [],
        },
    )


def test_get_section_marks_partial_text_window(tmp_path):
    settings = Settings(data_dir=tmp_path)
    store = JsonStore(settings)
    _write_pack(store, "book")

    pack = SectionService(store=store).get_section("book", "1.1", text_limit=12)

    assert pack.content.content_status == "partial"
    assert pack.content.is_truncated is True
    assert pack.content.total_chars == 20
    assert pack.content.returned_chars == 12
    assert pack.content.next_offset == 12
    assert "".join(block.text for block in pack.text_blocks) == "abcdefghijkl"
    assert pack.warnings


def test_get_section_continues_from_next_offset(tmp_path):
    settings = Settings(data_dir=tmp_path)
    store = JsonStore(settings)
    _write_pack(store, "book")

    pack = SectionService(store=store).get_section("book", "1.1", text_offset=12, text_limit=12)

    assert pack.content.content_status == "partial"
    assert pack.content.is_truncated is True
    assert pack.content.text_offset == 12
    assert pack.content.returned_chars == 8
    assert pack.content.next_offset is None
    assert "".join(block.text for block in pack.text_blocks) == "mnopqrst"


def test_get_section_without_text_limit_is_complete(tmp_path):
    settings = Settings(data_dir=tmp_path)
    store = JsonStore(settings)
    _write_pack(store, "book")

    pack = SectionService(store=store).get_section("book", "1.1")

    assert pack.content.content_status == "complete"
    assert pack.content.is_truncated is False
    assert pack.content.total_chars == 20
    assert pack.content.returned_chars == 20
    assert pack.content.next_offset is None
    assert "".join(block.text for block in pack.text_blocks) == "abcdefghijklmnopqrst"


def test_get_section_rejects_legacy_image_fields(tmp_path):
    settings = Settings(data_dir=tmp_path)
    store = JsonStore(settings)
    _write_pack(store, "book")
    raw = store.load_json("book", "section_packs/1.1.json")
    raw["source_pages"][0]["image_url"] = "https://legacy.example/page.png"
    store.save_json("book", "section_packs/1.1.json", raw)

    with pytest.raises(ValidationError, match="image_url"):
        SectionService(store=store).get_section("book", "1.1")
