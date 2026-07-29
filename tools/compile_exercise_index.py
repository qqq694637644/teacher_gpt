#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
import yaml
from pydantic import ValidationError

from app.models.exercise import (
    CompiledExerciseIndex,
    CompiledExerciseIndexPackage,
    ExerciseChapterShard,
)
from app.models.exercise_manifest import (
    ExerciseManifest,
    ExerciseManifestPackage,
    ExerciseManifestShard,
)
from app.models.locator import (
    ContentWindow,
    EvidenceRequirement,
    PageCoverage,
    PageRetrievalStep,
)
from app.repositories.locator_repository import LocatorRepository
from app.services.exercise_index_compiler import ExerciseIndexCompiler, ReferencePlanMap
from tools.compile_locator_index import _boundary_record, _evidence_exists
from tools.extract_pdf_candidates import (
    COLUMN_SPLIT_RATIO,
    ExerciseCandidate,
    clean_text,
    extract_exercise_candidates,
    extract_page_anchors,
    extract_problem_headings,
    sha256_file,
)

ANCHOR_RECORD_KEYS = {
    "figure": "figure_records",
    "equation": "equation_records",
    "example": "example_records",
    "table": "table_records",
}
ANCHOR_EVIDENCE_KINDS = {
    "figure": "contains_figure",
    "equation": "contains_equation",
    "example": "contains_example",
    "table": "contains_table",
}


def sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_exercise_manifest(path: Path) -> ExerciseManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "exercise_shards" in raw:
            package = ExerciseManifestPackage.model_validate(raw)
            exercises = []
            seen_chapters: set[str] = set()
            for shard_name in package.exercise_shards:
                shard_path = path.parent / shard_name
                shard_raw = yaml.safe_load(shard_path.read_text(encoding="utf-8"))
                shard = ExerciseManifestShard.model_validate(shard_raw)
                filename_chapter = str(int(shard_name.removesuffix(".yaml").rsplit(".", 1)[1]))
                if shard.chapter_id != filename_chapter:
                    raise ValueError(
                        f"exercise manifest shard chapter does not match filename: {shard_name}"
                    )
                if shard.chapter_id in seen_chapters:
                    raise ValueError(f"duplicate exercise manifest chapter: {shard.chapter_id}")
                seen_chapters.add(shard.chapter_id)
                exercises.extend(shard.exercises)
            raw = {
                **package.model_dump(
                    mode="json",
                    exclude={"exercise_shards", "chapter_ids"},
                ),
                "exercises": [item.model_dump(mode="json") for item in exercises],
            }
        return ExerciseManifest.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError, TypeError, ValueError) as exc:
        raise ValueError(f"exercise manifest validation failed: {exc}") from exc


def exercise_manifest_package_hashes(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    files = [path]
    files.extend(path.parent / name for name in raw.get("exercise_shards", []))
    return {file.name: sha256_file(file) for file in files}


def verify_complete_chapters(
    manifest: ExerciseManifest,
    expected_chapter_ids: set[str],
) -> None:
    actual = {item.chapter_id for item in manifest.exercises}
    if actual != expected_chapter_ids:
        missing = sorted(expected_chapter_ids - actual, key=int)
        extra = sorted(actual - expected_chapter_ids, key=int)
        raise ValueError(
            "exercise manifest does not cover all Problems chapters; "
            f"missing={missing}; extra={extra}"
        )


def verify_candidate_coverage(
    manifest: ExerciseManifest,
    candidates: list[ExerciseCandidate],
) -> dict[str, int]:
    # Page/bbox/column are verified directly below because the manifest intentionally
    # stores only retrieval semantics, not duplicate candidate-layout fields.
    expected_ids = {item.exercise_id for item in candidates}
    actual_ids = {item.exercise_id for item in manifest.exercises}
    if expected_ids != actual_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ValueError(f"exercise candidate coverage differs; missing={missing}; extra={extra}")
    candidate_by_id = {item.exercise_id: item for item in candidates}
    for node in manifest.exercises:
        candidate = candidate_by_id[node.exercise_id]
        if node.chapter_id != candidate.chapter_id:
            raise ValueError(f"chapter mismatch for exercise {node.exercise_id}")
        if node.exercise_number != candidate.exercise_number:
            raise ValueError(f"number mismatch for exercise {node.exercise_id}")
        if node.starred != candidate.starred:
            raise ValueError(f"starred flag mismatch for exercise {node.exercise_id}")
        if node.source_order != candidate.source_order:
            raise ValueError(f"source order mismatch for exercise {node.exercise_id}")
        first = node.problem_retrieval_plan[0]
        if first.page.pdf_page_index != candidate.pdf_page_index:
            raise ValueError(f"start page mismatch for exercise {node.exercise_id}")
        exercise_records = [
            item
            for item in first.required_evidence
            if item.kind == "contains_exercise" and item.value == node.exercise_id
        ]
        if len(exercise_records) != 1:
            raise ValueError(f"missing unique exercise evidence for {node.exercise_id}")
    return {
        "exercise_candidate_count": len(candidates),
        "starred_exercise_count": sum(item.starred for item in candidates),
    }


def _bbox_key(page_width: float, bbox: list[float]) -> tuple[int, float, float]:
    x0 = float(bbox[0])
    return (0 if x0 < page_width * COLUMN_SPLIT_RATIO else 1, float(bbox[1]), x0)


def _at_or_after_boundary(
    page_width: float,
    bbox: list[float],
    boundary_bbox: list[float],
) -> bool:
    column = 0 if float(bbox[0]) < page_width * COLUMN_SPLIT_RATIO else 1
    boundary_column = 0 if float(boundary_bbox[0]) < page_width * COLUMN_SPLIT_RATIO else 1
    if column != boundary_column:
        return column > boundary_column
    return float(bbox[1]) >= float(boundary_bbox[1]) - 0.5


def _record_in_window(
    record: dict[str, Any],
    *,
    page_width: float,
    start_record: dict[str, Any] | None,
    end_record: dict[str, Any] | None,
    reading_order: bool,
) -> bool:
    if reading_order:
        if start_record is not None and not _at_or_after_boundary(
            page_width,
            record["bbox"],
            start_record["bbox"],
        ):
            return False
        return not (
            end_record is not None
            and _at_or_after_boundary(
                page_width,
                record["bbox"],
                end_record["bbox"],
            )
        )
    y0 = float(record["bbox"][1])
    if start_record is not None and y0 < float(start_record["bbox"][1]) - 0.5:
        return False
    return not (end_record is not None and y0 >= float(end_record["bbox"][1]) - 0.5)


def _verify_coverage(
    page_anchor: dict[str, Any],
    coverage: PageCoverage,
    *,
    page_width: float,
    start_record: dict[str, Any] | None,
    end_record: dict[str, Any] | None,
    reading_order: bool,
) -> dict[str, list[str]]:
    expected = {
        "figure_ids": set(coverage.figure_ids),
        "equation_ids": set(coverage.equation_ids),
        "example_ids": set(coverage.example_ids),
        "table_ids": set(coverage.table_ids),
    }
    actual = {}
    for output_key, record_key in (
        ("figure_ids", "figure_records"),
        ("equation_ids", "equation_records"),
        ("example_ids", "example_records"),
        ("table_ids", "table_records"),
    ):
        actual[output_key] = {
            item["id"]
            for item in page_anchor[record_key]
            if _record_in_window(
                item,
                page_width=page_width,
                start_record=start_record,
                end_record=end_record,
                reading_order=reading_order,
            )
        }
    return {
        key: sorted(values - actual[key])
        for key, values in expected.items()
        if values - actual[key]
    }


def verify_manifest_anchors(
    manifest: ExerciseManifest,
    page_anchors: list[dict[str, Any]],
    page_widths: list[float],
) -> dict[str, int | str]:
    step_count = 0
    evidence_count = 0
    query_count = 0
    reference_count = 0
    cross_page_count = 0
    for node in manifest.exercises:
        if len(node.problem_retrieval_plan) > 1:
            cross_page_count += 1
        reference_count += len(node.reference_specs)
        for step in node.problem_retrieval_plan:
            step_count += 1
            page_index = step.page.pdf_page_index
            page_anchor = page_anchors[page_index]
            if page_anchor["printed_page_label"] != step.page.printed_page_label:
                raise ValueError(f"page anchor label mismatch for exercise {node.exercise_id}")
            start = step.content_window.start_at
            end = step.content_window.end_before
            start_record = _boundary_record(page_anchor, start) if start is not None else None
            end_record = _boundary_record(page_anchor, end) if end is not None else None
            if start is not None and start_record is None:
                raise ValueError(f"missing start boundary for exercise {node.exercise_id}")
            if end is not None and end_record is None:
                raise ValueError(f"missing end boundary for exercise {node.exercise_id}")
            reading_order = (start is not None and start.kind == "exercise") or (
                end is not None and end.kind == "exercise"
            )
            if start_record is not None and end_record is not None:
                if reading_order:
                    if _bbox_key(page_widths[page_index], end_record["bbox"]) <= _bbox_key(
                        page_widths[page_index], start_record["bbox"]
                    ):
                        raise ValueError(f"reversed exercise boundaries for {node.exercise_id}")
                elif float(end_record["bbox"][1]) <= float(start_record["bbox"][1]):
                    raise ValueError(f"reversed content boundaries for {node.exercise_id}")

            missing = _verify_coverage(
                page_anchor,
                step.coverage,
                page_width=page_widths[page_index],
                start_record=start_record,
                end_record=end_record,
                reading_order=reading_order,
            )
            if missing:
                raise ValueError(
                    f"coverage anchors do not exist for exercise {node.exercise_id} "
                    f"page {step.page.printed_page_label}: {missing}"
                )
            for evidence in step.required_evidence:
                evidence_count += 1
                if not _evidence_exists(page_anchor, evidence):
                    raise ValueError(
                        f"required evidence does not exist for exercise {node.exercise_id} "
                        f"page {step.page.printed_page_label}: {evidence.kind}={evidence.value!r}"
                    )
            anchors = [
                clean_text(item.value)
                for item in step.required_evidence
                if item.kind != "printed_page_equals"
            ]
            for query in step.queries:
                query_count += 1
                folded = clean_text(query.replace("--QDF=0", "")).casefold()
                if step.page.printed_page_label.casefold() not in folded:
                    raise ValueError(
                        f"query omits printed page for exercise {node.exercise_id}: {query!r}"
                    )
                if not any(anchor.casefold() in folded for anchor in anchors):
                    raise ValueError(
                        f"query has no source anchor for exercise {node.exercise_id}: {query!r}"
                    )
    return {
        "exercise_retrieval_step_count": step_count,
        "source_evidence_check_count": evidence_count,
        "query_text_anchor_check_count": query_count,
        "exercise_reference_count": reference_count,
        "cross_page_exercise_count": cross_page_count,
        "source_pdf_verification_status": "passed",
        "file_search_retrieval_status": "not_tested",
    }


def verify_source_pdf(
    manifest: ExerciseManifest,
    pdf_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, int | str]]:
    if sha256_file(pdf_path) != manifest.book.pdf_sha256:
        raise ValueError("source PDF SHA-256 does not match exercise manifest")
    document = fitz.open(pdf_path)
    try:
        if document.page_count != manifest.book.page_count:
            raise ValueError("source PDF page count does not match exercise manifest")
        for page in manifest.pages:
            label = clean_text(document[page.pdf_page_index].get_label())
            if label != page.printed_page_label:
                raise ValueError(
                    f"source PDF page label mismatch at index {page.pdf_page_index}: "
                    f"{label!r} != {page.printed_page_label!r}"
                )
        candidates = extract_exercise_candidates(document)
        expected_chapter_ids = set(extract_problem_headings(document))
        verify_complete_chapters(manifest, expected_chapter_ids)
        page_anchors = extract_page_anchors(document)
        page_widths = [float(document[index].rect.width) for index in range(document.page_count)]
        candidate_counts = verify_candidate_coverage(manifest, candidates)
        anchor_counts = verify_manifest_anchors(manifest, page_anchors, page_widths)
    finally:
        document.close()
    return page_anchors, {
        "exercise_chapter_count": len(expected_chapter_ids),
        **candidate_counts,
        **anchor_counts,
    }


def build_reference_plans(
    manifest: ExerciseManifest,
    page_anchors: list[dict[str, Any]],
) -> ReferencePlanMap:
    required = {
        (spec.kind, spec.target_id)
        for node in manifest.exercises
        for spec in node.reference_specs
        if spec.kind in ANCHOR_RECORD_KEYS
    }
    plans: ReferencePlanMap = {}
    for kind, target_id in sorted(required):
        record_key = ANCHOR_RECORD_KEYS[kind]
        matches = [
            (page_index, record)
            for page_index, page_anchor in enumerate(page_anchors)
            for record in page_anchor[record_key]
            if record["id"] == target_id
        ]
        if not matches:
            raise ValueError(f"cannot resolve {kind} reference {target_id}")
        page_index, _record = min(matches, key=lambda item: item[0])
        page = manifest.pages[page_index]
        evidence_kind = ANCHOR_EVIDENCE_KINDS[kind]
        plans[(kind, target_id)] = [
            PageRetrievalStep(
                sequence=1,
                page_role="single",
                page=page,
                content_window=ContentWindow(),
                queries=[
                    f"+({kind} {target_id}) +(printed page {page.printed_page_label}) --QDF=0",
                    f"+({target_id}) +({kind}) +(printed page {page.printed_page_label}) --QDF=0",
                ],
                required_evidence=[
                    EvidenceRequirement(
                        kind="printed_page_equals",
                        value=page.printed_page_label,
                        verification_mode="visual_required",
                    ),
                    EvidenceRequirement(
                        kind=evidence_kind,
                        value=target_id,
                        verification_mode="visual_required",
                    ),
                ],
                coverage=PageCoverage(),
            )
        ]
    return plans


def write_compiled_exercise_package(
    compiled: CompiledExerciseIndex,
    output: Path,
) -> dict[str, Any]:
    groups: dict[str, dict] = {}
    for exercise_id, locator in compiled.exercises.items():
        groups.setdefault(locator.chapter_id, {})[exercise_id] = locator

    output.parent.mkdir(parents=True, exist_ok=True)
    for stale in output.parent.glob("compiled_exercise_index.sections.*.json"):
        stale.unlink()

    shard_names: list[str] = []
    shard_hashes: dict[str, str] = {}
    for chapter_id in sorted(groups, key=int):
        shard_name = f"compiled_exercise_index.sections.{int(chapter_id):02d}.json"
        shard_path = output.parent / shard_name
        shard = ExerciseChapterShard(
            chapter_id=chapter_id,
            exercises=groups[chapter_id],
        )
        shard_path.write_text(
            json.dumps(shard.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        shard_names.append(shard_name)
        shard_hashes[shard_name] = sha256_file(shard_path)

    package = CompiledExerciseIndexPackage(
        index_status=compiled.index_status,
        book=compiled.book,
        pages=compiled.pages,
        chapters=compiled.chapters,
        exercise_shards=shard_names,
    )
    output.write_text(
        json.dumps(package.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "output_sha256": sha256_file(output),
        "assembled_index_sha256": sha256_json(compiled.model_dump(mode="json")),
        "exercise_shard_count": len(shard_names),
        "exercise_shard_sha256": shard_hashes,
    }


def _missing_exercise_numbers(exercise_ids: list[str]) -> list[int]:
    numbers = sorted(int(exercise_id.split(".", 1)[1]) for exercise_id in exercise_ids)
    if not numbers:
        return []
    return sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a strict Version 3 exercise index")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("section_index", type=Path)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_exercise_manifest(args.manifest)
    section_index = LocatorRepository.load(args.section_index).index
    page_anchors, verification = verify_source_pdf(manifest, args.pdf)
    reference_plans = build_reference_plans(manifest, page_anchors)
    compiled = ExerciseIndexCompiler().compile(manifest, section_index, reference_plans)

    output_details = write_compiled_exercise_package(compiled, args.output)
    chapter_reports = {
        chapter_id: {
            "first_exercise": summary.first_exercise,
            "last_exercise": summary.last_exercise,
            "exercise_count": summary.exercise_count,
            "missing_numbers": _missing_exercise_numbers(summary.exercise_ids),
            "duplicate_numbers": [],
        }
        for chapter_id, summary in compiled.chapters.items()
    }
    report = {
        "data_version": compiled.data_version,
        "index_status": compiled.index_status,
        "book_id": compiled.book.book_id,
        "pdf_sha256": compiled.book.pdf_sha256,
        "page_count": compiled.book.page_count,
        "exercise_count": len(compiled.exercises),
        "exercise_page_count": sum(
            len(locator.problem_retrieval_plan) for locator in compiled.exercises.values()
        ),
        "visual_required_exercise_count": sum(
            any(
                evidence.verification_mode == "visual_required"
                for step in locator.problem_retrieval_plan
                for evidence in step.required_evidence
            )
            for locator in compiled.exercises.values()
        ),
        "cross_exercise_reference_count": sum(
            target.kind == "exercise"
            for locator in compiled.exercises.values()
            for target in locator.reference_targets
        ),
        "chapter_reports": chapter_reports,
        "structural_validation_status": "passed",
        **verification,
        "manifest_package_sha256": exercise_manifest_package_hashes(args.manifest),
        "assembled_manifest_sha256": sha256_json(manifest.model_dump(mode="json")),
        **output_details,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
