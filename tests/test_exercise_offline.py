import fitz
import pytest
import yaml

from app.models.exercise_manifest import ExerciseManifestPackage
from app.repositories.exercise_repository import ExerciseRepository
from app.services.exercise_index_compiler import ExerciseIndexCompiler
from app.services.index_compiler import LocatorIndexCompiler
from tests.helpers import complete_exercise_manifest, complete_manifest
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
    assert second.reference_targets[0].kind == "exercise"
    assert second.reference_targets[0].retrieval_plan == first.problem_retrieval_plan

    output = tmp_path / "compiled_exercise_index.json"
    write_compiled_exercise_package(compiled, output)
    assert ExerciseRepository.load(output).index == compiled


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
    with pytest.raises(ValueError, match="does not cover all chapters"):
        verify_complete_chapters(complete_exercise_manifest())
