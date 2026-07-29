import json

import pytest
from pydantic import ValidationError

from app.core.errors import ExerciseIndexLoadError
from app.models.exercise import (
    CompiledExerciseIndex,
    CompiledExerciseIndexPackage,
    ExerciseChapterShard,
    ExerciseLocator,
)
from app.repositories.exercise_repository import ExerciseRepository
from tests.helpers import complete_exercise_index


def test_exercise_locator_requires_consistent_id_components() -> None:
    index = complete_exercise_index()
    raw = index.exercises["2.14"].model_dump(mode="json")
    raw["exercise_number"] = 13

    with pytest.raises(ValidationError, match="exercise_id must match"):
        ExerciseLocator.model_validate(raw)


def test_exercise_locator_requires_visual_exercise_start_boundary() -> None:
    index = complete_exercise_index()
    raw = index.exercises["2.14"].model_dump(mode="json")
    raw["problem_retrieval_plan"][0]["content_window"]["start_at"] = None

    with pytest.raises(ValidationError, match="must start at its exercise id"):
        ExerciseLocator.model_validate(raw)


def test_exercise_locator_rejects_unbalanced_query_parentheses() -> None:
    index = complete_exercise_index()
    raw = index.exercises["2.14"].model_dump(mode="json")
    raw["problem_retrieval_plan"][0]["queries"][0] = (
        "+(text broken (anchor) +(printed page 98) --QDF=0"
    )

    with pytest.raises(ValidationError, match="balanced parentheses"):
        ExerciseLocator.model_validate(raw)


def test_compiled_exercise_index_rejects_missing_cross_exercise_reference() -> None:
    index = complete_exercise_index()
    raw = index.model_dump(mode="json")
    target = raw["exercises"]["2.14"]["reference_targets"][0]
    target["kind"] = "exercise"
    target["target_id"] = "2.99"

    with pytest.raises(ValidationError, match="references missing exercise"):
        CompiledExerciseIndex.model_validate(raw)


def test_compiled_exercise_index_rejects_reference_cycles() -> None:
    index = complete_exercise_index()
    raw = index.model_dump(mode="json")
    first_target = raw["exercises"]["2.14"]["reference_targets"][0]
    first_target["kind"] = "exercise"
    first_target["target_id"] = "2.15"
    second = raw["exercises"]["2.15"]
    second["reference_targets"] = [
        {
            "kind": "exercise",
            "target_id": "2.14",
            "reason": "cycle",
            "retrieval_plan": second["problem_retrieval_plan"],
        }
    ]

    with pytest.raises(ValidationError, match="reference cycle"):
        CompiledExerciseIndex.model_validate(raw)


def test_exercise_repository_loads_strict_package(tmp_path) -> None:
    index = complete_exercise_index()
    shard_name = "compiled_exercise_index.sections.02.json"
    shard = ExerciseChapterShard(
        chapter_id="2",
        exercises=index.exercises,
    )
    (tmp_path / shard_name).write_text(
        json.dumps(shard.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    package = CompiledExerciseIndexPackage(
        index_status="complete",
        book=index.book,
        pages=index.pages,
        chapters=index.chapters,
        exercise_shards=[shard_name],
    )
    path = tmp_path / "compiled_exercise_index.json"
    path.write_text(
        json.dumps(package.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    repository = ExerciseRepository.load(path)

    assert repository.index == index
    assert repository.get_exercise("2.14").starred is True
    assert repository.list_chapter("2").exercise_count == 2


def test_exercise_repository_rejects_missing_shard(tmp_path) -> None:
    index = complete_exercise_index()
    package = CompiledExerciseIndexPackage(
        index_status="complete",
        book=index.book,
        pages=index.pages,
        chapters=index.chapters,
        exercise_shards=["compiled_exercise_index.sections.02.json"],
    )
    path = tmp_path / "compiled_exercise_index.json"
    path.write_text(
        json.dumps(package.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ExerciseIndexLoadError, match="invalid"):
        ExerciseRepository.load(path)
