#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import fitz

NUMBERED_HEADING_RE = re.compile(r"^(?P<id>\d+(?:\.\d+)*)\s+(?P<title>.+)$")
FIGURE_RE = re.compile(r"\bFIGURE\s+(\d+(?:\.\d+)+)\b", re.IGNORECASE)
EQUATION_RE = re.compile(r"\((\d+-\d+)\)")
EXAMPLE_RE = re.compile(r"\bEXAMPLE\s+(\d+(?:\.\d+)*)\b", re.IGNORECASE)
HEADING_FONT = "Futura-Heavy"
HEADING_COLOR = 28319


@dataclass(frozen=True)
class TextLine:
    text: str
    pdf_page_index: int
    pdf_page_number: int
    printed_page_label: str
    bbox: tuple[float, float, float, float]
    font_names: tuple[str, ...]
    max_font_size: float
    colors: tuple[int, ...]


@dataclass(frozen=True)
class HeadingCandidate:
    text: str
    printed_section_id: str | None
    pdf_page_index: int
    pdf_page_number: int
    printed_page_label: str
    bbox: tuple[float, float, float, float]
    numbered: bool
    style_signature: str


def clean_text(value: str) -> str:
    safe = value.encode("utf-8", errors="ignore").decode("utf-8")
    return re.sub(r"\s+", " ", safe).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def page_references(doc: fitz.Document) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for index in range(doc.page_count):
        label = clean_text(doc[index].get_label())
        if not label:
            raise ValueError(f"PDF page {index} has no page label")
        pages.append(
            {
                "pdf_page_index": index,
                "pdf_page_number": index + 1,
                "printed_page_label": label,
            }
        )
    labels = [page["printed_page_label"] for page in pages]
    if len(labels) != len(set(labels)):
        raise ValueError("PDF page labels are not unique")
    return pages


def extract_lines(page: fitz.Page) -> list[TextLine]:
    lines: list[TextLine] = []
    page_index = page.number
    page_label = clean_text(page.get_label())
    for block in page.get_text("dict").get("blocks", []):
        for raw_line in block.get("lines", []):
            spans = [span for span in raw_line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = clean_text("".join(span["text"] for span in spans))
            if not text:
                continue
            lines.append(
                TextLine(
                    text=text,
                    pdf_page_index=page_index,
                    pdf_page_number=page_index + 1,
                    printed_page_label=page_label,
                    bbox=tuple(round(float(value), 3) for value in raw_line["bbox"]),
                    font_names=tuple(sorted({span["font"] for span in spans})),
                    max_font_size=round(max(float(span["size"]) for span in spans), 3),
                    colors=tuple(sorted({int(span["color"]) for span in spans})),
                )
            )
    return lines


def is_heading_line(line: TextLine) -> bool:
    return (
        HEADING_FONT in line.font_names
        and HEADING_COLOR in line.colors
        and 10.5 <= line.max_font_size <= 11.5
        and not line.text.startswith("FIGURE ")
        and not line.text.startswith("TABLE ")
        and not line.text.startswith("EXAMPLE ")
    )


def merge_wrapped_heading_lines(lines: list[TextLine]) -> list[TextLine]:
    merged: list[TextLine] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if not is_heading_line(current):
            index += 1
            continue
        text = current.text
        bbox = list(current.bbox)
        next_index = index + 1
        while next_index < len(lines):
            following = lines[next_index]
            vertical_gap = following.bbox[1] - bbox[3]
            same_style = (
                is_heading_line(following)
                and following.font_names == current.font_names
                and abs(following.max_font_size - current.max_font_size) < 0.1
                and following.colors == current.colors
            )
            aligned = abs(following.bbox[0] - current.bbox[0]) <= 35
            if not same_style or not aligned or not (-2 <= vertical_gap <= 8):
                break
            text = f"{text} {following.text}"
            bbox[2] = max(bbox[2], following.bbox[2])
            bbox[3] = following.bbox[3]
            next_index += 1
        merged.append(
            TextLine(
                text=clean_text(text),
                pdf_page_index=current.pdf_page_index,
                pdf_page_number=current.pdf_page_number,
                printed_page_label=current.printed_page_label,
                bbox=tuple(bbox),
                font_names=current.font_names,
                max_font_size=current.max_font_size,
                colors=current.colors,
            )
        )
        index = next_index
    return merged


def extract_heading_candidates(doc: fitz.Document) -> list[HeadingCandidate]:
    candidates: list[HeadingCandidate] = []
    current_printed_section_id: str | None = None
    for page_index in range(doc.page_count):
        page = doc[page_index]
        heading_lines = merge_wrapped_heading_lines(extract_lines(page))
        for line in heading_lines:
            numbered_match = NUMBERED_HEADING_RE.match(line.text)
            if numbered_match:
                current_printed_section_id = numbered_match.group("id")
            candidates.append(
                HeadingCandidate(
                    text=line.text,
                    printed_section_id=current_printed_section_id,
                    pdf_page_index=line.pdf_page_index,
                    pdf_page_number=line.pdf_page_number,
                    printed_page_label=line.printed_page_label,
                    bbox=line.bbox,
                    numbered=numbered_match is not None,
                    style_signature=(
                        f"fonts={','.join(line.font_names)};size={line.max_font_size};"
                        f"colors={','.join(str(color) for color in line.colors)}"
                    ),
                )
            )
    return candidates


def extract_page_anchors(doc: fitz.Document) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        text = clean_text(page.get_text("text"))
        figures = list(dict.fromkeys(FIGURE_RE.findall(text)))
        equations = list(dict.fromkeys(EQUATION_RE.findall(text)))
        examples = list(dict.fromkeys(EXAMPLE_RE.findall(text)))
        anchors.append(
            {
                "pdf_page_index": page_index,
                "printed_page_label": clean_text(page.get_label()),
                "figure_ids": figures,
                "equation_ids": equations,
                "example_ids": examples,
            }
        )
    return anchors


def extract_outline(doc: fitz.Document) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for level, title, pdf_page_number, _destination in doc.get_toc(simple=False):
        cleaned = clean_text(title)
        if not cleaned:
            continue
        outline.append(
            {
                "level": int(level),
                "title": cleaned,
                "pdf_page_number": int(pdf_page_number),
                "pdf_page_index": int(pdf_page_number) - 1,
                "printed_page_label": clean_text(doc[int(pdf_page_number) - 1].get_label()),
            }
        )
    return outline


def extract_candidates(pdf_path: Path) -> dict[str, Any]:
    document = fitz.open(pdf_path)
    try:
        return {
            "source": {
                "pdf_filename": pdf_path.name,
                "pdf_sha256": sha256_file(pdf_path),
                "page_count": document.page_count,
                "metadata": document.metadata,
            },
            "pages": page_references(document),
            "outline": extract_outline(document),
            "heading_candidates": [
                asdict(candidate) for candidate in extract_heading_candidates(document)
            ],
            "page_anchors": extract_page_anchors(document),
        }
    finally:
        document.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract reviewed-manifest candidates from DIP4E")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    payload = extract_candidates(args.pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "page_count": payload["source"]["page_count"],
                "heading_candidates": len(payload["heading_candidates"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
