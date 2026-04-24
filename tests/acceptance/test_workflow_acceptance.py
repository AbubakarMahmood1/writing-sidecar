import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from writing_sidecar.mempalace_adapter import SUPPORTED_MEMPALACE_SPEC
from writing_sidecar.workflow import (
    FACT_LOG_FILENAME,
    FACT_PREVIEW_FILENAME,
    FACTS_SNAPSHOT_FILENAME,
    STATE_FILENAME,
    _collect_carry_forward_gap_findings,
    _build_checkpoint_sections,
    _fact_identity,
    build_writing_automation,
    build_writing_bundle,
    build_writing_context,
    build_writing_recap,
    build_writing_routine,
    build_writing_session,
    maintain_writing_sidecar,
    SEARCH_MODE_ROOMS,
    _ensure_dir,
    doctor_writing_sidecar,
    discover_sidecar_projects,
    default_output_dir,
    default_palace_dir,
    default_runtime_dir,
    export_writing_corpus,
    get_writing_sidecar_status,
    list_writing_projects,
    print_doctor_report,
    resolve_project_root,
    resolve_sidecar_project,
    scaffold_writing_sidecar,
    search_writing_sidecar,
    verify_writing_sidecar,
)
from tests.helpers import build_codex_rollout, cleanup_temp_dir, make_temp_dir, write_file

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
        write_file(project_root / "logs" / "checkpoints" / ".gitkeep", "# placeholder")

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
        assert manifest["room_counts"]["checkpoints"] == 0
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

def test_export_writing_corpus_auto_resolves_project_name_from_project_dir():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        summary = export_writing_corpus(
            vault_dir=str(project_root),
            project=None,
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )

        manifest = json.loads((output_root / STATE_FILENAME).read_text(encoding="utf-8"))
        assert summary["project_root"] == str(project_root.resolve())
        assert manifest["project"] == "Witcher-DC"
        assert (output_root / "mempalace.yaml").exists()
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
        "checkpoints": [
            {
                "room": "checkpoints",
                "source_file": "checkpoint.md",
                "similarity": 0.86,
                "text": "startup checkpoint on Arthur sponsorship",
            }
        ],
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
        assert str(project_root / "logs" / "checkpoints") in summary["created_dirs"]
        assert str(project_root / "logs" / "templates" / "checkpoint_snapshot.md") in summary["created_files"]
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
        output_root = default_output_dir(vault_root.resolve(), "Witcher-DC")
        palace_root = default_palace_dir(vault_root.resolve(), "Witcher-DC")
        runtime_root = default_runtime_dir(vault_root.resolve(), "Witcher-DC")
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
        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR SCRIPTING\n")
        write_file(project_root / "_story_bible" / "05_Current_Chapter_Notes.md", "**Phase:** SCRIPTING\n")
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
        assert report["assistant_ready"] is True
        assert all(item["status"] == "ok" for item in report["workflow_checks"])
        assert report["recommended_entrypoint"] == "writing-sidecar automate"
        assert "writing-sidecar automate" in report["recommended_automate_command"]
        assert " --mode suggested-create" in report["recommended_automation_command"]
        assert report["recommended_schedule_profile"] in {"weekday-morning", "weekday-evening", "daily-evening", "weekly-review"}
        assert "Writing Sidecar Doctor" in output
    finally:
        cleanup_temp_dir(tmp_path)

def test_doctor_auto_resolves_project_name_from_project_dir():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR SCRIPTING\n")
        write_file(project_root / "_story_bible" / "05_Current_Chapter_Notes.md", "**Phase:** SCRIPTING\n")

        report = doctor_writing_sidecar(vault_dir=str(project_root))

        assert report["project"] == "Witcher-DC"
        assert report["project_root"] == str(project_root.resolve())
    finally:
        cleanup_temp_dir(tmp_path)

def test_doctor_marks_unsupported_version(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR SCRIPTING\n")
        write_file(project_root / "_story_bible" / "05_Current_Chapter_Notes.md", "**Phase:** SCRIPTING\n")
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        monkeypatch.setattr("writing_sidecar.workflow.get_installed_mempalace_version", lambda: "3.4.0")
        monkeypatch.setattr(
            "writing_sidecar.workflow.ensure_supported_mempalace_version",
            lambda: (_ for _ in ()).throw(RuntimeError("Unsupported MemPalace version: 3.4.0. Expected >=3.1,<3.4.")),
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
        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR SCRIPTING\n")
        write_file(project_root / "_story_bible" / "05_Current_Chapter_Notes.md", "**Phase:** SCRIPTING\n")
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

def test_resolve_sidecar_project_auto_detects_enclosing_project():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        nested_dir = project_root / "notes" / "scratch"
        write_file(
            project_root / "writing-sidecar.yaml",
            "brainstorms:\n  - logs/brainstorms\naudits: []\ndiscarded_paths: []\n",
        )
        _ensure_dir(nested_dir)

        resolved = resolve_sidecar_project(str(nested_dir))
        discovered = discover_sidecar_projects(str(vault_root))

        assert resolved["project"] == "Witcher-DC"
        assert resolved["project_root"] == project_root.resolve()
        assert resolved["vault_root"] == vault_root.resolve()
        assert len(discovered) == 1
        assert discovered[0]["project_root"] == project_root.resolve()
    finally:
        cleanup_temp_dir(tmp_path)

def test_list_writing_projects_reports_states():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        clean_root = vault_root / "Witcher-DC"
        fresh_root = vault_root / "Second-Project"
        clean_palace = default_palace_dir(vault_root.resolve(), "Witcher-DC")

        _ensure_dir(clean_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(clean_root / "AGENTS.md", "gateway")
        write_file(clean_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR SCRIPTING\n**Next Action:** Build the next scene wireframe.\n")
        write_file(clean_root / "_story_bible" / "05_Current_Chapter_Notes.md", "**Phase:** COMPLETE\n")
        write_file(clean_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            palace_path=str(clean_palace),
        )
        _ensure_dir(clean_palace)

        _ensure_dir(fresh_root)
        scaffold_writing_sidecar(str(vault_root), "Second-Project")
        write_file(fresh_root / "_story_bible" / "research" / "notes.md", "Reference")

        report = list_writing_projects(str(vault_root))
        projects = {item["project"]: item for item in report["projects"]}

        assert report["count"] == 2
        assert projects["Second-Project"]["state"] == "not_built"
        assert projects["Second-Project"]["assistant_ready"] is False
        assert projects["Witcher-DC"]["state"] == "clean"
        assert projects["Witcher-DC"]["assistant_ready"] is True
        assert projects["Witcher-DC"]["operative_phase"] == "SCRIPTING"
        assert projects["Witcher-DC"]["recommended_entrypoint"] == "writing-sidecar automate"
        assert "writing-sidecar automate" in projects["Witcher-DC"]["recommended_automate_command"]
        assert " --mode suggested-create" in projects["Witcher-DC"]["recommended_automation_command"]
        assert projects["Witcher-DC"]["recommended_schedule_profile"] == "weekday-morning"
    finally:
        cleanup_temp_dir(tmp_path)

def test_verify_startup_reports_phase_drift_and_writes_cache():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(vault_root)
        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** READY FOR PROSE\n**Next Action:** Draft the chapter now.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            "**Phase:** AUDIT\n**Chapter:** 2\n",
        )
        write_file(project_root / "logs" / "checkpoints" / "2026-04-14_chapter-2_session_checkpoint.md", "checkpoint")
        write_file(project_root / "logs" / "brainstorms" / "2026-04-14_chapter-3_handoff.md", "handoff")

        report = verify_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            sync="never",
            scope="startup",
        )

        cache_path = default_output_dir(vault_root.resolve(), "Witcher-DC") / ".writing-sidecar-verify.json"
        cached = json.loads(cache_path.read_text(encoding="utf-8"))

        assert report["state"] == "error"
        assert any(item["kind"] == "phase_drift" for item in report["findings"])
        assert report["finding_counts"]["error"] >= 1
        assert cached["state"] == "error"
        assert cached["scope"] == "startup"
    finally:
        cleanup_temp_dir(tmp_path)

def test_verify_chapter_detects_state_conflict_and_cached_verification_becomes_stale():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(vault_root)
        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR SCRIPTING\n")
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** SCRIPTING

                ## THREADS CARRIED FORWARD

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur sponsorship | ACTIVE | He still owns the intake burden |
                """
            ).strip(),
        )
        write_file(
            project_root / "_story_bible" / "02C_Character_State_Tracker.md",
            textwrap.dedent(
                """
                ## Closeout Snapshot

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur sponsorship | RESOLVED | This should conflict with the live docs |
                """
            ).strip(),
        )

        report = verify_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            sync="never",
            scope="chapter",
        )
        assert report["state"] == "error"
        assert any(item["kind"] == "current_state_conflict" for item in report["findings"])

        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR SCRIPTING\n- changed after verify\n")

        doctor = doctor_writing_sidecar(vault_dir=str(vault_root), project="Witcher-DC")
        projects = list_writing_projects(str(vault_root))
        project = projects["projects"][0]

        assert doctor["continuity_state"] == "error"
        assert doctor["verification_stale"] is True
        assert project["continuity_state"] == "error"
        assert project["verification_stale"] is True
    finally:
        cleanup_temp_dir(tmp_path)

def test_build_writing_context_returns_startup_packet(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"

        write_file(
            project_root / "writing-sidecar.yaml",
            "brainstorms:\n  - logs/brainstorms\naudits:\n  - logs/audits\ndiscarded_paths: []\n",
        )
        write_file(project_root / "_story_bible" / "01_Story_So_Far.md", "- Arthur sponsored Ciri into Atlantis.\n")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            textwrap.dedent(
                """
                > **Purpose:** Live status file. Check this before planning or drafting.

                ## Current Phase

                **Status:** CHAPTER 1 COMPLETE -> READY FOR CHAPTER 2 PLANNING
                **Last Updated:** 2026-04-09

                ## Recommended Next Loadout

                For Chapter 2 planning:
                1. `02B_Character_Quick_Reference.md`
                2. `05_Current_Chapter_Notes.md`

                ## Next Action

                Open Chapter 2 from the Atlantis fallout position, then reset `05_Current_Chapter_Notes.md` when ready.
                """
            ).strip(),
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                > **Purpose:** Live scratchpad for the current writing session.

                ## CURRENT FOCUS

                **Arc:** Prime Earth Arrival / Darkseid Prelude
                **Chapter:** Under Protection

                ## CDLC STATUS

                **Phase:** COMPLETE
                **Audit Status:** PASS

                ## THREADS CARRIED FORWARD

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur's sponsorship of Ciri | ACTIVE | He has vouched for her intake |
                | Bruce's anomaly investigation | ACTIVE | He has a footprint, not an explanation |

                ## NEXT START POINT

                - physician testing sphere
                - guardian threat-presence in Atlantis
                """
            ).strip(),
        )
        write_file(project_root / "logs" / "brainstorms" / "handoff.md", "physician testing sphere")
        write_file(project_root / "logs" / "audits" / "audit.md", "Arthur sponsorship of Ciri")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": {
                    "brainstorms": [
                        {
                            "room": "brainstorms",
                            "source_file": "handoff.md",
                            "similarity": 0.91,
                            "text": "physician testing sphere limits",
                        },
                        {
                            "room": "brainstorms",
                            "source_file": "handoff.md",
                            "similarity": 0.89,
                            "text": "guardian threat-presence in Atlantis",
                        },
                    ],
                    "audits": [
                        {
                            "room": "audits",
                            "source_file": "audit.md",
                            "similarity": 0.83,
                            "text": "Arthur sponsorship of Ciri remains the carry-forward pressure",
                        }
                    ],
                    "checkpoints": [
                        {
                            "room": "checkpoints",
                            "source_file": "checkpoint.md",
                            "similarity": 0.95,
                            "text": "startup checkpoint keeps Atlantis intake pressure ahead of tooling chatter",
                        }
                    ],
                    "discarded_paths": [],
                    "chat_process": [
                        {
                            "room": "chat_process",
                            "source_file": "rollout.txt",
                            "similarity": 0.75,
                            "text": "meta workflow chatter that should not outrank story evidence",
                        }
                    ],
                    "research": [],
                    "archived_notes": [],
                }[kwargs["room"]],
            },
        )

        context = build_writing_context(
            vault_dir=str(project_root / "logs"),
            project=None,
            out_dir=str(output_root),
            palace_path=str(palace_root),
            mode="startup",
            sync="never",
            n_results=2,
        )

        assert context["project"] == "Witcher-DC"
        assert context["state"] == "clean"
        assert context["phase"] == "COMPLETE"
        assert context["current_chapter"] == "Under Protection"
        assert context["suggested_loadout"] == [
            "02B_Character_Quick_Reference.md",
            "05_Current_Chapter_Notes.md",
        ]
        assert [item["mode"] for item in context["queries_run"]] == ["planning", "history"]
        assert all("Purpose:" not in item["query"] for item in context["queries_run"])
        assert all(
            "The source-of-truth docs are aligned" not in item["query"]
            for item in context["queries_run"]
        )
        planning_sources = [hit["source_file"] for hit in context["results"][0]["results"]]
        assert planning_sources[0] == "checkpoint.md"
        assert planning_sources.count("handoff.md") == 1
        history_rooms = [hit["room"] for hit in context["results"][1]["results"]]
        assert history_rooms[0] == "checkpoints"
        assert context["results"]
        assert context["recent_artifacts"]
    finally:
        cleanup_temp_dir(tmp_path)

def test_build_writing_recap_continuity_uses_live_docs_and_sidecar(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(project_root / "_story_bible" / "01_Story_So_Far.md", "- Timeline: Ciri arrived after the offshore incident.\n- Reference: Atlantis remains on alert.\n")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Phase:** PROSE\n- Pending: Arthur owes the court a public explanation.\n- Risk: continuity drift around the medical chamber.\n")
        write_file(project_root / "_story_bible" / "05_Current_Chapter_Notes.md", "- Watch: keep chronology clean before any League convergence.\n")
        write_file(project_root / "logs" / "audits" / "audit.md", "duplicate trust loop should stay cut")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": [
                    {
                        "room": kwargs["room"],
                        "source_file": f"{kwargs['room']}.md",
                        "similarity": 0.88,
                        "text": f"{kwargs['query']} continuity evidence from {kwargs['room']}",
                    }
                ],
            },
        )

        recap = build_writing_recap(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            mode="continuity",
            sync="never",
            n_results=2,
        )

        assert recap["project"] == "Witcher-DC"
        assert recap["mode"] == "continuity"
        assert recap["sections"]["Timeline-Sensitive Facts"]
        assert recap["sections"]["Unresolved Obligations"]
        assert recap["results"]
    finally:
        cleanup_temp_dir(tmp_path)

def test_build_writing_recap_restart_avoids_duplicate_sections_and_boilerplate(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms:\n  - logs/brainstorms\naudits:\n  - logs/audits\ndiscarded_paths: []\n")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            textwrap.dedent(
                """
                > **Purpose:** Live status file. Check this before planning or drafting.

                ## Current Phase

                **Status:** CHAPTER 1 COMPLETE -> READY FOR CHAPTER 2 PLANNING
                **Last Updated:** 2026-04-09

                ## Locked Decisions

                - Arthur sponsors Ciri's intake

                ## Recommended Next Loadout

                For Chapter 2 planning:
                1. `02B_Character_Quick_Reference.md`
                2. `05_Current_Chapter_Notes.md`

                ## Next Action

                Open Chapter 2 from the Atlantis fallout position.
                """
            ).strip(),
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                > **Purpose:** Live scratchpad for the current writing session.

                ## CURRENT FOCUS

                **Arc:** Prime Earth Arrival / Darkseid Prelude
                **Chapter:** 1
                **Working Title:** Chill

                ## CDLC STATUS

                **Phase:** COMPLETE

                ## THREADS CARRIED FORWARD

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur's sponsorship of Ciri | ACTIVE | He has vouched for her intake |
                | Darkseid's redirected search | ACTIVE | Search pressure is building |

                ## NEXT START POINT

                - physician testing sphere
                """
            ).strip(),
        )
        write_file(project_root / "logs" / "brainstorms" / "handoff.md", "physician testing sphere")
        write_file(project_root / "logs" / "audits" / "audit.md", "Arthur sponsorship of Ciri remains the burden")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": [
                    {
                        "room": kwargs["room"],
                        "source_file": f"{kwargs['room']}.md",
                        "similarity": 0.88,
                        "text": f"{kwargs['query']} evidence from {kwargs['room']}",
                    }
                ],
            },
        )

        recap = build_writing_recap(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            mode="restart",
            sync="never",
            n_results=2,
        )

        where_we_are = recap["sections"]["Where We Are"]
        must_not_forget = recap["sections"]["Must Not Forget"]
        assert recap["sections"]["Suggested Next Loadout"] == [
            "02B_Character_Quick_Reference.md",
            "05_Current_Chapter_Notes.md",
        ]
        assert where_we_are
        assert must_not_forget
        assert set(where_we_are).isdisjoint(set(must_not_forget))
        assert all("Purpose:" not in item for item in where_we_are + must_not_forget)
        assert all("Last Updated:" not in item for item in where_we_are + must_not_forget)
    finally:
        cleanup_temp_dir(tmp_path)

def test_build_writing_session_startup_recommends_followup_and_can_write(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"

        write_file(
            project_root / "writing-sidecar.yaml",
            "brainstorms:\n  - logs/brainstorms\naudits:\n  - logs/audits\ndiscarded_paths: []\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            textwrap.dedent(
                """
                **Status:** CHAPTER 1 COMPLETE -> READY FOR CHAPTER 2 PLANNING

                ## Recommended Next Loadout

                For Chapter 2 planning:
                1. `02B_Character_Quick_Reference.md`
                2. `05_Current_Chapter_Notes.md`

                ## Next Action

                Open Chapter 2 from the Atlantis fallout position.
                """
            ).strip(),
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** COMPLETE
                **Chapter:** 1

                ## THREADS CARRIED FORWARD

                - Arthur's sponsorship of Ciri remains active.

                ## NEXT START POINT

                - physician testing sphere
                """
            ).strip(),
        )
        write_file(project_root / "logs" / "checkpoints" / "checkpoint.md", "startup checkpoint")
        write_file(project_root / "logs" / "brainstorms" / "handoff.md", "physician testing sphere")
        write_file(project_root / "logs" / "audits" / "audit.md", "Arthur sponsorship of Ciri")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": {
                    "checkpoints": [
                        {
                            "room": "checkpoints",
                            "source_file": "checkpoint.md",
                            "similarity": 0.94,
                            "text": "startup checkpoint keeps Atlantis pressure ahead of chatter",
                        }
                    ],
                    "brainstorms": [
                        {
                            "room": "brainstorms",
                            "source_file": "handoff.md",
                            "similarity": 0.9,
                            "text": "physician testing sphere",
                        }
                    ],
                    "audits": [
                        {
                            "room": "audits",
                            "source_file": "audit.md",
                            "similarity": 0.82,
                            "text": "Arthur sponsorship of Ciri remains the main burden",
                        }
                    ],
                    "discarded_paths": [],
                    "chat_process": [],
                    "research": [],
                    "archived_notes": [],
                }[kwargs["room"]],
            },
        )
        monkeypatch.setattr(
            "writing_sidecar.workflow._mine_exported_sidecar",
            lambda output_root, project, palace_path, runtime_root, refresh_palace=False: _ensure_dir(
                Path(palace_path)
            ),
        )

        preview = build_writing_session(
            vault_dir=str(project_root),
            task="startup",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            sync="never",
            n_results=2,
        )

        assert preview["task"] == "startup"
        assert preview["write_performed"] is False
        assert preview["operative_phase"] == "SCRIPTING"
        assert preview["suggested_loadout"] == [
            "02B_Character_Quick_Reference.md",
            "05_Current_Chapter_Notes.md",
        ]
        assert any("--task startup --write" in item for item in preview["recommended_actions"])
        assert any("--task scripting --write" in item for item in preview["recommended_actions"])
        assert any("--task scripting --write" in item for item in preview["recommended_commands"])

        written = build_writing_session(
            vault_dir=str(project_root),
            task="startup",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            sync="if-needed",
            write=True,
            n_results=2,
        )

        assert written["write_performed"] is True
        assert written["sync_performed"] is True
        assert any(path.endswith("_checkpoint.md") for path in written["paths_written"])
    finally:
        cleanup_temp_dir(tmp_path)

def test_build_writing_session_prose_uses_planning_history_and_continuity_watch(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(
            project_root / "_story_bible" / "01_Story_So_Far.md",
            "- Timeline: Atlantis intake happens before any League convergence.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            textwrap.dedent(
                """
                **Status:** PROSE PASS NEXT
                **Next Action:** Draft the Atlantis chamber scene without losing the sponsorship burden.
                """
            ).strip(),
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** COMPLETE
                **Chapter:** 2

                ## THREADS CARRIED FORWARD

                - Arthur's sponsorship of Ciri remains politically costly.
                - Keep continuity around the physician testing sphere.
                """
            ).strip(),
        )

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": [
                    {
                        "room": kwargs["room"],
                        "source_file": f"{kwargs['room']}.md",
                        "similarity": 0.88,
                        "text": f"{kwargs['query']} evidence from {kwargs['room']}",
                    }
                ],
            },
        )

        session = build_writing_session(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            task="prose",
            sync="never",
            n_results=2,
        )

        assert session["task"] == "prose"
        assert [item["mode"] for item in session["queries_run"]] == ["planning", "history"]
        assert session["suggested_loadout"] == [
            "_story_bible/00_AI_Writing_Rules.md",
            "_story_bible/02B_Character_Quick_Reference.md",
            "_story_bible/05_Current_Chapter_Notes.md",
        ]
        assert session["verification_scope"] == "chapter"
        assert session["continuity_state"] in {"clean", "warn", "error"}
        assert set(session["finding_counts"]) == {"error", "warn", "info"}
        assert session["recap_sections"]["Continuity Watch"]
        assert any("--task audit" in item for item in session["recommended_actions"])
    finally:
        cleanup_temp_dir(tmp_path)

@pytest.mark.parametrize(
    ("task", "expected_kinds"),
    [
        ("braindump", ["checkpoint"]),
        ("scripting", ["checkpoint"]),
        ("staging", ["checkpoint"]),
        ("planning", ["checkpoint"]),
        ("prose", ["checkpoint"]),
        ("audit", ["audit"]),
        ("handoff", ["handoff"]),
        ("closeout", ["closeout"]),
    ],
)
def test_build_writing_session_dispatches_expected_write_kinds(monkeypatch, task, expected_kinds):
    prepared = {
        "status": {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "output_root": "C:/vault/.sidecars/witcher_dc",
            "palace_path": "C:/vault/.palaces/witcher_dc",
            "runtime_root": "C:/vault/.mempalace-sidecar-runtime/witcher_dc",
            "state": "clean",
            "stale": False,
            "stale_reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
        },
        "sync_summary": None,
        "synced": False,
        "warnings": [],
    }
    doc_bundle = {
        "current_notes": {"exists": False, "path": "", "highlights": []},
        "current_chapter_notes": {"exists": False, "path": "", "highlights": []},
        "story_so_far": {"exists": False, "path": "", "highlights": []},
    }
    fake_context = {
        "project": "Witcher-DC",
        "project_root": "C:/vault/Witcher-DC",
        "vault_root": "C:/vault",
        "mode": task,
        "synced": False,
        "sync_summary": None,
        "state": "clean",
        "stale": False,
        "reasons": [],
        "last_synced_at": "2026-04-10T00:00:00+00:00",
        "phase": "PROSE",
        "current_chapter": "2",
        "current_arc": None,
        "suggested_loadout": ["doc.md"],
        "queries_run": [],
        "results": [],
        "warnings": [],
        "recent_artifacts": [],
        "doc_highlights": {},
        "source_priority": ["live_docs", "sidecar"],
    }
    fake_recap = {
        "project": "Witcher-DC",
        "project_root": "C:/vault/Witcher-DC",
        "vault_root": "C:/vault",
        "mode": "handoff",
        "synced": False,
        "sync_summary": None,
        "state": "clean",
        "stale": False,
        "reasons": [],
        "last_synced_at": "2026-04-10T00:00:00+00:00",
        "phase": "COMPLETE",
        "current_chapter": "2",
        "current_arc": None,
        "doc_sources": {},
        "sections": {"Current State": ["ready"]},
        "queries_run": [],
        "results": [],
        "warnings": [],
        "source_priority": ["live_docs", "sidecar"],
    }
    calls = []

    def fake_maintain(kind, sync, **kwargs):
        calls.append((kind, sync))
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "kind": kind,
            "mode": "write",
            "write_performed": True,
            "paths_written": [f"C:/tmp/{kind}.md"],
            "sync_performed": sync != "never",
            "sync_summary": {} if sync != "never" else None,
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "warnings": [],
            "source_inputs": [],
            "generated_sections": {kind: ["Summary"]},
            "artifacts": [],
        }

    monkeypatch.setattr("writing_sidecar.workflow.prepare_writing_sidecar", lambda **kwargs: prepared)
    monkeypatch.setattr("writing_sidecar.workflow._load_live_doc_bundle", lambda *args, **kwargs: doc_bundle)
    monkeypatch.setattr("writing_sidecar.workflow._build_context_payload", lambda *args, **kwargs: (doc_bundle, dict(fake_context)))
    monkeypatch.setattr("writing_sidecar.workflow._build_recap_payload", lambda *args, **kwargs: (doc_bundle, dict(fake_recap)))
    monkeypatch.setattr("writing_sidecar.workflow._derive_session_loadout", lambda *args, **kwargs: ["doc.md"])
    monkeypatch.setattr("writing_sidecar.workflow._build_session_recommended_actions", lambda **kwargs: ["next"])
    monkeypatch.setattr("writing_sidecar.workflow._collect_recent_artifacts", lambda *args, **kwargs: [])
    monkeypatch.setattr("writing_sidecar.workflow.maintain_writing_sidecar", fake_maintain)
    monkeypatch.setattr(
        "writing_sidecar.workflow._select_session_queries",
        lambda *args, **kwargs: [{"mode": "planning", "query": "q"}],
    )

    session = build_writing_session("C:/vault", project="Witcher-DC", task=task, write=True)

    assert [kind for kind, _ in calls] == expected_kinds
    assert session["write_performed"] is True

def test_build_writing_session_debug_only_writes_discarded_when_note_or_evidence_exists(monkeypatch):
    prepared = {
        "status": {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "output_root": "C:/vault/.sidecars/witcher_dc",
            "palace_path": "C:/vault/.palaces/witcher_dc",
            "runtime_root": "C:/vault/.mempalace-sidecar-runtime/witcher_dc",
            "state": "clean",
            "stale": False,
            "stale_reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
        },
        "sync_summary": None,
        "synced": False,
        "warnings": [],
    }
    doc_bundle = {
        "current_notes": {"exists": False, "path": "", "highlights": []},
        "current_chapter_notes": {"exists": False, "path": "", "highlights": []},
        "story_so_far": {"exists": False, "path": "", "highlights": []},
    }
    calls = []

    def fake_maintain(kind, sync, **kwargs):
        calls.append((kind, sync))
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "kind": kind,
            "mode": "write",
            "write_performed": True,
            "paths_written": [f"C:/tmp/{kind}.md"],
            "sync_performed": sync != "never",
            "sync_summary": {} if sync != "never" else None,
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "warnings": [],
            "source_inputs": [],
            "generated_sections": {kind: ["Summary"]},
            "artifacts": [],
        }

    monkeypatch.setattr("writing_sidecar.workflow.prepare_writing_sidecar", lambda **kwargs: prepared)
    monkeypatch.setattr("writing_sidecar.workflow._load_live_doc_bundle", lambda *args, **kwargs: doc_bundle)
    monkeypatch.setattr(
        "writing_sidecar.workflow._build_context_payload",
        lambda *args, **kwargs: (
            doc_bundle,
            {
                "project": "Witcher-DC",
                "project_root": "C:/vault/Witcher-DC",
                "vault_root": "C:/vault",
                "mode": "debug",
                "synced": False,
                "sync_summary": None,
                "state": "clean",
                "stale": False,
                "reasons": [],
                "last_synced_at": "2026-04-10T00:00:00+00:00",
                "phase": "DEBUG",
                "current_chapter": "2",
                "current_arc": None,
                "suggested_loadout": ["debug.md"],
                "queries_run": [{"mode": "audit", "query": "q"}],
                "results": [],
                "warnings": [],
                "recent_artifacts": [],
                "doc_highlights": {},
                "source_priority": ["live_docs", "sidecar"],
            },
        ),
    )
    monkeypatch.setattr("writing_sidecar.workflow._derive_session_loadout", lambda *args, **kwargs: ["debug.md"])
    monkeypatch.setattr("writing_sidecar.workflow._build_session_recommended_actions", lambda **kwargs: ["next"])
    monkeypatch.setattr("writing_sidecar.workflow._collect_recent_artifacts", lambda *args, **kwargs: [])
    monkeypatch.setattr("writing_sidecar.workflow.maintain_writing_sidecar", fake_maintain)
    monkeypatch.setattr(
        "writing_sidecar.workflow._select_session_queries",
        lambda *args, **kwargs: [{"mode": "audit", "query": "q"}],
    )

    build_writing_session("C:/vault", project="Witcher-DC", task="debug", write=True, sync="if-needed")
    assert calls == [("audit", "if-needed")]

    calls.clear()
    build_writing_session(
        "C:/vault",
        project="Witcher-DC",
        task="debug",
        write=True,
        sync="if-needed",
        notes=["Rejected the balanced braid."],
    )
    assert calls == [("audit", "never"), ("discarded", "if-needed")]

def test_build_writing_bundle_startup_preview_write_and_skip(monkeypatch):
    verify_calls = []
    recap_calls = []
    session_calls = []

    def fake_verify(**kwargs):
        verify_calls.append(kwargs)
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "scope": kwargs["scope"],
            "state": "warn",
            "verified_at": "2026-04-10T00:00:00+00:00",
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "findings": [{"severity": "warn", "title": "Checkpoint missing"}],
            "warnings": ["Checkpoint missing"],
            "recommended_actions": ["Create a checkpoint before continuing."],
            "query_packets": [],
            "source_snapshot": [],
            "cache_path": "C:/vault/.sidecars/witcher_dc/.writing-sidecar-verify.json",
            "sync_summary": None,
            "synced": False,
        }

    def fake_recap(**kwargs):
        recap_calls.append(kwargs)
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "mode": kwargs["mode"],
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "sections": {"Where We Are": ["Ready to re-enter Atlantis."]},
            "warnings": [],
            "synced": False,
            "sync_summary": None,
        }

    def fake_session(**kwargs):
        session_calls.append(kwargs)
        task = kwargs["task"]
        write = kwargs["write"]
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "task": task,
            "phase": "COMPLETE",
            "operative_phase": "SCRIPTING",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": [f"C:/vault/Witcher-DC/logs/checkpoints/{task}.md"],
            "recommended_actions": [
                f"Run `writing-sidecar session \"C:/vault/Witcher-DC\" --task {task} --write` when ready."
            ],
            "recommended_commands": [
                f"writing-sidecar session \"C:/vault/Witcher-DC\" --task {task} --write"
            ],
            "write_performed": write,
            "paths_written": [f"C:/vault/Witcher-DC/logs/checkpoints/{task}.md"] if write else [],
            "sync_performed": write and kwargs["sync"] != "never",
            "warnings": [],
            "queries_run": [],
            "results": [],
            "recap_sections": {},
            "verification_scope": "startup",
            "continuity_state": kwargs["verification_report"]["state"] if kwargs["verification_report"] else "unknown",
            "finding_counts": (
                kwargs["verification_report"]["finding_counts"]
                if kwargs["verification_report"]
                else {"error": 0, "warn": 0, "info": 0}
            ),
            "top_findings": kwargs["verification_report"]["findings"][:1] if kwargs["verification_report"] else [],
            "recommended_repairs": [],
            "synced": False,
            "sync_summary": None,
        }

    monkeypatch.setattr("writing_sidecar.workflow.verify_writing_sidecar", fake_verify)
    monkeypatch.setattr("writing_sidecar.workflow.build_writing_recap", fake_recap)
    monkeypatch.setattr("writing_sidecar.workflow.build_writing_session", fake_session)

    preview_report = build_writing_bundle("C:/vault", project="Witcher-DC", name="startup")
    assert preview_report["bundle"] == "startup"
    assert preview_report["continuity_state"] == "warn"
    assert [step["name"] for step in preview_report["steps"]] == [
        "verify-startup",
        "session-startup",
        "recap-restart",
        "write-startup",
    ]
    assert preview_report["steps"][-1]["status"] == "skipped"
    assert preview_report["recommended_commands"][0].startswith("writing-sidecar bundle ")
    assert '--project Witcher-DC --name startup --write' in preview_report["recommended_commands"][0]
    assert session_calls[0]["run_verification"] is False
    assert session_calls[0]["verification_report"]["state"] == "warn"

    verify_calls.clear()
    recap_calls.clear()
    session_calls.clear()
    skipped_report = build_writing_bundle(
        "C:/vault",
        project="Witcher-DC",
        name="startup",
        verify_mode="skip",
    )
    assert skipped_report["continuity_state"] == "unknown"
    assert skipped_report["steps"][0]["name"] == "verify-startup"
    assert skipped_report["steps"][0]["status"] == "skipped"
    assert verify_calls == []
    assert session_calls[0]["run_verification"] is False
    assert session_calls[0]["verification_report"] is None

    verify_calls.clear()
    recap_calls.clear()
    session_calls.clear()
    write_report = build_writing_bundle(
        "C:/vault",
        project="Witcher-DC",
        name="startup",
        write=True,
    )
    assert write_report["write_performed"] is True
    assert write_report["paths_written"] == ["C:/vault/Witcher-DC/logs/checkpoints/startup.md"]
    assert [call["task"] for call in session_calls] == ["startup", "startup"]
    assert [call["write"] for call in session_calls] == [False, True]
    assert session_calls[1]["sync"] == "if-needed"

def test_build_writing_bundle_audit_loop_writes_only_audit(monkeypatch):
    verify_calls = []
    session_calls = []

    def fake_verify(**kwargs):
        verify_calls.append(kwargs)
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "scope": kwargs["scope"],
            "state": "clean",
            "verified_at": "2026-04-10T00:00:00+00:00",
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "findings": [],
            "warnings": [],
            "recommended_actions": [],
            "query_packets": [],
            "source_snapshot": [],
            "cache_path": "C:/vault/.sidecars/witcher_dc/.writing-sidecar-verify.json",
            "sync_summary": None,
            "synced": False,
        }

    def fake_session(**kwargs):
        session_calls.append((kwargs["task"], kwargs["write"], kwargs["sync"]))
        task = kwargs["task"]
        write = kwargs["write"]
        artifact = f"C:/vault/Witcher-DC/logs/{'audits' if task == 'audit' else 'checkpoints'}/{task}.md"
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "task": task,
            "phase": "AUDIT",
            "operative_phase": "DEBUG" if task == "debug" else "AUDIT",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "doc_loadout": [f"{task}.md"],
            "file_targets": [f"C:/vault/Witcher-DC/{task}.md"],
            "artifact_targets": [artifact],
            "recommended_actions": [f"{task}-action"],
            "recommended_commands": [f"{task}-command"],
            "write_performed": write,
            "paths_written": [artifact] if write else [],
            "sync_performed": write and kwargs["sync"] != "never",
            "warnings": [],
            "queries_run": [],
            "results": [],
            "recap_sections": {},
            "verification_scope": "chapter",
            "continuity_state": "clean",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "top_findings": [],
            "recommended_repairs": [],
            "synced": False,
            "sync_summary": None,
        }

    monkeypatch.setattr("writing_sidecar.workflow.verify_writing_sidecar", fake_verify)
    monkeypatch.setattr("writing_sidecar.workflow.build_writing_session", fake_session)

    report = build_writing_bundle(
        "C:/vault",
        project="Witcher-DC",
        name="audit-loop",
        write=True,
        notes=["Balanced braid rejected."],
    )

    assert verify_calls[0]["scope"] == "chapter"
    assert [step["name"] for step in report["steps"]] == [
        "verify-chapter",
        "session-audit",
        "session-debug",
        "write-audit-loop",
    ]
    assert session_calls == [
        ("audit", False, "never"),
        ("debug", False, "never"),
        ("audit", True, "if-needed"),
    ]
    assert report["paths_written"] == ["C:/vault/Witcher-DC/logs/audits/audit.md"]
    assert report["write_performed"] is True
    assert report["artifact_targets"] == ["C:/vault/Witcher-DC/logs/audits/audit.md"]

def test_build_writing_routine_start_work_preview_and_write(monkeypatch):
    bundle_calls = []
    session_calls = []

    def fake_bundle(**kwargs):
        bundle_calls.append(kwargs)
        write = kwargs["write"]
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "bundle": kwargs["name"],
            "verify_mode": kwargs["verify_mode"],
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [{"severity": "warn", "title": "Checkpoint missing"}],
            "doc_loadout": ["_story_bible/05_Current_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Notes.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/checkpoints/startup.md"],
            "recap_sections": {"Where We Are": ["Atlantis restart is ready."]},
            "steps": [
                {
                    "name": "verify-startup",
                    "kind": "verify",
                    "command": "verify",
                    "status": "completed",
                    "write_capable": False,
                    "write_requested": False,
                    "summary": "warn",
                }
            ],
            "recommended_actions": ["bundle-action"],
            "recommended_commands": ["bundle-command"],
            "write_performed": write,
            "paths_written": ["C:/vault/Witcher-DC/logs/checkpoints/startup.md"] if write else [],
            "sync_performed": write,
            "warnings": ["Checkpoint missing"],
        }

    def fake_session(**kwargs):
        session_calls.append(kwargs)
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "task": kwargs["task"],
            "phase": "COMPLETE",
            "operative_phase": "SCRIPTING",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/checkpoints/scripting.md"],
            "recommended_actions": ["session-action"],
            "recommended_commands": ["session-command"],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
            "queries_run": [],
            "results": [],
            "recap_sections": {"Continuity Watch": ["Keep Arthur's sponsorship live."]},
            "verification_scope": "chapter",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [{"severity": "warn", "title": "Checkpoint missing"}],
            "recommended_repairs": [],
        }

    monkeypatch.setattr("writing_sidecar.workflow.build_writing_bundle", fake_bundle)
    monkeypatch.setattr("writing_sidecar.workflow.build_writing_session", fake_session)

    preview = build_writing_routine("C:/vault", project="Witcher-DC", name="start-work")
    assert preview["routine"] == "start-work"
    assert preview["steps"][-1]["name"] == "session-scripting"
    assert preview["doc_loadout"] == [
        "_story_bible/05_Current_Chapter_Notes.md",
        "_story_bible/05_Current_Notes.md",
    ]
    assert preview["write_performed"] is False
    assert bundle_calls[0]["name"] == "startup"
    assert bundle_calls[0]["write"] is False
    assert session_calls[0]["task"] == "scripting"
    assert session_calls[0]["sync"] == "never"
    assert session_calls[0]["run_verification"] is False
    assert session_calls[0]["verification_report"]["state"] == "warn"

    bundle_calls.clear()
    session_calls.clear()
    written = build_writing_routine("C:/vault", project="Witcher-DC", name="start-work", write=True)
    assert written["write_performed"] is True
    assert written["paths_written"] == ["C:/vault/Witcher-DC/logs/checkpoints/startup.md"]
    assert bundle_calls[0]["write"] is True
    assert session_calls[0]["write"] is False

def test_build_writing_routine_repair_cycle_writes_only_audit(monkeypatch):
    bundle_calls = []
    session_calls = []

    def fake_bundle(**kwargs):
        bundle_calls.append(kwargs)
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "bundle": kwargs["name"],
            "verify_mode": kwargs["verify_mode"],
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "DEBUG",
            "continuity_state": "clean",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "top_findings": [],
            "doc_loadout": ["audit.md"],
            "file_targets": ["C:/vault/Witcher-DC/audit.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/audits/audit.md"],
            "recap_sections": {},
            "steps": [
                {
                    "name": "verify-chapter",
                    "kind": "verify",
                    "command": "verify",
                    "status": "completed",
                    "write_capable": False,
                    "write_requested": False,
                    "summary": "clean",
                }
            ],
            "recommended_actions": ["bundle-action"],
            "recommended_commands": ["bundle-command"],
            "write_performed": kwargs["write"],
            "paths_written": ["C:/vault/Witcher-DC/logs/audits/audit.md"] if kwargs["write"] else [],
            "sync_performed": kwargs["write"],
            "warnings": [],
        }

    def fake_session(**kwargs):
        session_calls.append(kwargs)
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "task": "debug",
            "phase": "DEBUG",
            "operative_phase": "DEBUG",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "doc_loadout": ["debug.md"],
            "file_targets": ["C:/vault/Witcher-DC/debug.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/discarded_paths/debug.md"],
            "recommended_actions": ["session-action"],
            "recommended_commands": ["session-command"],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
            "queries_run": [],
            "results": [],
            "recap_sections": {},
            "verification_scope": "chapter",
            "continuity_state": "clean",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "top_findings": [],
            "recommended_repairs": [],
        }

    monkeypatch.setattr("writing_sidecar.workflow.build_writing_bundle", fake_bundle)
    monkeypatch.setattr("writing_sidecar.workflow.build_writing_session", fake_session)

    report = build_writing_routine(
        "C:/vault",
        project="Witcher-DC",
        name="repair-cycle",
        write=True,
    )

    assert bundle_calls[0]["name"] == "audit-loop"
    assert bundle_calls[0]["write"] is True
    assert session_calls[0]["task"] == "debug"
    assert session_calls[0]["write"] is False
    assert report["artifact_targets"] == [
        "C:/vault/Witcher-DC/logs/audits/audit.md",
        "C:/vault/Witcher-DC/logs/discarded_paths/debug.md",
    ]
    assert report["paths_written"] == ["C:/vault/Witcher-DC/logs/audits/audit.md"]
    assert report["write_performed"] is True

def test_build_writing_automation_recommended_resolves_to_explicit_routine(monkeypatch):
    status_payload = {
        "project": "Witcher-DC",
        "project_root": "C:/vault/Witcher-DC",
        "vault_root": "C:/vault",
        "output_root": "C:/vault/.sidecars/witcher_dc",
        "state": "clean",
        "stale": False,
    }
    routine_calls = []

    monkeypatch.setattr("writing_sidecar.workflow.get_writing_sidecar_status", lambda **kwargs: dict(status_payload))
    monkeypatch.setattr(
        "writing_sidecar.workflow._load_live_doc_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr("writing_sidecar.workflow._extract_phase", lambda *args, **kwargs: "COMPLETE")
    monkeypatch.setattr(
        "writing_sidecar.workflow._derive_operative_phase",
        lambda *args, **kwargs: "SCRIPTING",
    )
    monkeypatch.setattr(
        "writing_sidecar.workflow._extract_field",
        lambda _bundle, field_name: {
            "status": "READY FOR SCRIPTING",
            "next_action": "Open Chapter 2 from Atlantis.",
        }.get(field_name),
    )
    monkeypatch.setattr(
        "writing_sidecar.workflow._cached_verification_summary",
        lambda *args, **kwargs: {
            "continuity_state": "warn",
            "last_verified_at": "2026-04-10T00:00:00+00:00",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "verification_stale": False,
        },
    )
    monkeypatch.setattr(
        "writing_sidecar.workflow._collect_workflow_checks",
        lambda *args, **kwargs: [{"name": "checkpoint_template", "status": "ok"}],
    )

    def fake_routine(**kwargs):
        routine_calls.append(kwargs)
        return {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "routine": kwargs["name"],
            "verify_mode": kwargs["verify_mode"],
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [
                {
                    "severity": "warn",
                    "title": "Checkpoint missing",
                    "summary": "There is no fresh startup checkpoint yet.",
                }
            ],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/checkpoints/2026-04-10_startup_checkpoint.md"],
            "recap_sections": {},
            "steps": [],
            "recommended_actions": ["Open the chapter notes first."],
            "recommended_commands": ['writing-sidecar session "C:/vault/Witcher-DC" --task prose --write'],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": ["warning"],
        }

    monkeypatch.setattr("writing_sidecar.workflow.build_writing_routine", fake_routine)

    report = build_writing_automation(
        "C:/vault",
        project="Witcher-DC",
        name="recommended",
        verify_mode="strict",
        sync="never",
    )

    assert report["name"] == "recommended"
    assert report["routine"] == "move-to-prose"
    assert routine_calls[0]["name"] == "move-to-prose"
    assert report["entry_command"] == 'writing-sidecar routine "C:/vault/Witcher-DC" --name move-to-prose --verify strict --sync never'
    assert report["write_variant_command"] == 'writing-sidecar routine "C:/vault/Witcher-DC" --name move-to-prose --verify strict --sync never --write'
    assert report["recommended_commands"][0] == report["entry_command"]
    assert report["recommended_commands"][1] == report["write_variant_command"]
    assert "Use this exact command first" in report["prompt"]
    assert "Live docs outrank sidecar and checkpoint evidence" in report["prompt"]

def test_build_writing_automation_session_end_defaults_to_write(monkeypatch):
    monkeypatch.setattr(
        "writing_sidecar.workflow.build_writing_routine",
        lambda **kwargs: {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "routine": kwargs["name"],
            "verify_mode": kwargs["verify_mode"],
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "clean",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "top_findings": [],
            "doc_loadout": [],
            "file_targets": [],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/brainstorms/2026-04-10_handoff.md"],
            "recap_sections": {},
            "steps": [],
            "recommended_actions": [],
            "recommended_commands": [],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        },
    )

    report = build_writing_automation("C:/vault", project="Witcher-DC", name="session-end")

    assert report["routine"] == "session-end"
    assert report["entry_command"].endswith("--name session-end --verify advisory --write")
    assert report["write_variant_command"] is None

def test_build_writing_automation_suggested_create_uses_default_schedule_profile(monkeypatch):
    monkeypatch.setattr(
        "writing_sidecar.workflow.build_writing_routine",
        lambda **kwargs: {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "routine": kwargs["name"],
            "verify_mode": kwargs["verify_mode"],
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [
                {
                    "severity": "warn",
                    "title": "Checkpoint missing",
                    "summary": "There is no fresh startup checkpoint yet.",
                }
            ],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/checkpoints/2026-04-10_startup_checkpoint.md"],
            "recap_sections": {},
            "steps": [],
            "recommended_actions": ["Open the chapter notes first."],
            "recommended_commands": ['writing-sidecar session "C:/vault/Witcher-DC" --task prose --write'],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        },
    )

    report = build_writing_automation(
        "C:/vault",
        project="Witcher-DC",
        name="move-to-prose",
        mode="suggested-create",
    )

    assert report["routine"] == "move-to-prose"
    assert report["schedule_profile"] == "weekday-morning"
    assert report["automation_name"] == "Witcher-DC Move To Prose"
    assert report["automation_status"] == "ACTIVE"
    assert report["automation_rrule"] == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9;BYMINUTE=0"
    assert report["automation_cwds"] == ["C:/vault/Witcher-DC"]
    assert "Run this exact command first" in report["automation_prompt"]
    assert "Do not mutate canon or current-doc files" in report["automation_prompt"]

def test_build_writing_automation_suggested_create_honors_schedule_override(monkeypatch):
    monkeypatch.setattr(
        "writing_sidecar.workflow.build_writing_routine",
        lambda **kwargs: {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "routine": kwargs["name"],
            "verify_mode": kwargs["verify_mode"],
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "AUDIT",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [],
            "doc_loadout": [],
            "file_targets": [],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/audits/audit.md"],
            "recap_sections": {},
            "steps": [],
            "recommended_actions": [],
            "recommended_commands": [],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        },
    )

    report = build_writing_automation(
        "C:/vault",
        project="Witcher-DC",
        name="repair-cycle",
        mode="suggested-create",
        schedule_profile="weekly-review",
    )

    assert report["schedule_profile"] == "weekly-review"
    assert report["automation_rrule"] == "FREQ=WEEKLY;BYDAY=SA;BYHOUR=10;BYMINUTE=0"
    assert report["entry_command"] == 'writing-sidecar routine "C:/vault/Witcher-DC" --name repair-cycle --verify advisory'

def test_maintain_checkpoint_preview_and_write(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(project_root / "Chapter 1.txt", "Active chapter prose")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR PLANNING\n**Next Action:** Build the next Atlantis checkpoint.\n")
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            "**Phase:** COMPLETE\n**Chapter:** 1\n## NEXT START POINT\n- physician testing sphere\n",
        )

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": [
                    {
                        "room": kwargs["room"],
                        "source_file": f"{kwargs['room']}.md",
                        "similarity": 0.9,
                        "text": f"{kwargs['query']} evidence from {kwargs['room']}",
                    }
                ],
            },
        )

        preview = maintain_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            kind="checkpoint",
            sync="never",
            notes=["Lock the Atlantis planning spine."],
            write=False,
        )
        assert preview["write_performed"] is False
        assert preview["artifacts"][0]["kind"] == "checkpoint"
        assert "Session State" in preview["artifacts"][0]["sections"]
        assert not Path(preview["artifacts"][0]["path"]).exists()

        written = maintain_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            kind="checkpoint",
            sync="never",
            notes=["Lock the Atlantis planning spine."],
            write=True,
        )
        assert written["write_performed"] is True
        assert len(written["paths_written"]) == 1
        checkpoint_path = Path(written["paths_written"][0])
        assert checkpoint_path.exists()
        assert "Session Checkpoint" in checkpoint_path.read_text(encoding="utf-8")
    finally:
        cleanup_temp_dir(tmp_path)

def test_maintain_discarded_requires_note_or_existing_evidence(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(project_root / "Chapter 1.txt", "Active chapter prose")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR PLANNING\n")
        write_file(project_root / "_story_bible" / "05_Current_Chapter_Notes.md", "**Phase:** COMPLETE\n**Chapter:** 1\n")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {"query": kwargs["query"], "filters": {}, "results": []},
        )

        with pytest.raises(ValueError, match="Discarded-path maintenance needs"):
            maintain_writing_sidecar(
                vault_dir=str(vault_root),
                project="Witcher-DC",
                out_dir=str(output_root),
                palace_path=str(palace_root),
                kind="discarded",
                sync="never",
                write=False,
            )
    finally:
        cleanup_temp_dir(tmp_path)

def test_maintain_closeout_writes_multiple_artifacts_and_syncs(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"

        write_file(
            project_root / "writing-sidecar.yaml",
            "brainstorms:\n  - logs/brainstorms\naudits:\n  - logs/audits\ndiscarded_paths:\n  - logs/discarded_paths\n",
        )
        write_file(project_root / "Chapter 1.txt", "Active chapter prose")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** CHAPTER 1 COMPLETE -> READY FOR CHAPTER 2 PLANNING\n**Next Action:** Build the Chapter 2 handoff.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** COMPLETE
                **Chapter:** 1

                ## THREADS CARRIED FORWARD

                - Arthur sponsorship stays active.

                ## NEXT START POINT

                - physician testing sphere
                """
            ).strip(),
        )
        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": [
                    {
                        "room": kwargs["room"],
                        "source_file": f"{kwargs['room']}.md",
                        "similarity": 0.93,
                        "text": f"{kwargs['query']} evidence from {kwargs['room']}",
                    }
                ],
            },
        )
        monkeypatch.setattr(
            "writing_sidecar.workflow._mine_exported_sidecar",
            lambda output_root, project, palace_path, runtime_root, refresh_palace=False: _ensure_dir(
                Path(palace_path)
            ),
        )

        report = maintain_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            kind="closeout",
            sync="if-needed",
            notes=["Rejected the balanced braid version."],
            write=True,
        )

        written_names = {Path(path).name for path in report["paths_written"]}
        assert report["write_performed"] is True
        assert report["sync_performed"] is True
        assert any(name.endswith("_checkpoint.md") for name in written_names)
        assert any(name.endswith("_closeout_audit.md") for name in written_names)
        assert any(name.endswith("_handoff.md") for name in written_names)
        assert any(name.endswith("_discarded.md") for name in written_names)
        status = get_writing_sidecar_status(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        assert status["stale"] is False
        assert status["room_counts"]["checkpoints"] >= 1
    finally:
        cleanup_temp_dir(tmp_path)

def test_doctor_marks_missing_agents_as_warn_but_keeps_assistant_ready_true():
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "_story_bible" / "05_Current_Notes.md", "**Status:** READY FOR SCRIPTING\n")
        write_file(project_root / "_story_bible" / "05_Current_Chapter_Notes.md", "**Phase:** SCRIPTING\n")

        report = doctor_writing_sidecar(vault_dir=str(vault_root), project="Witcher-DC")

        agents_check = next(item for item in report["workflow_checks"] if item["name"] == "agents_gateway")
        assert agents_check["status"] == "warn"
        assert report["assistant_ready"] is True
        assert report["recommended_entrypoint"] == "writing-sidecar automate"
        assert report["recommended_routine"] in {"move-to-prose", "start-work"}
        assert "writing-sidecar automate" in report["recommended_automate_command"]
        assert " --mode suggested-create" in report["recommended_automation_command"]
    finally:
        cleanup_temp_dir(tmp_path)

def test_build_writing_session_scripting_and_staging_produce_distinct_packets(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** READY FOR CHAPTER 2 PLANNING\n**Next Action:** Lock the scene wireframe before prose.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** SCRIPTING
                **Chapter:** 2

                ## Script Layer

                - Arthur and Mera define the first political terms.

                ## Staging Layer

                - Atmosphere: sterile Atlantis pressure.
                - Internal Pressure: Arthur is carrying sponsorship burden.
                """
            ).strip(),
        )
        write_file(project_root / "logs" / "brainstorms" / "handoff.md", "Arthur and Mera define protection terms.")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {"query": kwargs["query"], "filters": {}, "results": []},
        )

        scripting = build_writing_session(
            vault_dir=str(project_root),
            task="scripting",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            sync="never",
            n_results=2,
        )
        staging = build_writing_session(
            vault_dir=str(project_root),
            task="staging",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            sync="never",
            n_results=2,
        )

        assert scripting["suggested_loadout"] != staging["suggested_loadout"]
        assert scripting["phase_guardrails"] != staging["phase_guardrails"]
        assert scripting["queries_run"][0]["query"] != staging["queries_run"][0]["query"]
        assert staging["queries_run"][0]["query"] != "COMPLETE"
        assert any("wireframe" in item.lower() or "sequence" in item.lower() for item in scripting["phase_guardrails"])
        assert any("atmosphere" in item.lower() or "internal pressure" in item.lower() for item in staging["phase_guardrails"])
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_writing_corpus_skips_oversized_rollouts(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        codex_home = tmp_path / ".codex"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        build_codex_rollout(
            codex_home / "sessions" / "2026" / "04" / "17" / "oversized.jsonl",
            cwd=str(project_root),
            user_text="Arthur sponsorship " + ("x" * 512),
            assistant_text="Atlantis intake",
        )

        monkeypatch.setattr("writing_sidecar.workflow.ROLLOUT_SCAN_MAX_BYTES", 128)

        summary = export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            codex_home=str(codex_home),
        )

        manifest = json.loads((output_root / STATE_FILENAME).read_text(encoding="utf-8"))
        assert summary["rooms"]["chat_process"] == 0
        assert manifest["room_counts"]["chat_process"] == 0
        assert all(entry["source_kind"] != "codex_rollout" for entry in manifest["tracked_inputs"])
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_writing_corpus_records_mine_backend_failures(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        def broken_mine(**kwargs):
            raise RuntimeError("Error loading hnsw index")

        monkeypatch.setattr("writing_sidecar.workflow.mine", broken_mine)

        summary = export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            mine_after_export=True,
        )

        assert summary["mine_skipped"] == "backend_error"
        assert "mine backend failure" in summary["mine_warning"]
        assert "Error loading hnsw index" in summary["mine_warning"]
        assert (output_root / STATE_FILENAME).exists()
    finally:
        cleanup_temp_dir(tmp_path)


def test_verify_writing_sidecar_survives_search_backend_failures(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** CHAPTER 3 DRAFTED\n**Next Action:** Audit the breach beats.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            "**Phase:** AUDIT\n**Chapter:** 3\n",
        )
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        _ensure_dir(palace_root)

        def broken_search(**kwargs):
            raise MemoryError("bad allocation")

        monkeypatch.setattr("writing_sidecar.workflow.search_memories", broken_search)

        report = verify_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            scope="chapter",
            sync="never",
        )

        assert report["scope"] == "chapter"
        assert report["query_packets"] == []
        assert any("search backend failure" in warning for warning in report["warnings"])
    finally:
        cleanup_temp_dir(tmp_path)


def test_build_writing_automation_survives_search_backend_failures(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** CHAPTER 3 STABLE -> READY FOR CHAPTER 4\n**Next Action:** Continue the Darkseid prelude.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            "**Phase:** SCRIPTING\n**Chapter:** 4\n",
        )
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        _ensure_dir(palace_root)

        def broken_search(**kwargs):
            raise RuntimeError("vector backend unavailable")

        monkeypatch.setattr("writing_sidecar.workflow.search_memories", broken_search)

        report = build_writing_automation(
            str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            name="recommended",
            verify_mode="skip",
            sync="never",
        )

        assert report["name"] == "recommended"
        assert report["routine"]
        assert any("search backend failure" in warning for warning in report["warnings"])
    finally:
        cleanup_temp_dir(tmp_path)


def test_build_writing_automation_skips_sidecar_queries_when_health_marks_backend_too_slow(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** CHAPTER 3 STABLE -> READY FOR CHAPTER 4\n**Next Action:** Continue the Darkseid prelude.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            "**Phase:** SCRIPTING\n**Chapter:** 4\n",
        )
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        _ensure_dir(palace_root)

        monkeypatch.setattr(
            "writing_sidecar.workflow._cached_health_summary",
            lambda *args, **kwargs: {
                "health_metrics": {
                    "command_families": {
                        "query": {"sample_count": 3, "median_ms": 32000, "p95_ms": 51000}
                    }
                }
            },
        )

        def should_not_run(**kwargs):
            raise AssertionError("search_memories should not run when the circuit breaker is active")

        monkeypatch.setattr("writing_sidecar.workflow.search_memories", should_not_run)

        report = build_writing_automation(
            str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            name="recommended",
            verify_mode="skip",
            sync="never",
        )

        assert any("query backend is currently too slow" in warning for warning in report["warnings"])
    finally:
        cleanup_temp_dir(tmp_path)


def test_export_writing_corpus_refresh_palace_resets_health_history(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = tmp_path / "sidecar"
        palace_root = tmp_path / "palace"
        runtime_root = tmp_path / "runtime"

        write_file(project_root / "writing-sidecar.yaml", "brainstorms: []\naudits: []\ndiscarded_paths: []\n")
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Apokolips research")
        write_file(output_root / "health" / "latest.json", '{"health_state":"review"}')
        write_file(output_root / "health" / "history.jsonl", '{"timestamp":"2026-04-16T00:00:00+00:00"}\n')

        monkeypatch.setattr(
            "writing_sidecar.workflow._mine_exported_sidecar",
            lambda output_root, project, palace_path, runtime_root, refresh_palace=False: None,
        )

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            mine_after_export=True,
            refresh_palace=True,
        )

        assert not (output_root / "health" / "latest.json").exists()
        assert not (output_root / "health" / "history.jsonl").exists()
    finally:
        cleanup_temp_dir(tmp_path)


def test_search_writing_sidecar_fast_path_works_without_search_memories(monkeypatch):
    import chromadb

    class FakeCollection:
        def query(self, **kwargs):
            return {
                "documents": [[
                    "Arthur sponsorship and Atlantis intake.",
                    "Checkpoint mentions Atlantis intake.",
                ]],
                "metadatas": [[
                    {"wing": "witcher_dc_writing_sidecar", "room": "brainstorms", "source_file": "handoff.md"},
                    {"wing": "witcher_dc_writing_sidecar", "room": "checkpoints", "source_file": "checkpoint.md"},
                ]],
                "distances": [[0.1, 0.2]],
            }

    class FakeClient:
        def __init__(self, path):
            self.path = path

        def get_collection(self, name):
            return FakeCollection()

    monkeypatch.setattr(chromadb, "PersistentClient", FakeClient)
    monkeypatch.setattr(
        "writing_sidecar.workflow.search_memories",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("fallback search should not run")),
    )

    result = search_writing_sidecar(
        query="Atlantis intake",
        palace_path="C:/fake-palace",
        wing="witcher_dc_writing_sidecar",
        mode="planning",
        n_results=2,
    )

    assert result["results"]
    assert [hit["room"] for hit in result["results"]] == ["checkpoints", "brainstorms"]

