from __future__ import annotations

from pathlib import Path

import pytest

from writing_sidecar.workflow import (
    build_writing_session,
    doctor_writing_sidecar,
    list_writing_projects,
    verify_writing_sidecar,
)

pytestmark = pytest.mark.live_vault


def test_live_vault_preview_commands_preserve_canon_docs(live_vault_root):
    if live_vault_root is None:
        pytest.skip("Set WRITING_SIDECAR_LIVE_VAULT to a vault path or 1 to enable live-vault smoke tests.")

    project_root = live_vault_root / "Witcher-DC"
    if not project_root.exists():
        pytest.skip(f"Witcher-DC was not found under {live_vault_root}.")

    current_notes_path = project_root / "_story_bible" / "05_Current_Notes.md"
    current_chapter_notes_path = project_root / "_story_bible" / "05_Current_Chapter_Notes.md"
    before_current_notes = current_notes_path.read_text(encoding="utf-8")
    before_current_chapter_notes = current_chapter_notes_path.read_text(encoding="utf-8")

    doctor = doctor_writing_sidecar(vault_dir=str(live_vault_root), project="Witcher-DC")
    projects = list_writing_projects(str(live_vault_root))
    verify = verify_writing_sidecar(
        vault_dir=str(live_vault_root),
        project="Witcher-DC",
        scope="chapter",
        sync="never",
    )
    session = build_writing_session(
        vault_dir=str(live_vault_root),
        project="Witcher-DC",
        task="startup",
        sync="never",
    )

    assert doctor["project"] == "Witcher-DC"
    assert any(item["project"] == "Witcher-DC" for item in projects["projects"])
    assert verify["project"] == "Witcher-DC"
    assert session["project"] == "Witcher-DC"
    assert session["write_performed"] is False
    assert current_notes_path.read_text(encoding="utf-8") == before_current_notes
    assert current_chapter_notes_path.read_text(encoding="utf-8") == before_current_chapter_notes
