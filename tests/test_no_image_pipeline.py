import json

import fitz
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.services.figure_service import FigureService
from app.services.pdf_ingestor import PDFIngestor
from app.services.storage import JsonStore


LEGACY_IMAGE_KEYS = {"image_url", "page_image_url", "image_path"}


def test_openapi_has_no_image_transport_contract() -> None:
    schema = create_app().openapi()
    serialized = json.dumps(schema)

    assert "/assets/books/{book_id}/{kind}/{filename}" not in schema["paths"]
    assert "render_pages" not in serialized
    assert "image_url" not in serialized
    assert "page_image_url" not in serialized
    assert "content_status" not in serialized
    assert "window_status" in serialized
    assert "data_version" in serialized


def test_figure_service_rejects_legacy_image_fields(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path)
    store = JsonStore(settings)
    store.save_json("book", "book_meta.json", {"book_id": "book", "version": "2"})
    store.save_json(
        "book",
        "figure_map.json",
        {
            "1.1": {
                "figure_id": "1.1",
                "caption": "A figure caption.",
                "page_number": 1,
                "context": "Nearby textbook text.",
                "image_url": "https://legacy.example/figure.png",
                "page_image_url": "https://legacy.example/page.png",
                "image_path": "figures/figure.png",
                "related_section_ids": ["1.1"],
            }
        },
    )

    with pytest.raises(ValidationError, match="image_url|page_image_url|image_path"):
        FigureService(store=store).get_figure("book", "Fig 1.1")


def test_ingestion_writes_text_metadata_without_image_assets(tmp_path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "1.1 INTRODUCTION\nFIGURE 1.1 Sample caption")
    document.save(pdf_path)
    document.close()

    settings = Settings(data_dir=tmp_path / "data")
    result = PDFIngestor(settings).ingest(book_id="sample", pdf_path=pdf_path, overwrite=True)
    book_dir = settings.books_dir / "sample"

    assert result["page_count"] == 1
    assert not (book_dir / "pages").exists()
    assert not (book_dir / "figures").exists()
    meta = json.loads((book_dir / "book_meta.json").read_text(encoding="utf-8"))
    assert meta["version"] == "2"
    pages = json.loads((book_dir / "page_text.json").read_text(encoding="utf-8"))["pages"]
    assert pages[0]["lines"]
    assert "font_size" in pages[0]["lines"][0]

    for json_path in book_dir.rglob("*.json"):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload)
        for key in LEGACY_IMAGE_KEYS:
            assert f'"{key}"' not in serialized
