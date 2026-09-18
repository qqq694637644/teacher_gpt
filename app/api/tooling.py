from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.core.security import require_api_key
from skill_temple.runtime import env_value_from_environment_or_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH_PREFIXES = ("/v1/skills", "/v1/workspace")


def _configured_path(name: str, default: Path) -> Path:
    value = env_value_from_environment_or_dotenv(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


def _prepare_runtime_paths() -> Path:
    skills_dir = _configured_path("SKILL_TEMPLE_SKILLS_DIR", _PROJECT_ROOT / "skills")
    if not skills_dir.exists() and not env_value_from_environment_or_dotenv(
        "SKILL_TEMPLE_SKILLS_DIR"
    ):
        skills_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SKILL_TEMPLE_SKILLS_DIR", str(skills_dir))

    workspace_root = _configured_path("WORKSPACE_ROOT", _PROJECT_ROOT / "workspaces")
    os.environ.setdefault("WORKSPACE_ROOT", str(workspace_root))

    operation_root = _configured_path(
        "WORKSPACE_OPERATION_ROOT",
        workspace_root / ".operations",
    )
    os.environ.setdefault("WORKSPACE_OPERATION_ROOT", str(operation_root))
    return skills_dir


def _is_tool_path(path: str) -> bool:
    return path.startswith(_TOOL_PATH_PREFIXES)


async def _tool_api_key_middleware(request: Request, call_next: Any) -> Any:
    if _is_tool_path(request.url.path):
        try:
            await require_api_key(
                request,
                authorization=request.headers.get("Authorization"),
                x_api_key=request.headers.get("X-API-Key"),
            )
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )
    return await call_next(request)


def install_skill_workspace_actions(app: FastAPI) -> None:
    """Mount the vendored Skill/workspace Action routes into the Teacher API."""

    skills_dir = _prepare_runtime_paths()
    from skill_temple.app import create_app as create_skill_temple_app

    source_app = create_skill_temple_app(skills_dir=skills_dir)

    for route in source_app.router.routes:
        if not isinstance(route, APIRoute):
            continue
        if _is_tool_path(route.path):
            app.router.routes.append(route)

    app.state.skill_temple_source_app = source_app
    app.state.local_workspace_service = source_app.state.local_workspace_service
    app.middleware("http")(_tool_api_key_middleware)
