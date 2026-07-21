from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.models.locator import (
    DATA_VERSION,
    BookMetadata,
    ContentWindow,
    EvidenceRequirement,
    HeadingLocation,
    PageCoverage,
    PageRange,
    PageReference,
    StrictModel,
)


class ManifestRetrievalStep(StrictModel):
    page: PageReference
    content_window: ContentWindow = Field(default_factory=ContentWindow)
    queries: Annotated[list[str], Field(min_length=2, max_length=4)]
    required_evidence: Annotated[list[EvidenceRequirement], Field(min_length=1)]
    coverage: PageCoverage = Field(default_factory=PageCoverage)
    verified: Literal[True]


class LearningUnitManifest(StrictModel):
    title: str = Field(min_length=1)
    source_heading: str = Field(min_length=1)
    source_heading_numbered: Literal[False] = False
    source_location: HeadingLocation
    source_level: int = Field(ge=1)
    page_range: PageRange
    outline: list[str] = Field(default_factory=list)
    retrieval_plan: Annotated[list[ManifestRetrievalStep], Field(min_length=1)]
    children: list[LearningUnitManifest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_children(self) -> LearningUnitManifest:
        if self.source_location.page.pdf_page_index != self.page_range.pdf_page_index_start:
            raise ValueError("learning unit heading must be on its page-range start")
        if self.children:
            levels = {child.source_level for child in self.children}
            if levels != {self.source_level + 1}:
                raise ValueError("all child headings must be exactly one structural level deeper")
        return self


class PrintedSectionManifest(StrictModel):
    printed_section_id: str = Field(pattern=r"^\d+(?:\.\d+)*$")
    parent_printed_section_id: str | None = Field(default=None, pattern=r"^\d+(?:\.\d+)*$")
    title: str = Field(min_length=1)
    source_heading: str = Field(min_length=1)
    source_location: HeadingLocation
    page_range: PageRange
    outline: list[str] = Field(default_factory=list)
    retrieval_plan: Annotated[list[ManifestRetrievalStep], Field(min_length=1)]
    learning_units: list[LearningUnitManifest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_learning_units(self) -> PrintedSectionManifest:
        if self.source_location.page.pdf_page_index != self.page_range.pdf_page_index_start:
            raise ValueError("printed heading must be on its page-range start")
        if self.learning_units:
            levels = {unit.source_level for unit in self.learning_units}
            if levels != {1}:
                raise ValueError("top-level learning units must all use source_level=1")
        return self


class BookManifest(StrictModel):
    data_version: Literal["3"] = DATA_VERSION
    index_status: Literal["complete"]
    book: BookMetadata
    pages: list[PageReference]
    printed_sections: Annotated[list[PrintedSectionManifest], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_manifest(self) -> BookManifest:
        if len(self.pages) != self.book.page_count:
            raise ValueError("manifest pages length must equal book.page_count")
        if [page.pdf_page_index for page in self.pages] != list(range(self.book.page_count)):
            raise ValueError("manifest pages must cover every PDF index in order")
        labels = [page.printed_page_label for page in self.pages]
        if len(labels) != len(set(labels)):
            raise ValueError("manifest printed_page_label values must be unique")

        ids = [section.printed_section_id for section in self.printed_sections]
        if len(ids) != len(set(ids)):
            raise ValueError("printed section ids must be unique")
        id_set = set(ids)
        for section in self.printed_sections:
            parent = section.parent_printed_section_id
            if parent is not None and parent not in id_set:
                raise ValueError(
                    f"printed section {section.printed_section_id} references missing parent {parent}"
                )
            if parent is not None and not section.printed_section_id.startswith(f"{parent}."):
                raise ValueError("printed section id must be nested under its parent id")
        return self
