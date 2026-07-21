import pytest
from pydantic import ValidationError

from app.models.locator import PageReference, PageRetrievalStep, SectionLocator
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
            {"kind": "printed_page_equals", "value": "99"},
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
        }
    )

    with pytest.raises(ValidationError, match="retrieval-only"):
        PageRetrievalStep.model_validate(raw)
