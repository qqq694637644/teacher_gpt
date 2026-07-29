from types import SimpleNamespace

import fitz
import pytest
import yaml

from app.models.exercise_manifest import ExerciseManifest, ExerciseManifestPackage
from app.models.locator import (
    ContentWindow,
    EvidenceRequirement,
    PageCoverage,
    PageRetrievalStep,
    query_parentheses_balanced,
    query_safe_anchor,
)
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
    _exercise_evidence_exists,
    load_exercise_manifest,
    verify_complete_chapters,
    write_compiled_exercise_package,
)
from tools.extract_pdf_candidates import (
    EXERCISE_RE,
    HEADING_COLOR,
    TextLine,
    _column_for_x,
    merge_visual_lines,
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
    assert [step.page for step in first.reference_targets[0].retrieval_plan] == [
        step.page for step in section_index.sections["2.6.5"].retrieval_plan
    ]
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
        *[step.page for step in first.problem_retrieval_plan],
        *[step.page for step in first.reference_retrieval_plan],
    ]
    assert any(
        item.kind == "contains_exercise" and item.value == "2.14"
        for item in second.reference_retrieval_plan[0].required_evidence
    )
    assert any(
        item.kind == "contains_heading"
        for step in second.reference_retrieval_plan[1:]
        for item in step.required_evidence
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


def test_exercise_compiler_uses_explicit_context_pages_and_coalesces_exact_windows() -> None:
    raw = complete_exercise_manifest().model_dump(mode="json")
    raw["exercises"][0]["reference_specs"] = [
        {
            "kind": "section",
            "target_id": "2.6",
            "reason": "Broad section context",
            "selected_context_pages": ["98"],
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
    assert locator.reference_targets[0].selected_context_pages == ["98"]
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
    assert compiler.reference_plan_stats.selected_context_reference_count == 1
    assert compiler.reference_plan_stats.execution_reference_step_count_before_merge == 5
    assert compiler.reference_plan_stats.coalesced_reference_step_count == 2
    assert compiler.reference_plan_stats.same_page_distinct_window_step_count == 0
    assert compiler.reference_plan_stats.deduplicated_reference_step_count == 3


def test_visual_line_merge_restores_formula_fragment_reading_order() -> None:
    page = SimpleNamespace(rect=SimpleNamespace(width=533.0))
    lines = [
        TextLine(
            text="in Eqs. (7-16) and",
            pdf_page_index=0,
            pdf_page_number=1,
            printed_page_label="534",
            bbox=(182.47, 66.36, 268.79, 75.36),
            font_names=("TimesTen-Roman",),
            max_font_size=9.0,
            colors=(2301728,),
        ),
        TextLine(
            text="7.3 * Prove that",
            pdf_page_index=0,
            pdf_page_number=1,
            printed_page_label="534",
            bbox=(51.15, 66.36, 145.44, 75.36),
            font_names=("TimesTen-Bold",),
            max_font_size=9.0,
            colors=(28319,),
        ),
        TextLine(
            text="=",
            pdf_page_index=0,
            pdf_page_number=1,
            printed_page_label="534",
            bbox=(151.19, 65.94, 156.13, 74.94),
            font_names=("Symbol",),
            max_font_size=9.0,
            colors=(2301728,),
        ),
        TextLine(
            text="(7-17) for real vectors.",
            pdf_page_index=0,
            pdf_page_number=1,
            printed_page_label="534",
            bbox=(75.05, 77.36, 236.34, 86.36),
            font_names=("TimesTen-Roman",),
            max_font_size=9.0,
            colors=(2301728,),
        ),
    ]

    merged = merge_visual_lines(page.rect.width, lines)

    assert merged[0].text == "7.3 * Prove that = in Eqs. (7-16) and"
    assert merged[1].text == "(7-17) for real vectors."


def test_contains_text_evidence_allows_interleaved_formula_fragments() -> None:
    evidence = EvidenceRequirement(
        kind="contains_text",
        value="Show that e 0 dm t 0 where t0 is a condition",
        verification_mode="text_or_visual",
    )
    page_anchor = {
        "normalized_text": "Show that e 0 equals dm inserted formula t 0 where t0 is a condition"
    }

    assert _exercise_evidence_exists(page_anchor, evidence)


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Use Eqs. (2-46) and (2-47).",
            [("equation", "2-46"), ("equation", "2-47")],
        ),
        (
            "Use Equation (2-46).",
            [("equation", "2-46")],
        ),
        (
            "Use Equations (2-46) and (2-47).",
            [("equation", "2-46"), ("equation", "2-47")],
        ),
        (
            "Use Eqs. (4-42) through (4-45).",
            [
                ("equation", "4-42"),
                ("equation", "4-43"),
                ("equation", "4-44"),
                ("equation", "4-45"),
            ],
        ),
        (
            "Apply Eqs. (6-6)-(6-12).",
            [("equation", f"6-{number}") for number in range(6, 13)],
        ),
        (
            "Review Sections 3.4-3.7.",
            [("section", f"3.{number}") for number in range(4, 8)],
        ),
        (
            "Compare Sections 2.4 and 2.5.",
            [("section", "2.4"), ("section", "2.5")],
        ),
        (
            "Use Figs. 2.3(a), 2.4(b), and 2.5(a, b).",
            [("figure", "2.3"), ("figure", "2.4"), ("figure", "2.5")],
        ),
        (
            ("Compare Tables 11.2 and 11.3, Examples 3.1, 3.2, and 3.3, and Problems 4.4 and 4.9."),
            [
                ("table", "11.2"),
                ("table", "11.3"),
                ("example", "3.1"),
                ("example", "3.2"),
                ("example", "3.3"),
                ("exercise", "4.4"),
                ("exercise", "4.9"),
            ],
        ),
        (
            (
                "Use Sec- tion 2.5, Prob- lem 7.13, Exam- ple 7.3, "
                "Equa- tion (2-46), Fig- ure 2.3(a), and Ta- ble 11.3."
            ),
            [
                ("section", "2.5"),
                ("exercise", "7.13"),
                ("example", "7.3"),
                ("equation", "2-46"),
                ("figure", "2.3"),
                ("table", "11.3"),
            ],
        ),
        (
            "Recompute the transform in Exam- fx () = ple 7.19.",
            [("example", "7.19")],
        ),
    ],
)
def test_reference_parser_expands_parallel_and_range_references(
    text: str,
    expected: list[tuple[str, str]],
) -> None:
    specs = _reference_specs(text, "12.99")

    assert [(item.kind, item.target_id) for item in specs] == expected


def test_query_safe_anchor_removes_unbalanced_parentheses() -> None:
    value = "versa. (Do not confuse correlation and statistical independence..."

    anchor = query_safe_anchor(value)
    queries = ExerciseIndexCompiler._safe_queries(
        [
            EvidenceRequirement(
                kind="printed_page_equals",
                value="86",
                verification_mode="visual_required",
            ),
            EvidenceRequirement(
                kind="contains_text",
                value=value,
                verification_mode="text_or_visual",
            ),
        ],
        "86",
    )

    assert anchor == "versa Do not confuse correlation and statistical independence"
    assert all(query_parentheses_balanced(query) for query in queries)
    assert all(anchor.casefold() in query.casefold() for query in queries)


def test_query_safe_anchor_normalizes_pdf_ligatures() -> None:
    assert query_safe_anchor("ﬁeld ﬁrst deﬁned ﬁgure ﬂat") == ("field first defined figure flat")


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
