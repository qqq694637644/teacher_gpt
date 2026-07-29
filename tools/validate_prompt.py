#!/usr/bin/env python3
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[1] / "PROMPT.md"
MAX_CHARACTERS = 8000
REQUIRED = {
    "gptGetSectionLocator",
    "gptGetExerciseLocator",
    "gptListChapterExercises",
    "file_search.msearch",
    "file_search.mclick",
    "required_evidence",
    "content_window",
    "reference_retrieval_plan",
    "传递依赖闭包",
    "只传入一条 query",
    "data_version",
    "contains_exercise",
    "EXERCISE_CATALOG_UNAVAILABLE",
}
FORBIDDEN = {
    "file_library.open_page",
    "file_library.search",
    "next_page",
    "previous_page",
    "gptGetSection(",
    "gptSearchBook",
    "gptGetFigure",
    "SectionPack",
    "next_offset",
    "content_status",
    "source_filter",
}


def validate_prompt(text: str) -> None:
    if len(text) > MAX_CHARACTERS:
        raise ValueError(f"PROMPT.md exceeds {MAX_CHARACTERS} characters: {len(text)}")
    missing = sorted(REQUIRED - {item for item in REQUIRED if item in text})
    if missing:
        raise ValueError(f"PROMPT.md is missing required terms: {missing}")
    found = sorted(item for item in FORBIDDEN if item in text)
    if found:
        raise ValueError(f"PROMPT.md contains forbidden Version 2 or invented tools: {found}")


def main() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    validate_prompt(text)
    print(f"PROMPT.md valid: {len(text)} characters")


if __name__ == "__main__":
    main()
