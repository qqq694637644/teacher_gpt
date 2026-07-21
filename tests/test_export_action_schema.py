from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from app.core.config import Settings
from app.main import create_app
from scripts.export_action_schema import (
    ActionSchemaExportError,
    export_action_schema,
    prepare_action_schema,
)


@contextmanager
def serve_openapi(payload: dict) -> Iterator[str]:
    encoded = json.dumps(payload).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path != "/openapi.json":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def live_openapi(tmp_path: Path) -> dict:
    app = create_app(
        Settings(
            locator_index_path=tmp_path / "unused.json",
            require_api_key=True,
        )
    )
    return app.openapi()


def test_export_fetches_running_backend_and_writes_yaml(tmp_path: Path) -> None:
    live_schema = live_openapi(tmp_path)
    output = tmp_path / "action_schema.yaml"

    with serve_openapi(live_schema) as backend_url:
        exported = export_action_schema(
            backend_url=backend_url,
            server_url="https://teacher-api.example.com",
            output_path=output,
            timeout_seconds=5,
        )

    written = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert written == exported
    assert written["servers"] == [{"url": "https://teacher-api.example.com"}]
    assert set(written["paths"]) == {
        "/health",
        "/gpt/section-locators/{section_id}",
    }

    parameters = written["paths"]["/gpt/section-locators/{section_id}"]["get"][
        "parameters"
    ]
    assert [(parameter["name"], parameter["in"]) for parameter in parameters] == [
        ("section_id", "path")
    ]
    assert not list(tmp_path.glob(".action_schema.yaml.*.tmp"))


def test_export_supports_json_and_defaults_server_to_backend(tmp_path: Path) -> None:
    live_schema = live_openapi(tmp_path)
    output = tmp_path / "action_schema.json"

    with serve_openapi(live_schema) as backend_url:
        export_action_schema(
            backend_url=f"{backend_url}/",
            server_url=None,
            output_path=output,
        )

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["servers"] == [{"url": backend_url}]


def test_prepare_rejects_unexpected_public_route(tmp_path: Path) -> None:
    live_schema = live_openapi(tmp_path)
    live_schema["paths"]["/admin/debug"] = {
        "get": {
            "operationId": "debugAdmin",
            "responses": {"200": {"description": "debug"}},
        }
    }

    with pytest.raises(ActionSchemaExportError, match="public paths differ"):
        prepare_action_schema(
            live_schema,
            server_url="https://teacher-api.example.com",
        )


def test_prepare_rejects_non_http_server_url(tmp_path: Path) -> None:
    with pytest.raises(ActionSchemaExportError, match="absolute http"):
        prepare_action_schema(
            live_openapi(tmp_path),
            server_url="teacher-api.example.com",
        )
