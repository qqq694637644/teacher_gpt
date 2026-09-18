from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _settings(tmp_path: Path, *, require_api_key: bool = False) -> Settings:
    return Settings(
        locator_index_path=tmp_path / "unused-locator.json",
        exercise_index_path=None,
        api_key="teacher-secret",
        require_api_key=require_api_key,
    )


def _write_demo_skill(skills_root: Path) -> None:
    skill_root = skills_root / "demo"
    (skill_root / "references").mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\n"
        "name: demo\n"
        "description: Demo integration skill.\n"
        "---\n\n"
        "# Demo\n\nRead `references/details.md`.\n",
        encoding="utf-8",
    )
    (skill_root / "references" / "details.md").write_text(
        "first\nsecond\nthird\n",
        encoding="utf-8",
    )


def _prepare(client: TestClient, key: str) -> str:
    response = client.post("/v1/workspace/prepare", json={"idempotency_key": key})
    assert response.status_code == 200, response.text
    return str(response.json()["workspace_id"])


def test_skill_actions_load_and_read_without_prompt_changes(tmp_path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    _write_demo_skill(skills_root)
    monkeypatch.setenv("SKILL_TEMPLE_SKILLS_DIR", str(skills_root))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("WORKSPACE_OPERATION_ROOT", str(tmp_path / "operations"))

    client = TestClient(create_app(_settings(tmp_path)))
    loaded = client.post("/v1/skills/load", json={"skill_ids": ["demo"]})
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    assert body["loaded_skill_ids"] == ["demo"]
    assert body["skills"][0]["referenced_paths"] == ["references/details.md"]

    read = client.post(
        "/v1/skills/read",
        json={
            "skill_id": "demo",
            "path": "references/details.md",
            "start_line": 2,
            "max_lines": 1,
        },
    )
    assert read.status_code == 200, read.text
    assert read.json()["content"] == "second"
    assert read.json()["next_start_line"] == 3


def test_tool_actions_reuse_teacher_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("WORKSPACE_OPERATION_ROOT", str(tmp_path / "operations"))

    client = TestClient(create_app(_settings(tmp_path, require_api_key=True)))
    denied = client.post("/v1/workspace/prepare", json={"idempotency_key": "auth-check"})
    assert denied.status_code == 401

    allowed = client.post(
        "/v1/workspace/prepare",
        json={"idempotency_key": "auth-check"},
        headers={"Authorization": "Bearer teacher-secret"},
    )
    assert allowed.status_code == 200, allowed.text


def test_workspace_survives_app_recreation(tmp_path, monkeypatch) -> None:
    workspace_root = tmp_path / "persistent-workspaces"
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("WORKSPACE_OPERATION_ROOT", str(tmp_path / "operations"))

    first_client = TestClient(create_app(_settings(tmp_path)))
    workspace_id = _prepare(first_client, "persistent-workspace-key")
    written = first_client.post(
        "/v1/workspace/write-file",
        json={
            "workspace_id": workspace_id,
            "path": "marker.txt",
            "content": "persistent\n",
        },
    )
    assert written.status_code == 200, written.text

    second_client = TestClient(create_app(_settings(tmp_path)))
    reused = second_client.post(
        "/v1/workspace/prepare",
        json={"workspace_id": workspace_id},
    )
    assert reused.status_code == 200, reused.text
    assert reused.json()["created"] is False
    assert reused.json()["empty"] is False

    read = second_client.post(
        "/v1/workspace/read-files",
        json={"workspace_id": workspace_id, "paths": ["marker.txt"]},
    )
    assert read.status_code == 200, read.text
    assert "persistent" in read.json()["files"][0]["content"]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is required")
def test_workspace_command_runs_pwsh(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("WORKSPACE_OPERATION_ROOT", str(tmp_path / "operations"))
    runtime_settings = Settings(
        locator_index_path=Path("catalog/dip4e/compiled_locator_index.json"),
        exercise_index_path=Path("catalog/dip4e/compiled_exercise_index.json"),
        api_key="teacher-secret",
        require_api_key=False,
    )
    with TestClient(create_app(runtime_settings)) as client:
        workspace_id = _prepare(client, "pwsh-command-key")

        started = client.post(
            "/v1/workspace/command",
            json={
                "action": "start",
                "idempotency_key": "pwsh-operation-key",
                "workspace_id": workspace_id,
                "script": "Write-Output 'pwsh-ok'",
                "timeout_seconds": 10,
                "plain_output": True,
            },
        )
        assert started.status_code == 200, started.text
        operation_id = started.json()["operation"]["operation_id"]

        operation = None
        for _ in range(100):
            response = client.post(
                "/v1/workspace/command",
                json={"action": "get", "operation_id": operation_id},
            )
            assert response.status_code == 200, response.text
            operation = response.json()["operation"]
            if operation["state"] != "running":
                break
            time.sleep(0.02)

        assert operation is not None
        assert operation["state"] == "succeeded"
        logs = client.post(
            "/v1/workspace/command",
            json={"action": "logs", "operation_id": operation_id},
        )
        assert logs.status_code == 200, logs.text
        assert "pwsh-ok" in logs.json()["stdout"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep is required")
def test_workspace_search_uses_vendored_search_action(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("WORKSPACE_OPERATION_ROOT", str(tmp_path / "operations"))
    client = TestClient(create_app(_settings(tmp_path)))
    workspace_id = _prepare(client, "search-workspace-key")
    workspace_dir = tmp_path / "workspaces" / workspace_id
    (workspace_dir / "alpha.txt").write_text("one\nNeedle value\nthree\n", encoding="utf-8")

    response = client.post(
        "/v1/workspace/search",
        json={"workspace_id": workspace_id, "query": "needle"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "ripgrep"
    assert body["match_count"] == 1
    assert Path(body["matches"][0]["path"]).name == "alpha.txt"
