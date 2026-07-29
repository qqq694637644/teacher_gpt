from __future__ import annotations

import re
from collections import defaultdict
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.models.locator import (
    DATA_VERSION,
    BookMetadata,
    PageRange,
    PageReference,
    PageRetrievalStep,
    StrictModel,
    query_parentheses_balanced,
    query_safe_anchor,
)

EXERCISE_ID_PATTERN = r"^\d+\.\d+$"
CHAPTER_ID_PATTERN = r"^\d+$"
ExerciseReferenceKind = Literal[
    "section",
    "figure",
    "equation",
    "example",
    "table",
    "exercise",
]
REFERENCE_ID_PATTERNS = {
    "section": r"^\d+(?:\.\d+)*$",
    "figure": r"^\d+(?:\.\d+)+$",
    "equation": r"^\d+-\d+$",
    "example": r"^\d+(?:\.\d+)+$",
    "table": r"^\d+(?:\.\d+)+$",
    "exercise": EXERCISE_ID_PATTERN,
}


def validate_reference_id(kind: str, target_id: str) -> None:
    pattern = REFERENCE_ID_PATTERNS[kind]
    if re.fullmatch(pattern, target_id) is None:
        raise ValueError(f"invalid {kind} reference id: {target_id}")


class ExerciseReferenceTarget(StrictModel):
    kind: ExerciseReferenceKind
    target_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    selected_context_pages: list[str] = Field(default_factory=list)
    retrieval_plan: Annotated[list[PageRetrievalStep], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_target_id(self) -> ExerciseReferenceTarget:
        validate_reference_id(self.kind, self.target_id)
        if len(self.selected_context_pages) != len(set(self.selected_context_pages)):
            raise ValueError("selected_context_pages must be unique")
        if any(not value.strip() for value in self.selected_context_pages):
            raise ValueError("selected_context_pages cannot contain blank labels")
        if self.selected_context_pages and self.kind != "section":
            raise ValueError("selected_context_pages is supported only for section references")
        return self


class ExerciseLocator(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    book_id: str = Field(min_length=1)
    exercise_id: str = Field(pattern=EXERCISE_ID_PATTERN)
    chapter_id: str = Field(pattern=CHAPTER_ID_PATTERN)
    exercise_number: int = Field(ge=1)
    starred: bool = False
    source_order: int = Field(ge=1)
    problem_page_range: PageRange
    problem_retrieval_plan: Annotated[list[PageRetrievalStep], Field(min_length=1)]
    reference_retrieval_plan: list[PageRetrievalStep] = Field(default_factory=list)
    reference_targets: list[ExerciseReferenceTarget] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_locator(self) -> ExerciseLocator:
        expected_id = f"{self.chapter_id}.{self.exercise_number}"
        if self.exercise_id != expected_id:
            raise ValueError("exercise_id must match chapter_id and exercise_number")

        plan = self.problem_retrieval_plan
        expected_indices = list(
            range(
                self.problem_page_range.pdf_page_index_start,
                self.problem_page_range.pdf_page_index_end + 1,
            )
        )
        if [step.sequence for step in plan] != list(range(1, len(plan) + 1)):
            raise ValueError("exercise retrieval plan sequence must be contiguous and start at 1")
        if [step.page.pdf_page_index for step in plan] != expected_indices:
            raise ValueError(
                "exercise retrieval plan must contain every physical page exactly once"
            )
        if plan[0].page.printed_page_label != self.problem_page_range.printed_page_start:
            raise ValueError(
                "exercise retrieval plan start label does not match problem_page_range"
            )
        if plan[-1].page.printed_page_label != self.problem_page_range.printed_page_end:
            raise ValueError("exercise retrieval plan end label does not match problem_page_range")

        first_evidence = {(item.kind, item.value) for item in plan[0].required_evidence}
        if ("contains_exercise", self.exercise_id) not in first_evidence:
            raise ValueError("first exercise retrieval step must require the exercise id")
        start_at = plan[0].content_window.start_at
        if start_at is None or (start_at.kind, start_at.value) != (
            "exercise",
            self.exercise_id,
        ):
            raise ValueError("first exercise retrieval step must start at its exercise id")

        if len(plan) == 1:
            if plan[0].page_role != "single":
                raise ValueError("a one-page exercise must use page_role=single")
        else:
            if plan[0].page_role != "start" or plan[-1].page_role != "end":
                raise ValueError("multi-page exercises must start with start and end with end")
            if any(step.page_role != "body" for step in plan[1:-1]):
                raise ValueError("intermediate exercise pages must use page_role=body")

        references = [(item.kind, item.target_id) for item in self.reference_targets]
        if len(references) != len(set(references)):
            raise ValueError("exercise reference targets must be unique")
        if ("exercise", self.exercise_id) in references:
            raise ValueError("exercise cannot reference itself")
        all_plans = [self.problem_retrieval_plan, self.reference_retrieval_plan]
        all_plans.extend(target.retrieval_plan for target in self.reference_targets)
        for plan_to_validate in all_plans:
            for step in plan_to_validate:
                if any(not query_parentheses_balanced(query) for query in step.queries):
                    raise ValueError("exercise retrieval queries must have balanced parentheses")
                for evidence in step.required_evidence:
                    if evidence.kind == "printed_page_equals":
                        continue
                    folded_anchor = query_safe_anchor(evidence.value).casefold()
                    if not any(folded_anchor in query.casefold() for query in step.queries):
                        raise ValueError(
                            "every non-page exercise evidence must have a matching safe query anchor"
                        )

        if self.reference_retrieval_plan and [
            step.sequence for step in self.reference_retrieval_plan
        ] != list(range(1, len(self.reference_retrieval_plan) + 1)):
            raise ValueError("reference retrieval plan sequence must be contiguous and start at 1")
        return self


class ChapterExerciseSummary(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    book_id: str = Field(min_length=1)
    chapter_id: str = Field(pattern=CHAPTER_ID_PATTERN)
    exercise_ids: Annotated[list[str], Field(min_length=1)]
    first_exercise: str = Field(pattern=EXERCISE_ID_PATTERN)
    last_exercise: str = Field(pattern=EXERCISE_ID_PATTERN)
    exercise_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_summary(self) -> ChapterExerciseSummary:
        if len(self.exercise_ids) != len(set(self.exercise_ids)):
            raise ValueError("chapter exercise_ids must be unique")
        if self.exercise_count != len(self.exercise_ids):
            raise ValueError("exercise_count must equal exercise_ids length")
        if self.first_exercise != self.exercise_ids[0]:
            raise ValueError("first_exercise must equal the first exercise_id")
        if self.last_exercise != self.exercise_ids[-1]:
            raise ValueError("last_exercise must equal the last exercise_id")
        if any(item.split(".", 1)[0] != self.chapter_id for item in self.exercise_ids):
            raise ValueError("all exercise_ids must belong to chapter_id")
        return self


class CompiledExerciseIndex(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    index_status: Literal["complete"]
    book: BookMetadata
    pages: list[PageReference]
    chapters: dict[str, ChapterExerciseSummary]
    exercises: dict[str, ExerciseLocator]

    @model_validator(mode="after")
    def validate_index(self) -> CompiledExerciseIndex:
        if len(self.pages) != self.book.page_count:
            raise ValueError("pages length must equal book.page_count")
        if [page.pdf_page_index for page in self.pages] != list(range(self.book.page_count)):
            raise ValueError("pages must cover every PDF index in order")
        labels = [page.printed_page_label for page in self.pages]
        if len(labels) != len(set(labels)):
            raise ValueError("printed_page_label values must be unique")
        if not self.chapters or not self.exercises:
            raise ValueError("complete exercise index must contain chapters and exercises")

        grouped: dict[str, list[ExerciseLocator]] = defaultdict(list)
        for exercise_id, locator in self.exercises.items():
            if exercise_id != locator.exercise_id:
                raise ValueError(f"exercise key does not match locator id: {exercise_id}")
            if locator.book_id != self.book.book_id:
                raise ValueError(f"exercise {exercise_id} has the wrong book_id")
            for step in locator.problem_retrieval_plan:
                canonical = self.pages[step.page.pdf_page_index]
                if step.page != canonical:
                    raise ValueError(
                        f"exercise {exercise_id} contains a noncanonical problem page reference"
                    )
            for target in locator.reference_targets:
                for step in target.retrieval_plan:
                    canonical = self.pages[step.page.pdf_page_index]
                    if step.page != canonical:
                        raise ValueError(
                            f"exercise {exercise_id} contains a noncanonical reference page"
                        )
                if target.kind == "exercise" and target.target_id not in self.exercises:
                    raise ValueError(
                        f"exercise {exercise_id} references missing exercise {target.target_id}"
                    )
            for step in locator.reference_retrieval_plan:
                canonical = self.pages[step.page.pdf_page_index]
                if step.page != canonical:
                    raise ValueError(
                        f"exercise {exercise_id} contains a noncanonical aggregate reference page"
                    )
            grouped[locator.chapter_id].append(locator)

        if set(grouped) != set(self.chapters):
            raise ValueError("chapter summaries must exactly match exercise chapters")
        for chapter_id, locators in grouped.items():
            summary = self.chapters[chapter_id]
            if summary.chapter_id != chapter_id or summary.book_id != self.book.book_id:
                raise ValueError(f"chapter summary metadata is invalid: {chapter_id}")
            ordered = sorted(locators, key=lambda item: item.source_order)
            source_orders = [item.source_order for item in ordered]
            if source_orders != list(range(1, len(source_orders) + 1)):
                raise ValueError(
                    f"source_order must be contiguous and start at 1 in chapter {chapter_id}"
                )
            expected_ids = [item.exercise_id for item in ordered]
            if summary.exercise_ids != expected_ids:
                raise ValueError(
                    f"chapter summary exercise order does not match locators: {chapter_id}"
                )

        graph = {
            exercise_id: [
                target.target_id
                for target in locator.reference_targets
                if target.kind == "exercise"
            ]
            for exercise_id, locator in self.exercises.items()
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(exercise_id: str) -> None:
            if exercise_id in visiting:
                raise ValueError(f"exercise reference cycle detected at {exercise_id}")
            if exercise_id in visited:
                return
            visiting.add(exercise_id)
            for target_id in graph[exercise_id]:
                visit(target_id)
            visiting.remove(exercise_id)
            visited.add(exercise_id)

        for exercise_id in graph:
            visit(exercise_id)
        return self


class ExerciseChapterShard(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    chapter_id: str = Field(pattern=CHAPTER_ID_PATTERN)
    exercises: dict[str, ExerciseLocator]

    @model_validator(mode="after")
    def validate_exercises(self) -> ExerciseChapterShard:
        if not self.exercises:
            raise ValueError("exercise shard must contain exercises")
        for exercise_id, locator in self.exercises.items():
            if exercise_id != locator.exercise_id:
                raise ValueError(f"exercise shard key does not match locator id: {exercise_id}")
            if locator.chapter_id != self.chapter_id:
                raise ValueError(f"exercise {exercise_id} is in the wrong chapter shard")
        return self


class CompiledExerciseIndexPackage(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    index_status: Literal["complete"]
    book: BookMetadata
    pages: list[PageReference]
    chapters: dict[str, ChapterExerciseSummary]
    exercise_shards: Annotated[list[str], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_shards(self) -> CompiledExerciseIndexPackage:
        if len(self.exercise_shards) != len(set(self.exercise_shards)):
            raise ValueError("exercise_shards must be unique")
        for name in self.exercise_shards:
            if re.fullmatch(r"compiled_exercise_index\.sections\.\d{2}\.json", name) is None:
                raise ValueError(f"invalid exercise shard filename: {name}")
        shard_chapters = {
            str(int(name.removesuffix(".json").rsplit(".", 1)[1])) for name in self.exercise_shards
        }
        if shard_chapters != set(self.chapters):
            raise ValueError("exercise shard chapters must exactly match chapter summaries")
        return self
