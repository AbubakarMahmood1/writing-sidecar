import json
import shutil
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from chromadb.api.client import SharedSystemClient

from writing_sidecar.mempalace_adapter import SUPPORTED_MEMPALACE_SPEC
from writing_sidecar.workflow import (
    STATE_FILENAME,
    SEARCH_MODE_ROOMS,
    _ensure_dir,
    doctor_writing_sidecar,
    default_output_dir,
    default_palace_dir,
    default_runtime_dir,
    export_writing_corpus,
    get_writing_sidecar_status,
    print_doctor_report,
    resolve_project_root,
    scaffold_writing_sidecar,
    search_writing_sidecar,
)


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


def test_default_writing_paths_accept_vault_root_or_project_dir():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(project_root)

        assert resolve_project_root(str(vault_root), "Witcher-DC") == project_root.resolve()
        assert resolve_project_root(str(project_root), "Witcher-DC") == project_root.resolve()
        assert default_output_dir(vault_root.resolve(), "Witcher-DC") == (
            vault_root.resolve() / ".sidecars" / "witcher_dc"
        )
        assert default_palace_dir(vault_root.resolve(), "Witcher-DC") == (
            vault_root.resolve() / ".palaces" / "witcher_dc"
        )
        assert default_runtime_dir(vault_root.resolve(), "Witcher-DC") == (
            vault_root.resolve() / ".mempalace-sidecar-runtime" / "witcher_dc"
        )
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_writing_corpus_writes_manifest_and_curates_rooms():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        codex_home = tmp_path / ".codex"

        write_file(project_root / "AGENTS.md", "live gateway")
        write_file(project_root / "Chapter 1.txt", "active chapter")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "live notes")
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        write_file(project_root / "_story_bible" / "chapters" / "1. Chill.md", "Archived note")

        brainstorm_dir = tmp_path / "extras" / "brainstorms"
        write_file(brainstorm_dir / "angles.md", "Atlantis intake angles")
        write_file(brainstorm_dir / "AGENTS.md", "should be excluded")

        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "09" / "rollout-a.jsonl",
            cwd=str(project_root),
            user_text="Why did Arthur sponsor Ciri?",
            assistant_text="Arthur takes responsibility for her intake.",
        )
        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "09" / "rollout-b.jsonl",
            cwd=str(tmp_path / "other-project"),
            user_text="Ignore me",
            assistant_text="Wrong project",
        )

        summary = export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            codex_home=str(codex_home),
            brainstorm_paths=[str(brainstorm_dir)],
            audit_paths=[str(project_root / "_story_bible" / "05_Current_Notes.md")],
        )

        manifest_path = output_root / STATE_FILENAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chat_files = list((output_root / "chat_process").glob("*.txt"))

        assert len(chat_files) == 1
        assert "Arthur takes responsibility" in chat_files[0].read_text(encoding="utf-8")
        assert (output_root / ".gitignore").read_text(encoding="utf-8") == (
            f"entities.json\nmempalace.yaml\n{STATE_FILENAME}\n"
        )
        assert summary["last_synced_at"]
        assert manifest["project"] == "Witcher-DC"
        assert manifest["project_root"] == str(project_root.resolve())
        assert manifest["output_root"] == str(output_root.resolve())
        assert manifest["room_counts"]["chat_process"] == 1
        assert manifest["room_counts"]["research"] == 1
        assert manifest["room_counts"]["archived_notes"] == 1
        assert manifest["room_counts"]["brainstorms"] == 1
        assert manifest["config"] is None
        assert {
            entry["source_kind"] for entry in manifest["tracked_inputs"]
        } == {"codex_rollout", "research", "archived_note", "brainstorm"}
        assert all(entry["size"] > 0 for entry in manifest["tracked_inputs"])
        assert all(entry["mtime"] for entry in manifest["tracked_inputs"])
        assert all(len(entry["sha256"]) == 64 for entry in manifest["tracked_inputs"])
        assert summary["rooms"]["audits"] == 0
        assert summary["runtime_root"] == str(default_runtime_dir(vault_root.resolve(), "Witcher-DC"))
        assert str(project_root / "_story_bible" / "05_Current_Notes.md") in summary["skipped_live_files"]

        status = get_writing_sidecar_status(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            codex_home=str(codex_home),
            brainstorm_paths=[str(brainstorm_dir)],
            audit_paths=[str(project_root / "_story_bible" / "05_Current_Notes.md")],
        )
        assert status["built"] is True
        assert status["stale"] is True
        assert any(item["reason"] == "palace_missing" for item in status["stale_reasons"])
    finally:
        cleanup_temp_dir(tmp_path)


def test_writing_status_handles_not_built_and_clean_state():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        config_path = project_root / "writing-sidecar.yaml"

        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        write_file(project_root / "logs" / "brainstorms" / "handoff.md", "physician testing sphere")
        write_file(
            config_path,
            "\n".join(
                [
                    "chat_project_terms:",
                    "  - League of Demons",
                    "brainstorms:",
                    "  - logs/brainstorms",
                ]
            ),
        )

        fresh_status = get_writing_sidecar_status(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        assert fresh_status["built"] is False
        assert fresh_status["stale"] is True
        assert [item["reason"] for item in fresh_status["stale_reasons"]] == [
            "manifest_missing",
            "palace_missing",
        ]

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        clean_status = get_writing_sidecar_status(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        assert clean_status["built"] is True
        assert clean_status["stale"] is False
        assert clean_status["room_counts"]["brainstorms"] == 1
        assert clean_status["room_counts"]["research"] == 1
        assert clean_status["last_synced_at"]
    finally:
        cleanup_temp_dir(tmp_path)


def test_writing_status_detects_config_change():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        config_path = project_root / "writing-sidecar.yaml"

        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        write_file(project_root / "logs" / "brainstorms" / "handoff.md", "physician testing sphere")
        write_file(
            config_path,
            "\n".join(
                [
                    "chat_project_terms:",
                    "  - League of Demons",
                    "brainstorms:",
                    "  - logs/brainstorms",
                ]
            ),
        )

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        write_file(
            config_path,
            "\n".join(
                [
                    "chat_project_terms:",
                    "  - League of Demons",
                    "  - Arthur sponsorship",
                    "brainstorms:",
                    "  - logs/brainstorms",
                ]
            ),
        )
        status = get_writing_sidecar_status(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        assert status["stale"] is True
        assert any(item["reason"] == "config_changed" for item in status["stale_reasons"])
    finally:
        cleanup_temp_dir(tmp_path)


def test_writing_status_detects_input_changed_added_and_missing():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        config_path = project_root / "writing-sidecar.yaml"
        brainstorm_file = project_root / "logs" / "brainstorms" / "handoff.md"

        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        write_file(brainstorm_file, "physician testing sphere")
        write_file(
            config_path,
            "\n".join(
                [
                    "chat_project_terms:",
                    "  - League of Demons",
                    "brainstorms:",
                    "  - logs/brainstorms",
                ]
            ),
        )

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        write_file(brainstorm_file, "physician testing sphere revised")
        write_file(project_root / "logs" / "brainstorms" / "new-angle.md", "new eligible input")
        changed_status = get_writing_sidecar_status(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        changed_reasons = {item["reason"] for item in changed_status["stale_reasons"]}
        assert "input_changed" in changed_reasons
        assert "input_added" in changed_reasons

        brainstorm_file.unlink()
        missing_status = get_writing_sidecar_status(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        assert any(item["reason"] == "input_missing" for item in missing_status["stale_reasons"])
    finally:
        cleanup_temp_dir(tmp_path)


@pytest.mark.parametrize(
    ("mode", "expected_rooms"),
    [
        ("planning", list(SEARCH_MODE_ROOMS["planning"])),
        ("audit", list(SEARCH_MODE_ROOMS["audit"])),
        ("history", list(SEARCH_MODE_ROOMS["history"])),
        ("research", list(SEARCH_MODE_ROOMS["research"])),
    ],
)
def test_writing_search_modes_preserve_room_priority(mode, expected_rooms, monkeypatch):
    search_data = {
        "brainstorms": [
            {
                "room": "brainstorms",
                "source_file": "handoff.md",
                "similarity": 0.81,
                "text": "physician testing sphere",
            }
        ],
        "discarded_paths": [
            {
                "room": "discarded_paths",
                "source_file": "discarded.md",
                "similarity": 0.77,
                "text": "duplicate trust loop",
            }
        ],
        "audits": [
            {
                "room": "audits",
                "source_file": "audit.md",
                "similarity": 0.74,
                "text": "Arthur sponsorship of Ciri",
            }
        ],
        "chat_process": [
            {
                "room": "chat_process",
                "source_file": "rollout.txt",
                "similarity": 0.70,
                "text": "Bruce anomaly investigation",
            }
        ],
        "research": [
            {
                "room": "research",
                "source_file": "dc.md",
                "similarity": 0.68,
                "text": "Atlantis medical chamber",
            }
        ],
        "archived_notes": [
            {
                "room": "archived_notes",
                "source_file": "chapter.md",
                "similarity": 0.65,
                "text": "Bruce anomaly investigation",
            }
        ],
    }

    def fake_search_memories(query, palace_path, wing=None, room=None, n_results=5):
        return {"query": query, "filters": {"wing": wing, "room": room}, "results": search_data[room][:n_results]}

    monkeypatch.setattr("writing_sidecar.workflow.search_memories", fake_search_memories)

    result = search_writing_sidecar(
        query="test query",
        palace_path="C:/fake-palace",
        wing="witcher_dc_writing_sidecar",
        mode=mode,
        n_results=4,
    )

    assert result["mode"] == mode
    assert result["room_order"] == expected_rooms
    assert [hit["room"] for hit in result["results"]] == expected_rooms[: len(result["results"])]
    assert len({(hit["source_file"], hit["text"]) for hit in result["results"]}) == len(result["results"])


def test_scaffold_writing_sidecar_creates_files_and_respects_force():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(project_root)

        summary = scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        assert str(project_root / "logs" / "templates" / "audit_snapshot.md") in summary["created_files"]
        assert (project_root / "logs" / "templates" / "chapter_handoff.md").exists()
        assert (project_root / "logs" / "templates" / "discarded_path.md").exists()
        config_text = (project_root / "writing-sidecar.yaml").read_text(encoding="utf-8")
        assert "brainstorms: []" in config_text
        assert "discarded_paths: []" in config_text
        assert ".sidecars/" in (project_root / "logs" / "README.md").read_text(encoding="utf-8")

        write_file(project_root / "logs" / "README.md", "custom readme")
        untouched = scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        assert str(project_root / "logs" / "README.md") in untouched["skipped_files"]
        assert (project_root / "logs" / "README.md").read_text(encoding="utf-8") == "custom readme"

        forced = scaffold_writing_sidecar(str(vault_root), "Witcher-DC", force=True)
        assert str(project_root / "logs" / "README.md") in forced["overwritten_files"]
        assert "sidecar-safe process memory" in (
            project_root / "logs" / "README.md"
        ).read_text(encoding="utf-8")
    finally:
        cleanup_temp_dir(tmp_path)


def test_writing_sync_cli_respects_sync_policy(monkeypatch, capsys):
    import writing_sidecar.cli as cli

    tmp_path = make_temp_dir()
    try:
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"
        _ensure_dir(palace_root)
        clean_status = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "output_root": "C:/vault/.sidecars/witcher_dc",
            "config_path": None,
            "manifest_path": "C:/vault/.sidecars/witcher_dc/.writing-sidecar-state.json",
            "palace_path": str(palace_root.resolve()),
            "runtime_root": str(runtime_root.resolve()),
            "room_counts": {"brainstorms": 1},
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "built": True,
            "stale": False,
            "stale_reasons": [],
        }
        stale_status = dict(clean_status)
        stale_status["stale"] = True
        stale_status["stale_reasons"] = [{"reason": "input_changed", "source_path": "C:/vault/file.md"}]

        export_calls = []

        monkeypatch.setattr(cli, "get_writing_sidecar_status", lambda **kwargs: clean_status)
        monkeypatch.setattr(
            cli,
            "export_writing_corpus",
            lambda **kwargs: export_calls.append(kwargs) or {},
        )

        monkeypatch.setattr(
            sys,
            "argv",
            ["writing-sidecar", "sync", str(tmp_path), "--project", "Witcher-DC"],
        )
        cli.main(sys.argv[1:])
        output = capsys.readouterr().out
        assert "Sidecar is current; skipping rebuild." in output
        assert export_calls == []

        monkeypatch.setattr(cli, "get_writing_sidecar_status", lambda **kwargs: stale_status)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "writing-sidecar",
                "sync",
                str(tmp_path),
                "--project",
                "Witcher-DC",
                "--sync",
                "never",
            ],
        )
        cli.main(sys.argv[1:])
        output = capsys.readouterr().out
        assert "Warning: sidecar is stale; skipping rebuild because --sync never was used." in output
        assert export_calls == []
    finally:
        cleanup_temp_dir(tmp_path)


def test_writing_search_cli_rebuilds_if_needed(monkeypatch, capsys):
    import writing_sidecar.cli as cli

    tmp_path = make_temp_dir()
    try:
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"
        _ensure_dir(palace_root)

        stale_status = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "output_root": "C:/vault/.sidecars/witcher_dc",
            "config_path": None,
            "manifest_path": "C:/vault/.sidecars/witcher_dc/.writing-sidecar-state.json",
            "palace_path": str(palace_root.resolve()),
            "runtime_root": str(runtime_root.resolve()),
            "room_counts": {"brainstorms": 1},
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "built": True,
            "stale": True,
            "stale_reasons": [{"reason": "input_changed", "source_path": "C:/vault/file.md"}],
        }
        clean_status = dict(stale_status)
        clean_status["stale"] = False
        clean_status["stale_reasons"] = []

        status_calls = [stale_status, clean_status]
        export_calls = []

        def fake_status(**kwargs):
            if len(status_calls) > 1:
                return status_calls.pop(0)
            return clean_status

        def fake_export(**kwargs):
            export_calls.append(kwargs)
            return {
                "project_root": "C:/vault/Witcher-DC",
                "vault_root": "C:/vault",
                "output_root": "C:/vault/.sidecars/witcher_dc",
                "rooms": {"brainstorms": 1},
                "skipped_live_files": [],
                "skipped_missing_paths": [],
                "loaded_config_path": None,
                "generated_config_path": "C:/vault/.sidecars/witcher_dc/mempalace.yaml",
                "manifest_path": "C:/vault/.sidecars/witcher_dc/.writing-sidecar-state.json",
                "palace_path": str(palace_root.resolve()),
                "runtime_root": str(runtime_root.resolve()),
                "mine_skipped": None,
                "last_synced_at": "2026-04-10T00:00:00+00:00",
                "stale": False,
                "stale_reasons": [],
            }

        monkeypatch.setattr(cli, "get_writing_sidecar_status", fake_status)
        monkeypatch.setattr(cli, "export_writing_corpus", fake_export)
        monkeypatch.setattr(
            cli,
            "search_writing_sidecar",
            lambda **kwargs: {
                "query": kwargs["query"],
                "wing": kwargs["wing"],
                "mode": kwargs["mode"],
                "room_order": list(SEARCH_MODE_ROOMS[kwargs["mode"]]),
                "results": [
                    {
                        "room": "brainstorms",
                        "source_file": "handoff.md",
                        "similarity": 0.91,
                        "text": "physician testing sphere",
                    }
                ],
            },
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "writing-sidecar",
                "search",
                str(tmp_path),
                "--project",
                "Witcher-DC",
                "--query",
                "physician testing sphere",
                "--sidecar-palace",
                str(palace_root),
                "--runtime-root",
                str(runtime_root),
            ],
        )
        cli.main(sys.argv[1:])
        output = capsys.readouterr().out
        assert len(export_calls) == 1
        assert export_calls[0]["mine_after_export"] is True
        assert "Writing Sidecar Results for: \"physician testing sphere\"" in output
        assert "physician testing sphere" in output
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_then_mine_sidecar_is_searchable_and_status_is_clean():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"
        codex_home = tmp_path / ".codex"

        write_file(
            project_root / "writing-sidecar.yaml",
            "\n".join(
                [
                    "chat_project_terms:",
                    "  - League of Demons",
                    "brainstorms:",
                    "  - logs/brainstorms",
                    "audits:",
                    "  - logs/audits",
                    "discarded_paths:",
                    "  - logs/discarded_paths",
                ]
            ),
        )
        write_file(project_root / "_story_bible" / "research" / "atlantis.md", "Atlantis medical chamber")
        write_file(project_root / "_story_bible" / "chapters" / "1. Chill.md", "Arthur sponsorship fallout")
        write_file(
            project_root / "logs" / "brainstorms" / "chapter-2_handoff.md",
            "physician testing sphere and Atlantis fallout",
        )
        write_file(
            project_root / "logs" / "audits" / "chapter-1_closeout_audit.md",
            "Arthur sponsorship of Ciri holds the house rhythm together",
        )
        write_file(
            project_root / "logs" / "discarded_paths" / "chapter-1_discarded.md",
            "duplicate trust loop and house rhythm should stay cut",
        )
        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "10" / "rollout-a.jsonl",
            cwd=str(vault_root),
            user_text="Bruce anomaly investigation in Witcher-DC is still open.",
            assistant_text="Let's keep Bruce anomaly investigation in the sidecar history.",
        )

        script = textwrap.dedent(
            f"""
            from unittest.mock import patch

            from chromadb.api.client import SharedSystemClient
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

            import sys
            sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / "src")!r})

            from writing_sidecar.workflow import (
                _project_wing,
                export_writing_corpus,
                get_writing_sidecar_status,
                search_writing_sidecar,
            )


            def fake_embed(self, input):
                terms = [
                    'arthur',
                    'ciri',
                    'atlantis',
                    'intake',
                    'witcher',
                    'dc',
                    'audit',
                    'research',
                    'physician',
                    'sphere',
                    'duplicate',
                    'trust',
                    'loop',
                    'bruce',
                    'anomaly',
                    'history',
                ]
                return [[float(text.lower().count(term)) for term in terms] for text in input]


            with patch.object(ONNXMiniLM_L6_V2, '__call__', fake_embed):
                summary = export_writing_corpus(
                    vault_dir={str(vault_root)!r},
                    project='Witcher-DC',
                    out_dir={str(output_root)!r},
                    codex_home={str(codex_home)!r},
                    mine_after_export=True,
                    palace_path={str(palace_root)!r},
                    runtime_root={str(runtime_root)!r},
                    refresh_palace=True,
                )
                status = get_writing_sidecar_status(
                    vault_dir={str(vault_root)!r},
                    project='Witcher-DC',
                    out_dir={str(output_root)!r},
                    codex_home={str(codex_home)!r},
                    palace_path={str(palace_root)!r},
                    runtime_root={str(runtime_root)!r},
                )
                planning = search_writing_sidecar(
                    'physician testing sphere',
                    {str(palace_root)!r},
                    wing=_project_wing('Witcher-DC'),
                    mode='planning',
                    n_results=4,
                )
                audit = search_writing_sidecar(
                    'duplicate trust loop',
                    {str(palace_root)!r},
                    wing=_project_wing('Witcher-DC'),
                    mode='audit',
                    n_results=4,
                )
                history = search_writing_sidecar(
                    'Bruce anomaly investigation',
                    {str(palace_root)!r},
                    wing=_project_wing('Witcher-DC'),
                    mode='history',
                    n_results=4,
                )

            assert summary['palace_path'] == {str(palace_root.resolve())!r}
            assert summary['runtime_root'] == {str(runtime_root.resolve())!r}
            assert summary['rooms']['brainstorms'] == 1
            assert summary['rooms']['audits'] == 1
            assert summary['rooms']['discarded_paths'] == 1
            assert status['stale'] is False
            assert planning['results']
            assert audit['results']
            assert any(hit['room'] in ('audits', 'discarded_paths') for hit in audit['results'])
            assert any('duplicate trust loop' in hit['text'] for hit in audit['results'])
            assert history['results']
            assert any(hit['room'] == 'chat_process' for hit in history['results'])
            assert any('Bruce anomaly investigation' in hit['text'] for hit in history['results'])
            SharedSystemClient.clear_system_cache()
            print('ok')
            """
        )

        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert "ok" in completed.stdout
    finally:
        cleanup_temp_dir(tmp_path)


def test_doctor_reports_supported_version_and_writable_paths(monkeypatch, capsys):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        report = doctor_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            codex_home=str(tmp_path / ".codex"),
        )
        print_doctor_report(report)
        output = capsys.readouterr().out

        assert report["mempalace_version"]
        assert report["supported_spec"] == SUPPORTED_MEMPALACE_SPEC
        assert any(item["name"] == "mempalace_version" and item["status"] == "ok" for item in report["checks"])
        assert any(item["name"] == "codex_home" and item["status"] == "warn" for item in report["checks"])
        assert "Writing Sidecar Doctor" in output
    finally:
        cleanup_temp_dir(tmp_path)


def test_doctor_marks_unsupported_version(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        monkeypatch.setattr("writing_sidecar.workflow.get_installed_mempalace_version", lambda: "3.2.0")
        monkeypatch.setattr(
            "writing_sidecar.workflow.ensure_supported_mempalace_version",
            lambda: (_ for _ in ()).throw(RuntimeError("Unsupported MemPalace version: 3.2.0. Expected >=3.1,<3.2.")),
        )

        report = doctor_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
        )
        assert report["ok"] is False
        assert any(item["name"] == "mempalace_version" and item["status"] == "fail" for item in report["checks"])
    finally:
        cleanup_temp_dir(tmp_path)


def test_doctor_marks_unwritable_paths(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        monkeypatch.setattr("writing_sidecar.workflow._check_writable_path", lambda path: (False, "Not writable: denied"))

        report = doctor_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
        )
        assert report["ok"] is False
        assert any(item["name"] == "output_root" and item["status"] == "fail" for item in report["checks"])
        assert any(item["name"] == "palace_path" and item["status"] == "fail" for item in report["checks"])
        assert any(item["name"] == "runtime_root" and item["status"] == "fail" for item in report["checks"])
    finally:
        cleanup_temp_dir(tmp_path)
