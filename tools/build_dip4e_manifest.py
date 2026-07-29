#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
import yaml

from app.models.locator import (
    BookMetadata,
    BoundaryAnchor,
    ContentWindow,
    EvidenceRequirement,
    HeadingLocation,
    PageClassification,
    PageCoverage,
    PageRange,
    PageReference,
)
from app.models.manifest import (
    BookManifest,
    BookManifestPackage,
    LearningUnitManifest,
    ManifestRetrievalStep,
    PrintedSectionManifest,
    PrintedSectionManifestShard,
)
from tools.extract_pdf_candidates import (
    TERMINAL_BOUNDARY_RE,
    HeadingCandidate,
    clean_text,
    extract_heading_candidates,
    extract_lines,
    extract_page_anchors,
    page_references,
    sha256_file,
)

BODY_START_INDEX = 18
BODY_END_INDEX = 995
ACRONYMS = {
    "2-D",
    "3-D",
    "CNN",
    "DFT",
    "FFT",
    "HSI",
    "IDFT",
    "JPEG",
    "PCA",
    "RGB",
    "SIFT",
}


@dataclass
class SourceBoundary:
    kind: Literal["heading", "text"]
    text: str
    pdf_page_index: int
    pdf_page_number: int
    printed_page_label: str
    bbox: tuple[float, float, float, float]


@dataclass
class SourceNode:
    title: str
    source_heading: str
    source_location: HeadingLocation
    source_level: int
    start_index: int
    end_index: int = 0
    end_before: SourceBoundary | None = None
    children: list[SourceNode] = field(default_factory=list)


def _smart_title(value: str) -> str:
    words: list[str] = []
    for index, token in enumerate(value.split()):
        bare = token.strip("(),")
        if bare in ACRONYMS or re.fullmatch(r"\d+-D", bare):
            replacement = bare
        elif index > 0 and bare.lower() in {
            "a",
            "an",
            "and",
            "as",
            "at",
            "by",
            "for",
            "from",
            "in",
            "of",
            "on",
            "or",
            "the",
            "to",
            "using",
            "versus",
            "with",
        }:
            replacement = bare.lower()
        else:
            replacement = bare.capitalize()
        words.append(token.replace(bare, replacement))
    return " ".join(words)


def _display_title(source_heading: str) -> str:
    without_number = re.sub(r"^\d+(?:\.\d+)*\s+", "", source_heading)
    if without_number.upper() == without_number:
        return _smart_title(without_number)
    return without_number


def _is_top_level_heading(text: str) -> bool:
    letters = [character for character in text if character.isalpha()]
    return (
        bool(letters) and sum(character.isupper() for character in letters) / len(letters) >= 0.85
    )


def _page_reference(raw: dict[str, Any]) -> PageReference:
    return PageReference.model_validate(raw)


def _heading_location(candidate: HeadingCandidate, pages: list[PageReference]) -> HeadingLocation:
    return HeadingLocation(page=pages[candidate.pdf_page_index], bbox=candidate.bbox)


def _heading_boundary(candidate: HeadingCandidate) -> SourceBoundary:
    return SourceBoundary(
        kind="heading",
        text=candidate.text,
        pdf_page_index=candidate.pdf_page_index,
        pdf_page_number=candidate.pdf_page_number,
        printed_page_label=candidate.printed_page_label,
        bbox=candidate.bbox,
    )


def _page_range(start: int, end: int, pages: list[PageReference]) -> PageRange:
    return PageRange(
        pdf_page_index_start=start,
        pdf_page_index_end=end,
        pdf_page_number_start=start + 1,
        pdf_page_number_end=end + 1,
        printed_page_start=pages[start].printed_page_label,
        printed_page_end=pages[end].printed_page_label,
    )


def _within_window(record: dict[str, Any], *, start_y: float | None, end_y: float | None) -> bool:
    y0 = float(record["bbox"][1])
    if start_y is not None and y0 < start_y - 0.5:
        return False
    return not (end_y is not None and y0 >= end_y - 0.5)


def _coverage_for_page(
    page_anchor: dict[str, Any], *, start_y: float | None, end_y: float | None
) -> PageCoverage:
    def ids(key: str) -> list[str]:
        return list(
            dict.fromkeys(
                record["id"]
                for record in page_anchor[key]
                if _within_window(record, start_y=start_y, end_y=end_y)
            )
        )

    return PageCoverage(
        subheadings=list(
            dict.fromkeys(
                record["text"]
                for record in page_anchor["heading_records"]
                if _within_window(record, start_y=start_y, end_y=end_y)
            )
        ),
        figure_ids=ids("figure_records"),
        equation_ids=ids("equation_records"),
        example_ids=ids("example_records"),
        table_ids=ids("table_records"),
    )


def _distinctive_text(
    document: fitz.Document,
    page_index: int,
    *,
    start_y: float | None,
    end_y: float | None,
) -> str:
    candidates: list[tuple[int, str]] = []
    for line in extract_lines(document[page_index]):
        if start_y is not None and line.bbox[1] < start_y - 0.5:
            continue
        if end_y is not None and line.bbox[1] >= end_y - 0.5:
            continue
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", line.text)
        if len(words) < 6:
            continue
        if line.text.startswith(("FIGURE ", "TABLE ", "EXAMPLE ")):
            continue
        phrase = clean_text(line.text)
        candidates.append((len({word.casefold() for word in words[:10]}), phrase))
    if not candidates:
        for line in extract_lines(document[page_index]):
            if start_y is not None and line.bbox[1] < start_y - 0.5:
                continue
            if end_y is not None and line.bbox[1] >= end_y - 0.5:
                continue
            if len(line.text) >= 20:
                candidates.append((1, clean_text(line.text[:100])))
    if not candidates:
        raise ValueError(f"cannot derive a text anchor for PDF page index {page_index}")
    return max(candidates, key=lambda item: (item[0], len(item[1])))[1]


def _build_plan(
    document: fitz.Document,
    pages: list[PageReference],
    page_anchors: list[dict[str, Any]],
    node: SourceNode,
) -> list[ManifestRetrievalStep]:
    steps: list[ManifestRetrievalStep] = []
    for page_index in range(node.start_index, node.end_index + 1):
        first = page_index == node.start_index
        last = page_index == node.end_index
        start_anchor = BoundaryAnchor(kind="heading", value=node.source_heading) if first else None
        end_anchor = None
        if last and node.end_before is not None and node.end_before.pdf_page_index == page_index:
            end_anchor = BoundaryAnchor(kind=node.end_before.kind, value=node.end_before.text)

        start_y = node.source_location.bbox[1] if first else None
        end_y = node.end_before.bbox[1] if end_anchor is not None else None
        coverage = _coverage_for_page(page_anchors[page_index], start_y=start_y, end_y=end_y)
        text_anchor = _distinctive_text(
            document,
            page_index,
            start_y=start_y,
            end_y=end_y,
        )

        evidence = [
            EvidenceRequirement(
                kind="printed_page_equals",
                value=pages[page_index].printed_page_label,
                verification_mode="visual_required",
            ),
            EvidenceRequirement(
                kind="contains_text",
                value=text_anchor,
                verification_mode="text_or_visual",
            ),
        ]
        if start_anchor is not None:
            evidence.append(
                EvidenceRequirement(
                    kind=("contains_heading" if end_anchor.kind == "heading" else "contains_text"),
                    value=start_anchor.value,
                    verification_mode="visual_required",
                )
            )
        if end_anchor is not None:
            evidence.append(
                EvidenceRequirement(
                    kind="contains_heading",
                    value=end_anchor.value,
                    verification_mode="visual_required",
                )
            )

        query_anchor = start_anchor.value if start_anchor is not None else text_anchor
        label = pages[page_index].printed_page_label
        queries = [
            f"+({query_anchor}) +(printed page {label}) --QDF=0",
            f"{node.title} {text_anchor} printed page {label} --QDF=0",
        ]
        steps.append(
            ManifestRetrievalStep(
                page=pages[page_index],
                content_window=ContentWindow(start_at=start_anchor, end_before=end_anchor),
                queries=queries,
                required_evidence=evidence,
                coverage=coverage,
            )
        )
    return steps


def _build_unit_manifest(
    document: fitz.Document,
    pages: list[PageReference],
    page_anchors: list[dict[str, Any]],
    node: SourceNode,
) -> LearningUnitManifest:
    return LearningUnitManifest(
        title=node.title,
        source_heading=node.source_heading,
        source_location=node.source_location,
        source_level=node.source_level,
        page_range=_page_range(node.start_index, node.end_index, pages),
        outline=[child.title for child in node.children],
        retrieval_plan=_build_plan(document, pages, page_anchors, node),
        children=[
            _build_unit_manifest(document, pages, page_anchors, child) for child in node.children
        ],
    )


def _has_content_before_boundary(document: fitz.Document, boundary: SourceBoundary) -> bool:
    for line in extract_lines(document[boundary.pdf_page_index]):
        if line.bbox[1] >= boundary.bbox[1] - 0.5:
            continue
        if line.bbox[1] < 85:
            continue
        if re.fullmatch(r"\d+", line.text):
            continue
        if len(line.text) >= 20:
            return True
    return False


def _range_end_before_next(
    document: fitz.Document,
    current_start: int,
    next_boundary: SourceBoundary,
) -> tuple[int, SourceBoundary | None]:
    if next_boundary.pdf_page_index == current_start:
        return next_boundary.pdf_page_index, next_boundary
    if _has_content_before_boundary(document, next_boundary):
        return next_boundary.pdf_page_index, next_boundary
    return next_boundary.pdf_page_index - 1, None


def _assign_ranges(
    document: fitz.Document,
    nodes: list[SourceNode],
    parent_end: int,
    parent_end_before: SourceBoundary | None = None,
) -> None:
    for index, node in enumerate(nodes):
        next_node = nodes[index + 1] if index + 1 < len(nodes) else None
        node.end_index = parent_end
        node.end_before = parent_end_before if next_node is None else None
        if next_node is not None:
            next_boundary = SourceBoundary(
                kind="heading",
                text=next_node.source_heading,
                pdf_page_index=next_node.start_index,
                pdf_page_number=next_node.start_index + 1,
                printed_page_label=next_node.source_location.page.printed_page_label,
                bbox=next_node.source_location.bbox,
            )
            node.end_index, node.end_before = _range_end_before_next(
                document,
                node.start_index,
                next_boundary,
            )
        if node.children:
            _assign_ranges(document, node.children, node.end_index, node.end_before)


def _learning_tree(
    document: fitz.Document,
    candidates: list[HeadingCandidate],
    pages: list[PageReference],
    section_end: int,
    section_end_before: SourceBoundary | None,
) -> list[SourceNode]:
    roots: list[SourceNode] = []
    current_root: SourceNode | None = None
    for candidate in candidates:
        top_level = _is_top_level_heading(candidate.text)
        level = 1 if top_level or current_root is None else 2
        node = SourceNode(
            title=_display_title(candidate.text),
            source_heading=candidate.text,
            source_location=_heading_location(candidate, pages),
            source_level=level,
            start_index=candidate.pdf_page_index,
        )
        if level == 1:
            roots.append(node)
            current_root = node
        else:
            assert current_root is not None
            current_root.children.append(node)
    _assign_ranges(document, roots, section_end, section_end_before)
    return roots


def _terminal_boundaries(
    document: fitz.Document,
    chapter_start: int,
    chapter_end: int,
) -> list[SourceBoundary]:
    boundaries: list[SourceBoundary] = []
    for page_index in range(chapter_start, chapter_end + 1):
        for line in extract_lines(document[page_index]):
            if TERMINAL_BOUNDARY_RE.fullmatch(clean_text(line.text)) is None:
                continue
            boundaries.append(
                SourceBoundary(
                    kind="text",
                    text=clean_text(line.text),
                    pdf_page_index=line.pdf_page_index,
                    pdf_page_number=line.pdf_page_number,
                    printed_page_label=line.printed_page_label,
                    bbox=line.bbox,
                )
            )
    return sorted(boundaries, key=lambda item: (item.pdf_page_index, item.bbox[1], item.bbox[0]))


def build_manifest(pdf_path: Path) -> BookManifest:
    document = fitz.open(pdf_path)
    try:
        pages = [_page_reference(item) for item in page_references(document)]
        page_anchors = extract_page_anchors(document)
        candidates = extract_heading_candidates(document)
        chapter_candidates = [
            candidate
            for candidate in candidates
            if candidate.numbered and re.fullmatch(r"\d+", candidate.text.split()[0])
        ]
        numbered_sections = [
            candidate
            for candidate in candidates
            if candidate.numbered and "." in candidate.text.split()[0]
        ]
        unnumbered_by_section: dict[str, list[HeadingCandidate]] = {}
        for candidate in candidates:
            if candidate.numbered or candidate.printed_section_id is None:
                continue
            if TERMINAL_BOUNDARY_RE.fullmatch(clean_text(candidate.text)) is not None:
                continue
            unnumbered_by_section.setdefault(candidate.printed_section_id, []).append(candidate)

        chapter_end_by_id: dict[str, int] = {}
        for index, chapter in enumerate(chapter_candidates):
            chapter_end_by_id[chapter.text.split()[0]] = (
                chapter_candidates[index + 1].pdf_page_index - 1
                if index + 1 < len(chapter_candidates)
                else BODY_END_INDEX
            )

        sections_by_chapter: dict[str, list[HeadingCandidate]] = {}
        for candidate in numbered_sections:
            sections_by_chapter.setdefault(candidate.text.split()[0].split(".")[0], []).append(
                candidate
            )

        printed_sections: list[PrintedSectionManifest] = []
        for chapter in chapter_candidates:
            chapter_id = chapter.text.split()[0]
            chapter_end = chapter_end_by_id[chapter_id]
            terminal_boundaries = _terminal_boundaries(
                document,
                chapter.pdf_page_index,
                chapter_end,
            )
            chapter_node = SourceNode(
                title=_display_title(chapter.text),
                source_heading=chapter.text,
                source_location=_heading_location(chapter, pages),
                source_level=0,
                start_index=chapter.pdf_page_index,
                end_index=chapter_end,
            )
            printed_sections.append(
                PrintedSectionManifest(
                    printed_section_id=chapter_id,
                    title=chapter_node.title,
                    source_heading=chapter_node.source_heading,
                    source_location=chapter_node.source_location,
                    page_range=_page_range(chapter_node.start_index, chapter_node.end_index, pages),
                    outline=[
                        candidate.text.split()[0] for candidate in sections_by_chapter[chapter_id]
                    ],
                    retrieval_plan=_build_plan(document, pages, page_anchors, chapter_node),
                )
            )

            chapter_sections = sections_by_chapter[chapter_id]
            for section_index, section in enumerate(chapter_sections):
                section_id = section.text.split()[0]
                next_section = (
                    chapter_sections[section_index + 1]
                    if section_index + 1 < len(chapter_sections)
                    else None
                )
                section_end = chapter_end
                section_end_before = None
                if next_section is not None:
                    section_end, section_end_before = _range_end_before_next(
                        document,
                        section.pdf_page_index,
                        _heading_boundary(next_section),
                    )
                elif terminal_boundaries:
                    terminal = next(
                        (
                            boundary
                            for boundary in terminal_boundaries
                            if (
                                boundary.pdf_page_index,
                                boundary.bbox[1],
                                boundary.bbox[0],
                            )
                            > (
                                section.pdf_page_index,
                                section.bbox[1],
                                section.bbox[0],
                            )
                        ),
                        None,
                    )
                    if terminal is not None:
                        section_end, section_end_before = _range_end_before_next(
                            document,
                            section.pdf_page_index,
                            terminal,
                        )
                section_node = SourceNode(
                    title=_display_title(section.text),
                    source_heading=section.text,
                    source_location=_heading_location(section, pages),
                    source_level=0,
                    start_index=section.pdf_page_index,
                    end_index=section_end,
                    end_before=section_end_before,
                )
                roots = _learning_tree(
                    document,
                    unnumbered_by_section.get(section_id, []),
                    pages,
                    section_end,
                    section_end_before,
                )
                printed_sections.append(
                    PrintedSectionManifest(
                        printed_section_id=section_id,
                        parent_printed_section_id=chapter_id,
                        title=section_node.title,
                        source_heading=section_node.source_heading,
                        source_location=section_node.source_location,
                        page_range=_page_range(
                            section_node.start_index, section_node.end_index, pages
                        ),
                        outline=[node.title for node in roots],
                        retrieval_plan=_build_plan(document, pages, page_anchors, section_node),
                        learning_units=[
                            _build_unit_manifest(document, pages, page_anchors, node)
                            for node in roots
                        ],
                    )
                )

        classifications = []
        for page in pages:
            if page.pdf_page_index < BODY_START_INDEX:
                category = "front_matter"
                reason = "front matter before Chapter 1"
            elif page.pdf_page_index <= BODY_END_INDEX:
                category = "body"
                reason = "chapter content"
            else:
                category = "back_matter"
                reason = "bibliography, index, or back cover"
            classifications.append(PageClassification(page=page, category=category, reason=reason))

        return BookManifest(
            data_version="3",
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
            page_classifications=classifications,
            printed_sections=printed_sections,
        )
    finally:
        document.close()


def write_manifest_package(manifest: BookManifest, output: Path) -> None:
    groups: dict[str, list[PrintedSectionManifest]] = {}
    for section in manifest.printed_sections:
        chapter = section.printed_section_id.split(".", 1)[0]
        groups.setdefault(chapter, []).append(section)

    output.parent.mkdir(parents=True, exist_ok=True)
    for stale in output.parent.glob("manifest.sections.*.yaml"):
        stale.unlink()

    shard_names: list[str] = []
    for chapter in sorted(groups, key=int):
        shard_name = f"manifest.sections.{int(chapter):02d}.yaml"
        shard_path = output.parent / shard_name
        shard = PrintedSectionManifestShard(
            data_version="3",
            printed_sections=groups[chapter],
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

    package = BookManifestPackage(
        data_version=manifest.data_version,
        index_status=manifest.index_status,
        book=manifest.book,
        pages=manifest.pages,
        page_classifications=manifest.page_classifications,
        printed_section_shards=shard_names,
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
    parser = argparse.ArgumentParser(description="Build the complete DIP4E Version 3 manifest")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    manifest = build_manifest(args.pdf)
    write_manifest_package(manifest, args.output)
    print(
        f"wrote {args.output}: pages={len(manifest.pages)}, "
        f"printed_sections={len(manifest.printed_sections)}"
    )


if __name__ == "__main__":
    main()
