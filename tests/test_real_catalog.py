from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

REAL_INDEX = Path("catalog/dip4e/compiled_locator_index.json")
REAL_EXERCISE_INDEX = Path("catalog/dip4e/compiled_exercise_index.json")


def test_real_catalog_starts_and_serves_reviewed_sections() -> None:
    settings = Settings(
        locator_index_path=REAL_INDEX,
        exercise_index_path=REAL_EXERCISE_INDEX,
        require_api_key=False,
    )

    with TestClient(create_app(settings)) as client:
        health = client.get("/health")
        spatial = client.get("/gpt/section-locators/2.6.5")
        chapter_one = client.get("/gpt/section-locators/1.3")
        chapter_twelve = client.get("/gpt/section-locators/12.5")
        exercise = client.get("/gpt/exercise-locators/2.14")
        chapter_exercises = client.get("/gpt/chapters/2/exercises")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "data_version": "3",
        "book_id": "dip4e",
        "section_count": 444,
        "page_count": 1022,
        "exercise_catalog_status": "ready",
        "exercise_count": 492,
    }

    assert spatial.status_code == 200
    spatial_payload = spatial.json()
    assert spatial_payload["title"] == "Spatial Operations"
    assert spatial_payload["printed_section_id"] == "2.6"
    assert spatial_payload["page_range"]["printed_page_start"] == "98"
    assert spatial_payload["page_range"]["printed_page_end"] == "106"
    assert len(spatial_payload["retrieval_plan"]) == 9

    assert chapter_one.status_code == 200
    assert chapter_one.json()["printed_section_id"] == "1.3"
    assert chapter_twelve.status_code == 200
    assert chapter_twelve.json()["printed_section_id"] == "12.5"

    assert exercise.status_code == 200
    exercise_payload = exercise.json()
    assert exercise_payload["exercise_id"] == "2.14"
    assert exercise_payload["problem_page_range"]["printed_page_start"] == "115"
    assert exercise_payload["problem_retrieval_plan"][0]["content_window"]["start_at"] == {
        "kind": "exercise",
        "value": "2.14",
    }

    assert chapter_exercises.status_code == 200
    chapter_payload = chapter_exercises.json()
    assert chapter_payload["exercise_count"] == 41
    assert chapter_payload["first_exercise"] == "2.1"
    assert chapter_payload["last_exercise"] == "2.41"
