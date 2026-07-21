from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: str = "ok"
    default_book_id: str


class BookMeta(ApiModel):
    book_id: str
    title: str | None = None
    author: str | None = None
    source_file: str | None = None
    page_count: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    version: Literal["2"] = "2"
    notes: str | None = None


class TocItem(ApiModel):
    section_id: str
    title: str
    level: int = 1
    page_start: int | None = None
    page_end: int | None = None
    parent_section_id: str | None = None
    section_type: Literal["official", "derived", "alias", "manual"] = "official"
    children: list["TocItem"] = Field(default_factory=list)


class TocResponse(ApiModel):
    book_id: str
    title: str | None = None
    items: list[TocItem]


class SourcePage(ApiModel):
    page_index: int = Field(description="0-based PDF page index")
    page_number: int = Field(description="1-based PDF page number")


class TextBlock(ApiModel):
    type: Literal["paragraph", "heading", "note"] = "paragraph"
    text: str
    page_number: int | None = None


class FigureRef(ApiModel):
    figure_id: str
    label: str | None = None
    caption: str | None = None
    page_index: int | None = None
    page_number: int | None = None
    context: str | None = None


class EquationRef(ApiModel):
    equation_id: str
    text: str | None = None
    page_number: int | None = None
    context: str | None = None


class ExampleRef(ApiModel):
    example_id: str
    title: str | None = None
    page_number: int | None = None
    text: str | None = None


class SectionContentMeta(ApiModel):
    window_status: Literal["complete", "partial"] = "complete"
    is_truncated: bool = False
    text_offset: int = Field(default=0, ge=0)
    text_limit: int | None = Field(default=None, ge=1)
    total_chars: int = Field(default=0, ge=0)
    returned_chars: int = Field(default=0, ge=0)
    next_offset: int | None = Field(default=None, ge=0)


class SectionPack(ApiModel):
    data_version: Literal["2"]
    book_id: str
    section_id: str
    resolved_section_id: str | None = Field(default=None)
    parent_section_id: str | None = None
    title: str
    page_start: int | None = None
    page_end: int | None = None
    section_type: Literal["official", "derived", "alias", "manual"] = "official"
    summary: str | None = None
    text_blocks: list[TextBlock] = Field(default_factory=list)
    content: SectionContentMeta = Field(default_factory=SectionContentMeta)
    figures: list[FigureRef] = Field(default_factory=list)
    equations: list[EquationRef] = Field(default_factory=list)
    examples: list[ExampleRef] = Field(default_factory=list)
    source_pages: list[SourcePage] = Field(default_factory=list)
    previous_sections: list[str] = Field(default_factory=list)
    next_sections: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SearchResult(ApiModel):
    section_id: str
    title: str
    page_start: int | None = None
    page_end: int | None = None
    score: float
    snippet: str | None = None


class SearchResponse(ApiModel):
    book_id: str
    query: str
    results: list[SearchResult]


class PrerequisitesResponse(ApiModel):
    book_id: str
    section_id: str
    prerequisites: list[SearchResult]


class FigureResponse(FigureRef):
    book_id: str
    related_section_ids: list[str] = Field(default_factory=list)


class IngestResponse(ApiModel):
    book_id: str
    title: str | None = None
    page_count: int
    official_sections: int
    derived_sections: int
    figures: int
    data_path: str
    warnings: list[str] = Field(default_factory=list)
