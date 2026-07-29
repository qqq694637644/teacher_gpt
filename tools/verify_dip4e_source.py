#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import fitz

try:
    from tools.extract_pdf_candidates import extract_heading_candidates
except ModuleNotFoundError:  # Direct execution: python tools/verify_dip4e_source.py
    from extract_pdf_candidates import extract_heading_candidates

EXPECTED_SHA256 = "7b2b48ed87b454970d0916e1dbd7a5160e33d28db0dcdeba647b61eb5d3b850b"
EXPECTED_PAGE_COUNT = 1022
EXPECTED_LABELS = {
    0: "Cover",
    1: "IFC",
    2: "1",
    99: "98",
    106: "105",
    107: "106",
    1020: "1019",
    1021: "Back Cover",
}
EXPECTED_PAGE_ANCHORS = {
    99: ["SPATIAL OPERATIONS", "FIGURE 2.37"],
    100: ["Single-Pixel Operations", "Neighborhood Operations", "(2-42)", "(2-43)"],
    101: ["Geometric Transformations", "FIGURE 2.39"],
    102: ["(2-44)", "homogeneous coordinates", "intensity interpolation"],
    103: ["inverse mapping", "TABLE 2.3", "MATLAB"],
    104: ["EXAMPLE 2.9", "Image Registration"],
    105: ["FIGURE 2.40", "(2-46)"],
    106: ["FIGURE 2.41", "(2-47)"],
    107: ["EXAMPLE 2.10", "VECTOR AND MATRIX OPERATIONS"],
}
EXPECTED_26_TOP_LEVEL = [
    "ELEMENTWISE VERSUS MATRIX OPERATIONS",
    "LINEAR VERSUS NONLINEAR OPERATIONS",
    "ARITHMETIC OPERATIONS",
    "SET AND LOGICAL OPERATIONS",
    "SPATIAL OPERATIONS",
    "VECTOR AND MATRIX OPERATIONS",
    "IMAGE TRANSFORMS",
    "IMAGE INTENSITIES AS RANDOM VARIABLES",
]
EXPECTED_26_CHILDREN = [
    "Basic Set Operations",
    "Logical Operations",
    "Single-Pixel Operations",
    "Neighborhood Operations",
    "Geometric Transformations",
    "Image Registration",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def verify(pdf_path: Path) -> dict[str, object]:
    actual_sha = sha256_file(pdf_path)
    if actual_sha != EXPECTED_SHA256:
        raise ValueError(f"unexpected PDF SHA-256: {actual_sha}")

    document = fitz.open(pdf_path)
    try:
        if document.page_count != EXPECTED_PAGE_COUNT:
            raise ValueError(f"unexpected PDF page count: {document.page_count}")
        for page_index, expected_label in EXPECTED_LABELS.items():
            actual_label = document[page_index].get_label().strip()
            if actual_label != expected_label:
                raise ValueError(
                    f"page label mismatch at {page_index}: {actual_label!r} != {expected_label!r}"
                )
        for page_index, anchors in EXPECTED_PAGE_ANCHORS.items():
            page_text = normalize_text(document[page_index].get_text("text"))
            missing = [anchor for anchor in anchors if anchor not in page_text]
            if missing:
                raise ValueError(f"page {page_index} is missing anchors: {missing}")

        section_26 = [
            candidate
            for candidate in extract_heading_candidates(document)
            if candidate.printed_section_id == "2.6" and not candidate.numbered
        ]
        top_level = [candidate.text for candidate in section_26 if candidate.text.isupper()]
        children = [candidate.text for candidate in section_26 if not candidate.text.isupper()]
        if top_level != EXPECTED_26_TOP_LEVEL:
            raise ValueError(f"unexpected 2.6 top-level heading order: {top_level}")
        if children != EXPECTED_26_CHILDREN:
            raise ValueError(f"unexpected 2.6 child heading order: {children}")
    finally:
        document.close()

    return {
        "pdf_sha256": actual_sha,
        "page_count": EXPECTED_PAGE_COUNT,
        "verified_page_labels": len(EXPECTED_LABELS),
        "verified_spatial_operations_pages": len(EXPECTED_PAGE_ANCHORS),
        "verified_2_6_top_level_headings": len(EXPECTED_26_TOP_LEVEL),
        "verified_2_6_child_headings": len(EXPECTED_26_CHILDREN),
        "spatial_operations_project_id": "2.6.5",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the exact DIP4E source PDF")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.pdf), ensure_ascii=False))


if __name__ == "__main__":
    main()
