import pytest
from pydantic import ValidationError

from app.models.locator import (
    CompiledLocatorIndex,
    EvidenceRequirement,
    PageReference,
    PageRetrievalStep,
    SectionLocator,
)
from app.services.index_compiler import LocatorIndexCompiler
from tests.helpers import complete_manifest


def test_page_reference_rejects_ambiguous_numbering() -> None:
    with pytest.raises(ValidationError, match="pdf_page_number"):
        PageReference(
            pdf_page_index=106,
            pdf_page_number=106,
            printed_page_label="105",
        )


def test_page_step_requires_matching_printed_page_evidence() -> None:
    raw = {
        "sequence": 1,
        "page_role": "single",
        "page": {
            "pdf_page_index": 0,
            "pdf_page_number": 1,
            "printed_page_label": "98",
        },
        "content_window": {"start_at": None, "end_before": None},
        "queries": ["query one --QDF=0", "query two --QDF=0"],
        "required_evidence": [
            {
                "kind": "printed_page_equals",
                "value": "99",
                "verification_mode": "visual_required",
            },
        ],
        "coverage": {},
    }
    with pytest.raises(ValidationError, match="printed_page_equals"):
        PageRetrievalStep.model_validate(raw)


def test_locator_requires_every_physical_page() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    raw = compiled.sections["2.6"].model_dump()
    raw["retrieval_plan"].pop(1)
    for sequence, step in enumerate(raw["retrieval_plan"], start=1):
        step["sequence"] = sequence

    with pytest.raises(ValidationError, match="every physical page"):
        SectionLocator.model_validate(raw)


def test_compiled_index_rejects_unknown_fields() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    raw = compiled.model_dump()
    raw["legacy_data"] = True

    with pytest.raises(ValidationError, match="legacy_data"):
        type(compiled).model_validate(raw)


def test_page_step_rejects_query_without_qdf_zero() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    raw = compiled.sections["2.6.5"].retrieval_plan[0].model_dump()
    raw["queries"][0] = raw["queries"][0].replace(" --QDF=0", "")

    with pytest.raises(ValidationError, match="--QDF=0"):
        PageRetrievalStep.model_validate(raw)


def test_page_step_requires_boundary_evidence() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    raw = compiled.sections["2.6.5"].retrieval_plan[0].model_dump()
    raw["content_window"]["start_at"] = {
        "kind": "heading",
        "value": "A missing boundary",
    }

    with pytest.raises(ValidationError, match="matching required evidence"):
        PageRetrievalStep.model_validate(raw)


def test_page_step_rejects_indb_as_required_evidence() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    raw = compiled.sections["2.6.5"].retrieval_plan[0].model_dump()
    raw["required_evidence"].append(
        {
            "kind": "contains_text",
            "value": "DIP4E_GLOBAL_Print_Ready.indb 98",
            "verification_mode": "text_or_visual",
        }
    )

    with pytest.raises(ValidationError, match="retrieval-only"):
        PageRetrievalStep.model_validate(raw)


def test_printed_page_evidence_requires_visual_verification() -> None:
    with pytest.raises(ValidationError, match="visual verification"):
        EvidenceRequirement(
            kind="printed_page_equals",
            value="105",
            verification_mode="text_or_visual",
        )


def test_content_window_boundary_requires_visual_evidence() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    raw = compiled.sections["2.6.5"].retrieval_plan[0].model_dump()
    for evidence in raw["required_evidence"]:
        if evidence["kind"] == "contains_heading" and evidence["value"] == "Spatial Operations":
            evidence["verification_mode"] = "text_or_visual"

    with pytest.raises(ValidationError, match="boundaries must require visual"):
        PageRetrievalStep.model_validate(raw)


def test_compiled_index_rejects_child_outside_parent_range() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    raw = compiled.model_dump(mode="json")
    parent = raw["sections"]["2.6.5"]
    parent["page_range"] = {
        "pdf_page_index_start": 2,
        "pdf_page_index_end": 2,
        "pdf_page_number_start": 3,
        "pdf_page_number_end": 3,
        "printed_page_start": "100",
        "printed_page_end": "100",
    }
    parent["retrieval_plan"] = [parent["retrieval_plan"][0]]
    parent["retrieval_plan"][0]["sequence"] = 1
    parent["retrieval_plan"][0]["page_role"] = "single"

    with pytest.raises(ValidationError, match="outside parent range"):
        CompiledLocatorIndex.model_validate(raw)


def test_compiled_index_rejects_implicit_same_page_sibling_boundary() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    raw = compiled.model_dump(mode="json")
    previous = raw["sections"]["2.6.1"]
    previous["retrieval_plan"][-1]["content_window"]["end_before"] = None

    with pytest.raises(ValidationError, match="same-page sibling boundary"):
        CompiledLocatorIndex.model_validate(raw)


def test_compiled_index_rejects_uncovered_body_page() -> None:
    pages = [
        {"pdf_page_index": 0, "pdf_page_number": 1, "printed_page_label": "1"},
        {"pdf_page_index": 1, "pdf_page_number": 2, "printed_page_label": "2"},
    ]
    raw = {
        "data_version": "3",
        "index_status": "complete",
        "book": {
            "book_id": "dip4e",
            "title": "Book",
            "author": "Author",
            "pdf_filename": "book.pdf",
            "pdf_sha256": "0" * 64,
            "page_count": 2,
        },
        "pages": pages,
        "page_classifications": [
            {"page": page, "category": "body", "reason": "test"} for page in pages
        ],
        "sections": {
            "1": {
                "data_version": "3",
                "book_id": "dip4e",
                "section_kind": "printed",
                "section_id": "1",
                "printed_section_id": "1",
                "parent_section_id": None,
                "title": "Introduction",
                "source_heading": "1 Introduction",
                "source_heading_numbered": True,
                "source_location": {"page": pages[0], "bbox": [0, 10, 100, 20]},
                "source_level": 0,
                "hierarchy_depth": 1,
                "page_range": {
                    "pdf_page_index_start": 0,
                    "pdf_page_index_end": 0,
                    "pdf_page_number_start": 1,
                    "pdf_page_number_end": 1,
                    "printed_page_start": "1",
                    "printed_page_end": "1",
                },
                "outline": [],
                "retrieval_plan": [
                    {
                        "sequence": 1,
                        "page_role": "single",
                        "page": pages[0],
                        "content_window": {"start_at": None, "end_before": None},
                        "queries": [
                            "1 Introduction printed page 1 --QDF=0",
                            "Introduction page 1 --QDF=0",
                        ],
                        "required_evidence": [
                            {
                                "kind": "printed_page_equals",
                                "value": "1",
                                "verification_mode": "visual_required",
                            },
                            {
                                "kind": "contains_heading",
                                "value": "1 Introduction",
                                "verification_mode": "visual_required",
                            },
                        ],
                        "coverage": {
                            "subheadings": [],
                            "figure_ids": [],
                            "equation_ids": [],
                            "example_ids": [],
                            "table_ids": [],
                        },
                    }
                ],
            }
        },
    }

    with pytest.raises(ValidationError, match="explicit parent-only content"):
        CompiledLocatorIndex.model_validate(raw)
