import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.core.config import Settings
from app.main import create_app
from app.services.index_compiler import LocatorIndexCompiler
from tests.helpers import complete_manifest


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


def _response_validator(curated: dict, schema_name: str) -> Draft202012Validator:
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/components/schemas/{schema_name}",
            "components": curated["components"],
        }
    )


def test_real_api_responses_validate_against_curated_action_schema(tmp_path) -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    index_path = tmp_path / "compiled_locator_index.json"
    index_path.write_text(
        json.dumps(compiled.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    curated = yaml.safe_load(
        Path("examples/openai_action_schema_one_book.yaml").read_text(encoding="utf-8")
    )

    with TestClient(
        create_app(Settings(locator_index_path=index_path, require_api_key=False))
    ) as client:
        health = client.get("/health")
        locator = client.get("/gpt/section-locators/2.6.5")

    health.raise_for_status()
    locator.raise_for_status()
    _response_validator(curated, "HealthResponse").validate(health.json())
    _response_validator(curated, "SectionLocator").validate(locator.json())
