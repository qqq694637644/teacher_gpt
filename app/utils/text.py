from __future__ import annotations

import re
from difflib import SequenceMatcher

_SECTION_ID_RE = re.compile(r"^(?P<id>\d+(?:\.\d+)*)(?:\s+|\t+)(?P<title>.+?)\s*$")
_FIGURE_RE = re.compile(r"\b(?:FIGURE|Figure|Fig\.)\s+(?P<id>\d+(?:\.\d+)+)\b[:\s]*(?P<caption>.*)")
_EQUATION_RE = re.compile(r"\((?P<id>\d+\s*-\s*\d+[a-zA-Z]?)\)")
_EXAMPLE_RE = re.compile(r"\b(?:EXAMPLE|Example)\s+(?P<id>\d+(?:\.\d+)*)\s*:?\s*(?P<title>.*)")

_SKIP_UPPER_HEADINGS = {
    "SUMMARY",
    "PROBLEMS",
    "REFERENCES",
    "FURTHER READING",
    "CONTENTS",
    "PREFACE",
}


def normalize_text(text: str) -> str:
    """Normalize extracted PDF text without destroying formulas too aggressively."""
    # Some PDFs contain invalid surrogate code points in extracted text.
    # They cannot be serialized to JSON safely, so drop them early.
    text = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    replacements = {
        "\u00ad": "",
        "\ufeff": "",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\x00": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_section_heading(line: str) -> tuple[str, str] | None:
    match = _SECTION_ID_RE.match(line.strip())
    if not match:
        return None
    sid = match.group("id")
    title = clean_title(match.group("title"))
    return sid, title


def clean_title(title: str) -> str:
    title = normalize_text(title)
    title = re.sub(r"\s+", " ", title)
    return title.strip(" -:\t")


def is_probable_upper_heading(line: str) -> bool:
    line = clean_title(line)
    if not line:
        return False
    if len(line) < 4 or len(line) > 100:
        return False
    if re.match(r"^(FIGURE|Figure|TABLE|Table|EXAMPLE|Example)\b", line):
        return False
    if parse_section_heading(line):
        return False
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 4:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.82:
        return False
    compact = re.sub(r"[^A-Z ]", "", line.upper()).strip()
    if compact in _SKIP_UPPER_HEADINGS:
        return False
    if len(line.split()) < 2 and len(line) < 12:
        return False
    return True


def split_paragraphs(text: str, max_chars: int = 2200) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    raw_parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(raw_parts) <= 1:
        raw_parts = [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+(?=[A-Z0-9\u4e00-\u9fff])", text) if p.strip()]
    parts: list[str] = []
    for part in raw_parts:
        if len(part) <= max_chars:
            parts.append(part)
            continue
        start = 0
        while start < len(part):
            chunk = part[start : start + max_chars]
            cut = max(chunk.rfind(". "), chunk.rfind("。"), chunk.rfind("; "), chunk.rfind("\n"))
            if cut < max_chars * 0.45:
                cut = len(chunk)
            else:
                cut += 1
            parts.append(part[start : start + cut].strip())
            start += cut
    return [p for p in parts if p]


def extract_figures_from_page(text: str) -> list[dict[str, str]]:
    figures: list[dict[str, str]] = []
    lines = [line.strip() for line in normalize_text(text).splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        match = _FIGURE_RE.search(line)
        if not match:
            continue
        caption = match.group("caption").strip()
        continuation: list[str] = []
        for follow in lines[idx + 1 : idx + 5]:
            if _FIGURE_RE.search(follow) or _EXAMPLE_RE.search(follow):
                break
            if parse_section_heading(follow) or is_probable_upper_heading(follow):
                break
            # Keep short continuation lines; captions in PDFs are often split.
            if len(follow) <= 260:
                continuation.append(follow)
        full_caption = " ".join([caption, *continuation]).strip()
        figures.append(
            {
                "figure_id": match.group("id"),
                "label": f"Fig {match.group('id')}",
                "caption": full_caption,
            }
        )
    return figures


def extract_equations_from_text(text: str, page_number: int | None = None) -> list[dict[str, str | int | None]]:
    result: list[dict[str, str | int | None]] = []
    normalized = normalize_text(text)
    for match in _EQUATION_RE.finditer(normalized):
        eq_id = match.group("id").replace(" ", "")
        start = max(0, match.start() - 180)
        end = min(len(normalized), match.end() + 180)
        context = normalized[start:end].replace("\n", " ").strip()
        result.append({"equation_id": eq_id, "context": context, "page_number": page_number})
    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped = []
    for item in result:
        key = str(item["equation_id"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def extract_examples_from_text(text: str, page_number: int | None = None) -> list[dict[str, str | int | None]]:
    result: list[dict[str, str | int | None]] = []
    for match in _EXAMPLE_RE.finditer(normalize_text(text)):
        title = clean_title(match.group("title"))
        result.append({"example_id": match.group("id"), "title": title, "page_number": page_number})
    return result


def compact_snippet(text: str, query: str, max_chars: int = 320) -> str:
    text = normalize_text(text).replace("\n", " ")
    if len(text) <= max_chars:
        return text
    q = query.lower().strip()
    lower = text.lower()
    idx = lower.find(q) if q else -1
    if idx < 0:
        tokens = [t for t in re.split(r"\W+", q) if len(t) >= 3]
        hits = [lower.find(t) for t in tokens if lower.find(t) >= 0]
        idx = min(hits) if hits else 0
    start = max(0, idx - max_chars // 3)
    end = min(len(text), start + max_chars)
    return ("..." if start > 0 else "") + text[start:end].strip() + ("..." if end < len(text) else "")


def lexical_score(query: str, title: str, text: str) -> float:
    q = query.lower().strip()
    if not q:
        return 0.0
    hay_title = title.lower()
    hay_text = text.lower()
    tokens = [t for t in re.split(r"\W+", q) if t]
    if not tokens:
        return 0.0
    score = 0.0
    if q in hay_title:
        score += 5.0
    if q in hay_text:
        score += 2.0
    title_ratio = SequenceMatcher(None, q, hay_title).ratio()
    score += 2.0 * title_ratio
    for token in tokens:
        if token in hay_title:
            score += 1.5
        if token in hay_text:
            score += 0.3
    # Normalize softly.
    return min(score / 10.0, 1.0)
