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

def test_cli_json_output_for_status_context_projects_doctor_session_verify_and_automate(monkeypatch, capsys):
    import writing_sidecar.cli as cli

    tmp_path = make_temp_dir()
    try:
        status_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "output_root": "C:/vault/.sidecars/witcher_dc",
            "config_path": "C:/vault/Witcher-DC/writing-sidecar.yaml",
            "manifest_path": "C:/vault/.sidecars/witcher_dc/.writing-sidecar-state.json",
            "palace_path": "C:/vault/.palaces/witcher_dc",
            "runtime_root": "C:/vault/.mempalace-sidecar-runtime/witcher_dc",
            "room_counts": {"brainstorms": 1},
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "built": True,
            "stale": False,
            "state": "clean",
            "stale_reasons": [],
        }
        context_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "mode": "startup",
            "synced": False,
            "sync_summary": None,
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "phase": "STAGING",
            "operative_phase": "STAGING",
            "current_chapter": "Under Protection",
            "current_arc": None,
            "suggested_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "queries_run": [],
            "results": [],
            "warnings": [],
            "recent_artifacts": [],
            "doc_highlights": {},
            "source_priority": ["live_docs", "sidecar"],
        }
        doctor_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "output_root": "C:/vault/.sidecars/witcher_dc",
            "palace_path": "C:/vault/.palaces/witcher_dc",
            "runtime_root": "C:/vault/.mempalace-sidecar-runtime/witcher_dc",
            "codex_home": "C:/Users/test/.codex",
            "config_path": None,
            "mempalace_version": "3.1.0",
            "supported_spec": SUPPORTED_MEMPALACE_SPEC,
            "checks": [],
            "workflow_checks": [],
            "assistant_ready": True,
            "recommended_entrypoint": "writing-sidecar automate",
            "recommended_routine": "move-to-prose",
            "recommended_automate_command": 'writing-sidecar automate "C:/vault/Witcher-DC" --name move-to-prose',
            "recommended_automation_command": 'writing-sidecar automate "C:/vault/Witcher-DC" --name move-to-prose --mode suggested-create',
            "recommended_schedule_profile": "weekday-morning",
            "continuity_state": "warn",
            "last_verified_at": "2026-04-10T00:00:00+00:00",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "verification_stale": False,
            "ok": True,
        }
        projects_payload = {
            "vault_root": "C:/vault",
            "count": 1,
            "projects": [
                {
                    "project": "Witcher-DC",
                    "project_root": "C:/vault/Witcher-DC",
                    "config_path": "C:/vault/Witcher-DC/writing-sidecar.yaml",
                    "state": "clean",
                    "stale": False,
                    "last_synced_at": "2026-04-10T00:00:00+00:00",
                    "last_checkpoint_at": "2026-04-10T00:00:00+00:00",
                     "operative_phase": "SCRIPTING",
                     "next_action": "Open Chapter 2 from Atlantis.",
                     "assistant_ready": True,
                     "recommended_entrypoint": "writing-sidecar automate",
                     "recommended_routine": "move-to-prose",
                     "recommended_automate_command": 'writing-sidecar automate "C:/vault/Witcher-DC" --name move-to-prose',
                     "recommended_automation_command": 'writing-sidecar automate "C:/vault/Witcher-DC" --name move-to-prose --mode suggested-create',
                     "recommended_schedule_profile": "weekday-morning",
                     "continuity_state": "warn",
                     "last_verified_at": "2026-04-10T00:00:00+00:00",
                     "finding_counts": {"error": 0, "warn": 1, "info": 0},
                    "verification_stale": False,
                    "room_counts": {"brainstorms": 1},
                    "reasons": [],
                }
            ],
        }
        verify_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "scope": "chapter",
            "state": "warn",
            "verified_at": "2026-04-10T00:00:00+00:00",
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "findings": [],
            "warnings": [],
            "recommended_actions": [],
            "query_packets": [],
            "source_snapshot": [],
            "cache_path": "C:/vault/.sidecars/witcher_dc/.writing-sidecar-verify.json",
            "sync_summary": None,
            "synced": False,
        }
        session_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "task": "startup",
            "phase": "COMPLETE",
            "operative_phase": "SCRIPTING",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "suggested_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "continuity_watch": ["Arthur sponsorship stays active."],
            "phase_guardrails": ["Keep live docs canonical."],
            "done_criteria": ["The next real task is explicit."],
            "recommended_commands": ["writing-sidecar session \"C:/vault/Witcher-DC\" --task scripting --write"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/checkpoints/2026-04-10_chapter-1_session_checkpoint.md"],
            "recommended_actions": ["next"],
            "write_performed": False,
            "sync_performed": False,
            "queries_run": [],
            "results": [],
            "recap_sections": {},
            "warnings": [],
            "verification_scope": "startup",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [],
            "recommended_repairs": [],
        }
        bundle_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "bundle": "startup",
            "verify_mode": "advisory",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/checkpoints/2026-04-10_startup_checkpoint.md"],
            "recap_sections": {"Where We Are": ["ready"]},
            "steps": [
                {
                    "name": "verify-startup",
                    "kind": "verify",
                    "command": "writing-sidecar verify C:/vault --project Witcher-DC --scope startup",
                    "status": "completed",
                    "write_capable": False,
                    "write_requested": False,
                    "summary": "Continuity is WARN",
                }
            ],
            "recommended_actions": ["Open the current chapter notes."],
            "recommended_commands": ["writing-sidecar bundle C:/vault --project Witcher-DC --name startup --write"],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        }
        routine_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "routine": "start-work",
            "verify_mode": "advisory",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/checkpoints/2026-04-10_startup_checkpoint.md"],
            "recap_sections": {"Where We Are": ["ready"]},
            "steps": [],
            "recommended_actions": ["Open the current chapter notes."],
            "recommended_commands": ["writing-sidecar routine C:/vault --project Witcher-DC --name start-work --write"],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        }
        automate_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "target": "codex",
            "name": "recommended",
            "routine": "move-to-prose",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "warn",
            "finding_counts": {"error": 0, "warn": 1, "info": 0},
            "top_findings": [],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["C:/vault/Witcher-DC/logs/checkpoints/2026-04-10_startup_checkpoint.md"],
            "entry_command": 'writing-sidecar routine "C:/vault/Witcher-DC" --name move-to-prose --verify advisory',
            "write_variant_command": 'writing-sidecar routine "C:/vault/Witcher-DC" --name move-to-prose --verify advisory --write',
            "prompt": "prompt",
            "expected_outputs": ["output"],
            "recommended_actions": ["Open the current chapter notes."],
            "recommended_commands": ['writing-sidecar routine "C:/vault/Witcher-DC" --name move-to-prose --verify advisory'],
            "warnings": [],
        }
        suggested_automate_payload = {
            **automate_payload,
            "automation_name": "Witcher-DC Move To Prose",
            "automation_prompt": "automation-prompt",
            "automation_rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9;BYMINUTE=0",
            "automation_cwds": ["C:/vault/Witcher-DC"],
            "automation_status": "ACTIVE",
            "schedule_profile": "weekday-morning",
        }

        monkeypatch.setattr(cli, "get_writing_sidecar_status", lambda **kwargs: status_payload)
        monkeypatch.setattr(cli, "build_writing_context", lambda **kwargs: context_payload)
        monkeypatch.setattr(cli, "doctor_writing_sidecar", lambda **kwargs: doctor_payload)
        monkeypatch.setattr(cli, "list_writing_projects", lambda *args, **kwargs: projects_payload)
        monkeypatch.setattr(cli, "verify_writing_sidecar", lambda **kwargs: verify_payload)
        monkeypatch.setattr(cli, "build_writing_session", lambda **kwargs: session_payload)
        monkeypatch.setattr(cli, "build_writing_bundle", lambda **kwargs: bundle_payload)
        monkeypatch.setattr(cli, "build_writing_routine", lambda **kwargs: routine_payload)
        monkeypatch.setattr(
            cli,
            "build_writing_automation",
            lambda **kwargs: suggested_automate_payload if kwargs.get("mode") == "suggested-create" else automate_payload,
        )

        for argv, key in (
            (["writing-sidecar", "status", str(tmp_path), "--project", "Witcher-DC", "--format", "json"], "state"),
            (["writing-sidecar", "context", str(tmp_path), "--project", "Witcher-DC", "--format", "json"], "mode"),
            (["writing-sidecar", "doctor", str(tmp_path), "--project", "Witcher-DC", "--format", "json"], "ok"),
            (["writing-sidecar", "projects", str(tmp_path), "--format", "json"], "count"),
            (["writing-sidecar", "verify", str(tmp_path), "--project", "Witcher-DC", "--format", "json"], "scope"),
            (["writing-sidecar", "session", str(tmp_path), "--project", "Witcher-DC", "--format", "json"], "task"),
            (["writing-sidecar", "bundle", str(tmp_path), "--project", "Witcher-DC", "--format", "json"], "bundle"),
            (["writing-sidecar", "routine", str(tmp_path), "--project", "Witcher-DC", "--format", "json"], "routine"),
            (["writing-sidecar", "automate", str(tmp_path), "--project", "Witcher-DC", "--format", "json"], "prompt"),
        ):
            monkeypatch.setattr(sys, "argv", argv)
            cli.main(sys.argv[1:])
            parsed = json.loads(capsys.readouterr().out)
            assert key in parsed

        monkeypatch.setattr(
            sys,
            "argv",
            ["writing-sidecar", "automate", str(tmp_path), "--project", "Witcher-DC", "--mode", "suggested-create", "--format", "json"],
        )
        cli.main(sys.argv[1:])
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["automation_name"] == "Witcher-DC Move To Prose"
    finally:
        cleanup_temp_dir(tmp_path)

def test_cli_context_recap_session_verify_bundle_routine_and_automate_support_out_files(monkeypatch):
    import writing_sidecar.cli as cli

    tmp_path = make_temp_dir()
    try:
        context_out = tmp_path / "context.txt"
        recap_out = tmp_path / "recap.txt"
        session_out = tmp_path / "session.txt"
        verify_out = tmp_path / "verify.txt"
        bundle_out = tmp_path / "bundle.txt"
        routine_out = tmp_path / "routine.txt"
        automate_out = tmp_path / "automate.txt"

        context_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "mode": "startup",
            "synced": False,
            "sync_summary": None,
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "phase": "COMPLETE",
            "operative_phase": "SCRIPTING",
            "current_chapter": "2",
            "current_arc": None,
            "suggested_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "queries_run": [],
            "results": [],
            "warnings": [],
            "recent_artifacts": [],
            "doc_highlights": {},
            "source_priority": ["live_docs", "sidecar"],
        }
        recap_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "mode": "restart",
            "synced": False,
            "sync_summary": None,
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "phase": "COMPLETE",
            "current_chapter": "2",
            "current_arc": None,
            "sections": {"Where We Are": ["ready"]},
            "queries_run": [],
            "results": [],
            "warnings": [],
            "source_priority": ["live_docs", "sidecar"],
        }
        session_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "task": "startup",
            "phase": "COMPLETE",
            "operative_phase": "SCRIPTING",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "suggested_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "continuity_watch": ["watch"],
            "phase_guardrails": ["guardrail"],
            "done_criteria": ["done"],
            "recommended_commands": ["command"],
            "artifact_targets": ["target"],
            "recommended_actions": ["action"],
            "write_performed": False,
            "sync_performed": False,
            "queries_run": [],
            "results": [],
            "recap_sections": {},
            "warnings": [],
            "verification_scope": "startup",
            "continuity_state": "clean",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "top_findings": [],
            "recommended_repairs": [],
        }
        verify_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "scope": "chapter",
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
        bundle_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "bundle": "startup",
            "verify_mode": "advisory",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "clean",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "top_findings": [],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["target"],
            "recap_sections": {"Where We Are": ["ready"]},
            "steps": [],
            "recommended_actions": ["action"],
            "recommended_commands": ["command"],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        }
        routine_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "routine": "start-work",
            "verify_mode": "advisory",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "clean",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "top_findings": [],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["target"],
            "recap_sections": {"Where We Are": ["ready"]},
            "steps": [],
            "recommended_actions": ["action"],
            "recommended_commands": ["command"],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        }
        automate_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "target": "codex",
            "name": "recommended",
            "routine": "move-to-prose",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "clean",
            "finding_counts": {"error": 0, "warn": 0, "info": 0},
            "top_findings": [],
            "doc_loadout": ["_story_bible/05_Current_Chapter_Notes.md"],
            "file_targets": ["C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md"],
            "artifact_targets": ["target"],
            "entry_command": "entry-command",
            "write_variant_command": "write-command",
            "prompt": "prompt",
            "expected_outputs": ["output"],
            "recommended_actions": ["action"],
            "recommended_commands": ["command"],
            "warnings": [],
        }

        monkeypatch.setattr(cli, "build_writing_context", lambda **kwargs: context_payload)
        monkeypatch.setattr(cli, "build_writing_recap", lambda **kwargs: recap_payload)
        monkeypatch.setattr(cli, "build_writing_session", lambda **kwargs: session_payload)
        monkeypatch.setattr(cli, "verify_writing_sidecar", lambda **kwargs: verify_payload)
        monkeypatch.setattr(cli, "build_writing_bundle", lambda **kwargs: bundle_payload)
        monkeypatch.setattr(cli, "build_writing_routine", lambda **kwargs: routine_payload)
        monkeypatch.setattr(cli, "build_writing_automation", lambda **kwargs: automate_payload)
        monkeypatch.setattr(cli, "render_writing_context", lambda payload: "context-rendered")
        monkeypatch.setattr(cli, "render_writing_recap", lambda payload: "recap-rendered")
        monkeypatch.setattr(cli, "render_writing_session", lambda payload: "session-rendered")
        monkeypatch.setattr(cli, "render_writing_verify", lambda payload: "verify-rendered")
        monkeypatch.setattr(cli, "render_writing_bundle", lambda payload: "bundle-rendered")
        monkeypatch.setattr(cli, "render_writing_routine", lambda payload: "routine-rendered")
        monkeypatch.setattr(cli, "render_writing_automation", lambda payload: "automate-rendered")

        cli.main(["context", str(tmp_path), "--project", "Witcher-DC", "--out", str(context_out)])
        cli.main(["recap", str(tmp_path), "--project", "Witcher-DC", "--out", str(recap_out)])
        cli.main(["verify", str(tmp_path), "--project", "Witcher-DC", "--out", str(verify_out)])
        cli.main(["session", str(tmp_path), "--project", "Witcher-DC", "--out", str(session_out)])
        cli.main(["bundle", str(tmp_path), "--project", "Witcher-DC", "--out", str(bundle_out)])
        cli.main(["routine", str(tmp_path), "--project", "Witcher-DC", "--out", str(routine_out)])
        cli.main(["automate", str(tmp_path), "--project", "Witcher-DC", "--out", str(automate_out)])

        assert context_out.read_text(encoding="utf-8") == "context-rendered"
        assert recap_out.read_text(encoding="utf-8") == "recap-rendered"
        assert verify_out.read_text(encoding="utf-8") == "verify-rendered"
        assert session_out.read_text(encoding="utf-8") == "session-rendered"
        assert bundle_out.read_text(encoding="utf-8") == "bundle-rendered"
        assert routine_out.read_text(encoding="utf-8") == "routine-rendered"
        assert automate_out.read_text(encoding="utf-8") == "automate-rendered"
    finally:
        cleanup_temp_dir(tmp_path)

def test_cli_verify_strict_exits_only_on_errors(monkeypatch):
    import writing_sidecar.cli as cli

    tmp_path = make_temp_dir()
    try:
        error_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "scope": "chapter",
            "state": "error",
            "verified_at": "2026-04-10T00:00:00+00:00",
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "finding_counts": {"error": 1, "warn": 0, "info": 0},
            "findings": [],
            "warnings": [],
            "recommended_actions": [],
            "query_packets": [],
            "source_snapshot": [],
            "cache_path": "C:/vault/.sidecars/witcher_dc/.writing-sidecar-verify.json",
            "sync_summary": None,
            "synced": False,
        }
        clean_payload = dict(error_payload)
        clean_payload["state"] = "clean"
        clean_payload["finding_counts"] = {"error": 0, "warn": 0, "info": 0}

        monkeypatch.setattr(cli, "verify_writing_sidecar", lambda **kwargs: error_payload)
        with pytest.raises(SystemExit):
            cli.main(["verify", str(tmp_path), "--project", "Witcher-DC", "--strict"])

        monkeypatch.setattr(cli, "verify_writing_sidecar", lambda **kwargs: clean_payload)
        cli.main(["verify", str(tmp_path), "--project", "Witcher-DC", "--strict"])
    finally:
        cleanup_temp_dir(tmp_path)

def test_cli_bundle_strict_exits_only_on_errors(monkeypatch):
    import writing_sidecar.cli as cli

    tmp_path = make_temp_dir()
    try:
        error_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "bundle": "startup",
            "verify_mode": "strict",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "error",
            "finding_counts": {"error": 1, "warn": 0, "info": 0},
            "top_findings": [],
            "doc_loadout": [],
            "file_targets": [],
            "artifact_targets": [],
            "recap_sections": {},
            "steps": [],
            "recommended_actions": [],
            "recommended_commands": [],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        }
        clean_payload = dict(error_payload)
        clean_payload["continuity_state"] = "clean"
        clean_payload["finding_counts"] = {"error": 0, "warn": 0, "info": 0}

        monkeypatch.setattr(cli, "build_writing_bundle", lambda **kwargs: error_payload)
        with pytest.raises(SystemExit):
            cli.main(["bundle", str(tmp_path), "--project", "Witcher-DC", "--verify", "strict"])

        monkeypatch.setattr(cli, "build_writing_bundle", lambda **kwargs: clean_payload)
        cli.main(["bundle", str(tmp_path), "--project", "Witcher-DC", "--verify", "strict"])
    finally:
        cleanup_temp_dir(tmp_path)

def test_cli_routine_strict_exits_only_on_errors(monkeypatch):
    import writing_sidecar.cli as cli

    tmp_path = make_temp_dir()
    try:
        error_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "routine": "start-work",
            "verify_mode": "strict",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "error",
            "finding_counts": {"error": 1, "warn": 0, "info": 0},
            "top_findings": [],
            "doc_loadout": [],
            "file_targets": [],
            "artifact_targets": [],
            "recap_sections": {},
            "steps": [],
            "recommended_actions": [],
            "recommended_commands": [],
            "write_performed": False,
            "paths_written": [],
            "sync_performed": False,
            "warnings": [],
        }
        clean_payload = dict(error_payload)
        clean_payload["continuity_state"] = "clean"
        clean_payload["finding_counts"] = {"error": 0, "warn": 0, "info": 0}

        monkeypatch.setattr(cli, "build_writing_routine", lambda **kwargs: error_payload)
        with pytest.raises(SystemExit):
            cli.main(["routine", str(tmp_path), "--project", "Witcher-DC", "--verify", "strict"])

        monkeypatch.setattr(cli, "build_writing_routine", lambda **kwargs: clean_payload)
        cli.main(["routine", str(tmp_path), "--project", "Witcher-DC", "--verify", "strict"])
    finally:
        cleanup_temp_dir(tmp_path)

def test_cli_automate_strict_exits_only_on_errors(monkeypatch):
    import writing_sidecar.cli as cli

    tmp_path = make_temp_dir()
    try:
        error_payload = {
            "project": "Witcher-DC",
            "project_root": "C:/vault/Witcher-DC",
            "vault_root": "C:/vault",
            "target": "codex",
            "name": "recommended",
            "routine": "move-to-prose",
            "state": "clean",
            "stale": False,
            "reasons": [],
            "last_synced_at": "2026-04-10T00:00:00+00:00",
            "operative_phase": "SCRIPTING",
            "continuity_state": "error",
            "finding_counts": {"error": 1, "warn": 0, "info": 0},
            "top_findings": [],
            "doc_loadout": [],
            "file_targets": [],
            "artifact_targets": [],
            "entry_command": "entry-command",
            "write_variant_command": "write-command",
            "prompt": "prompt",
            "expected_outputs": [],
            "recommended_actions": [],
            "recommended_commands": [],
            "warnings": [],
        }
        clean_payload = dict(error_payload)
        clean_payload["continuity_state"] = "clean"
        clean_payload["finding_counts"] = {"error": 0, "warn": 0, "info": 0}

        monkeypatch.setattr(cli, "build_writing_automation", lambda **kwargs: error_payload)
        with pytest.raises(SystemExit):
            cli.main(["automate", str(tmp_path), "--project", "Witcher-DC", "--verify", "strict"])

        monkeypatch.setattr(cli, "build_writing_automation", lambda **kwargs: clean_payload)
        cli.main(["automate", str(tmp_path), "--project", "Witcher-DC", "--verify", "strict"])
    finally:
        cleanup_temp_dir(tmp_path)

