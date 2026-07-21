#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import fitz
import yaml
from pydantic import ValidationError

from app.models.manifest import BookManifest
from app.services.index_compiler import LocatorIndexCompiler
from tools.extract_pdf_candidates import HeadingCandidate, extract_heading_candidates


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def verify_source_pdf(manifest: BookManifest, pdf_path: Path) -> dict[str, int]:
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
    finally:
        document.close()
    return heading_counts


def load_manifest(path: Path) -> BookManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read manifest: {path}") from exc
    try:
        return BookManifest.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"manifest validation failed: {exc}") from exc


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
    args.output.write_text(
        json.dumps(compiled.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
        **heading_counts,
        "output_sha256": sha256_file(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
