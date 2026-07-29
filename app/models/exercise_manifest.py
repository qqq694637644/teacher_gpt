from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.models.exercise import (
    CHAPTER_ID_PATTERN,
    EXERCISE_ID_PATTERN,
    ExerciseReferenceKind,
    validate_reference_id,
)
from app.models.locator import (
    DATA_VERSION,
    BookMetadata,
    PageRange,
    PageReference,
    StrictModel,
)
from app.models.manifest import ManifestRetrievalStep


class ExerciseReferenceSpec(StrictModel):
    kind: ExerciseReferenceKind
    target_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    selected_context_pages: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target_id(self) -> ExerciseReferenceSpec:
        validate_reference_id(self.kind, self.target_id)
        if len(self.selected_context_pages) != len(set(self.selected_context_pages)):
            raise ValueError("selected_context_pages must be unique")
        if any(not value.strip() for value in self.selected_context_pages):
            raise ValueError("selected_context_pages cannot contain blank labels")
        if self.selected_context_pages and self.kind != "section":
            raise ValueError("selected_context_pages is supported only for section references")
        return self


class ExerciseManifestNode(StrictModel):
    exercise_id: str = Field(pattern=EXERCISE_ID_PATTERN)
    chapter_id: str = Field(pattern=CHAPTER_ID_PATTERN)
    exercise_number: int = Field(ge=1)
    starred: bool = False
    source_order: int = Field(ge=1)
    problem_page_range: PageRange
    problem_retrieval_plan: Annotated[list[ManifestRetrievalStep], Field(min_length=1)]
    reference_specs: list[ExerciseReferenceSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_node(self) -> ExerciseManifestNode:
        if self.exercise_id != f"{self.chapter_id}.{self.exercise_number}":
            raise ValueError("exercise_id must match chapter_id and exercise_number")
        expected_indices = list(
            range(
                self.problem_page_range.pdf_page_index_start,
                self.problem_page_range.pdf_page_index_end + 1,
            )
        )
        actual_indices = [step.page.pdf_page_index for step in self.problem_retrieval_plan]
        if actual_indices != expected_indices:
            raise ValueError("problem_retrieval_plan must contain every physical page exactly once")
        if (
            self.problem_retrieval_plan[0].page.printed_page_label
            != self.problem_page_range.printed_page_start
        ):
            raise ValueError("problem retrieval start label does not match problem_page_range")
        if (
            self.problem_retrieval_plan[-1].page.printed_page_label
            != self.problem_page_range.printed_page_end
        ):
            raise ValueError("problem retrieval end label does not match problem_page_range")
        start = self.problem_retrieval_plan[0].content_window.start_at
        if start is None or (start.kind, start.value) != ("exercise", self.exercise_id):
            raise ValueError("first problem retrieval step must start at its exercise id")
        references = [(item.kind, item.target_id) for item in self.reference_specs]
        if len(references) != len(set(references)):
            raise ValueError("exercise reference specs must be unique")
        if ("exercise", self.exercise_id) in references:
            raise ValueError("exercise cannot reference itself")
        return self


class ExerciseManifest(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    index_status: Literal["complete"]
    book: BookMetadata
    pages: list[PageReference]
    exercises: Annotated[list[ExerciseManifestNode], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_manifest(self) -> ExerciseManifest:
        if len(self.pages) != self.book.page_count:
            raise ValueError("exercise manifest pages length must equal book.page_count")
        if [page.pdf_page_index for page in self.pages] != list(range(self.book.page_count)):
            raise ValueError("exercise manifest pages must cover every PDF index in order")
        labels = [page.printed_page_label for page in self.pages]
        if len(labels) != len(set(labels)):
            raise ValueError("exercise manifest printed_page_label values must be unique")

        ids = [item.exercise_id for item in self.exercises]
        if len(ids) != len(set(ids)):
            raise ValueError("exercise ids must be unique")
        chapter_orders: dict[str, list[int]] = {}
        for item in self.exercises:
            chapter_orders.setdefault(item.chapter_id, []).append(item.source_order)
            for step in item.problem_retrieval_plan:
                if step.page != self.pages[step.page.pdf_page_index]:
                    raise ValueError(f"exercise {item.exercise_id} uses a noncanonical page")
        for chapter_id, orders in chapter_orders.items():
            if orders != list(range(1, len(orders) + 1)):
                raise ValueError(
                    f"source_order must be contiguous and start at 1 in chapter {chapter_id}"
                )
        return self


class ExerciseManifestShard(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    chapter_id: str = Field(pattern=CHAPTER_ID_PATTERN)
    exercises: Annotated[list[ExerciseManifestNode], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_exercises(self) -> ExerciseManifestShard:
        if any(item.chapter_id != self.chapter_id for item in self.exercises):
            raise ValueError("exercise manifest shard contains another chapter")
        return self


class ExerciseManifestPackage(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    index_status: Literal["complete"]
    book: BookMetadata
    pages: list[PageReference]
    chapter_ids: Annotated[list[str], Field(min_length=1)]
    exercise_shards: Annotated[list[str], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_shards(self) -> ExerciseManifestPackage:
        if len(self.exercise_shards) != len(set(self.exercise_shards)):
            raise ValueError("exercise_shards must be unique")
        if len(self.chapter_ids) != len(set(self.chapter_ids)):
            raise ValueError("chapter_ids must be unique")
        if any(re.fullmatch(CHAPTER_ID_PATTERN, value) is None for value in self.chapter_ids):
            raise ValueError("chapter_ids contains an invalid chapter id")
        for name in self.exercise_shards:
            if re.fullmatch(r"exercises\.sections\.\d{2}\.yaml", name) is None:
                raise ValueError(f"invalid exercise manifest shard filename: {name}")
        shard_chapters = {
            str(int(name.removesuffix(".yaml").rsplit(".", 1)[1])) for name in self.exercise_shards
        }
        if shard_chapters != set(self.chapter_ids):
            raise ValueError("exercise shard chapters must exactly match chapter_ids")
        return self
