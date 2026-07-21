#!/usr/bin/env python3
"""Fetch the running backend OpenAPI document and write a GPT Action schema file."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

EXPECTED_PATHS = {
    "/health",
    "/gpt/section-locators/{section_id}",
}
EXPECTED_OPERATION_IDS = {
    "healthCheck",
    "gptGetSectionLocator",
}
AUTH_HEADER_NAMES = {
    "authorization",
    "x-api-key",
}
DEFAULT_OUTPUT = Path("examples/openai_action_schema_one_book.yaml")


class ActionSchemaExportError(RuntimeError):
    """Raised when the live backend cannot produce a safe GPT Action schema."""


def _normalize_http_url(value: str, *, argument_name: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ActionSchemaExportError(
            f"{argument_name} must be an absolute http(s) URL: {value!r}"
        )
    return normalized


def fetch_openapi(backend_url: str, *, timeout_seconds: float = 15.0) -> dict[str, Any]:
    """Fetch `/openapi.json` from a running backend."""

    normalized_backend_url = _normalize_http_url(
        backend_url,
        argument_name="--backend-url",
    )
    openapi_url = f"{normalized_backend_url}/openapi.json"
    request = Request(
        openapi_url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ActionSchemaExportError(
                    f"Backend returned HTTP {status} for {openapi_url}"
                )
            raw = response.read()
    except HTTPError as exc:
        raise ActionSchemaExportError(
            f"Backend returned HTTP {exc.code} for {openapi_url}"
        ) from exc
    except URLError as exc:
        raise ActionSchemaExportError(
            f"Cannot reach backend OpenAPI endpoint {openapi_url}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise ActionSchemaExportError(
            f"Timed out fetching backend OpenAPI endpoint {openapi_url}"
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActionSchemaExportError(
            f"Backend OpenAPI endpoint did not return valid UTF-8 JSON: {openapi_url}"
        ) from exc
    if not isinstance(payload, dict):
        raise ActionSchemaExportError("Backend OpenAPI document must be a JSON object")
    return payload


def _operation_ids(schema: dict[str, Any]) -> set[str]:
    operation_ids: set[str] = set()
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {
                "get",
                "put",
                "post",
                "delete",
                "options",
                "head",
                "patch",
                "trace",
            }:
                continue
            if isinstance(operation, dict) and isinstance(operation.get("operationId"), str):
                operation_ids.add(operation["operationId"])
    return operation_ids


def _remove_action_auth_header_parameters(schema: dict[str, Any]) -> None:
    """Remove auth headers supplied by GPT Action authentication settings."""

    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters")
            if not isinstance(parameters, list):
                continue
            filtered = []
            for parameter in parameters:
                if not isinstance(parameter, dict):
                    filtered.append(parameter)
                    continue
                is_action_auth_header = (
                    str(parameter.get("in", "")).casefold() == "header"
                    and str(parameter.get("name", "")).casefold() in AUTH_HEADER_NAMES
                )
                if not is_action_auth_header:
                    filtered.append(parameter)
            if filtered:
                operation["parameters"] = filtered
            else:
                operation.pop("parameters", None)


def prepare_action_schema(
    live_schema: dict[str, Any],
    *,
    server_url: str,
) -> dict[str, Any]:
    """Validate and sanitize the live OpenAPI document for GPT Actions."""

    schema = deepcopy(live_schema)
    openapi_version = schema.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version.startswith("3.1"):
        raise ActionSchemaExportError(
            f"Backend must expose OpenAPI 3.1; received {openapi_version!r}"
        )

    paths = schema.get("paths")
    if not isinstance(paths, dict):
        raise ActionSchemaExportError("Backend OpenAPI document has no paths object")
    actual_paths = set(paths)
    if actual_paths != EXPECTED_PATHS:
        raise ActionSchemaExportError(
            "Backend public paths differ from the GPT Action contract; "
            f"expected={sorted(EXPECTED_PATHS)!r}, actual={sorted(actual_paths)!r}"
        )

    actual_operation_ids = _operation_ids(schema)
    if actual_operation_ids != EXPECTED_OPERATION_IDS:
        raise ActionSchemaExportError(
            "Backend operation IDs differ from the GPT Action contract; "
            f"expected={sorted(EXPECTED_OPERATION_IDS)!r}, "
            f"actual={sorted(actual_operation_ids)!r}"
        )

    normalized_server_url = _normalize_http_url(
        server_url,
        argument_name="--server-url",
    )
    schema["servers"] = [{"url": normalized_server_url}]
    _remove_action_auth_header_parameters(schema)
    return schema


def _serialize_schema(schema: dict[str, Any], output_path: Path) -> str:
    suffix = output_path.suffix.casefold()
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_dump(
            schema,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
    if suffix == ".json":
        return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    raise ActionSchemaExportError(
        f"--output must end in .yaml, .yml, or .json: {output_path}"
    )


def write_action_schema(schema: dict[str, Any], output_path: Path) -> None:
    """Atomically write YAML or JSON Action schema output."""

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = _serialize_schema(schema, output_path)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def export_action_schema(
    *,
    backend_url: str,
    server_url: str | None,
    output_path: Path,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Fetch, validate, sanitize, and write a backend Action schema."""

    live_schema = fetch_openapi(backend_url, timeout_seconds=timeout_seconds)
    action_schema = prepare_action_schema(
        live_schema,
        server_url=server_url or backend_url,
    )
    write_action_schema(action_schema, output_path)
    return action_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch /openapi.json from a running Teacher GPT backend and write a "
            "validated GPT Action schema file."
        )
    )
    parser.add_argument(
        "--backend-url",
        required=True,
        help="Running backend base URL used to fetch /openapi.json.",
    )
    parser.add_argument(
        "--server-url",
        help=(
            "Public HTTPS base URL written into the Action schema. Defaults to "
            "--backend-url."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output .yaml/.yml/.json file (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="HTTP timeout in seconds (default: 15).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("error: --timeout must be greater than zero", file=sys.stderr)
        return 2
    try:
        schema = export_action_schema(
            backend_url=args.backend_url,
            server_url=args.server_url,
            output_path=args.output,
            timeout_seconds=args.timeout,
        )
    except ActionSchemaExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output_path = args.output.resolve()
    print(
        f"Wrote GPT Action schema to {output_path} "
        f"({len(schema['paths'])} paths, server={schema['servers'][0]['url']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
