from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.repositories.exercise_repository import ExerciseRepository

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


def test_real_exercise_reference_plans_preserve_reviewed_pdf_context_and_windows() -> None:
    index = ExerciseRepository.load(REAL_EXERCISE_INDEX).index

    exercise_3_8 = index.exercises["3.8"]
    assert [step.page.printed_page_label for step in exercise_3_8.reference_retrieval_plan] == [
        "135",
        "136",
    ]
    section_3_3 = next(
        target
        for target in exercise_3_8.reference_targets
        if target.kind == "section" and target.target_id == "3.3"
    )
    assert section_3_3.selected_context_pages == ["135", "136"]

    exercise_11_2 = index.exercises["11.2"]
    assert [step.page.printed_page_label for step in exercise_11_2.reference_retrieval_plan] == [
        "815",
        "816",
    ]
    section_11_2 = next(
        target
        for target in exercise_11_2.reference_targets
        if target.kind == "section" and target.target_id == "11.2"
    )
    assert section_11_2.selected_context_pages == ["815", "816"]

    exercise_11_22 = index.exercises["11.22"]
    assert [step.page.printed_page_label for step in exercise_11_22.reference_retrieval_plan] == [
        "850",
        "851",
    ]
    table_target = next(
        target for target in exercise_11_22.reference_targets if target.kind == "table"
    )
    assert [step.page.printed_page_label for step in table_target.retrieval_plan] == ["851"]

    exercise_2_20 = index.exercises["2.20"]
    assert len(exercise_2_20.reference_retrieval_plan) == 1
    step_2_20 = exercise_2_20.reference_retrieval_plan[0]
    assert step_2_20.page.printed_page_label == "115"
    assert step_2_20.content_window.start_at.model_dump() == {
        "kind": "exercise",
        "value": "2.19",
    }
    assert step_2_20.content_window.end_before.model_dump() == {
        "kind": "exercise",
        "value": "2.20",
    }

    exercise_4_12 = index.exercises["4.12"]
    page_309_steps = [
        step
        for step in exercise_4_12.reference_retrieval_plan
        if step.page.printed_page_label == "309"
    ]
    assert len(page_309_steps) == 2
    assert {
        (
            step.content_window.start_at.value,
            step.content_window.end_before.value,
        )
        for step in page_309_steps
    } == {("4.4", "4.5"), ("4.9", "4.10")}

    exercise_2_11 = index.exercises["2.11"]
    assert [step.page.printed_page_label for step in exercise_2_11.reference_retrieval_plan] == [
        "70",
        "71",
    ]
    page_71 = exercise_2_11.reference_retrieval_plan[1]
    for evidence in page_71.required_evidence:
        if evidence.kind == "printed_page_equals":
            continue
        assert any(evidence.value.casefold() in query.casefold() for query in page_71.queries)
    assert any("2-15" in query for query in page_71.queries)
    assert any("2-16" in query for query in page_71.queries)


def test_real_exercise_catalog_expands_parallel_and_range_references() -> None:
    index = ExerciseRepository.load(REAL_EXERCISE_INDEX).index

    expected_equations = {
        "2.38": ["2-46", "2-47"],
        "4.11": ["4-25", "4-26"],
        "4.15": ["4-42", "4-43", "4-44", "4-45"],
        "4.25": ["4-59", "4-60"],
        "4.27": ["4-71", "4-72"],
    }
    for exercise_id, expected in expected_equations.items():
        locator = index.exercises[exercise_id]
        actual = [
            target.target_id for target in locator.reference_targets if target.kind == "equation"
        ]
        assert actual == expected
        for target_id in expected:
            target = next(
                target
                for target in locator.reference_targets
                if target.kind == "equation" and target.target_id == target_id
            )
            assert target.retrieval_plan
            matching_steps = [
                step
                for step in locator.reference_retrieval_plan
                if any(
                    evidence.kind == "contains_equation" and evidence.value == target_id
                    for evidence in step.required_evidence
                )
            ]
            assert matching_steps
            assert any(
                target_id.casefold() in query.casefold()
                for step in matching_steps
                for query in step.queries
            )
