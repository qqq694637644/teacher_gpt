#!/usr/bin/env python3
"""Offline PDF ingestion script.

Example:
  python scripts/ingest_book.py \
    --book-id dip4e \
    --pdf "/path/to/Digital Image ProcessingRafael.pdf" \
    --title "Digital Image Processing" \
    --aliases examples/aliases_dip4e.json \
    --overwrite
"""
from __future__ import annotations

import sys
from pathlib import Path as _Path

_PROJECT_ROOT = _Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import argparse
import json
from pathlib import Path

from app.services.pdf_ingestor import PDFIngestor


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a textbook PDF into Teaching GPT Backend storage.")
    parser.add_argument("--book-id", required=True, help="Stable book id, e.g. dip4e")
    parser.add_argument("--pdf", required=True, help="Path to source PDF")
    parser.add_argument("--title", default=None, help="Book title")
    parser.add_argument("--author", default=None, help="Book author")
    parser.add_argument("--aliases", default=None, help="Optional JSON mapping aliases, e.g. {'2.4.4':'2.4.5'}")
    parser.add_argument("--overwrite", action="store_true", help="Delete existing book folder before ingesting")
    parser.add_argument("--no-render", action="store_true", help="Do not render page images")
    args = parser.parse_args()

    aliases = None
    if args.aliases:
        aliases = json.loads(Path(args.aliases).read_text(encoding="utf-8"))

    result = PDFIngestor().ingest(
        book_id=args.book_id,
        pdf_path=args.pdf,
        title=args.title,
        author=args.author,
        render_pages=not args.no_render,
        overwrite=args.overwrite,
        aliases=aliases,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
