from __future__ import annotations

import difflib
import json
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from chromadb.api.client import SharedSystemClient

from writing_sidecar.workflow import (
    _ensure_dir,
    default_output_dir,
    default_palace_dir,
    default_runtime_dir,
    export_writing_corpus,
)

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"
GOLDEN_ROOT = Path(__file__).resolve().parent / "golden"
TIMESTAMP_KEYS = {
    "verified_at",
    "updated_at",
    "previewed_at",
    "modified_at",
    "last_synced_at",
    "last_verified_at",
    "last_fact_sync_at",
    "last_checkpoint_at",
    "last_health_check_at",
}
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
DATE_STAMP_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}(?=_)")
SHA256_PATTERN = re.compile(r"\b[a-fA-F0-9]{64}\b")


def write_file(path: Path, content: str):
    _ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def build_codex_rollout(path: Path, cwd: str, user_text: str, assistant_text: str):
    entries = [
        {
            "timestamp": "2026-04-09T13:28:53.003Z",
            "type": "session_meta",
            "payload": {"id": path.stem, "cwd": cwd},
        },
        {
            "timestamp": "2026-04-09T13:28:53.011Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": user_text},
        },
        {
            "timestamp": "2026-04-09T13:28:53.200Z",
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": assistant_text},
        },
        {
            "timestamp": "2026-04-09T13:28:53.300Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "ignored tool output",
            },
        },
    ]
    write_file(path, "\n".join(json.dumps(entry) for entry in entries))


def make_temp_dir() -> Path:
    root = (
        Path(__file__).resolve().parents[1]
        / "test-artifacts-writing-export"
        / f"mempalace-writing-export-{uuid.uuid4().hex[:8]}"
    )
    _ensure_dir(root)
    return root


def cleanup_temp_dir(path: Path):
    SharedSystemClient.clear_system_cache()
    shutil.rmtree(path, ignore_errors=True)


def copy_fixture_vault(name: str) -> tuple[Path, Path]:
    tmp_path = make_temp_dir()
    source = FIXTURES_ROOT / name / "vault"
    vault_root = tmp_path / "vault"
    shutil.copytree(source, vault_root)
    return tmp_path, vault_root


def resolve_fixture_project_root(vault_root: Path, project_name: str) -> Path:
    for config_path in vault_root.rglob("writing-sidecar.yaml"):
        if config_path.parent.name == project_name:
            return config_path.parent
    raise FileNotFoundError(f"Could not find project {project_name!r} under {vault_root}")


def stub_empty_search(monkeypatch):
    monkeypatch.setattr(
        "writing_sidecar.workflow.search_memories",
        lambda **kwargs: {
            "query": kwargs["query"],
            "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
            "results": [],
        },
    )
    monkeypatch.setattr(
        "writing_sidecar.workflow._mine_exported_sidecar",
        lambda output_root, project, palace_path, runtime_root, refresh_palace=False: _ensure_dir(
            Path(palace_path)
        ),
    )


def prepare_fixture_environment(
    fixture_name: str,
    project_name: str,
    *,
    monkeypatch=None,
    build: bool = True,
) -> dict:
    tmp_path, vault_root = copy_fixture_vault(fixture_name)
    project_root = resolve_fixture_project_root(vault_root, project_name)
    output_root = default_output_dir(vault_root.resolve(), project_name)
    palace_root = default_palace_dir(vault_root.resolve(), project_name)
    runtime_root = default_runtime_dir(vault_root.resolve(), project_name)

    if build:
        export_writing_corpus(
            vault_dir=str(vault_root),
            project=project_name,
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        _ensure_dir(palace_root)

    if monkeypatch is not None:
        stub_empty_search(monkeypatch)

    return {
        "tmp_path": tmp_path,
        "vault_root": vault_root,
        "project_root": project_root,
        "project_name": project_name,
        "output_root": output_root,
        "palace_root": palace_root,
        "runtime_root": runtime_root,
        "codex_home": Path.home() / ".codex",
    }


@contextmanager
def fixture_workspace(
    fixture_name: str,
    project_name: str,
    *,
    build: bool = True,
    invoke_from_project_root: bool = False,
):
    context = prepare_fixture_environment(fixture_name, project_name, build=build)
    context["call_vault_dir"] = context["project_root"] if invoke_from_project_root else context["vault_root"]
    context["call_project"] = None if invoke_from_project_root else project_name
    patches = [
        patch(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": [],
            },
        ),
        patch(
            "writing_sidecar.workflow._mine_exported_sidecar",
            lambda output_root, project, palace_path, runtime_root, refresh_palace=False: _ensure_dir(
                Path(palace_path)
            ),
        ),
    ]
    try:
        for active_patch in patches:
            active_patch.start()
        yield context
    finally:
        for active_patch in reversed(patches):
            active_patch.stop()
        cleanup_temp_dir(context["tmp_path"])


def workflow_kwargs(context: dict) -> dict:
    return {
        "vault_dir": str(context["call_vault_dir"]),
        "project": context["call_project"],
        "out_dir": str(context["output_root"]),
        "palace_path": str(context["palace_root"]),
        "runtime_root": str(context["runtime_root"]),
    }


def snapshot_path(*parts: str) -> Path:
    return GOLDEN_ROOT.joinpath(*parts)


def _path_replacements(context: dict) -> list[tuple[str, str]]:
    replacements = [
        (str(context["vault_root"].resolve()), "<VAULT_ROOT>"),
        (str(context["project_root"].resolve()), "<PROJECT_ROOT>"),
        (str(context["output_root"].resolve()), "<OUTPUT_ROOT>"),
        (str(context["palace_root"].resolve()), "<PALACE_ROOT>"),
        (str(context["runtime_root"].resolve()), "<RUNTIME_ROOT>"),
        (str(context["codex_home"].resolve()), "<CODEX_HOME>"),
    ]
    return sorted(replacements, key=lambda item: len(item[0]), reverse=True)


def normalize_for_snapshot(payload, context: dict):
    replacements = _path_replacements(context)

    def normalize(value, *, key: str | None = None):
        if key in TIMESTAMP_KEYS and value is not None:
            return "<TIMESTAMP>"
        if key == "mtime" and value is not None:
            return "<MTIME>"
        if isinstance(value, dict):
            normalized_dict = {
                child_key: normalize(child_value, key=child_key) for child_key, child_value in value.items()
            }
            if {"id", "kind", "severity"}.issubset(normalized_dict):
                normalized_dict["id"] = f"<FINDING_ID:{normalized_dict['kind']}>"
            return normalized_dict
        if isinstance(value, list):
            return [normalize(item, key=key) for item in value]
        if isinstance(value, str):
            normalized = value
            for actual, placeholder in replacements:
                normalized = normalized.replace(actual, placeholder)
                normalized = normalized.replace(actual.replace("\\", "/"), placeholder)
            normalized = TIMESTAMP_PATTERN.sub("<TIMESTAMP>", normalized)
            normalized = DATE_STAMP_PATTERN.sub("<DATE>", normalized)
            normalized = SHA256_PATTERN.sub("<SHA256>", normalized)
            return normalized
        return value

    return normalize(payload)


def assert_matches_json_snapshot(actual_payload, snapshot_file: Path, context: dict):
    expected = json.loads(snapshot_file.read_text(encoding="utf-8"))
    actual = normalize_for_snapshot(actual_payload, context)
    if actual == expected:
        return
    expected_text = json.dumps(expected, indent=2, sort_keys=True)
    actual_text = json.dumps(actual, indent=2, sort_keys=True)
    diff = "\n".join(
        difflib.unified_diff(
            expected_text.splitlines(),
            actual_text.splitlines(),
            fromfile=str(snapshot_file),
            tofile="actual",
            lineterm="",
        )
    )
    raise AssertionError(f"Snapshot mismatch for {snapshot_file}:\n{diff}")
