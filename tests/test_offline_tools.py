from pathlib import Path

import fitz
import pytest

from tests.helpers import complete_manifest
from tools.compile_locator_index import (
    _iter_manifest_steps,
    manifest_heading_keys,
    verify_heading_coverage,
    verify_manifest_anchors,
)
from tools.extract_pdf_candidates import (
    HEADING_COLOR,
    HEADING_FONT,
    HeadingCandidate,
    TextLine,
    is_heading_line,
    page_references,
)
from tools.validate_prompt import validate_prompt


def test_heading_candidate_requires_verified_dip4e_style() -> None:
    heading = TextLine(
        text="SPATIAL OPERATIONS",
        pdf_page_index=99,
        pdf_page_number=100,
        printed_page_label="98",
        bbox=(120.0, 543.0, 233.0, 555.0),
        font_names=(HEADING_FONT,),
        max_font_size=10.954,
        colors=(HEADING_COLOR,),
    )
    figure_label = TextLine(
        text="FIGURE 2.41",
        pdf_page_index=106,
        pdf_page_number=107,
        printed_page_label="105",
        bbox=(51.0, 77.0, 91.0, 87.0),
        font_names=(HEADING_FONT,),
        max_font_size=10.954,
        colors=(HEADING_COLOR,),
    )

    assert is_heading_line(heading)
    assert not is_heading_line(figure_label)


def test_page_references_use_pdf_page_labels(tmp_path: Path) -> None:
    pdf_path = tmp_path / "labels.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.set_page_labels(
        [
            {"startpage": 0, "prefix": "Cover", "firstpagenum": 1},
            {"startpage": 1, "prefix": "", "firstpagenum": 1, "style": "D"},
        ]
    )
    document.save(pdf_path)
    document.close()

    loaded = fitz.open(pdf_path)
    try:
        assert page_references(loaded) == [
            {
                "pdf_page_index": 0,
                "pdf_page_number": 1,
                "printed_page_label": "Cover",
            },
            {
                "pdf_page_index": 1,
                "pdf_page_number": 2,
                "printed_page_label": "1",
            },
        ]
    finally:
        loaded.close()


def test_prompt_validator_rejects_invented_page_tool() -> None:
    valid = (
        "gptGetSectionLocator gptGetExerciseLocator gptListChapterExercises "
        "file_search.msearch file_search.mclick contains_exercise "
        "required_evidence content_window reference_retrieval_plan data_version "
        "只传入一条 query "
        "EXERCISE_CATALOG_UNAVAILABLE"
    )
    validate_prompt(valid)

    with pytest.raises(ValueError, match="forbidden"):
        validate_prompt(valid + " file_library.open_page")

    with pytest.raises(ValueError, match="forbidden"):
        validate_prompt(valid + ' source_filter=["file_library"]')


def test_complete_manifest_must_cover_every_source_heading_candidate() -> None:
    manifest = complete_manifest()
    candidates = []
    for text, page_index, bbox, numbered, printed_section_id in manifest_heading_keys(manifest):
        candidates.append(
            HeadingCandidate(
                text=text,
                printed_section_id=printed_section_id,
                pdf_page_index=page_index,
                pdf_page_number=page_index + 1,
                printed_page_label=manifest.pages[page_index].printed_page_label,
                bbox=bbox,
                numbered=numbered,
                style_signature="test",
            )
        )

    counts = verify_heading_coverage(manifest, candidates)
    assert counts == {
        "heading_candidate_count": 16,
        "numbered_heading_count": 2,
        "learning_heading_count": 14,
    }

    with pytest.raises(ValueError, match="missing="):
        verify_heading_coverage(manifest, candidates[:-1])


def _page_anchors_for_manifest(manifest):
    heading_y = {}

    def record_units(units):
        for unit in units:
            heading_y[(unit.source_location.page.pdf_page_index, unit.source_heading)] = (
                unit.source_location.bbox[1]
            )
            record_units(unit.children)

    for section in manifest.printed_sections:
        heading_y[(section.source_location.page.pdf_page_index, section.source_heading)] = (
            section.source_location.bbox[1]
        )
        record_units(section.learning_units)

    anchors = [
        {
            "pdf_page_index": page.pdf_page_index,
            "printed_page_label": page.printed_page_label,
            "heading_records": [],
            "text_records": [],
            "figure_records": [],
            "equation_records": [],
            "example_records": [],
            "table_records": [],
            "figure_ids": [],
            "equation_ids": [],
            "example_ids": [],
            "table_ids": [],
            "normalized_text": "",
            "running_header": "",
        }
        for page in manifest.pages
    ]
    for _section_id, _source_heading, steps in _iter_manifest_steps(manifest):
        for step in steps:
            anchor = anchors[step.page.pdf_page_index]
            for heading in step.coverage.subheadings:
                y = heading_y.get((step.page.pdf_page_index, heading), 50)
                anchor["heading_records"].append({"text": heading, "bbox": [0, y, 1, y + 1]})
            for evidence in step.required_evidence:
                if evidence.kind in {"contains_heading", "contains_text"}:
                    anchor["normalized_text"] += f" {evidence.value}"
                if evidence.kind == "contains_text":
                    anchor["text_records"].append({"text": evidence.value, "bbox": [0, 10, 1, 11]})
                if evidence.kind == "contains_heading":
                    y = heading_y.get((step.page.pdf_page_index, evidence.value), 50)
                    anchor["heading_records"].append(
                        {"text": evidence.value, "bbox": [0, y, 1, y + 1]}
                    )
    return anchors


def test_source_anchor_verifier_rejects_wrong_figure_and_query() -> None:
    manifest = complete_manifest()
    anchors = _page_anchors_for_manifest(manifest)
    raw = manifest.model_dump(mode="json")
    step = raw["printed_sections"][1]["learning_units"][4]["retrieval_plan"][0]
    step["coverage"]["figure_ids"] = ["99.99"]
    step["queries"] = [
        "completely wrong query printed page 100 --QDF=0",
        "another wrong query printed page 100 --QDF=0",
    ]
    broken = type(manifest).model_validate(raw)

    with pytest.raises(ValueError, match="coverage anchors do not exist"):
        verify_manifest_anchors(broken, anchors)


def test_source_anchor_verifier_rejects_unanchored_queries() -> None:
    manifest = complete_manifest()
    anchors = _page_anchors_for_manifest(manifest)
    raw = manifest.model_dump(mode="json")
    step = raw["printed_sections"][1]["learning_units"][4]["retrieval_plan"][0]
    step["queries"] = [
        "completely wrong query printed page 100 --QDF=0",
        "another wrong query printed page 100 --QDF=0",
    ]
    broken = type(manifest).model_validate(raw)

    with pytest.raises(ValueError, match="no source-PDF anchor"):
        verify_manifest_anchors(broken, anchors)


def test_source_anchor_verifier_rejects_coverage_outside_content_window() -> None:
    manifest = complete_manifest()
    anchors = _page_anchors_for_manifest(manifest)
    raw = manifest.model_dump(mode="json")
    step = raw["printed_sections"][1]["learning_units"][0]["retrieval_plan"][0]
    step["coverage"]["figure_ids"] = ["9.9"]
    page_anchor = anchors[step["page"]["pdf_page_index"]]
    page_anchor["figure_ids"].append("9.9")
    page_anchor["figure_records"].append({"id": "9.9", "bbox": [0, 50, 1, 51]})
    broken = type(manifest).model_validate(raw)

    with pytest.raises(ValueError, match="coverage anchors do not exist"):
        verify_manifest_anchors(broken, anchors)
