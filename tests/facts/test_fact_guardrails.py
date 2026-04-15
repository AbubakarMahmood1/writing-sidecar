from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from writing_sidecar.health import HEALTH_HISTORY_FILENAME, HEALTH_LATEST_FILENAME
from writing_sidecar.workflow import (
    FACT_LOG_FILENAME,
    FACT_PREVIEW_FILENAME,
    FACTS_SNAPSHOT_FILENAME,
    build_writing_automation,
    build_writing_bundle,
    build_writing_routine,
    build_writing_session,
    doctor_writing_sidecar,
    list_writing_projects,
    verify_writing_sidecar,
)
from tests.helpers import workflow_kwargs


def test_witcher_fixture_fact_preview_budget_and_signal(witcher_fixture):
    kwargs = workflow_kwargs(witcher_fixture)

    verify_writing_sidecar(**kwargs, scope="chapter", sync="if-needed")
    preview_path = Path(kwargs["out_dir"]) / "facts" / FACT_PREVIEW_FILENAME
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    category_counts = Counter(item["category"] for item in preview["operations"])
    continuity_threads = {item["subject"] for item in preview["operations"] if item["category"] == "continuity_thread"}
    locked_decisions = {item["subject"] for item in preview["operations"] if item["category"] == "locked_decision"}
    timeline_subjects = {item["subject"] for item in preview["operations"] if item["category"] == "timeline_fact"}

    assert len(preview["operations"]) <= 25
    assert category_counts["timeline_fact"] <= 1
    assert 4 <= category_counts["chapter_state"] <= 6
    assert 1 <= category_counts["project_state"] <= 2
    assert category_counts["arc_state"] == 1
    assert "Arthur sponsorship of Ciri" in continuity_threads
    assert "Atlantis political pressure" in continuity_threads
    assert "Keep Arthur's sponsorship burden visible." in continuity_threads
    assert "Keep Atlantis intake fallout localized first." in locked_decisions
    assert "Preserve Arthur's sponsorship burden as the chapter spine." in locked_decisions
    assert "Darkseid War — Year 2-3 — Major involvement" not in timeline_subjects
    assert "Justice League forced to work with Ciri" not in timeline_subjects


def test_preview_commands_keep_fact_writes_preview_only(witcher_fixture):
    kwargs = workflow_kwargs(witcher_fixture)
    project_root = Path(witcher_fixture["project_root"])
    facts_dir = Path(kwargs["out_dir"]) / "facts"
    health_dir = Path(kwargs["out_dir"]) / "health"
    preview_path = facts_dir / FACT_PREVIEW_FILENAME
    snapshot_path = facts_dir / FACTS_SNAPSHOT_FILENAME
    log_path = facts_dir / FACT_LOG_FILENAME
    latest_health_path = health_dir / HEALTH_LATEST_FILENAME
    history_health_path = health_dir / HEALTH_HISTORY_FILENAME
    current_notes_path = project_root / "_story_bible" / "05_Current_Notes.md"
    current_chapter_notes_path = project_root / "_story_bible" / "05_Current_Chapter_Notes.md"
    before_current_notes = current_notes_path.read_text(encoding="utf-8")
    before_current_chapter_notes = current_chapter_notes_path.read_text(encoding="utf-8")

    doctor_writing_sidecar(**kwargs)
    list_writing_projects(str(witcher_fixture["vault_root"]))

    assert latest_health_path.exists() is False
    assert history_health_path.exists() is False

    verify_writing_sidecar(**kwargs, scope="chapter", sync="if-needed")
    build_writing_session(**kwargs, task="startup")
    build_writing_bundle(**kwargs, name="startup")
    build_writing_routine(**kwargs, name="move-to-prose")
    build_writing_automation(**kwargs, name="recommended")

    assert preview_path.exists()
    assert snapshot_path.exists() is False
    assert log_path.exists() is False
    assert latest_health_path.exists()
    assert history_health_path.exists()
    history_events = [line for line in history_health_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(history_events) == 5
    assert current_notes_path.read_text(encoding="utf-8") == before_current_notes
    assert current_chapter_notes_path.read_text(encoding="utf-8") == before_current_chapter_notes


def test_write_capable_flow_persists_fact_files_without_mutating_canon_docs(witcher_fixture):
    kwargs = workflow_kwargs(witcher_fixture)
    project_root = Path(witcher_fixture["project_root"])
    facts_dir = Path(kwargs["out_dir"]) / "facts"
    health_dir = Path(kwargs["out_dir"]) / "health"
    preview_path = facts_dir / FACT_PREVIEW_FILENAME
    snapshot_path = facts_dir / FACTS_SNAPSHOT_FILENAME
    log_path = facts_dir / FACT_LOG_FILENAME
    latest_health_path = health_dir / HEALTH_LATEST_FILENAME
    history_health_path = health_dir / HEALTH_HISTORY_FILENAME
    current_notes_path = project_root / "_story_bible" / "05_Current_Notes.md"
    current_chapter_notes_path = project_root / "_story_bible" / "05_Current_Chapter_Notes.md"
    before_current_notes = current_notes_path.read_text(encoding="utf-8")
    before_current_chapter_notes = current_chapter_notes_path.read_text(encoding="utf-8")

    packet = build_writing_session(**kwargs, task="startup", write=True, sync="if-needed")

    assert preview_path.exists()
    assert snapshot_path.exists()
    assert log_path.exists()
    assert latest_health_path.exists()
    assert history_health_path.exists()
    assert packet["fact_write_performed"] is True
    assert any(path.endswith(FACTS_SNAPSHOT_FILENAME) for path in packet["fact_paths_written"])
    assert any(path.endswith(FACT_LOG_FILENAME) for path in packet["fact_paths_written"])
    assert current_notes_path.read_text(encoding="utf-8") == before_current_notes
    assert current_chapter_notes_path.read_text(encoding="utf-8") == before_current_chapter_notes
