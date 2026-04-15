from __future__ import annotations

from writing_sidecar.workflow import (
    build_writing_automation,
    build_writing_bundle,
    build_writing_routine,
    build_writing_session,
    doctor_writing_sidecar,
    list_writing_projects,
    verify_writing_sidecar,
)
from tests.helpers import assert_matches_json_snapshot, snapshot_path, workflow_kwargs


def _collect_witcher_outputs(context: dict) -> dict:
    kwargs = workflow_kwargs(context)
    return {
        "doctor": doctor_writing_sidecar(**kwargs),
        "projects": list_writing_projects(str(context["vault_root"])),
        "verify_chapter": verify_writing_sidecar(**kwargs, scope="chapter", sync="if-needed"),
        "session_startup": build_writing_session(**kwargs, task="startup"),
        "session_prose": build_writing_session(**kwargs, task="prose"),
        "bundle_startup": build_writing_bundle(**kwargs, name="startup"),
        "routine_move_to_prose": build_writing_routine(**kwargs, name="move-to-prose"),
        "automate_recommended": build_writing_automation(**kwargs, name="recommended"),
    }


def _collect_template_outputs(context: dict) -> dict:
    kwargs = workflow_kwargs(context)
    return {
        "doctor": doctor_writing_sidecar(**kwargs),
        "projects": list_writing_projects(str(context["vault_root"])),
        "verify_startup": verify_writing_sidecar(**kwargs, scope="startup", sync="never"),
        "automate_recommended": build_writing_automation(**kwargs, name="recommended", sync="never"),
    }


def test_witcher_fixture_contracts_and_snapshots(witcher_fixture):
    outputs = _collect_witcher_outputs(witcher_fixture)

    doctor = outputs["doctor"]
    assert {
        "project",
        "project_root",
        "vault_root",
        "assistant_ready",
        "recommended_entrypoint",
        "recommended_routine",
        "recommended_automate_command",
        "recommended_automation_command",
        "recommended_schedule_profile",
        "fact_layer_ready",
        "last_fact_sync_at",
    }.issubset(doctor)
    assert doctor["recommended_entrypoint"] == "writing-sidecar automate"

    projects = outputs["projects"]
    assert {"vault_root", "count", "projects"}.issubset(projects)
    assert projects["count"] == 1
    project = projects["projects"][0]
    assert {
        "project",
        "project_root",
        "state",
        "operative_phase",
        "recommended_entrypoint",
        "recommended_routine",
        "recommended_automate_command",
        "recommended_automation_command",
        "recommended_schedule_profile",
        "fact_layer_ready",
        "last_fact_sync_at",
    }.issubset(project)

    verify = outputs["verify_chapter"]
    assert {
        "project",
        "project_root",
        "vault_root",
        "scope",
        "state",
        "finding_counts",
        "fact_layer_state",
        "fact_counts",
        "fact_ops_preview",
        "fact_conflicts",
        "last_fact_sync_at",
    }.issubset(verify)
    assert verify["fact_layer_state"] == "preview_only"

    for key in ("session_startup", "session_prose"):
        session = outputs[key]
        assert {
            "project",
            "project_root",
            "vault_root",
            "task",
            "operative_phase",
            "continuity_state",
            "fact_layer_state",
            "fact_counts",
            "fact_highlights",
            "fact_conflicts",
            "last_fact_sync_at",
            "write_performed",
            "fact_write_performed",
            "fact_paths_written",
        }.issubset(session)
        assert session["write_performed"] is False
        assert session["fact_write_performed"] is False

    bundle = outputs["bundle_startup"]
    assert {
        "project",
        "project_root",
        "vault_root",
        "bundle",
        "verify_mode",
        "operative_phase",
        "fact_layer_state",
        "fact_counts",
        "fact_highlights",
        "fact_conflicts",
        "last_fact_sync_at",
        "steps",
        "write_performed",
    }.issubset(bundle)
    assert bundle["write_performed"] is False

    routine = outputs["routine_move_to_prose"]
    assert {
        "project",
        "project_root",
        "vault_root",
        "routine",
        "verify_mode",
        "operative_phase",
        "fact_layer_state",
        "fact_counts",
        "fact_highlights",
        "fact_conflicts",
        "last_fact_sync_at",
        "steps",
        "write_performed",
    }.issubset(routine)
    assert routine["write_performed"] is False

    automate = outputs["automate_recommended"]
    assert {
        "project",
        "project_root",
        "vault_root",
        "target",
        "name",
        "routine",
        "entry_command",
        "write_variant_command",
        "prompt",
        "expected_outputs",
        "recommended_actions",
        "recommended_commands",
        "warnings",
    }.issubset(automate)

    snapshot_map = {
        "doctor": snapshot_path("witcher_dc_representative", "doctor.json"),
        "projects": snapshot_path("witcher_dc_representative", "projects.json"),
        "verify_chapter": snapshot_path("witcher_dc_representative", "verify_chapter.json"),
        "session_startup": snapshot_path("witcher_dc_representative", "session_startup.json"),
        "session_prose": snapshot_path("witcher_dc_representative", "session_prose.json"),
        "routine_move_to_prose": snapshot_path("witcher_dc_representative", "routine_move_to_prose.json"),
        "automate_recommended": snapshot_path("witcher_dc_representative", "automate_recommended.json"),
    }
    for name, file_path in snapshot_map.items():
        assert_matches_json_snapshot(outputs[name], file_path, witcher_fixture)


def test_template_fixture_contracts_and_snapshots(template_fixture):
    outputs = _collect_template_outputs(template_fixture)

    doctor = outputs["doctor"]
    assert {
        "project",
        "project_root",
        "vault_root",
        "assistant_ready",
        "recommended_entrypoint",
        "recommended_routine",
        "recommended_automate_command",
        "recommended_automation_command",
        "recommended_schedule_profile",
        "fact_layer_ready",
        "last_fact_sync_at",
        "ok",
    }.issubset(doctor)
    assert doctor["assistant_ready"] is False

    projects = outputs["projects"]
    assert {"vault_root", "count", "projects"}.issubset(projects)
    assert projects["count"] == 1
    project = projects["projects"][0]
    assert {
        "project",
        "project_root",
        "state",
        "recommended_entrypoint",
        "recommended_routine",
        "recommended_automate_command",
        "recommended_automation_command",
        "recommended_schedule_profile",
        "fact_layer_ready",
        "last_fact_sync_at",
    }.issubset(project)
    assert project["state"] == "not_built"

    verify = outputs["verify_startup"]
    assert {
        "project",
        "project_root",
        "vault_root",
        "scope",
        "state",
        "finding_counts",
        "fact_layer_state",
        "fact_counts",
        "fact_ops_preview",
        "fact_conflicts",
        "last_fact_sync_at",
        "warnings",
    }.issubset(verify)
    assert verify["fact_layer_state"] == "preview_only"

    automate = outputs["automate_recommended"]
    assert {
        "project",
        "project_root",
        "vault_root",
        "target",
        "name",
        "routine",
        "state",
        "entry_command",
        "write_variant_command",
        "prompt",
        "expected_outputs",
        "recommended_actions",
        "recommended_commands",
        "warnings",
    }.issubset(automate)
    assert automate["state"] == "not_built"

    snapshot_map = {
        "doctor": snapshot_path("cdlc_template_not_built", "doctor.json"),
        "projects": snapshot_path("cdlc_template_not_built", "projects.json"),
        "verify_startup": snapshot_path("cdlc_template_not_built", "verify_startup.json"),
        "automate_recommended": snapshot_path("cdlc_template_not_built", "automate_recommended.json"),
    }
    for name, file_path in snapshot_map.items():
        assert_matches_json_snapshot(outputs[name], file_path, template_fixture)
