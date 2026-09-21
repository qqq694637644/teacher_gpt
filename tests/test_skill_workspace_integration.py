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


def test_skill_catalog_rescans_and_action_logs_are_mounted(tmp_path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    _write_demo_skill(skills_root)
    monkeypatch.setenv("SKILL_TEMPLE_SKILLS_DIR", str(skills_root))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("WORKSPACE_OPERATION_ROOT", str(tmp_path / "operations"))

    client = TestClient(create_app(_settings(tmp_path)))
    first = client.get("/v1/skills")
    assert first.status_code == 200, first.text
    assert {item["skill_id"] for item in first.json()["skills"]} == {"demo"}

    added = skills_root / "later"
    added.mkdir(parents=True)
    (added / "SKILL.md").write_text(
        "---\nname: later\ndescription: Added after startup.\n---\n\n# Later\n",
        encoding="utf-8",
    )
    refreshed = client.get("/v1/skills")
    assert refreshed.status_code == 200, refreshed.text
    assert {item["skill_id"] for item in refreshed.json()["skills"]} == {"demo", "later"}

    _prepare(client, "action-log-workspace")
    events = client.get("/v1/action-logs", params={"wait": 0})
    assert events.status_code == 200, events.text
    items = events.json()["items"]
    prepared = next(item for item in items if "ACTION prepareWorkspace" in item["text"])
    assert prepared["event"]["kind"] == "generic"
    assert prepared["event"]["phase"] == "completed"
    assert prepared["event"]["payload"]["operation"] == "prepare_workspace"


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
        started_body = started.json()
        operation_id = started_body["operation"]["operation_id"]
        assert started_body["operation"]["state"] == "succeeded"
        assert "pwsh-ok" in started_body["stdout"]

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

        activity_items = client.get(
            "/v1/action-logs", params={"after": 0, "wait": 0, "limit": 100}
        ).json()["items"]
        command_events = [
            item["event"]
            for item in activity_items
            if item.get("event", {}).get("activity_id") == f"command:{operation_id}"
        ]
        assert command_events[0]["phase"] == "started"
        assert command_events[-1]["phase"] == "completed"
        assert command_events[-1]["payload"]["state"] == "succeeded"
        assert command_events[-1]["payload"]["stdout_preview"] == ["pwsh-ok"]


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
