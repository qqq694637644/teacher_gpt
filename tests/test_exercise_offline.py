import fitz
import pytest
import yaml

from app.models.exercise_manifest import ExerciseManifest, ExerciseManifestPackage
from app.models.locator import ContentWindow, EvidenceRequirement, PageCoverage, PageRetrievalStep
from app.repositories.exercise_repository import ExerciseRepository
from app.services.exercise_index_compiler import ExerciseIndexCompiler
from app.services.index_compiler import LocatorIndexCompiler
from tests.helpers import PAGES, complete_exercise_manifest, complete_manifest
from tools.build_dip4e_exercise_manifest import (
    _reference_specs,
    write_exercise_manifest_package,
)
from tools.build_dip4e_manifest import SourceNode, _assign_ranges, _terminal_boundaries
from tools.compile_exercise_index import (
    load_exercise_manifest,
    verify_complete_chapters,
    write_compiled_exercise_package,
)
from tools.extract_pdf_candidates import (
    EXERCISE_RE,
    HEADING_COLOR,
    TextLine,
    _column_for_x,
)


def test_exercise_manifest_package_round_trips(tmp_path) -> None:
    manifest = complete_exercise_manifest()
    path = tmp_path / "exercises.yaml"

    write_exercise_manifest_package(manifest, path)
    loaded = load_exercise_manifest(path)

    assert loaded == manifest
    assert sorted(item.name for item in tmp_path.glob("exercises.sections.*.yaml")) == [
        "exercises.sections.02.yaml"
    ]
    package = ExerciseManifestPackage.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    assert package.chapter_ids == ["2"]


def test_exercise_compiler_resolves_section_and_exercise_references(tmp_path) -> None:
    manifest = complete_exercise_manifest()
    section_index = LocatorIndexCompiler().compile(complete_manifest())

    compiled = ExerciseIndexCompiler().compile(manifest, section_index)

    first = compiled.exercises["2.14"]
    second = compiled.exercises["2.15"]
    assert first.reference_targets[0].kind == "section"
    assert first.reference_targets[0].target_id == "2.6.5"
    assert (
        first.reference_targets[0].retrieval_plan == section_index.sections["2.6.5"].retrieval_plan
    )
    assert [step.page for step in first.reference_retrieval_plan] == [
        step.page for step in section_index.sections["2.6.5"].retrieval_plan
    ]
    assert any(
        item.kind == "contains_heading"
        for item in first.reference_retrieval_plan[0].required_evidence
    )
    assert second.reference_targets[0].kind == "exercise"
    assert second.reference_targets[0].retrieval_plan == first.problem_retrieval_plan
    assert [step.page for step in second.reference_retrieval_plan] == [
        step.page for step in first.problem_retrieval_plan
    ]
    assert any(
        item.kind == "contains_exercise" and item.value == "2.14"
        for item in second.reference_retrieval_plan[0].required_evidence
    )

    output = tmp_path / "compiled_exercise_index.json"
    write_compiled_exercise_package(compiled, output)
    assert ExerciseRepository.load(output).index == compiled


def _equation_reference_step() -> PageRetrievalStep:
    page = PAGES[0]
    return PageRetrievalStep(
        sequence=1,
        page_role="single",
        page=page,
        content_window=ContentWindow(),
        queries=[
            f"+(equation 2-1) +(printed page {page.printed_page_label}) --QDF=0",
            f"+(2-1) +(equation) +(printed page {page.printed_page_label}) --QDF=0",
        ],
        required_evidence=[
            EvidenceRequirement(
                kind="printed_page_equals",
                value=page.printed_page_label,
                verification_mode="visual_required",
            ),
            EvidenceRequirement(
                kind="contains_equation",
                value="2-1",
                verification_mode="visual_required",
            ),
        ],
        coverage=PageCoverage(equation_ids=["2-1"]),
    )


def test_exercise_compiler_prunes_broad_sections_and_deduplicates_pages() -> None:
    raw = complete_exercise_manifest().model_dump(mode="json")
    raw["exercises"][0]["reference_specs"] = [
        {
            "kind": "section",
            "target_id": "2.6",
            "reason": "Broad section context",
        },
        {
            "kind": "equation",
            "target_id": "2-1",
            "reason": "Precise equation dependency",
        },
    ]
    manifest = ExerciseManifest.model_validate(raw)
    section_index = LocatorIndexCompiler().compile(complete_manifest())
    compiler = ExerciseIndexCompiler()

    compiled = compiler.compile(
        manifest,
        section_index,
        {("equation", "2-1"): [_equation_reference_step()]},
    )

    locator = compiled.exercises["2.14"]
    assert [(target.kind, target.target_id) for target in locator.reference_targets] == [
        ("section", "2.6"),
        ("equation", "2-1"),
    ]
    assert len(locator.reference_targets[0].retrieval_plan) == 4
    assert [step.page.pdf_page_index for step in locator.reference_retrieval_plan] == [0]
    assert {
        (item.kind, item.value) for item in locator.reference_retrieval_plan[0].required_evidence
    } == {
        ("printed_page_equals", "98"),
        (
            "contains_heading",
            "2.6 INTRODUCTION TO THE BASIC MATHEMATICAL TOOLS USED IN DIGITAL IMAGE PROCESSING",
        ),
        ("contains_equation", "2-1"),
    }
    assert compiler.reference_plan_stats.raw_reference_step_count == 6
    assert compiler.reference_plan_stats.pruned_context_reference_count == 1
    assert compiler.reference_plan_stats.duplicate_reference_page_count == 1
    assert compiler.reference_plan_stats.deduplicated_reference_step_count == 2


def test_reference_parser_extracts_supported_explicit_dependencies() -> None:
    text = "Use Section 2.5, Eq. (2-43), Figure 2.38, Table 2.3, Example 2.5, and Problem 2.6."

    specs = _reference_specs(text, "2.14")

    assert [(item.kind, item.target_id) for item in specs] == [
        ("section", "2.5"),
        ("equation", "2-43"),
        ("figure", "2.38"),
        ("table", "2.3"),
        ("example", "2.5"),
        ("exercise", "2.6"),
    ]


def test_reference_parser_applies_audited_source_erratum() -> None:
    specs = _reference_specs(
        "Sketch the result using the 3 x 3 Laplacian kernel in Fig. 10.10.4(a).",
        "10.23",
    )

    assert len(specs) == 1
    assert specs[0].kind == "figure"
    assert specs[0].target_id == "10.4"
    assert "prints Fig. 10.10.4(a)" in specs[0].reason


def test_terminal_boundary_is_inherited_by_last_learning_unit() -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 120), "Summary")
    try:
        boundaries = _terminal_boundaries(document, 0, 0)
        assert len(boundaries) == 1
        assert boundaries[0].kind == "text"
        assert boundaries[0].text == "Summary"

        node = SourceNode(
            title="Last unit",
            source_heading="LAST UNIT",
            source_location=complete_manifest().printed_sections[1].source_location,
            source_level=1,
            start_index=0,
        )
        _assign_ranges(document, [node], 0, boundaries[0])
        assert node.end_before == boundaries[0]
    finally:
        document.close()


def test_full_book_guard_rejects_partial_exercise_manifest() -> None:
    with pytest.raises(ValueError, match="does not cover all Problems chapters"):
        verify_complete_chapters(complete_exercise_manifest(), {"2", "3"})


def test_full_book_guard_accepts_exact_problems_chapters() -> None:
    verify_complete_chapters(complete_exercise_manifest(), {"2"})


def test_exercise_layout_filter_distinguishes_reference_from_problem_number() -> None:
    reference = TextLine(
        text="12.32 is 1. Is this vector augmented? Explain.",
        pdf_page_index=0,
        pdf_page_number=1,
        printed_page_label="1",
        bbox=(79.0, 400.0, 250.0, 410.0),
        font_names=("TimesTen-Roman",),
        max_font_size=9.0,
        colors=(2301728,),
    )
    problem = TextLine(
        text="12.32 * Show the validity of Eq. (12-106).",
        pdf_page_index=0,
        pdf_page_number=1,
        printed_page_label="1",
        bbox=(50.0, 287.0, 207.0, 296.0),
        font_names=("TimesTen-Bold", "TimesTen-Roman"),
        max_font_size=9.0,
        colors=(HEADING_COLOR, 2301728),
    )

    assert EXERCISE_RE.match(reference.text) is not None
    assert "TimesTen-Bold" not in reference.font_names
    assert EXERCISE_RE.match(problem.text) is not None
    assert "TimesTen-Bold" in problem.font_names
    assert HEADING_COLOR in problem.colors
    problem_match = EXERCISE_RE.match(problem.text)
    assert problem_match is not None
    assert problem_match.group("trailing_star") is not None


def test_exercise_column_split_handles_narrow_book_gutter() -> None:
    assert _column_for_x(533.0, 253.0) == 0
    assert _column_for_x(533.0, 263.0) == 1
