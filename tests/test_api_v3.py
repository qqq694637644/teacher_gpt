import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import LocatorIndexLoadError
from app.main import create_app
from app.services.index_compiler import LocatorIndexCompiler
from tests.helpers import complete_manifest


def write_index(tmp_path):
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    path = tmp_path / "compiled_locator_index.json"
    path.write_text(
        json.dumps(compiled.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_api_exposes_only_health_and_section_locator(tmp_path) -> None:
    settings = Settings(
        locator_index_path=write_index(tmp_path),
        require_api_key=False,
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "data_version": "3",
            "book_id": "dip4e",
            "section_count": 16,
            "page_count": 4,
        }

        response = client.get("/gpt/section-locators/2.6.5")
        assert response.status_code == 200
        payload = response.json()
        assert payload["title"] == "Spatial Operations"
        assert payload["printed_section_id"] == "2.6"
        assert payload["section_kind"] == "learning_unit"

        assert client.get("/gpt/sections/2.6.6").status_code == 404
        assert client.get("/gpt/search?q=spatial").status_code == 404
        assert client.get("/gpt/figures/2.41").status_code == 404
        assert client.post("/admin/books/upload").status_code == 404


def test_api_returns_strict_not_found_error(tmp_path) -> None:
    settings = Settings(
        locator_index_path=write_index(tmp_path),
        require_api_key=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/gpt/section-locators/2.6.99")

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "SECTION_NOT_FOUND",
        "detail": "Section id does not exist: 2.6.99",
    }


def test_application_startup_fails_without_complete_index(tmp_path) -> None:
    settings = Settings(
        locator_index_path=tmp_path / "missing.json",
        require_api_key=False,
    )
    with pytest.raises(LocatorIndexLoadError, match="not found"):
        with TestClient(create_app(settings)):
            pass
