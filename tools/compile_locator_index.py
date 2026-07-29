#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
import yaml
from pydantic import ValidationError

from app.models.locator import (
    CompiledLocatorIndexPackage,
    EvidenceRequirement,
    LocatorSectionShard,
    PageCoverage,
)
from app.models.manifest import (
    BookManifest,
    BookManifestPackage,
    PrintedSectionManifestShard,
)
from app.services.index_compiler import LocatorIndexCompiler
from tools.extract_pdf_candidates import (
    HeadingCandidate,
    clean_text,
    extract_heading_candidates,
    extract_page_anchors,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


HeadingKey = tuple[str, int, tuple[float, float, float, float], bool, str]


def _heading_key(
    *,
    text: str,
    page_index: int,
    bbox: tuple[float, float, float, float],
    numbered: bool,
    printed_section_id: str,
) -> HeadingKey:
    return (
        text,
        page_index,
        tuple(round(float(value), 3) for value in bbox),
        numbered,
        printed_section_id,
    )


def manifest_heading_keys(manifest: BookManifest) -> list[HeadingKey]:
    keys: list[HeadingKey] = []

    def add_units(units, printed_section_id: str) -> None:
        for unit in units:
            keys.append(
                _heading_key(
                    text=unit.source_heading,
                    page_index=unit.source_location.page.pdf_page_index,
                    bbox=unit.source_location.bbox,
                    numbered=False,
                    printed_section_id=printed_section_id,
                )
            )
            add_units(unit.children, printed_section_id)

    for section in manifest.printed_sections:
        keys.append(
            _heading_key(
                text=section.source_heading,
                page_index=section.source_location.page.pdf_page_index,
                bbox=section.source_location.bbox,
                numbered=True,
                printed_section_id=section.printed_section_id,
            )
        )
        add_units(section.learning_units, section.printed_section_id)
    return keys


def source_heading_keys(candidates: list[HeadingCandidate]) -> list[HeadingKey]:
    return [
        _heading_key(
            text=candidate.text,
            page_index=candidate.pdf_page_index,
            bbox=candidate.bbox,
            numbered=candidate.numbered,
            printed_section_id=candidate.printed_section_id,
        )
        for candidate in candidates
        if candidate.printed_section_id is not None
    ]


def verify_heading_coverage(
    manifest: BookManifest, candidates: list[HeadingCandidate]
) -> dict[str, int]:
    expected = Counter(source_heading_keys(candidates))
    actual = Counter(manifest_heading_keys(manifest))
    missing = list((expected - actual).elements())
    extra = list((actual - expected).elements())
    if missing or extra:
        raise ValueError(
            "manifest heading coverage differs from the source PDF; "
            f"missing={missing[:10]!r}; extra={extra[:10]!r}"
        )
    return {
        "heading_candidate_count": sum(expected.values()),
        "numbered_heading_count": sum(1 for key in expected.elements() if key[3]),
        "learning_heading_count": sum(1 for key in expected.elements() if not key[3]),
    }


def _iter_manifest_steps(manifest: BookManifest):
    def walk_units(units, printed_section_id: str):
        for unit in units:
            yield printed_section_id, unit.source_heading, unit.retrieval_plan
            yield from walk_units(unit.children, printed_section_id)

    for section in manifest.printed_sections:
        yield section.printed_section_id, section.source_heading, section.retrieval_plan
        yield from walk_units(section.learning_units, section.printed_section_id)


def _evidence_exists(page_anchor: dict, evidence: EvidenceRequirement) -> bool:
    value = clean_text(evidence.value)
    if evidence.kind == "printed_page_equals":
        return value == page_anchor["printed_page_label"]
    if evidence.kind == "contains_figure":
        return value in page_anchor["figure_ids"]
    if evidence.kind == "contains_equation":
        return value in page_anchor["equation_ids"]
    if evidence.kind == "contains_example":
        return value in page_anchor["example_ids"]
    if evidence.kind == "contains_table":
        return value in page_anchor["table_ids"]
    if evidence.kind == "contains_exercise":
        return value in {item["id"] for item in page_anchor.get("exercise_records", [])}
    if evidence.kind == "running_header_contains":
        return value.casefold() in page_anchor["running_header"].casefold()
    if evidence.kind == "contains_heading":
        heading_values = [clean_text(item["text"]) for item in page_anchor["heading_records"]]
        return (
            value in heading_values or value.casefold() in page_anchor["normalized_text"].casefold()
        )
    if evidence.kind == "contains_text":
        return value.casefold() in page_anchor["normalized_text"].casefold()
    raise AssertionError(f"unsupported evidence kind: {evidence.kind}")


def _boundary_record(page_anchor: dict, boundary) -> dict | None:
    record_key = {
        "heading": "heading_records",
        "figure": "figure_records",
        "equation": "equation_records",
        "example": "example_records",
        "table": "table_records",
        "text": "text_records",
        "exercise": "exercise_records",
    }[boundary.kind]
    value_key = "text" if boundary.kind in {"heading", "text"} else "id"
    expected = clean_text(boundary.value)
    for record in page_anchor[record_key]:
        actual = clean_text(record[value_key])
        if actual == expected or (
            boundary.kind == "text" and expected.casefold() in actual.casefold()
        ):
            return record
    return None


def _coverage_missing(
    page_anchor: dict,
    coverage: PageCoverage,
    *,
    start_y: float | None,
    end_y: float | None,
) -> dict[str, list[str]]:
    def in_window(record: dict) -> bool:
        y0 = float(record["bbox"][1])
        if start_y is not None and y0 < start_y - 0.5:
            return False
        return not (end_y is not None and y0 >= end_y - 0.5)

    actual = {
        "subheadings": {
            clean_text(item["text"]) for item in page_anchor["heading_records"] if in_window(item)
        },
        "figure_ids": {item["id"] for item in page_anchor["figure_records"] if in_window(item)},
        "equation_ids": {item["id"] for item in page_anchor["equation_records"] if in_window(item)},
        "example_ids": {item["id"] for item in page_anchor["example_records"] if in_window(item)},
        "table_ids": {item["id"] for item in page_anchor["table_records"] if in_window(item)},
    }
    expected = {
        "subheadings": {clean_text(value) for value in coverage.subheadings},
        "figure_ids": set(coverage.figure_ids),
        "equation_ids": set(coverage.equation_ids),
        "example_ids": set(coverage.example_ids),
        "table_ids": set(coverage.table_ids),
    }
    return {
        key: sorted(values - actual[key])
        for key, values in expected.items()
        if values - actual[key]
    }


def verify_manifest_anchors(
    manifest: BookManifest, page_anchors: list[dict]
) -> dict[str, int | str]:
    step_count = 0
    evidence_count = 0
    coverage_anchor_count = 0
    query_count = 0
    for section_id, source_heading, steps in _iter_manifest_steps(manifest):
        for step_index, step in enumerate(steps):
            step_count += 1
            page_anchor = page_anchors[step.page.pdf_page_index]
            if page_anchor["printed_page_label"] != step.page.printed_page_label:
                raise ValueError(f"page anchor label mismatch for {section_id}")

            start_record = (
                _boundary_record(page_anchor, step.content_window.start_at)
                if step.content_window.start_at is not None
                else None
            )
            end_record = (
                _boundary_record(page_anchor, step.content_window.end_before)
                if step.content_window.end_before is not None
                else None
            )
            if step.content_window.start_at is not None and start_record is None:
                raise ValueError(
                    f"content-window start boundary does not exist on source page for {section_id}"
                )
            if step.content_window.end_before is not None and end_record is None:
                raise ValueError(
                    f"content-window end boundary does not exist on source page for {section_id}"
                )
            start_y = float(start_record["bbox"][1]) if start_record is not None else None
            end_y = float(end_record["bbox"][1]) if end_record is not None else None
            if start_y is not None and end_y is not None and end_y <= start_y:
                raise ValueError(f"content-window boundaries are reversed for {section_id}")

            missing = _coverage_missing(
                page_anchor,
                step.coverage,
                start_y=start_y,
                end_y=end_y,
            )
            if missing:
                raise ValueError(
                    f"coverage anchors do not exist on source page for {section_id} "
                    f"page {step.page.printed_page_label}: {missing}"
                )
            coverage_anchor_count += sum(
                len(values)
                for values in (
                    step.coverage.subheadings,
                    step.coverage.figure_ids,
                    step.coverage.equation_ids,
                    step.coverage.example_ids,
                    step.coverage.table_ids,
                )
            )

            for evidence in step.required_evidence:
                evidence_count += 1
                if not _evidence_exists(page_anchor, evidence):
                    raise ValueError(
                        f"required evidence does not exist on source page for {section_id} "
                        f"page {step.page.printed_page_label}: {evidence.kind}={evidence.value!r}"
                    )

            query_anchors = [
                clean_text(item.value)
                for item in step.required_evidence
                if item.kind != "printed_page_equals"
            ]
            if step_index == 0:
                query_anchors.append(clean_text(source_heading))
            query_anchors = [value for value in query_anchors if value]
            for query in step.queries:
                query_count += 1
                folded = clean_text(query.replace("--QDF=0", "")).casefold()
                if step.page.printed_page_label.casefold() not in folded:
                    raise ValueError(
                        f"query does not contain target printed page for {section_id}: {query!r}"
                    )
                if not any(anchor.casefold() in folded for anchor in query_anchors):
                    raise ValueError(
                        f"query has no source-PDF anchor for {section_id} "
                        f"page {step.page.printed_page_label}: {query!r}"
                    )

    return {
        "retrieval_step_count": step_count,
        "source_evidence_check_count": evidence_count,
        "coverage_anchor_check_count": coverage_anchor_count,
        "query_text_anchor_check_count": query_count,
        "source_pdf_verification_status": "passed",
        "file_search_retrieval_status": "not_tested",
    }


def verify_source_pdf(manifest: BookManifest, pdf_path: Path) -> dict[str, int | str]:
    actual_sha = sha256_file(pdf_path)
    if actual_sha != manifest.book.pdf_sha256:
        raise ValueError("source PDF SHA-256 does not match manifest")

    document = fitz.open(pdf_path)
    try:
        if document.page_count != manifest.book.page_count:
            raise ValueError("source PDF page count does not match manifest")
        for page_ref in manifest.pages:
            actual_label = document[page_ref.pdf_page_index].get_label().strip()
            if actual_label != page_ref.printed_page_label:
                raise ValueError(
                    "source PDF page label mismatch at index "
                    f"{page_ref.pdf_page_index}: {actual_label!r} != "
                    f"{page_ref.printed_page_label!r}"
                )
        heading_counts = verify_heading_coverage(manifest, extract_heading_candidates(document))
        anchor_counts = verify_manifest_anchors(manifest, extract_page_anchors(document))
    finally:
        document.close()
    return {**heading_counts, **anchor_counts}


def load_manifest(path: Path) -> BookManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "printed_section_shards" in raw:
            package = BookManifestPackage.model_validate(raw)
            printed_sections = []
            for shard_name in package.printed_section_shards:
                shard_path = path.parent / shard_name
                shard_raw = yaml.safe_load(shard_path.read_text(encoding="utf-8"))
                shard = PrintedSectionManifestShard.model_validate(shard_raw)
                printed_sections.extend(shard.printed_sections)
            raw = {
                **package.model_dump(mode="json", exclude={"printed_section_shards"}),
                "printed_sections": [
                    section.model_dump(mode="json") for section in printed_sections
                ],
            }
        return BookManifest.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError, TypeError, ValueError) as exc:
        raise ValueError(f"manifest validation failed: {exc}") from exc


def manifest_package_hashes(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    files = [path]
    files.extend(path.parent / name for name in raw.get("printed_section_shards", []))
    return {file.name: sha256_file(file) for file in files}


def write_compiled_package(compiled, output: Path) -> dict[str, object]:
    groups: dict[str, dict] = {}
    for section_id, locator in compiled.sections.items():
        chapter = section_id.split(".", 1)[0]
        groups.setdefault(chapter, {})[section_id] = locator

    for stale in output.parent.glob("compiled_locator_index.sections.*.json"):
        stale.unlink()

    shard_names: list[str] = []
    shard_hashes: dict[str, str] = {}
    for chapter in sorted(groups, key=int):
        shard_name = f"compiled_locator_index.sections.{int(chapter):02d}.json"
        shard_path = output.parent / shard_name
        shard = LocatorSectionShard(data_version="3", sections=groups[chapter])
        shard_path.write_text(
            json.dumps(shard.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        shard_names.append(shard_name)
        shard_hashes[shard_name] = sha256_file(shard_path)

    package = CompiledLocatorIndexPackage(
        data_version=compiled.data_version,
        index_status=compiled.index_status,
        book=compiled.book,
        pages=compiled.pages,
        page_classifications=compiled.page_classifications,
        section_shards=shard_names,
    )
    output.write_text(
        json.dumps(package.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "output_sha256": sha256_file(output),
        "assembled_index_sha256": sha256_json(compiled.model_dump(mode="json")),
        "section_shard_count": len(shard_names),
        "section_shard_sha256": shard_hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a strict Version 3 locator index")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    heading_counts = verify_source_pdf(manifest, args.pdf)
    compiled = LocatorIndexCompiler().compile(manifest)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_details = write_compiled_package(compiled, args.output)

    report = {
        "data_version": compiled.data_version,
        "index_status": compiled.index_status,
        "book_id": compiled.book.book_id,
        "pdf_sha256": compiled.book.pdf_sha256,
        "page_count": compiled.book.page_count,
        "section_count": len(compiled.sections),
        "printed_section_count": sum(
            section.section_kind == "printed" for section in compiled.sections.values()
        ),
        "learning_unit_count": sum(
            section.section_kind == "learning_unit" for section in compiled.sections.values()
        ),
        "page_classification_counts": dict(
            Counter(item.category for item in compiled.page_classifications)
        ),
        "structural_validation_status": "passed",
        "uncovered_body_pages": [],
        **heading_counts,
        "manifest_package_sha256": manifest_package_hashes(args.manifest),
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
