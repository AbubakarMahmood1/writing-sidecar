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

def test_verify_ignores_ordinary_draft_language_and_filters_low_signal_artifact_lines():
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
            "**Status:** READY FOR SCRIPTING\n**Next Action:** Draft the next scene from Arthur's sponsorship burden.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            "**Phase:** SCRIPTING\n**Chapter:** 2\n",
        )
        write_file(
            project_root / "logs" / "brainstorms" / "2026-04-14_chapter-2_handoff.md",
            textwrap.dedent(
                """
                Project: League of Demons
                Date: 2026-04-14

                ## Carry-Forward Threads

                - Mera balancing caution, royalty, and practical need

                ## Sources Used

                - 20260408rollout-2026-04-08T11-52-17-019d6bdc-f8fc-7731-aff2-a5d327f62a42.txt
                """
            ).strip(),
        )

        report = verify_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            sync="never",
            scope="startup",
        )

        kinds = {item["kind"] for item in report["findings"]}
        carry_forward = next(item for item in report["findings"] if item["kind"] == "carry_forward_gap")

        assert "placeholder_active" not in kinds
        assert any("Mera balancing caution" in line for line in carry_forward["evidence"])
        assert all(not line.startswith("Date:") for line in carry_forward["evidence"])
        assert all(".txt" not in line for line in carry_forward["evidence"])
    finally:
        cleanup_temp_dir(tmp_path)

def test_verify_writes_fact_preview_without_snapshot_or_log(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = default_output_dir(vault_root.resolve(), "Witcher-DC")
        palace_root = default_palace_dir(vault_root.resolve(), "Witcher-DC")

        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** READY FOR SCRIPTING\n**Next Action:** Build the intake scene beats.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** SCRIPTING
                **Chapter:** 2

                ## Locked Decisions

                - Keep the Atlantis intake fallout localized before any broader convergence.

                ## Threads Carried Forward

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur sponsorship | ACTIVE | He still owns the intake burden |
                """
            ).strip(),
        )
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Atlantis intake reference")

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
                "results": [],
            },
        )

        report = verify_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            sync="never",
            scope="chapter",
        )

        facts_dir = output_root / "facts"
        preview_path = facts_dir / FACT_PREVIEW_FILENAME
        snapshot_path = facts_dir / FACTS_SNAPSHOT_FILENAME
        log_path = facts_dir / FACT_LOG_FILENAME

        assert preview_path.exists()
        assert snapshot_path.exists() is False
        assert log_path.exists() is False
        assert report["fact_layer_state"] in {"preview_only", "needs_review"}
        assert report["fact_ops_preview"] or report["fact_highlights"]
    finally:
        cleanup_temp_dir(tmp_path)

def test_verify_fact_reconciliation_reports_update_delete_and_none(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = default_output_dir(vault_root.resolve(), "Witcher-DC")
        palace_root = default_palace_dir(vault_root.resolve(), "Witcher-DC")

        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** READY FOR SCRIPTING\n**Next Action:** Build the intake scene beats.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** SCRIPTING
                **Chapter:** 2

                ## Threads Carried Forward

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur sponsorship | ACTIVE | He still owns the intake burden |
                """
            ).strip(),
        )
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Atlantis intake reference")

        export_writing_corpus(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
        )
        _ensure_dir(palace_root)

        facts_dir = output_root / "facts"
        _ensure_dir(facts_dir)
        snapshot_path = facts_dir / FACTS_SNAPSHOT_FILENAME
        snapshot_path.write_text(
            json.dumps(
                {
                    "project": "Witcher-DC",
                    "project_root": str(project_root.resolve()),
                    "vault_root": str(vault_root.resolve()),
                    "updated_at": "2026-04-10T00:00:00+00:00",
                    "source_snapshot": [],
                    "fact_counts": {},
                    "facts": [
                        {
                            "id": _fact_identity("project_state", "project", "status"),
                            "category": "project_state",
                            "subject": "project",
                            "attribute": "status",
                            "value": "READY FOR BRAINDUMP",
                            "status": "active",
                            "chapter": "2",
                            "arc": None,
                            "sources": [
                                {
                                    "path": str(project_root / "_story_bible" / "05_Current_Notes.md"),
                                    "source": "current_notes",
                                    "line": "status: READY FOR BRAINDUMP",
                                }
                            ],
                            "updated_at": "2026-04-10T00:00:00+00:00",
                            "confidence": 1.0,
                            "notes": None,
                        },
                        {
                            "id": _fact_identity("continuity_thread", "Arthur sponsorship", "status"),
                            "category": "continuity_thread",
                            "subject": "Arthur sponsorship",
                            "attribute": "status",
                            "value": "ACTIVE",
                            "status": "active",
                            "chapter": "2",
                            "arc": None,
                            "sources": [
                                {
                                    "path": str(project_root / "_story_bible" / "05_Current_Chapter_Notes.md"),
                                    "source": "current_chapter_notes",
                                    "line": "Arthur sponsorship — ACTIVE — He still owns the intake burden",
                                }
                            ],
                            "updated_at": "2026-04-10T00:00:00+00:00",
                            "confidence": 1.0,
                            "notes": None,
                        },
                        {
                            "id": _fact_identity("locked_decision", "Retire the old braid opening.", "decision"),
                            "category": "locked_decision",
                            "subject": "Retire the old braid opening.",
                            "attribute": "decision",
                            "value": "locked",
                            "status": "active",
                            "chapter": "2",
                            "arc": None,
                            "sources": [
                                {
                                    "path": str(project_root / "_story_bible" / "05_Current_Chapter_Notes.md"),
                                    "source": "current_chapter_notes",
                                    "line": "Retire the old braid opening.",
                                }
                            ],
                            "updated_at": "2026-04-10T00:00:00+00:00",
                            "confidence": 1.0,
                            "notes": None,
                        },
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            "writing_sidecar.workflow.search_memories",
            lambda **kwargs: {
                "query": kwargs["query"],
                "filters": {"wing": kwargs["wing"], "room": kwargs["room"]},
                "results": [],
            },
        )

        verify_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            sync="never",
            scope="chapter",
        )

        preview = json.loads((facts_dir / FACT_PREVIEW_FILENAME).read_text(encoding="utf-8"))
        operations = {
            (item["category"], item["subject"], item["attribute"]): item["operation"]
            for item in preview["operations"]
        }

        assert operations[("project_state", "project", "status")] == "UPDATE"
        assert operations[("continuity_thread", "Arthur sponsorship", "status")] == "NONE"
        assert operations[("locked_decision", "Retire the old braid opening.", "decision")] == "DELETE"
        assert any(item["operation"] == "ADD" for item in preview["operations"])
    finally:
        cleanup_temp_dir(tmp_path)

def test_carry_forward_gap_ignores_discarded_rationale_and_audit_progression_noise():
    bundle = {
        "current_notes": {
            "path": "C:/vault/Witcher-DC/_story_bible/05_Current_Notes.md",
            "sections": {"_root": []},
            "highlights": [
                "Chapter 2 should open inside Atlantis after intake.",
                "Arthur and Mera deciding how much institutional protection Ciri gets.",
            ],
        },
        "current_chapter_notes": {
            "path": "C:/vault/Witcher-DC/_story_bible/05_Current_Chapter_Notes.md",
            "sections": {"_root": []},
            "highlights": [
                "Convert rescue into politics, medicine, and future obligation.",
                "The guardian remains unnamed from Arthur's POV.",
                "Arthur's sponsorship of Ciri remains active.",
            ],
        },
        "story_so_far": {},
        "state_tracker": {},
        "timeline": {},
        "latest_checkpoint": {"exists": False},
        "latest_handoff": {
            "exists": True,
            "path": "C:/vault/Witcher-DC/logs/brainstorms/handoff.md",
            "sections": {
                "Starting Position": [
                    "Chapter 2 should open inside Atlantis after intake.",
                ],
                "Guardrails For Chapter 2": [
                    "Keep Atlantis intake fallout as politics, medicine, and consequences.",
                ],
            },
            "highlights": [],
        },
        "latest_audit": {
            "exists": True,
            "path": "C:/vault/Witcher-DC/logs/audits/audit.md",
            "sections": {
                "Audit Progression": [
                    "76 — FAIL — Atmosphere outrunning activation",
                ],
                "Carry-Forward Threads Logged At Closeout": [
                    "Arthur's sponsorship of Ciri",
                ],
                "What The Final Version Does Better": [
                    "Atlantis intake now turns into medicine, institutional pressure, and obligation instead of looping the same trust test.",
                ],
            },
            "highlights": [],
        },
        "latest_discarded": {
            "exists": True,
            "path": "C:/vault/Witcher-DC/logs/discarded_paths/discarded.md",
            "sections": {
                "Discarded Path 2": [
                    "Why it was rejected:",
                    "slowed the shift from rescue into politics and obligation",
                    "Keep instead:",
                    "once Arthur passes the first test, move the next conflict toward sponsorship, medicine, and palace pressure",
                ],
                "Discarded Path 3": [
                    "Why it was rejected:",
                    "sharp readers will catch the knowledge leak",
                    "Keep instead:",
                    "use \"the guardian\" or equivalent until Arthur's knowledge changes",
                ],
            },
            "highlights": [],
        },
    }

    findings = _collect_carry_forward_gap_findings(bundle, "chapter")

    assert findings == []

def test_checkpoint_sections_do_not_append_raw_sidecar_preview_when_live_carry_forward_is_strong():
    doc_bundle = {
        "current_notes": {
            "sections": {},
            "highlights": [],
        },
        "current_chapter_notes": {
            "sections": {
                "Threads Carried Forward": [
                    "Arthur's sponsorship of Ciri — ACTIVE — He has vouched for her intake and will now have to answer for it",
                    "Bruce's anomaly investigation — ACTIVE — Timestamp drift archived; passive hooks are in place",
                    "Barry's timing-slip concern — ACTIVE — He has no proof yet, but he knows something went wrong",
                    "Atlantis political pressure — ACTIVE — Mera, the physician, guards, and palace channels are now involved",
                ],
            },
            "highlights": [],
        },
        "story_so_far": {
            "sections": {},
            "highlights": [],
        },
    }
    results = [
        {
            "results": [
                {
                    "room": "brainstorms",
                    "source_file": "2026-04-09_chapter-2_atlantis-fallout_handoff.md",
                    "text": "# Chapter 2 Atlantis Fallout Handoff\n\nArthur and Mera deciding how much institutional protection Ciri gets.",
                },
                {
                    "room": "audits",
                    "source_file": "2026-04-09_chapter-1_closeout_audit.md",
                    "text": "# Chapter 1 Closeout Audit\n\nArthur's sponsorship of Ciri is clear and politically costly.",
                },
            ]
        }
    ]

    sections = _build_checkpoint_sections(doc_bundle, results, "SCRIPTING", [])

    assert len(sections["Carry-Forward Threads"]) == 4
    assert all("handoff (" not in item.lower() for item in sections["Carry-Forward Threads"])
    assert all("audit (" not in item.lower() for item in sections["Carry-Forward Threads"])

def test_verify_fact_preview_ignores_broad_timeline_history_lines(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = default_output_dir(vault_root.resolve(), "Witcher-DC")
        palace_root = default_palace_dir(vault_root.resolve(), "Witcher-DC")

        _ensure_dir(project_root)
        scaffold_writing_sidecar(str(vault_root), "Witcher-DC")
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** READY FOR SCRIPTING\n**Next Action:** Build the intake scene beats.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** SCRIPTING
                **Chapter:** 2

                ## Threads Carried Forward

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur sponsorship | ACTIVE | He still owns the intake burden |
                """
            ).strip(),
        )
        write_file(
            project_root / "_story_bible" / "06_Timeline.md",
            textwrap.dedent(
                """
                # Timeline

                ## PHASE 4: ATLANTIS INTERLUDE

                - Justice League forced to work with Ciri

                ## EVENT CROSS-REFERENCE

                - Darkseid War — Year 2-3 — Major involvement
                """
            ).strip(),
        )
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Atlantis intake reference")

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
                "results": [],
            },
        )

        report = verify_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            sync="never",
            scope="timeline",
        )

        timeline_subjects = {
            item.get("subject")
            for item in report["fact_ops_preview"]
            if item.get("category") == "timeline_fact"
        }
        assert "Justice League forced to work with Ciri" not in timeline_subjects
        assert "Darkseid War — Year 2-3 — Major involvement" not in timeline_subjects
        assert timeline_subjects == set()
    finally:
        cleanup_temp_dir(tmp_path)

def test_session_write_persists_fact_snapshot_and_log(monkeypatch):
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
            "**Status:** READY FOR SCRIPTING\n**Next Action:** Build the Atlantis intake sequence.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** SCRIPTING
                **Chapter:** 2

                ## Locked Decisions

                - Keep Atlantis intake fallout localized first.

                ## Threads Carried Forward

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur sponsorship | ACTIVE | He still owns the intake burden |
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
                "results": [],
            },
        )
        monkeypatch.setattr(
            "writing_sidecar.workflow._mine_exported_sidecar",
            lambda output_root, project, palace_path, runtime_root, refresh_palace=False: _ensure_dir(
                Path(palace_path)
            ),
        )

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

        facts_dir = output_root / "facts"
        assert (facts_dir / FACTS_SNAPSHOT_FILENAME).exists()
        assert (facts_dir / FACT_LOG_FILENAME).exists()
        assert written["fact_layer_ready"] is True
        assert written["fact_write_performed"] is True
        assert any(path.endswith(FACTS_SNAPSHOT_FILENAME) for path in written["fact_paths_written"])
    finally:
        cleanup_temp_dir(tmp_path)

def test_doctor_and_projects_report_fact_layer_ready_after_write(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = default_output_dir(vault_root.resolve(), "Witcher-DC")
        palace_root = default_palace_dir(vault_root.resolve(), "Witcher-DC")
        runtime_root = default_runtime_dir(vault_root.resolve(), "Witcher-DC")

        write_file(
            project_root / "writing-sidecar.yaml",
            "brainstorms:\n  - logs/brainstorms\naudits:\n  - logs/audits\ndiscarded_paths: []\n",
        )
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** READY FOR SCRIPTING\n**Next Action:** Build the Atlantis intake sequence.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** SCRIPTING
                **Chapter:** 2

                ## Threads Carried Forward

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur sponsorship | ACTIVE | He still owns the intake burden |
                """
            ).strip(),
        )
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Atlantis intake reference")
        write_file(project_root / "logs" / "checkpoints" / "checkpoint.md", "startup checkpoint")

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
                "results": [],
            },
        )
        monkeypatch.setattr(
            "writing_sidecar.workflow._mine_exported_sidecar",
            lambda output_root, project, palace_path, runtime_root, refresh_palace=False: _ensure_dir(
                Path(palace_path)
            ),
        )

        build_writing_session(
            vault_dir=str(project_root),
            task="startup",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            sync="if-needed",
            write=True,
            n_results=2,
        )

        doctor = doctor_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        projects = list_writing_projects(str(vault_root))
        project = next(item for item in projects["projects"] if item["project"] == "Witcher-DC")

        assert doctor["fact_layer_ready"] is True
        assert doctor["last_fact_sync_at"]
        assert project["fact_layer_ready"] is True
        assert project["last_fact_sync_at"]
    finally:
        cleanup_temp_dir(tmp_path)

def test_doctor_and_projects_report_preview_timestamp_before_fact_write(monkeypatch):
    tmp_path = make_temp_dir()
    try:
        vault_root = tmp_path / "vault"
        project_root = vault_root / "Witcher-DC"
        output_root = default_output_dir(vault_root.resolve(), "Witcher-DC")
        palace_root = default_palace_dir(vault_root.resolve(), "Witcher-DC")
        runtime_root = default_runtime_dir(vault_root.resolve(), "Witcher-DC")

        write_file(
            project_root / "writing-sidecar.yaml",
            "brainstorms:\n  - logs/brainstorms\naudits:\n  - logs/audits\ndiscarded_paths: []\n",
        )
        write_file(project_root / "AGENTS.md", "gateway")
        write_file(
            project_root / "_story_bible" / "05_Current_Notes.md",
            "**Status:** READY FOR SCRIPTING\n**Next Action:** Build the Atlantis intake sequence.\n",
        )
        write_file(
            project_root / "_story_bible" / "05_Current_Chapter_Notes.md",
            textwrap.dedent(
                """
                **Phase:** SCRIPTING
                **Chapter:** 2

                ## Threads Carried Forward

                | Thread | Status | Notes |
                |--------|--------|-------|
                | Arthur sponsorship | ACTIVE | He still owns the intake burden |
                """
            ).strip(),
        )
        write_file(project_root / "_story_bible" / "research" / "dc.md", "Atlantis intake reference")
        write_file(project_root / "logs" / "checkpoints" / "checkpoint.md", "startup checkpoint")

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
                "results": [],
            },
        )
        monkeypatch.setattr(
            "writing_sidecar.workflow._mine_exported_sidecar",
            lambda output_root, project, palace_path, runtime_root, refresh_palace=False: _ensure_dir(
                Path(palace_path)
            ),
        )

        verify_writing_sidecar(
            vault_dir=str(project_root),
            project=None,
            scope="chapter",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
            sync="if-needed",
            n_results=2,
        )

        doctor = doctor_writing_sidecar(
            vault_dir=str(vault_root),
            project="Witcher-DC",
            out_dir=str(output_root),
            palace_path=str(palace_root),
            runtime_root=str(runtime_root),
        )
        projects = list_writing_projects(str(vault_root))
        project = next(item for item in projects["projects"] if item["project"] == "Witcher-DC")

        assert doctor["fact_layer_ready"] is False
        assert doctor["last_fact_sync_at"]
        assert project["fact_layer_ready"] is False
        assert project["last_fact_sync_at"]
    finally:
        cleanup_temp_dir(tmp_path)

