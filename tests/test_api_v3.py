import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ExerciseIndexLoadError, LocatorIndexLoadError
from app.main import create_app
from app.services.index_compiler import LocatorIndexCompiler
from tests.helpers import complete_exercise_index, complete_manifest


def write_index(tmp_path):
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    path = tmp_path / "compiled_locator_index.json"
    path.write_text(
        json.dumps(compiled.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def write_exercise_index(tmp_path):
    compiled = complete_exercise_index()
    path = tmp_path / "compiled_exercise_index.json"
    path.write_text(
        json.dumps(compiled.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_api_serves_section_and_exercise_locators(tmp_path) -> None:
    settings = Settings(
        locator_index_path=write_index(tmp_path),
        exercise_index_path=write_exercise_index(tmp_path),
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
            "exercise_catalog_status": "ready",
            "exercise_count": 2,
        }

        response = client.get("/gpt/section-locators/2.6.5")
        assert response.status_code == 200
        payload = response.json()
        assert payload["title"] == "Spatial Operations"
        assert payload["printed_section_id"] == "2.6"
        assert payload["section_kind"] == "learning_unit"

        exercise = client.get("/gpt/exercise-locators/2.14")
        assert exercise.status_code == 200
        assert exercise.json()["exercise_id"] == "2.14"
        assert exercise.json()["starred"] is True

        chapter = client.get("/gpt/chapters/2/exercises")
        assert chapter.status_code == 200
        assert chapter.json()["exercise_ids"] == ["2.14", "2.15"]

        assert client.get("/gpt/sections/2.6.6").status_code == 404
        assert client.get("/gpt/search?q=spatial").status_code == 404
        assert client.get("/gpt/figures/2.41").status_code == 404
        assert client.post("/admin/books/upload").status_code == 404


def test_exercise_api_reports_unconfigured_catalog(tmp_path) -> None:
    settings = Settings(
        locator_index_path=write_index(tmp_path),
        require_api_key=False,
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/health")
        response = client.get("/gpt/exercise-locators/2.14")

    assert health.json()["exercise_catalog_status"] == "not_configured"
    assert health.json()["exercise_count"] == 0
    assert response.status_code == 503
    assert response.json()["error_code"] == "EXERCISE_CATALOG_UNAVAILABLE"


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


def test_api_returns_strict_exercise_not_found_and_validation_errors(tmp_path) -> None:
    settings = Settings(
        locator_index_path=write_index(tmp_path),
        exercise_index_path=write_exercise_index(tmp_path),
        require_api_key=False,
    )
    with TestClient(create_app(settings)) as client:
        missing = client.get("/gpt/exercise-locators/2.99")
        malformed = client.get("/gpt/exercise-locators/not-an-id")

    assert missing.status_code == 404
    assert missing.json() == {
        "error_code": "EXERCISE_NOT_FOUND",
        "detail": "Exercise or chapter id does not exist: 2.99",
    }
    assert malformed.status_code == 422


def test_application_startup_fails_without_complete_index(tmp_path) -> None:
    settings = Settings(
        locator_index_path=tmp_path / "missing.json",
        require_api_key=False,
    )
    with (
        pytest.raises(LocatorIndexLoadError, match="not found"),
        TestClient(create_app(settings)),
    ):
        pass


def test_application_startup_fails_for_configured_missing_exercise_index(tmp_path) -> None:
    settings = Settings(
        locator_index_path=write_index(tmp_path),
        exercise_index_path=tmp_path / "missing-exercises.json",
        require_api_key=False,
    )
    with (
        pytest.raises(ExerciseIndexLoadError, match="not found"),
        TestClient(create_app(settings)),
    ):
        pass
