#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
import yaml

from app.models.exercise_manifest import (
    ExerciseManifest,
    ExerciseManifestNode,
    ExerciseManifestPackage,
    ExerciseManifestShard,
    ExerciseReferenceSpec,
)
from app.models.locator import (
    BookMetadata,
    BoundaryAnchor,
    ContentWindow,
    EvidenceRequirement,
    PageCoverage,
    PageRange,
    PageReference,
)
from app.models.manifest import ManifestRetrievalStep
from tools.extract_pdf_candidates import (
    COLUMN_SPLIT_RATIO,
    ExerciseCandidate,
    TextLine,
    chapter_end_indices,
    clean_text,
    extract_chapter_candidates,
    extract_exercise_candidates,
    extract_lines,
    extract_page_anchors,
    extract_problem_headings,
    page_references,
    sha256_file,
)

SECTION_REF_RE = re.compile(r"\bSections?\s+(\d+(?:\.\d+)*)", re.IGNORECASE)
EQUATION_REF_RE = re.compile(
    r"\b(?:Eqs?\.?|Equations?)\s*\((\d+-\d+)\)",
    re.IGNORECASE,
)
FIGURE_REF_RE = re.compile(
    r"\b(?:Figs?\.?|Figures?)\s+(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)
TABLE_REF_RE = re.compile(r"\bTables?\s+(\d+(?:\.\d+)*)", re.IGNORECASE)
EXAMPLE_REF_RE = re.compile(r"\bExamples?\s+(\d+(?:\.\d+)*)", re.IGNORECASE)
PROBLEM_REF_RE = re.compile(r"\b(?:Problems?|Exercises?)\s+(\d+\.\d+)", re.IGNORECASE)
REFERENCE_OVERRIDES = {
    ("figure", "10.10.4"): (
        "10.4",
        (
            "Source exercise 10.23 prints Fig. 10.10.4(a); normalized to Fig. 10.4(a), "
            "the referenced 3 x 3 Laplacian kernel."
        ),
    ),
}
SELECTED_CONTEXT_PAGE_OVERRIDES = {
    ("2.11", "section", "2.4"): ["70", "71"],
    ("3.8", "section", "3.3"): ["135", "136"],
    ("11.2", "section", "11.2"): ["815", "816"],
    ("11.22", "section", "11.4"): ["850", "851"],
}


def _page_reference(raw: dict[str, Any]) -> PageReference:
    return PageReference.model_validate(raw)


def _page_range(start: int, end: int, pages: list[PageReference]) -> PageRange:
    return PageRange(
        pdf_page_index_start=start,
        pdf_page_index_end=end,
        pdf_page_number_start=start + 1,
        pdf_page_number_end=end + 1,
        printed_page_start=pages[start].printed_page_label,
        printed_page_end=pages[end].printed_page_label,
    )


def _column(page_width: float, x0: float) -> int:
    return 0 if x0 < page_width * COLUMN_SPLIT_RATIO else 1


def _bbox_key(page_width: float, bbox: tuple[float, float, float, float] | list[float]):
    return (_column(page_width, float(bbox[0])), float(bbox[1]), float(bbox[0]))


def _line_key(page: fitz.Page, line: TextLine):
    return _bbox_key(page.rect.width, line.bbox)


def _at_or_after_boundary(
    page_width: float,
    bbox: tuple[float, float, float, float] | list[float],
    boundary_bbox: tuple[float, float, float, float] | list[float],
) -> bool:
    column = _column(page_width, float(bbox[0]))
    boundary_column = _column(page_width, float(boundary_bbox[0]))
    if column != boundary_column:
        return column > boundary_column
    return float(bbox[1]) >= float(boundary_bbox[1]) - 0.5


def _before_boundary(
    page_width: float,
    bbox: tuple[float, float, float, float] | list[float],
    boundary_bbox: tuple[float, float, float, float] | list[float],
) -> bool:
    return not _at_or_after_boundary(page_width, bbox, boundary_bbox)


def _meaningful_lines_before(document: fitz.Document, candidate: ExerciseCandidate) -> bool:
    page = document[candidate.pdf_page_index]
    for line in extract_lines(page):
        if not _before_boundary(page.rect.width, line.bbox, candidate.bbox):
            continue
        if line.bbox[1] < 80:
            continue
        text = clean_text(line.text)
        if not text or re.fullmatch(r"\d+", text):
            continue
        if text.casefold() == "problems" or text == candidate.exercise_id:
            continue
        if len(text) >= 12:
            return True
    return False


def _exercise_end(
    document: fitz.Document,
    current: ExerciseCandidate,
    following: ExerciseCandidate | None,
    chapter_end: int,
) -> tuple[int, ExerciseCandidate | None]:
    if following is None:
        return chapter_end, None
    if following.pdf_page_index == current.pdf_page_index:
        return following.pdf_page_index, following
    if _meaningful_lines_before(document, following):
        return following.pdf_page_index, following
    return following.pdf_page_index - 1, None


def _window_lines(
    document: fitz.Document,
    page_index: int,
    *,
    start: ExerciseCandidate | None,
    end: ExerciseCandidate | None,
) -> list[TextLine]:
    page = document[page_index]
    lines = []
    for line in extract_lines(page):
        if start is not None and not _at_or_after_boundary(
            page.rect.width,
            line.bbox,
            start.bbox,
        ):
            continue
        if end is not None and not _before_boundary(
            page.rect.width,
            line.bbox,
            end.bbox,
        ):
            continue
        lines.append(line)
    return sorted(lines, key=lambda item: _line_key(page, item))


def _distinctive_text(lines: list[TextLine], exercise_id: str) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    for line in lines:
        text = clean_text(line.text)
        if text.startswith(exercise_id):
            text = clean_text(text[len(exercise_id) :])
        if not text or text == "*":
            continue
        if text.startswith(("FIGURE ", "TABLE ", "EXAMPLE ")):
            continue
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", text)
        if len(words) >= 4:
            candidates.append((len({word.casefold() for word in words[:12]}), len(text), text))
    if not candidates:
        for line in lines:
            text = clean_text(line.text)
            if len(text) >= 12 and exercise_id not in text:
                candidates.append((1, len(text), text))
    return max(candidates)[2] if candidates else None


def _content_evidence(
    text_anchor: str | None,
    coverage: PageCoverage,
    start_anchor: BoundaryAnchor | None,
) -> tuple[str, str]:
    if text_anchor is not None:
        return "contains_text", text_anchor
    for evidence_kind, values in (
        ("contains_figure", coverage.figure_ids),
        ("contains_equation", coverage.equation_ids),
        ("contains_table", coverage.table_ids),
        ("contains_example", coverage.example_ids),
    ):
        if values:
            return evidence_kind, values[0]
    if start_anchor is not None:
        return "contains_exercise", start_anchor.value
    raise ValueError("exercise continuation page has no reliable content anchor")


def _coverage(
    page_anchor: dict[str, Any],
    page_width: float,
    *,
    start: ExerciseCandidate | None,
    end: ExerciseCandidate | None,
) -> PageCoverage:
    def ids(key: str) -> list[str]:
        values = []
        for record in page_anchor[key]:
            if start is not None and not _at_or_after_boundary(
                page_width,
                record["bbox"],
                start.bbox,
            ):
                continue
            if end is not None and not _before_boundary(
                page_width,
                record["bbox"],
                end.bbox,
            ):
                continue
            values.append(record["id"])
        return list(dict.fromkeys(values))

    return PageCoverage(
        figure_ids=ids("figure_records"),
        equation_ids=ids("equation_records"),
        example_ids=ids("example_records"),
        table_ids=ids("table_records"),
    )


def _build_problem_plan(
    document: fitz.Document,
    pages: list[PageReference],
    page_anchors: list[dict[str, Any]],
    current: ExerciseCandidate,
    following: ExerciseCandidate | None,
    end_index: int,
) -> tuple[list[ManifestRetrievalStep], str]:
    steps: list[ManifestRetrievalStep] = []
    collected_text: list[str] = []
    for page_index in range(current.pdf_page_index, end_index + 1):
        first = page_index == current.pdf_page_index
        last = page_index == end_index
        start_candidate = current if first else None
        end_candidate = following if last and following is not None else None
        lines = _window_lines(
            document,
            page_index,
            start=start_candidate,
            end=end_candidate,
        )
        collected_text.extend(line.text for line in lines)
        page = pages[page_index]
        start_anchor = BoundaryAnchor(kind="exercise", value=current.exercise_id) if first else None
        end_anchor = (
            BoundaryAnchor(kind="exercise", value=following.exercise_id)
            if end_candidate is not None
            else None
        )
        coverage = _coverage(
            page_anchors[page_index],
            document[page_index].rect.width,
            start=start_candidate,
            end=end_candidate,
        )
        text_anchor = _distinctive_text(lines, current.exercise_id)
        content_kind, content_value = _content_evidence(
            text_anchor,
            coverage,
            start_anchor,
        )
        evidence = [
            EvidenceRequirement(
                kind="printed_page_equals",
                value=page.printed_page_label,
                verification_mode="visual_required",
            ),
        ]
        if content_kind != "contains_exercise":
            evidence.append(
                EvidenceRequirement(
                    kind=content_kind,
                    value=content_value,
                    verification_mode=(
                        "text_or_visual" if content_kind == "contains_text" else "visual_required"
                    ),
                )
            )
        if start_anchor is not None:
            evidence.append(
                EvidenceRequirement(
                    kind="contains_exercise",
                    value=start_anchor.value,
                    verification_mode="visual_required",
                )
            )
        if end_anchor is not None:
            evidence.append(
                EvidenceRequirement(
                    kind="contains_exercise",
                    value=end_anchor.value,
                    verification_mode="visual_required",
                )
            )
        primary_anchor = current.exercise_id if first else content_value
        if content_value != primary_anchor:
            secondary_query = (
                f"+({content_value}) +(printed page {page.printed_page_label}) --QDF=0"
            )
        else:
            secondary_query = (
                f"+({primary_anchor}) +(Problems) +(printed page {page.printed_page_label}) --QDF=0"
            )
        queries = [
            f"+({primary_anchor}) +(printed page {page.printed_page_label}) --QDF=0",
            secondary_query,
        ]
        steps.append(
            ManifestRetrievalStep(
                page=page,
                content_window=ContentWindow(start_at=start_anchor, end_before=end_anchor),
                queries=queries,
                required_evidence=evidence,
                coverage=coverage,
            )
        )
    return steps, clean_text(" ".join(collected_text))


def _reference_specs(text: str, exercise_id: str) -> list[ExerciseReferenceSpec]:
    patterns = (
        ("section", SECTION_REF_RE),
        ("equation", EQUATION_REF_RE),
        ("figure", FIGURE_REF_RE),
        ("table", TABLE_REF_RE),
        ("example", EXAMPLE_REF_RE),
        ("exercise", PROBLEM_REF_RE),
    )
    specs: list[ExerciseReferenceSpec] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in patterns:
        for match in pattern.finditer(text):
            target_id = match.group(1)
            override = REFERENCE_OVERRIDES.get((kind, target_id))
            reason = f"Explicit {kind} reference in exercise text"
            if override is not None:
                target_id, reason = override
            key = (kind, target_id)
            if key in seen or (kind == "exercise" and target_id == exercise_id):
                continue
            seen.add(key)
            specs.append(
                ExerciseReferenceSpec(
                    kind=kind,
                    target_id=target_id,
                    reason=reason,
                    selected_context_pages=SELECTED_CONTEXT_PAGE_OVERRIDES.get(
                        (exercise_id, kind, target_id),
                        [],
                    ),
                )
            )
    return specs


def build_exercise_manifest(pdf_path: Path) -> ExerciseManifest:
    document = fitz.open(pdf_path)
    try:
        pages = [_page_reference(item) for item in page_references(document)]
        page_anchors = extract_page_anchors(document)
        candidates = extract_exercise_candidates(document)
        chapters = extract_chapter_candidates(document)
        chapter_end = chapter_end_indices(document, chapters)
        expected_chapter_ids = set(extract_problem_headings(document))
        grouped: dict[str, list[ExerciseCandidate]] = {}
        for candidate in candidates:
            grouped.setdefault(candidate.chapter_id, []).append(candidate)
        if set(grouped) != expected_chapter_ids:
            missing = sorted(expected_chapter_ids - set(grouped), key=int)
            extra = sorted(set(grouped) - expected_chapter_ids, key=int)
            raise ValueError(
                "exercise candidates do not cover all Problems chapters; "
                f"missing={missing}; extra={extra}"
            )

        exercises: list[ExerciseManifestNode] = []
        for chapter_id in sorted(grouped, key=int):
            chapter_candidates = sorted(grouped[chapter_id], key=lambda item: item.source_order)
            for index, current in enumerate(chapter_candidates):
                following = (
                    chapter_candidates[index + 1] if index + 1 < len(chapter_candidates) else None
                )
                end_index, end_before = _exercise_end(
                    document,
                    current,
                    following,
                    chapter_end[chapter_id],
                )
                plan, problem_text = _build_problem_plan(
                    document,
                    pages,
                    page_anchors,
                    current,
                    end_before,
                    end_index,
                )
                exercises.append(
                    ExerciseManifestNode(
                        exercise_id=current.exercise_id,
                        chapter_id=chapter_id,
                        exercise_number=current.exercise_number,
                        starred=current.starred,
                        source_order=current.source_order,
                        problem_page_range=_page_range(
                            current.pdf_page_index,
                            end_index,
                            pages,
                        ),
                        problem_retrieval_plan=plan,
                        reference_specs=_reference_specs(problem_text, current.exercise_id),
                    )
                )

        return ExerciseManifest(
            index_status="complete",
            book=BookMetadata(
                book_id="dip4e",
                title="Digital Image Processing, 4e",
                author="Rafael C. Gonzalez and Richard E. Woods",
                pdf_filename="Digital Image ProcessingRafael.pdf",
                pdf_sha256=sha256_file(pdf_path),
                page_count=document.page_count,
            ),
            pages=pages,
            exercises=exercises,
        )
    finally:
        document.close()


def write_exercise_manifest_package(manifest: ExerciseManifest, output: Path) -> None:
    groups: dict[str, list[ExerciseManifestNode]] = {}
    for exercise in manifest.exercises:
        groups.setdefault(exercise.chapter_id, []).append(exercise)

    output.parent.mkdir(parents=True, exist_ok=True)
    for stale in output.parent.glob("exercises.sections.*.yaml"):
        stale.unlink()

    shard_names: list[str] = []
    for chapter_id in sorted(groups, key=int):
        shard_name = f"exercises.sections.{int(chapter_id):02d}.yaml"
        shard_path = output.parent / shard_name
        shard = ExerciseManifestShard(
            chapter_id=chapter_id,
            exercises=groups[chapter_id],
        )
        shard_path.write_text(
            yaml.safe_dump(
                shard.model_dump(mode="json"),
                allow_unicode=True,
                sort_keys=False,
                width=120,
            ),
            encoding="utf-8",
        )
        shard_names.append(shard_name)

    package = ExerciseManifestPackage(
        index_status=manifest.index_status,
        book=manifest.book,
        pages=manifest.pages,
        chapter_ids=sorted(groups, key=int),
        exercise_shards=shard_names,
    )
    output.write_text(
        yaml.safe_dump(
            package.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the complete DIP4E exercise manifest")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    manifest = build_exercise_manifest(args.pdf)
    write_exercise_manifest_package(manifest, args.output)
    print(f"wrote {args.output}: pages={len(manifest.pages)}, exercises={len(manifest.exercises)}")


if __name__ == "__main__":
    main()
