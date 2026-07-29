from __future__ import annotations

import re
from collections import defaultdict
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DATA_VERSION = "3"
SECTION_ID_PATTERN = r"^\d+(?:\.\d+)*$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageReference(StrictModel):
    pdf_page_index: int = Field(ge=0)
    pdf_page_number: int = Field(ge=1)
    printed_page_label: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_page_number(self) -> PageReference:
        if self.pdf_page_number != self.pdf_page_index + 1:
            raise ValueError("pdf_page_number must equal pdf_page_index + 1")
        return self


class PageClassification(StrictModel):
    page: PageReference
    category: Literal["front_matter", "body", "back_matter"]
    reason: str = Field(min_length=1)


class PageRange(StrictModel):
    pdf_page_index_start: int = Field(ge=0)
    pdf_page_index_end: int = Field(ge=0)
    pdf_page_number_start: int = Field(ge=1)
    pdf_page_number_end: int = Field(ge=1)
    printed_page_start: str = Field(min_length=1)
    printed_page_end: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self) -> PageRange:
        if self.pdf_page_index_end < self.pdf_page_index_start:
            raise ValueError("page range end precedes start")
        if self.pdf_page_number_start != self.pdf_page_index_start + 1:
            raise ValueError("pdf_page_number_start must equal index start + 1")
        if self.pdf_page_number_end != self.pdf_page_index_end + 1:
            raise ValueError("pdf_page_number_end must equal index end + 1")
        return self


class HeadingLocation(StrictModel):
    page: PageReference
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)]

    @model_validator(mode="after")
    def validate_bbox(self) -> HeadingLocation:
        x0, y0, x1, y1 = self.bbox
        if x1 <= x0 or y1 <= y0:
            raise ValueError("heading bbox must have positive width and height")
        return self


BoundaryKind = Literal[
    "heading",
    "figure",
    "equation",
    "example",
    "table",
    "text",
    "exercise",
]
EvidenceKind = Literal[
    "printed_page_equals",
    "contains_heading",
    "contains_figure",
    "contains_equation",
    "contains_example",
    "contains_table",
    "contains_text",
    "contains_exercise",
    "running_header_contains",
]
BOUNDARY_TO_EVIDENCE: dict[str, str] = {
    "heading": "contains_heading",
    "figure": "contains_figure",
    "equation": "contains_equation",
    "example": "contains_example",
    "table": "contains_table",
    "text": "contains_text",
    "exercise": "contains_exercise",
}
RETRIEVAL_ONLY_ANCHOR = "DIP4E_GLOBAL_Print_Ready.indb"


class BoundaryAnchor(StrictModel):
    kind: BoundaryKind
    value: str = Field(min_length=1)


class ContentWindow(StrictModel):
    start_at: BoundaryAnchor | None = None
    end_before: BoundaryAnchor | None = None


class EvidenceRequirement(StrictModel):
    kind: EvidenceKind
    value: str = Field(min_length=1)
    verification_mode: Literal["visual_required", "text_or_visual"]

    @model_validator(mode="after")
    def validate_mode(self) -> EvidenceRequirement:
        if self.kind == "printed_page_equals" and self.verification_mode != "visual_required":
            raise ValueError("printed_page_equals evidence must require visual verification")
        return self


class PageCoverage(StrictModel):
    subheadings: list[str] = Field(default_factory=list)
    figure_ids: list[str] = Field(default_factory=list)
    equation_ids: list[str] = Field(default_factory=list)
    example_ids: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)


class PageRetrievalStep(StrictModel):
    sequence: int = Field(ge=1)
    page_role: Literal["start", "body", "end", "single"]
    page: PageReference
    content_window: ContentWindow = Field(default_factory=ContentWindow)
    queries: Annotated[list[str], Field(min_length=2, max_length=4)]
    required_evidence: Annotated[list[EvidenceRequirement], Field(min_length=1)]
    coverage: PageCoverage = Field(default_factory=PageCoverage)

    @model_validator(mode="after")
    def validate_step(self) -> PageRetrievalStep:
        normalized_queries = [query.strip() for query in self.queries]
        if any(not query for query in normalized_queries):
            raise ValueError("retrieval queries cannot be blank")
        if len(set(normalized_queries)) != len(normalized_queries):
            raise ValueError("retrieval queries must be unique")
        if any("--QDF=0" not in query for query in normalized_queries):
            raise ValueError("every retrieval query must include --QDF=0")

        page_evidence = [
            item.value for item in self.required_evidence if item.kind == "printed_page_equals"
        ]
        if page_evidence != [self.page.printed_page_label]:
            raise ValueError(
                "required_evidence must contain exactly one printed_page_equals matching the page"
            )
        if any(RETRIEVAL_ONLY_ANCHOR in item.value for item in self.required_evidence):
            raise ValueError("retrieval-only indb anchors cannot be required evidence")
        for boundary in (self.content_window.start_at, self.content_window.end_before):
            if boundary is None:
                continue
            if RETRIEVAL_ONLY_ANCHOR in boundary.value:
                raise ValueError("retrieval-only indb anchors cannot define content windows")
            required_kind = BOUNDARY_TO_EVIDENCE[boundary.kind]
            matching = [
                item
                for item in self.required_evidence
                if item.kind == required_kind and item.value == boundary.value
            ]
            if not matching:
                raise ValueError("content-window boundary must have matching required evidence")
            if matching[0].verification_mode != "visual_required":
                raise ValueError("content-window boundaries must require visual verification")
        return self


class SectionLocator(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    book_id: str = Field(min_length=1)
    section_kind: Literal["printed", "learning_unit"]
    section_id: str = Field(pattern=SECTION_ID_PATTERN)
    printed_section_id: str = Field(pattern=SECTION_ID_PATTERN)
    parent_section_id: str | None = Field(default=None, pattern=SECTION_ID_PATTERN)
    title: str = Field(min_length=1)
    source_heading: str = Field(min_length=1)
    source_heading_numbered: bool
    source_location: HeadingLocation
    source_level: int = Field(ge=0)
    hierarchy_depth: int = Field(ge=1)
    page_range: PageRange
    outline: list[str] = Field(default_factory=list)
    retrieval_plan: Annotated[list[PageRetrievalStep], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_locator(self) -> SectionLocator:
        plan = self.retrieval_plan
        expected_indices = list(
            range(self.page_range.pdf_page_index_start, self.page_range.pdf_page_index_end + 1)
        )
        if [step.sequence for step in plan] != list(range(1, len(plan) + 1)):
            raise ValueError("retrieval plan sequence must be contiguous and start at 1")
        if [step.page.pdf_page_index for step in plan] != expected_indices:
            raise ValueError("retrieval plan must contain every physical page exactly once")
        if plan[0].page.printed_page_label != self.page_range.printed_page_start:
            raise ValueError("retrieval plan start label does not match page_range")
        if plan[-1].page.printed_page_label != self.page_range.printed_page_end:
            raise ValueError("retrieval plan end label does not match page_range")
        first_evidence = {(item.kind, item.value) for item in plan[0].required_evidence}
        if ("contains_heading", self.source_heading) not in first_evidence:
            raise ValueError("first retrieval step must require the source heading")

        if len(plan) == 1:
            if plan[0].page_role != "single":
                raise ValueError("a one-page section must use page_role=single")
        else:
            if plan[0].page_role != "start" or plan[-1].page_role != "end":
                raise ValueError("multi-page sections must start with start and end with end")
            if any(step.page_role != "body" for step in plan[1:-1]):
                raise ValueError("intermediate pages must use page_role=body")

        if self.section_kind == "printed":
            if self.section_id != self.printed_section_id:
                raise ValueError("printed section id must equal printed_section_id")
            if not self.source_heading_numbered:
                raise ValueError("printed section heading must be marked numbered")
            if self.source_level != 0:
                raise ValueError("printed sections must use source_level=0")
        else:
            prefix = f"{self.printed_section_id}."
            if not self.section_id.startswith(prefix):
                raise ValueError("learning unit id must be nested under printed_section_id")
            if self.parent_section_id is None:
                raise ValueError("learning unit requires parent_section_id")
            expected_source_level = self.hierarchy_depth - len(self.printed_section_id.split("."))
            if self.source_level != expected_source_level:
                raise ValueError("learning-unit source_level does not match generated hierarchy")
        if self.hierarchy_depth != len(self.section_id.split(".")):
            raise ValueError("hierarchy_depth does not match section_id")
        expected_parent = self.section_id.rsplit(".", 1)[0] if "." in self.section_id else None
        if self.parent_section_id != expected_parent:
            raise ValueError("parent_section_id must be the immediate section-id parent")
        if self.source_location.page.pdf_page_index != self.page_range.pdf_page_index_start:
            raise ValueError("source heading must be on the first page of the section range")
        return self


class BookMetadata(StrictModel):
    book_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    author: str = Field(min_length=1)
    pdf_filename: str = Field(min_length=1)
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)


class CompiledLocatorIndex(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    index_status: Literal["complete"]
    book: BookMetadata
    pages: list[PageReference]
    page_classifications: list[PageClassification]
    sections: dict[str, SectionLocator]

    @model_validator(mode="after")
    def validate_index(self) -> CompiledLocatorIndex:
        if len(self.pages) != self.book.page_count:
            raise ValueError("pages length must equal book.page_count")
        expected_indices = list(range(self.book.page_count))
        if [page.pdf_page_index for page in self.pages] != expected_indices:
            raise ValueError("pages must cover every PDF index in order")
        labels = [page.printed_page_label for page in self.pages]
        if len(labels) != len(set(labels)):
            raise ValueError("printed_page_label values must be unique")
        if not self.sections:
            raise ValueError("complete index must contain sections")
        if len(self.page_classifications) != len(self.pages):
            raise ValueError("page_classifications must contain every PDF page")
        for expected, classification in zip(self.pages, self.page_classifications, strict=True):
            if classification.page != expected:
                raise ValueError("page_classifications must use canonical pages in order")

        children: dict[str, list[SectionLocator]] = defaultdict(list)
        for section_id, locator in self.sections.items():
            if section_id != locator.section_id:
                raise ValueError(f"section key does not match locator id: {section_id}")
            if locator.book_id != self.book.book_id:
                raise ValueError(f"section {section_id} has the wrong book_id")
            if (
                locator.parent_section_id is not None
                and locator.parent_section_id not in self.sections
            ):
                raise ValueError(
                    f"section {section_id} references missing parent {locator.parent_section_id}"
                )
            if locator.parent_section_id is not None:
                children[locator.parent_section_id].append(locator)
            printed = self.sections.get(locator.printed_section_id)
            if printed is None or printed.section_kind != "printed":
                raise ValueError(
                    f"section {section_id} references missing printed section "
                    f"{locator.printed_section_id}"
                )
            source_page = self.pages[locator.source_location.page.pdf_page_index]
            if locator.source_location.page != source_page:
                raise ValueError(f"section {section_id} has a noncanonical source page")
            for step in locator.retrieval_plan:
                canonical = self.pages[step.page.pdf_page_index]
                if step.page != canonical:
                    raise ValueError(
                        f"section {section_id} contains a page reference that differs from pages[]"
                    )

        for parent_id, child_locators in children.items():
            parent = self.sections[parent_id]
            ordered = sorted(
                child_locators,
                key=lambda item: (
                    item.source_location.page.pdf_page_index,
                    item.source_location.bbox[1],
                    item.source_location.bbox[0],
                ),
            )
            for child in ordered:
                if not self._range_contains(parent.page_range, child.page_range):
                    raise ValueError(
                        f"child section {child.section_id} is outside parent range {parent_id}"
                    )
                printed = self.sections[child.printed_section_id]
                if child.section_kind == "learning_unit" and not self._range_contains(
                    printed.page_range, child.page_range
                ):
                    raise ValueError(
                        f"learning unit {child.section_id} is outside printed section range"
                    )
            for previous, current in pairwise(ordered):
                gap = (
                    current.page_range.pdf_page_index_start - previous.page_range.pdf_page_index_end
                )
                if gap not in (0, 1):
                    raise ValueError(
                        f"sibling ranges have an unexplained gap or overlap: "
                        f"{previous.section_id}, {current.section_id}"
                    )
                if gap == 0:
                    previous_last = previous.retrieval_plan[-1]
                    current_first = current.retrieval_plan[0]
                    expected = ("heading", current.source_heading)
                    previous_boundary = previous_last.content_window.end_before
                    current_boundary = current_first.content_window.start_at
                    if (
                        previous_boundary is None
                        or (previous_boundary.kind, previous_boundary.value) != expected
                        or current_boundary is None
                        or (current_boundary.kind, current_boundary.value) != expected
                    ):
                        raise ValueError(
                            f"same-page sibling boundary is not explicit: "
                            f"{previous.section_id}, {current.section_id}"
                        )

        body_pages = {
            item.page.pdf_page_index
            for item in self.page_classifications
            if item.category == "body"
        }
        content_pages: set[int] = set()
        for section_id, locator in self.sections.items():
            child_locators = children.get(section_id, [])
            locator_pages = set(
                range(
                    locator.page_range.pdf_page_index_start,
                    locator.page_range.pdf_page_index_end + 1,
                )
            )
            if locator.section_kind == "learning_unit" or not child_locators:
                content_pages.update(locator_pages)
                continue

            child_pages: set[int] = set()
            for child in child_locators:
                child_pages.update(
                    range(
                        child.page_range.pdf_page_index_start,
                        child.page_range.pdf_page_index_end + 1,
                    )
                )
            content_pages.update(locator_pages - child_pages)
        uncovered = sorted(body_pages - content_pages)
        if uncovered:
            raise ValueError(
                "body pages are not covered by a learning unit, leaf printed section, "
                "or explicit parent-only content: "
                f"{uncovered[:20]}"
            )
        return self

    @staticmethod
    def _range_contains(parent: PageRange, child: PageRange) -> bool:
        return (
            parent.pdf_page_index_start <= child.pdf_page_index_start
            and child.pdf_page_index_end <= parent.pdf_page_index_end
        )


class LocatorSectionShard(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    sections: dict[str, SectionLocator]

    @model_validator(mode="after")
    def validate_sections(self) -> LocatorSectionShard:
        if not self.sections:
            raise ValueError("section shard must contain sections")
        for section_id, locator in self.sections.items():
            if section_id != locator.section_id:
                raise ValueError(f"section shard key does not match locator id: {section_id}")
        return self


class CompiledLocatorIndexPackage(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    index_status: Literal["complete"]
    book: BookMetadata
    pages: list[PageReference]
    page_classifications: list[PageClassification]
    section_shards: Annotated[list[str], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_shards(self) -> CompiledLocatorIndexPackage:
        if len(self.section_shards) != len(set(self.section_shards)):
            raise ValueError("section_shards must be unique")
        for name in self.section_shards:
            if re.fullmatch(r"compiled_locator_index\.sections\.\d{2}\.json", name) is None:
                raise ValueError(f"invalid section shard filename: {name}")
        return self


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    data_version: Literal["3"] = DATA_VERSION
    book_id: str
    section_count: int = Field(ge=1)
    page_count: int = Field(ge=1)
    exercise_catalog_status: Literal["ready", "not_configured"]
    exercise_count: int = Field(ge=0)


class SectionNotFoundResponse(StrictModel):
    error_code: Literal["SECTION_NOT_FOUND"]
    detail: str


class ExerciseNotFoundResponse(StrictModel):
    error_code: Literal["EXERCISE_NOT_FOUND"]
    detail: str


class ExerciseCatalogUnavailableResponse(StrictModel):
    error_code: Literal["EXERCISE_CATALOG_UNAVAILABLE"]
    detail: str
