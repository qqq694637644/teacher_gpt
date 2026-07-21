from pathlib import Path

import yaml

from app.core.config import Settings
from app.main import create_app


def test_live_openapi_contains_only_version_3_action_paths(tmp_path) -> None:
    app = create_app(Settings(locator_index_path=tmp_path / "unused.json", require_api_key=False))
    schema = app.openapi()

    assert set(schema["paths"]) == {
        "/health",
        "/gpt/section-locators/{section_id}",
    }
    operations = {
        operation["operationId"] for path in schema["paths"].values() for operation in path.values()
    }
    assert operations == {"healthCheck", "gptGetSectionLocator"}


def test_curated_action_schema_matches_public_operations() -> None:
    path = Path("examples/openai_action_schema_one_book.yaml")
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert schema["openapi"] == "3.1.0"
    assert set(schema["paths"]) == {
        "/health",
        "/gpt/section-locators/{section_id}",
    }
    operations = {
        operation["operationId"]
        for route in schema["paths"].values()
        for operation in route.values()
    }
    assert operations == {"healthCheck", "gptGetSectionLocator"}
    serialized = path.read_text(encoding="utf-8")
    for forbidden in (
        "SectionPack",
        "next_offset",
        "gptGetFigure",
        "gptSearchBook",
        "/gpt/sections/",
    ):
        assert forbidden not in serialized
    section = schema["components"]["schemas"]["SectionLocator"]
    assert "source_location" in section["required"]
    assert "source_level" in section["required"]
