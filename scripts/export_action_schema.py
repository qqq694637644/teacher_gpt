#!/usr/bin/env python3
"""Generate the GPT Action schema into the repository examples directory."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app

OUTPUT_PATH = PROJECT_ROOT / "examples" / "openai_action_schema_one_book.yaml"


def main() -> None:
    schema = app.openapi()
    schema["servers"] = [{"url": "https://YOUR_DOMAIN"}]
    action_paths = (
        "/gpt/section-locators/{section_id}",
        "/gpt/exercise-locators/{exercise_id}",
        "/gpt/chapters/{chapter_id}/exercises",
        "/v1/skills/load",
        "/v1/skills/read",
        "/v1/workspace/prepare",
        "/v1/workspace/command",
        "/v1/workspace/inspect",
        "/v1/workspace/search",
        "/v1/workspace/read-files",
        "/v1/workspace/write-file",
        "/v1/workspace/apply-patch",
    )
    schema["paths"] = {path: schema["paths"][path] for path in action_paths}

    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters", [])
            operation["parameters"] = [
                parameter for parameter in parameters if parameter.get("in") != "header"
            ]
            if not operation["parameters"]:
                operation.pop("parameters", None)

    OUTPUT_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
