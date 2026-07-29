from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import ExerciseIndexLoadError, ExerciseNotFoundError
from app.models.exercise import (
    ChapterExerciseSummary,
    CompiledExerciseIndex,
    CompiledExerciseIndexPackage,
    ExerciseChapterShard,
    ExerciseLocator,
)


class ExerciseRepository:
    def __init__(self, index: CompiledExerciseIndex):
        self.index = index

    @classmethod
    def load(cls, path: Path) -> ExerciseRepository:
        if not path.is_file():
            raise ExerciseIndexLoadError(f"Compiled exercise index not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if "exercise_shards" in raw:
                package = CompiledExerciseIndexPackage.model_validate(raw)
                exercises: dict[str, ExerciseLocator] = {}
                seen_chapters: set[str] = set()
                for shard_name in package.exercise_shards:
                    shard_path = path.parent / shard_name
                    shard_raw = json.loads(shard_path.read_text(encoding="utf-8"))
                    shard = ExerciseChapterShard.model_validate(shard_raw)
                    filename_chapter = str(int(shard_name.removesuffix(".json").rsplit(".", 1)[1]))
                    if shard.chapter_id != filename_chapter:
                        raise ValueError(
                            f"exercise shard chapter does not match filename: {shard_name}"
                        )
                    if shard.chapter_id in seen_chapters:
                        raise ValueError(f"duplicate exercise chapter shard: {shard.chapter_id}")
                    seen_chapters.add(shard.chapter_id)
                    duplicates = exercises.keys() & shard.exercises.keys()
                    if duplicates:
                        raise ValueError(
                            f"duplicate exercise IDs across shards: {sorted(duplicates)}"
                        )
                    exercises.update(shard.exercises)
                raw = {
                    **package.model_dump(mode="json", exclude={"exercise_shards"}),
                    "exercises": {
                        exercise_id: locator.model_dump(mode="json")
                        for exercise_id, locator in exercises.items()
                    },
                }
            index = CompiledExerciseIndex.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise ExerciseIndexLoadError(f"Compiled exercise index is invalid: {exc}") from exc
        return cls(index)

    def get_exercise(self, exercise_id: str) -> ExerciseLocator:
        try:
            return self.index.exercises[exercise_id]
        except KeyError as exc:
            raise ExerciseNotFoundError(exercise_id) from exc

    def list_chapter(self, chapter_id: str) -> ChapterExerciseSummary:
        try:
            return self.index.chapters[chapter_id]
        except KeyError as exc:
            raise ExerciseNotFoundError(chapter_id) from exc
