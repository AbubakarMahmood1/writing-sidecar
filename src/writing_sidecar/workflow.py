#!/usr/bin/env python3
"""
writing_export.py — Build a writing-process sidecar corpus outside the live project.

This command exports selected process memory into a staging directory that can be
initialized and mined with normal MemPalace commands. It does not mutate the live
story bible or active chapter files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import yaml

from .mempalace_adapter import (
    SUPPORTED_MEMPALACE_SPEC,
    ensure_supported_mempalace_version,
    get_installed_mempalace_version,
    mine,
    normalize,
    search_memories,
)

DEFAULT_CODEX_HOME = Path(os.path.expanduser("~/.codex"))
DEFAULT_WRITING_CONFIG_FILENAMES = ("writing-sidecar.yaml", "writing-sidecar.yml")
DEFAULT_SIDECAR_OUTPUT_DIRNAME = ".sidecars"
DEFAULT_SIDECAR_PALACE_DIRNAME = ".palaces"
DEFAULT_RUNTIME_DIRNAME = ".mempalace-sidecar-runtime"
STATE_FILENAME = ".writing-sidecar-state.json"
STATE_VERSION = 1
SEARCH_MODE_ROOMS = {
    "planning": ("checkpoints", "brainstorms", "discarded_paths", "audits", "chat_process"),
    "audit": ("audits", "discarded_paths", "checkpoints", "chat_process", "archived_notes"),
    "history": ("checkpoints", "audits", "brainstorms", "discarded_paths", "chat_process"),
    "research": ("research", "archived_notes"),
}
CONTEXT_MODES = ("startup", "planning", "audit", "history", "research")
RECAP_MODES = ("restart", "handoff", "continuity")
MAINTAIN_KINDS = ("checkpoint", "audit", "handoff", "discarded", "closeout")
SESSION_TASKS = ("startup", "planning", "prose", "audit", "debug", "handoff", "closeout")
FIXED_ROOMS = (
    "chat_process",
    "checkpoints",
    "brainstorms",
    "audits",
    "discarded_paths",
    "research",
    "archived_notes",
)
LIVE_GATEWAY_FILES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}
LIVE_NOTES_FILES = {"05_Current_Notes.md", "05_Current_Chapter_Notes.md"}
ROOM_DESCRIPTIONS = {
    "chat_process": "Normalized AI conversations and process chatter tied to this project.",
    "checkpoints": "Structured session-safe checkpoints captured during startup, planning, and closeout.",
    "brainstorms": "Idea dumps, alternatives, and exploratory notes.",
    "audits": "Review passes, criticism, and structured analysis.",
    "discarded_paths": "Cut scenes, abandoned branches, and paths not chosen.",
    "research": "Reference material and research notes safe to archive.",
    "archived_notes": "Archived chapter notes and historical planning material.",
}
DOC_RELATIVE_PATHS = {
    "story_so_far": Path("_story_bible") / "01_Story_So_Far.md",
    "current_notes": Path("_story_bible") / "05_Current_Notes.md",
    "current_chapter_notes": Path("_story_bible") / "05_Current_Chapter_Notes.md",
}
PHASE_LOADOUT = {
    "BRAINDUMP": [
        "_story_bible/05_Current_Notes.md",
        "_story_bible/05_Current_Chapter_Notes.md",
        "_story_bible/04_Ideas_and_Future.md",
    ],
    "SCRIPTING": [
        "_story_bible/02B_Character_Quick_Reference.md",
        "_story_bible/04_Ideas_and_Future.md",
        "_story_bible/05_Current_Chapter_Notes.md",
    ],
    "STAGING": [
        "_story_bible/02B_Character_Quick_Reference.md",
        "_story_bible/02C_Character_State_Tracker.md",
        "_story_bible/03_World_Rules.md",
        "_story_bible/05_Current_Chapter_Notes.md",
    ],
    "PROSE": [
        "_story_bible/00_AI_Writing_Rules.md",
        "_story_bible/02B_Character_Quick_Reference.md",
        "_story_bible/05_Current_Chapter_Notes.md",
    ],
    "AUDIT": [
        "_story_bible/96_Prose_Audit_Protocol.md",
        "_story_bible/97_Editorial_Standards.md",
        "current chapter prose",
    ],
    "DEBUG": [
        "latest audit output",
        "current chapter prose",
        "only the rules needed for the dominant failure",
    ],
    "COMPLETE": [
        "logs/checkpoints/",
        "logs/audits/",
        "logs/brainstorms/",
        "logs/discarded_paths/",
        "writing-sidecar sync",
    ],
}
PROJECT_SCAN_PRUNE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".sidecars",
    ".palaces",
    ".mempalace-sidecar-runtime",
    ".pytest_cache",
    ".tmp-tests",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}
FIELD_LABELS = {
    "status": ("Status",),
    "phase": ("Phase",),
    "chapter": ("Current Chapter", "Chapter"),
    "arc": ("Current Arc", "Arc"),
    "working_title": ("Working Title",),
    "next_action": ("Next Action",),
    "audit_status": ("Audit Status",),
    "latest_score": ("Latest Score",),
}
STRUCTURED_HIGHLIGHT_FIELDS = (
    "status",
    "phase",
    "arc",
    "chapter",
    "working_title",
    "audit_status",
    "latest_score",
    "next_action",
)
PREFERRED_SECTION_KEYWORDS = (
    "current focus",
    "recommended next loadout",
    "next action",
    "threads carried forward",
    "continuity closeout",
    "next start point",
    "chapter goals",
    "what is actually ready",
    "open work",
    "locked decisions",
)
LOW_VALUE_LINE_PREFIXES = (
    "purpose:",
    "last updated:",
    "sources used",
    "source:",
)
LOW_VALUE_LINE_SUBSTRINGS = (
    "template-only",
    "check this before planning or drafting",
    "live scratchpad for the current writing session",
)
QUERY_STOP_LEADS = {
    "open",
    "start",
    "continue",
    "reset",
    "run",
    "use",
    "check",
    "review",
    "build",
    "move",
}
DOC_SECTION_HINTS = {
    "startup_where": (
        "what is actually ready",
        "current focus",
        "current phase",
        "cdlc status",
    ),
    "startup_memory": (
        "locked decisions",
        "threads carried forward",
        "continuity closeout",
        "next start point",
    ),
    "handoff_state": ("current focus", "what is actually ready", "cdlc status"),
    "handoff_risks": ("open work", "chapter goals", "threads carried forward"),
    "continuity_facts": ("continuity closeout", "threads carried forward"),
}


def resolve_project_root(vault_dir: str, project: str) -> Path:
    """Resolve a project path from either a vault root or a direct project path."""
    base_path = Path(vault_dir).expanduser().resolve()
    if base_path.is_file():
        base_path = base_path.parent
    if not base_path.exists():
        raise FileNotFoundError(f"Vault path not found: {base_path}")

    direct_match = base_path.name.lower() == project.lower()
    candidate = base_path / project
    ancestor_match = next(
        (
            ancestor
            for ancestor in (base_path, *base_path.parents)
            if ancestor.name.lower() == project.lower() and ancestor.is_dir()
        ),
        None,
    )

    if direct_match and base_path.is_dir():
        return base_path
    if ancestor_match is not None:
        return ancestor_match.resolve()
    if candidate.is_dir():
        return candidate.resolve()

    raise FileNotFoundError(
        f"Could not resolve project '{project}' from {base_path}. "
        "Pass the vault root or the project directory itself."
    )


def _find_project_config_path(project_root: Path) -> Path | None:
    for filename in DEFAULT_WRITING_CONFIG_FILENAMES:
        candidate = project_root / filename
        if candidate.exists():
            return candidate.resolve()
    return None


def _candidate_project(project_root: Path) -> dict:
    project_root = project_root.expanduser().resolve()
    return {
        "project": project_root.name,
        "project_root": project_root,
        "config_path": _find_project_config_path(project_root),
    }


def find_enclosing_sidecar_project(path: str | Path) -> dict | None:
    base_path = Path(path).expanduser().resolve()
    if base_path.is_file():
        base_path = base_path.parent
    for ancestor in (base_path, *base_path.parents):
        config_path = _find_project_config_path(ancestor)
        if config_path:
            return {
                "project": ancestor.name,
                "project_root": ancestor.resolve(),
                "config_path": config_path,
            }
    return None


def discover_sidecar_projects(vault_dir: str | Path) -> list[dict]:
    base_path = Path(vault_dir).expanduser().resolve()
    if base_path.is_file():
        base_path = base_path.parent

    enclosing = find_enclosing_sidecar_project(base_path)
    if enclosing:
        return [enclosing]

    discovered: dict[str, dict] = {}
    for root, dirnames, filenames in os.walk(base_path):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in PROJECT_SCAN_PRUNE_DIRS
        ]
        config_name = next(
            (filename for filename in DEFAULT_WRITING_CONFIG_FILENAMES if filename in filenames),
            None,
        )
        if not config_name:
            continue
        project_root = Path(root).resolve()
        discovered[str(project_root)] = {
            "project": project_root.name,
            "project_root": project_root,
            "config_path": (project_root / config_name).resolve(),
        }
    return [discovered[key] for key in sorted(discovered)]


def resolve_sidecar_project(vault_dir: str, project: str | None = None) -> dict:
    base_path = Path(vault_dir).expanduser().resolve()
    if base_path.is_file():
        base_path = base_path.parent
    if project:
        project_root = resolve_project_root(str(base_path), project)
        return {
            "project": project_root.name,
            "project_root": project_root,
            "vault_root": resolve_vault_root(str(base_path), project_root),
            "config_path": _find_project_config_path(project_root),
        }

    enclosing = find_enclosing_sidecar_project(base_path)
    if enclosing:
        project_root = enclosing["project_root"]
        return {
            "project": enclosing["project"],
            "project_root": project_root,
            "vault_root": resolve_vault_root(str(base_path), project_root),
            "config_path": enclosing["config_path"],
        }

    candidates = discover_sidecar_projects(base_path)
    if not candidates:
        raise FileNotFoundError(
            f"Could not auto-resolve a sidecar-enabled project from {base_path}. "
            "Pass --project explicitly or run writing-sidecar init first."
        )
    if len(candidates) > 1:
        choices = ", ".join(candidate["project"] for candidate in candidates)
        raise ValueError(
            f"Ambiguous sidecar project under {base_path}. "
            f"Pass --project explicitly. Candidates: {choices}"
        )

    project_root = candidates[0]["project_root"]
    return {
        "project": candidates[0]["project"],
        "project_root": project_root,
        "vault_root": resolve_vault_root(str(base_path), project_root),
        "config_path": candidates[0]["config_path"],
    }


def default_output_dir(vault_root: Path, project: str) -> Path:
    """Default staging directory for writing sidecars."""
    return vault_root / DEFAULT_SIDECAR_OUTPUT_DIRNAME / _project_slug(project)


def default_palace_dir(vault_root: Path, project: str) -> Path:
    """Default palace directory for a writing sidecar."""
    return vault_root / DEFAULT_SIDECAR_PALACE_DIRNAME / _project_slug(project)


def default_runtime_dir(vault_root: Path, project: str) -> Path:
    """Default runtime/cache directory for sidecar mining and search."""
    return vault_root / DEFAULT_RUNTIME_DIRNAME / _project_slug(project)


def _prepare_writing_context(
    vault_dir: str,
    project: str | None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
) -> dict:
    resolved_project = resolve_sidecar_project(vault_dir, project)
    project_name = resolved_project["project"]
    project_root = resolved_project["project_root"]
    vault_root = resolved_project["vault_root"]
    output_root = (
        Path(out_dir).expanduser().resolve()
        if out_dir
        else default_output_dir(vault_root, project_name).resolve()
    )
    codex_root = Path(codex_home).expanduser().resolve() if codex_home else DEFAULT_CODEX_HOME
    target_palace = (
        Path(palace_path).expanduser().resolve()
        if palace_path
        else default_palace_dir(vault_root, project_name).resolve()
    )
    sidecar_runtime_root = (
        Path(runtime_root).expanduser().resolve()
        if runtime_root
        else default_runtime_dir(vault_root, project_name).resolve()
    )
    writing_config, loaded_config_path = _load_writing_export_config(project_root, config_path)
    config_base_dir = loaded_config_path.parent if loaded_config_path else project_root
    project_terms = _build_project_terms(
        project_name,
        project_root,
        writing_config.get("chat_project_terms", []),
    )
    excluded_chat_terms = _build_term_list(writing_config.get("chat_exclude_terms", []))
    brainstorm_inputs = _merge_opt_in_paths(
        config_base_dir,
        writing_config.get("brainstorms", []),
        brainstorm_paths or [],
    )
    audit_inputs = _merge_opt_in_paths(
        config_base_dir,
        writing_config.get("audits", []),
        audit_paths or [],
    )
    discarded_inputs = _merge_opt_in_paths(
        config_base_dir,
        writing_config.get("discarded_paths", []),
        discarded_paths or [],
    )

    return {
        "project": project_name,
        "project_root": project_root,
        "vault_root": vault_root,
        "output_root": output_root,
        "codex_root": codex_root,
        "palace_path": target_palace,
        "runtime_root": sidecar_runtime_root,
        "writing_config": writing_config,
        "loaded_config_path": loaded_config_path,
        "generated_config_path": output_root / "mempalace.yaml",
        "manifest_path": output_root / STATE_FILENAME,
        "project_terms": project_terms,
        "excluded_chat_terms": excluded_chat_terms,
        "brainstorm_inputs": brainstorm_inputs,
        "audit_inputs": audit_inputs,
        "discarded_inputs": discarded_inputs,
    }


def _new_export_summary(context: dict) -> dict:
    return {
        "project_root": str(context["project_root"]),
        "vault_root": str(context["vault_root"]),
        "output_root": str(context["output_root"]),
        "rooms": {room: 0 for room in FIXED_ROOMS},
        "skipped_live_files": [],
        "skipped_missing_paths": [],
        "loaded_config_path": (
            str(context["loaded_config_path"]) if context["loaded_config_path"] else None
        ),
        "generated_config_path": str(context["generated_config_path"]),
        "manifest_path": str(context["manifest_path"]),
        "palace_path": str(context["palace_path"]),
        "runtime_root": str(context["runtime_root"]),
        "mine_skipped": None,
        "last_synced_at": None,
        "stale": None,
        "stale_reasons": [],
    }


def _status_state(built: bool, stale: bool) -> str:
    if not built:
        return "not_built"
    return "stale" if stale else "clean"


def _collect_writing_entries(context: dict, summary: dict, dry_run: bool) -> list:
    planned_entries = []

    _export_codex_chat_process(
        codex_root=context["codex_root"],
        project_root=context["project_root"],
        vault_root=context["vault_root"],
        project_terms=context["project_terms"],
        excluded_chat_terms=context["excluded_chat_terms"],
        output_root=context["output_root"],
        summary=summary,
        dry_run=dry_run,
        planned_entries=planned_entries,
    )
    _copy_tree_if_present(
        source_dir=context["project_root"] / "logs" / "checkpoints",
        room_name="checkpoints",
        source_kind="checkpoint",
        output_root=context["output_root"],
        project_root=context["project_root"],
        summary=summary,
        dry_run=dry_run,
        planned_entries=planned_entries,
    )
    _copy_tree_if_present(
        source_dir=context["project_root"] / "_story_bible" / "research",
        room_name="research",
        source_kind="research",
        output_root=context["output_root"],
        project_root=context["project_root"],
        summary=summary,
        dry_run=dry_run,
        planned_entries=planned_entries,
    )
    _copy_tree_if_present(
        source_dir=context["project_root"] / "_story_bible" / "chapters",
        room_name="archived_notes",
        source_kind="archived_note",
        output_root=context["output_root"],
        project_root=context["project_root"],
        summary=summary,
        dry_run=dry_run,
        planned_entries=planned_entries,
    )
    _copy_opt_in_paths(
        raw_paths=context["brainstorm_inputs"],
        room_name="brainstorms",
        source_kind="brainstorm",
        output_root=context["output_root"],
        project_root=context["project_root"],
        summary=summary,
        dry_run=dry_run,
        planned_entries=planned_entries,
    )
    _copy_opt_in_paths(
        raw_paths=context["audit_inputs"],
        room_name="audits",
        source_kind="audit",
        output_root=context["output_root"],
        project_root=context["project_root"],
        summary=summary,
        dry_run=dry_run,
        planned_entries=planned_entries,
    )
    _copy_opt_in_paths(
        raw_paths=context["discarded_inputs"],
        room_name="discarded_paths",
        source_kind="discarded_path",
        output_root=context["output_root"],
        project_root=context["project_root"],
        summary=summary,
        dry_run=dry_run,
        planned_entries=planned_entries,
    )

    return planned_entries


def export_writing_corpus(
    vault_dir: str,
    project: str | None = None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    mine_after_export: bool = False,
    palace_path: str = None,
    runtime_root: str = None,
    refresh_palace: bool = False,
    dry_run: bool = False,
) -> dict:
    """Export a curated writing-process corpus into fixed sidecar rooms."""
    context = _prepare_writing_context(
        vault_dir=vault_dir,
        project=project,
        out_dir=out_dir,
        codex_home=codex_home,
        config_path=config_path,
        brainstorm_paths=brainstorm_paths,
        audit_paths=audit_paths,
        discarded_paths=discarded_paths,
        palace_path=palace_path,
        runtime_root=runtime_root,
    )

    summary = _new_export_summary(context)

    if not dry_run:
        _ensure_dir(context["output_root"])
        _write_export_gitignore(context["output_root"])
        _write_sidecar_config(context["output_root"], context["project"])
        for room in FIXED_ROOMS:
            room_dir = context["output_root"] / room
            if room_dir.exists():
                shutil.rmtree(room_dir)
            _ensure_dir(room_dir)

    planned_entries = _collect_writing_entries(context, summary, dry_run=dry_run)

    if not dry_run:
        _write_state_manifest(context, summary, planned_entries)

    if mine_after_export:
        if dry_run:
            summary["mine_skipped"] = "dry_run"
        else:
            _mine_exported_sidecar(
                output_root=context["output_root"],
                project=context["project"],
                palace_path=context["palace_path"],
                runtime_root=context["runtime_root"],
                refresh_palace=refresh_palace,
            )
            _write_state_manifest(context, summary, planned_entries)

    return summary


def print_export_summary(summary: dict, dry_run: bool = False):
    """Render a compact export summary."""
    print(f"\n{'=' * 55}")
    print("  Writing Sidecar Export")
    print(f"{'=' * 55}")
    print(f"  Project: {summary['project_root']}")
    print(f"  Vault:   {summary['vault_root']}")
    print(f"  Output:  {summary['output_root']}")
    if dry_run:
        print("  DRY RUN — nothing was written")
    if summary.get("loaded_config_path"):
        print(f"  Config:  {summary['loaded_config_path']}")
    elif summary.get("generated_config_path") and not dry_run:
        print(f"  Config:  {summary['generated_config_path']}")
    if summary.get("manifest_path") and not dry_run:
        print(f"  State:   {summary['manifest_path']}")
    if summary.get("palace_path"):
        print(f"  Palace:  {summary['palace_path']}")
    if summary.get("runtime_root") and (summary.get("palace_path") or summary.get("mine_skipped")):
        print(f"  Runtime: {summary['runtime_root']}")
    if summary.get("last_synced_at") and not dry_run:
        print(f"  Synced:  {summary['last_synced_at']}")
    if summary.get("mine_skipped") == "dry_run":
        print("  Mine:    skipped because --dry-run was used")
    print("\n  By room:")
    for room, count in summary["rooms"].items():
        print(f"    {room:20} {count}")
    if summary["skipped_live_files"]:
        print("\n  Skipped live source-of-truth files:")
        for path in summary["skipped_live_files"]:
            print(f"    {path}")
    if summary["skipped_missing_paths"]:
        print("\n  Missing optional paths:")
        for path in summary["skipped_missing_paths"]:
            print(f"    {path}")
    print(f"\n{'=' * 55}\n")


def get_writing_sidecar_status(
    vault_dir: str,
    project: str | None = None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
) -> dict:
    """Inspect whether a writing sidecar is current or stale without mutating it."""
    context = _prepare_writing_context(
        vault_dir=vault_dir,
        project=project,
        out_dir=out_dir,
        codex_home=codex_home,
        config_path=config_path,
        brainstorm_paths=brainstorm_paths,
        audit_paths=audit_paths,
        discarded_paths=discarded_paths,
        palace_path=palace_path,
        runtime_root=runtime_root,
    )
    summary = _new_export_summary(context)
    current_entries = _collect_writing_entries(context, summary, dry_run=True)
    manifest = _load_state_manifest(context["manifest_path"])
    status = {
        "project": context["project"],
        "project_root": str(context["project_root"]),
        "vault_root": str(context["vault_root"]),
        "output_root": str(context["output_root"]),
        "config_path": str(context["loaded_config_path"]) if context["loaded_config_path"] else None,
        "manifest_path": str(context["manifest_path"]),
        "palace_path": str(context["palace_path"]),
        "runtime_root": str(context["runtime_root"]),
        "room_counts": manifest.get("room_counts", {}) if manifest else {},
        "last_synced_at": manifest.get("synced_at") if manifest else None,
        "built": manifest is not None,
        "stale": True,
        "state": "not_built",
        "stale_reasons": [],
        "reasons": [],
    }

    if manifest is None:
        status["stale_reasons"].append({"reason": "manifest_missing"})
        if not context["palace_path"].exists():
            status["stale_reasons"].append({"reason": "palace_missing"})
        status["reasons"] = list(status["stale_reasons"])
        status["state"] = _status_state(status["built"], True)
        return status

    if not context["palace_path"].exists():
        status["stale_reasons"].append({"reason": "palace_missing"})

    current_config = _describe_optional_file(context["loaded_config_path"])
    manifest_config = manifest.get("config")
    if current_config != manifest_config:
        status["stale_reasons"].append({"reason": "config_changed"})

    manifest_inputs = {entry["source_path"]: entry for entry in manifest.get("tracked_inputs", [])}
    current_inputs = {entry["source_path"]: entry for entry in current_entries}

    for source_path, tracked in manifest_inputs.items():
        source = Path(source_path)
        if not source.exists():
            status["stale_reasons"].append({"reason": "input_missing", "source_path": source_path})
            continue
        current_signature = _describe_file(source)
        tracked_signature = {
            "size": tracked.get("size"),
            "mtime": tracked.get("mtime"),
            "sha256": tracked.get("sha256"),
        }
        if current_signature != tracked_signature:
            status["stale_reasons"].append({"reason": "input_changed", "source_path": source_path})

    for source_path in sorted(set(current_inputs) - set(manifest_inputs)):
        status["stale_reasons"].append({"reason": "input_added", "source_path": source_path})

    status["reasons"] = list(status["stale_reasons"])
    status["stale"] = bool(status["stale_reasons"])
    status["state"] = _status_state(status["built"], status["stale"])
    return status


def print_writing_status(status: dict):
    print(f"\n{'=' * 55}")
    print("  Writing Sidecar Status")
    print(f"{'=' * 55}")
    print(f"  Project: {status['project_root']}")
    print(f"  Vault:   {status['vault_root']}")
    print(f"  Output:  {status['output_root']}")
    print(f"  Palace:  {status['palace_path']}")
    print(f"  Runtime: {status['runtime_root']}")
    if status.get("config_path"):
        print(f"  Config:  {status['config_path']}")
    print(f"  State:   {status['manifest_path']}")
    if status.get("last_synced_at"):
        print(f"  Synced:  {status['last_synced_at']}")

    state_label = {
        "not_built": "NOT BUILT",
        "stale": "STALE",
        "clean": "CLEAN",
    }.get(status.get("state"), "UNKNOWN")
    print(f"  Status:  {state_label}")

    if status.get("room_counts"):
        print("\n  Room counts:")
        for room, count in status["room_counts"].items():
            print(f"    {room:20} {count}")

    if status["stale_reasons"]:
        print("\n  Reasons:")
        for item in status["stale_reasons"]:
            reason = item["reason"]
            path = item.get("source_path")
            if path:
                print(f"    {reason:16} {path}")
            else:
                print(f"    {reason}")
    print(f"\n{'=' * 55}\n")


def prepare_writing_sidecar(
    vault_dir: str,
    project: str | None = None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
    sync: str = "if-needed",
    refresh_palace: bool = False,
) -> dict:
    status = get_writing_sidecar_status(
        vault_dir=vault_dir,
        project=project,
        out_dir=out_dir,
        codex_home=codex_home,
        config_path=config_path,
        brainstorm_paths=brainstorm_paths,
        audit_paths=audit_paths,
        discarded_paths=discarded_paths,
        palace_path=palace_path,
        runtime_root=runtime_root,
    )
    should_sync = refresh_palace or sync == "always" or (sync == "if-needed" and status["stale"])
    summary = None
    warnings = []

    if should_sync:
        summary = export_writing_corpus(
            vault_dir=vault_dir,
            project=project,
            out_dir=out_dir,
            codex_home=codex_home,
            config_path=config_path,
            brainstorm_paths=brainstorm_paths,
            audit_paths=audit_paths,
            discarded_paths=discarded_paths,
            mine_after_export=True,
            palace_path=palace_path,
            runtime_root=runtime_root,
            refresh_palace=refresh_palace,
            dry_run=False,
        )
        status = get_writing_sidecar_status(
            vault_dir=vault_dir,
            project=project,
            out_dir=out_dir,
            codex_home=codex_home,
            config_path=config_path,
            brainstorm_paths=brainstorm_paths,
            audit_paths=audit_paths,
            discarded_paths=discarded_paths,
            palace_path=palace_path,
            runtime_root=runtime_root,
        )
    elif sync == "never" and status["stale"]:
        warnings.append("sidecar is stale; skipping rebuild because --sync never was used.")

    return {
        "status": status,
        "sync_summary": summary,
        "synced": summary is not None,
        "warnings": warnings,
    }


def search_writing_sidecar(query: str, palace_path: str, wing: str, mode: str, n_results: int = 5) -> dict:
    if mode not in SEARCH_MODE_ROOMS:
        raise ValueError(f"Unknown writing-search mode: {mode}")

    primary = []
    deferred = []
    seen = set()
    seen_sources = set()
    rooms = SEARCH_MODE_ROOMS[mode]
    for room in rooms:
        results = search_memories(
            query=query,
            palace_path=palace_path,
            wing=wing,
            room=room,
            n_results=n_results,
        )
        if results.get("error"):
            return results
        for hit in results.get("results", []):
            key = (hit.get("source_file"), hit.get("text"))
            if key in seen:
                continue
            seen.add(key)
            hit["mode"] = mode
            source_key = hit.get("source_file") or f"{room}:{len(seen)}"
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                primary.append(hit)
            else:
                deferred.append(hit)

    merged = (primary + deferred)[:n_results]

    return {
        "query": query,
        "wing": wing,
        "mode": mode,
        "room_order": list(rooms),
        "results": merged,
    }


def print_writing_search_results(search_data: dict):
    query = search_data["query"]
    mode = search_data["mode"]
    wing = search_data["wing"]
    hits = search_data.get("results", [])

    if not hits:
        print(f'\n  No writing-sidecar results found for: "{query}"')
        return

    print(f"\n{'=' * 60}")
    print(f'  Writing Sidecar Results for: "{query}"')
    print(f"  Wing: {wing}")
    print(f"  Mode: {mode}")
    print(f"{'=' * 60}\n")

    for i, hit in enumerate(hits, 1):
        print(f"  [{i}] {hit.get('room', '?')}")
        print(f"      Source: {hit.get('source_file', '?')}")
        print(f"      Match:  {hit.get('similarity', '?')}")
        print()
        for line in hit.get("text", "").strip().split("\n"):
            print(f"      {line}")
        print()
        print(f"  {'─' * 56}")
    print()


def list_writing_projects(vault_dir: str) -> dict:
    base_path = Path(vault_dir).expanduser().resolve()
    if base_path.is_file():
        base_path = base_path.parent

    projects = []
    for candidate in discover_sidecar_projects(base_path):
        status = get_writing_sidecar_status(
            vault_dir=str(candidate["project_root"]),
            project=candidate["project"],
        )
        projects.append(
            {
                "project": status["project"],
                "project_root": status["project_root"],
                "config_path": str(candidate["config_path"]) if candidate["config_path"] else None,
                "state": status["state"],
                "stale": status["stale"],
                "last_synced_at": status["last_synced_at"],
                "room_counts": status.get("room_counts", {}),
                "reasons": status.get("stale_reasons", []),
            }
        )

    return {
        "vault_root": str(base_path),
        "count": len(projects),
        "projects": projects,
    }


def print_writing_projects(report: dict):
    print(f"\n{'=' * 60}")
    print("  Writing Sidecar Projects")
    print(f"{'=' * 60}")
    print(f"  Vault: {report['vault_root']}")
    print(f"  Count: {report['count']}")
    if not report["projects"]:
        print("\n  No sidecar-enabled projects found.\n")
        print(f"{'=' * 60}\n")
        return

    for item in report["projects"]:
        print(f"\n  {item['project']} [{item['state'].upper()}]")
        print(f"    Root:   {item['project_root']}")
        print(f"    Config: {item['config_path']}")
        if item.get("last_synced_at"):
            print(f"    Synced: {item['last_synced_at']}")
        if item.get("reasons"):
            print("    Reasons:")
            for reason in item["reasons"]:
                if reason.get("source_path"):
                    print(f"      - {reason['reason']}: {reason['source_path']}")
                else:
                    print(f"      - {reason['reason']}")
    print(f"\n{'=' * 60}\n")


def _doc_highlights_payload(doc_bundle: dict) -> dict:
    return {
        name: {
            "path": payload["path"],
            "highlights": payload["highlights"],
        }
        for name, payload in doc_bundle.items()
        if payload["exists"]
    }


def _build_context_payload(
    prepared: dict,
    mode: str,
    n_results: int,
    *,
    query_plan: list[dict] | None = None,
    doc_bundle: dict | None = None,
) -> tuple[dict, dict]:
    status = prepared["status"]
    doc_bundle = doc_bundle or _load_live_doc_bundle(Path(status["project_root"]))
    query_plan = query_plan or _select_context_queries(doc_bundle, status["project"], mode)
    warnings = list(prepared["warnings"])
    results = _run_sidecar_queries(
        status,
        query_plan,
        n_results=n_results,
        warnings=warnings,
        curated_for_context=True,
    )
    phase = _extract_phase(doc_bundle)

    return doc_bundle, {
        "project": status["project"],
        "project_root": status["project_root"],
        "vault_root": status["vault_root"],
        "mode": mode,
        "synced": prepared["synced"],
        "sync_summary": prepared["sync_summary"],
        "state": status["state"],
        "stale": status["stale"],
        "reasons": status["stale_reasons"],
        "last_synced_at": status["last_synced_at"],
        "phase": phase,
        "current_chapter": _extract_field(doc_bundle, "chapter"),
        "current_arc": _extract_field(doc_bundle, "arc"),
        "suggested_loadout": _derive_suggested_loadout(doc_bundle, phase),
        "queries_run": query_plan,
        "results": results,
        "warnings": warnings,
        "recent_artifacts": _collect_recent_artifacts(Path(status["output_root"])),
        "doc_highlights": _doc_highlights_payload(doc_bundle),
        "source_priority": ["live_docs", "sidecar"],
    }


def _build_recap_payload(
    prepared: dict,
    mode: str,
    n_results: int,
    *,
    query_plan: list[dict] | None = None,
    doc_bundle: dict | None = None,
) -> tuple[dict, dict]:
    status = prepared["status"]
    doc_bundle = doc_bundle or _load_live_doc_bundle(Path(status["project_root"]))
    query_plan = query_plan or _select_recap_queries(doc_bundle, status["project"], mode)
    warnings = list(prepared["warnings"])
    results = _run_sidecar_queries(
        status,
        query_plan,
        n_results=n_results,
        warnings=warnings,
        curated_for_context=True,
    )
    phase = _extract_phase(doc_bundle)

    return doc_bundle, {
        "project": status["project"],
        "project_root": status["project_root"],
        "vault_root": status["vault_root"],
        "mode": mode,
        "synced": prepared["synced"],
        "sync_summary": prepared["sync_summary"],
        "state": status["state"],
        "stale": status["stale"],
        "reasons": status["stale_reasons"],
        "last_synced_at": status["last_synced_at"],
        "phase": phase,
        "current_chapter": _extract_field(doc_bundle, "chapter"),
        "current_arc": _extract_field(doc_bundle, "arc"),
        "doc_sources": {
            name: payload["path"]
            for name, payload in doc_bundle.items()
            if payload["exists"]
        },
        "sections": _build_recap_sections(doc_bundle, results, phase, mode),
        "queries_run": query_plan,
        "results": results,
        "warnings": warnings,
        "source_priority": ["live_docs", "sidecar"],
    }


def build_writing_context(
    vault_dir: str,
    project: str | None = None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
    sync: str = "if-needed",
    refresh_palace: bool = False,
    mode: str = "startup",
    n_results: int = 3,
) -> dict:
    if mode not in CONTEXT_MODES:
        raise ValueError(f"Unknown writing context mode: {mode}")

    prepared = prepare_writing_sidecar(
        vault_dir=vault_dir,
        project=project,
        out_dir=out_dir,
        codex_home=codex_home,
        config_path=config_path,
        brainstorm_paths=brainstorm_paths,
        audit_paths=audit_paths,
        discarded_paths=discarded_paths,
        palace_path=palace_path,
        runtime_root=runtime_root,
        sync=sync,
        refresh_palace=refresh_palace,
    )
    _, context_data = _build_context_payload(prepared, mode, n_results)
    return context_data


def render_writing_context(context_data: dict) -> str:
    lines = [
        "",
        "=" * 60,
        "  Writing Sidecar Context",
        "=" * 60,
        f"  Project: {context_data['project_root']}",
        f"  Mode:    {context_data['mode']}",
        f"  State:   {context_data['state'].upper()}",
    ]
    if context_data.get("phase"):
        lines.append(f"  Phase:   {context_data['phase']}")
    if context_data.get("current_chapter"):
        lines.append(f"  Chapter: {context_data['current_chapter']}")
    if context_data.get("current_arc"):
        lines.append(f"  Arc:     {context_data['current_arc']}")
    if context_data.get("last_synced_at"):
        lines.append(f"  Synced:  {context_data['last_synced_at']}")

    if context_data.get("warnings"):
        lines.append("\n  Warnings:")
        for warning in context_data["warnings"]:
            lines.append(f"    - {warning}")

    lines.append("\n  Live doc highlights:")
    for doc_name in ("current_notes", "current_chapter_notes", "story_so_far"):
        payload = context_data["doc_highlights"].get(doc_name)
        if not payload:
            continue
        lines.append(f"    {doc_name}:")
        for item in payload["highlights"][:4]:
            lines.append(f"      - {item}")

    if context_data.get("suggested_loadout"):
        lines.append("\n  Suggested loadout:")
        for item in context_data["suggested_loadout"]:
            lines.append(f"    - {item}")

    if context_data.get("recent_artifacts"):
        lines.append("\n  Recent sidecar artifacts:")
        for item in context_data["recent_artifacts"][:4]:
            lines.append(f"    - {item['room']}: {item['path']}")

    if context_data.get("results"):
        lines.append("\n  Sidecar evidence:")
        for packet in context_data["results"]:
            lines.append(f'    {packet["mode"]} -> "{packet["query"]}"')
            if not packet.get("results"):
                lines.append("      - no hits")
                continue
            for hit in packet["results"][:3]:
                lines.append(
                    f"      - {hit.get('room', '?')}: {hit.get('source_file', '?')} :: {_preview_text(hit.get('text', ''))}"
                )
    else:
        lines.append("\n  Sidecar evidence:")
        lines.append("    - no context hits were available")

    lines.extend(["", "=" * 60, ""])
    return "\n".join(lines)


def print_writing_context(context_data: dict):
    print(render_writing_context(context_data))


def build_writing_recap(
    vault_dir: str,
    project: str | None = None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
    sync: str = "if-needed",
    refresh_palace: bool = False,
    mode: str = "restart",
    n_results: int = 3,
) -> dict:
    if mode not in RECAP_MODES:
        raise ValueError(f"Unknown writing recap mode: {mode}")

    prepared = prepare_writing_sidecar(
        vault_dir=vault_dir,
        project=project,
        out_dir=out_dir,
        codex_home=codex_home,
        config_path=config_path,
        brainstorm_paths=brainstorm_paths,
        audit_paths=audit_paths,
        discarded_paths=discarded_paths,
        palace_path=palace_path,
        runtime_root=runtime_root,
        sync=sync,
        refresh_palace=refresh_palace,
    )
    _, recap_data = _build_recap_payload(prepared, mode, n_results)
    return recap_data


def render_writing_recap(recap_data: dict) -> str:
    lines = [
        "",
        "=" * 60,
        f"  Writing Sidecar Recap ({recap_data['mode']})",
        "=" * 60,
        f"  Project: {recap_data['project_root']}",
        f"  State:   {recap_data['state'].upper()}",
    ]
    if recap_data.get("phase"):
        lines.append(f"  Phase:   {recap_data['phase']}")
    if recap_data.get("current_chapter"):
        lines.append(f"  Chapter: {recap_data['current_chapter']}")
    if recap_data.get("current_arc"):
        lines.append(f"  Arc:     {recap_data['current_arc']}")

    if recap_data.get("warnings"):
        lines.append("\n  Warnings:")
        for warning in recap_data["warnings"]:
            lines.append(f"    - {warning}")

    for title, items in recap_data["sections"].items():
        lines.append(f"\n  {title}:")
        if not items:
            lines.append("    - none")
            continue
        for item in items:
            lines.append(f"    - {item}")

    if recap_data.get("results"):
        lines.append("\n  Sidecar evidence:")
        for packet in recap_data["results"]:
            lines.append(f'    {packet["mode"]} -> "{packet["query"]}"')
            if not packet.get("results"):
                lines.append("      - no hits")
                continue
            for hit in packet["results"][:3]:
                lines.append(
                    f"      - {hit.get('room', '?')}: {hit.get('source_file', '?')} :: {_preview_text(hit.get('text', ''))}"
                )

    lines.extend(["", "=" * 60, ""])
    return "\n".join(lines)


def print_writing_recap(recap_data: dict):
    print(render_writing_recap(recap_data))


def build_writing_session(
    vault_dir: str,
    project: str | None = None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
    sync: str = "if-needed",
    refresh_palace: bool = False,
    task: str = "startup",
    notes: Sequence[str] | None = None,
    write: bool = False,
    n_results: int = 3,
) -> dict:
    if task not in SESSION_TASKS:
        raise ValueError(f"Unknown writing session task: {task}")

    prepared = prepare_writing_sidecar(
        vault_dir=vault_dir,
        project=project,
        out_dir=out_dir,
        codex_home=codex_home,
        config_path=config_path,
        brainstorm_paths=brainstorm_paths,
        audit_paths=audit_paths,
        discarded_paths=discarded_paths,
        palace_path=palace_path,
        runtime_root=runtime_root,
        sync=sync,
        refresh_palace=refresh_palace,
    )
    status = prepared["status"]
    project_root = status["project_root"]
    doc_bundle = _load_live_doc_bundle(Path(project_root))

    recap_sections: dict[str, list[str]] = {}

    if task in {"startup", "planning", "audit"}:
        _, base = _build_context_payload(prepared, task, n_results, doc_bundle=doc_bundle)
    elif task in {"handoff", "closeout"}:
        _, recap = _build_recap_payload(prepared, "handoff", n_results, doc_bundle=doc_bundle)
        base = {
            "project": recap["project"],
            "project_root": recap["project_root"],
            "vault_root": recap["vault_root"],
            "mode": task,
            "synced": recap["synced"],
            "sync_summary": recap["sync_summary"],
            "state": recap["state"],
            "stale": recap["stale"],
            "reasons": recap["reasons"],
            "last_synced_at": recap["last_synced_at"],
            "phase": recap["phase"],
            "current_chapter": recap["current_chapter"],
            "current_arc": recap["current_arc"],
            "suggested_loadout": _derive_session_loadout(doc_bundle, recap["phase"], task),
            "queries_run": recap["queries_run"],
            "results": recap["results"],
            "warnings": recap["warnings"],
            "recent_artifacts": _collect_recent_artifacts(Path(status["output_root"])),
            "doc_highlights": _doc_highlights_payload(doc_bundle),
            "recap_sections": recap["sections"],
            "source_priority": recap["source_priority"],
        }
    else:
        query_plan = _select_session_queries(doc_bundle, status["project"], task)
        _, base = _build_context_payload(
            prepared,
            task,
            n_results,
            query_plan=query_plan,
            doc_bundle=doc_bundle,
        )
        base["suggested_loadout"] = _derive_session_loadout(doc_bundle, base["phase"], task)
        if task == "prose":
            recap_sections = _build_prose_session_sections(doc_bundle, base["results"])
            base["recap_sections"] = recap_sections

    if task in {"startup", "planning", "audit"}:
        base["suggested_loadout"] = _derive_session_loadout(doc_bundle, base["phase"], task)
    if task not in {"handoff", "closeout"}:
        base.setdefault("recap_sections", recap_sections)

    write_reports = []
    if write:
        write_reports = _perform_session_writes(
            task=task,
            vault_dir=vault_dir,
            project=project,
            out_dir=out_dir,
            codex_home=codex_home,
            config_path=config_path,
            brainstorm_paths=brainstorm_paths,
            audit_paths=audit_paths,
            discarded_paths=discarded_paths,
            palace_path=palace_path,
            runtime_root=runtime_root,
            sync=sync,
            notes=notes,
            results=base["results"],
        )

    final_status = base
    if write_reports:
        final_report = write_reports[-1]
        final_status = {
            **base,
            "state": final_report["state"],
            "stale": final_report["stale"],
            "reasons": final_report["reasons"],
            "last_synced_at": final_report["last_synced_at"],
            "warnings": _unique_lines(base["warnings"] + final_report["warnings"]),
        }
    else:
        final_status = {**base, "warnings": _unique_lines(base["warnings"])}

    project_root_path = Path(project_root)
    output_root = Path(status["output_root"])
    final_status["task"] = task
    final_status["recommended_actions"] = _build_session_recommended_actions(
        task=task,
        project_root=project_root_path,
        doc_bundle=doc_bundle,
        phase=final_status["phase"],
        suggested_loadout=final_status.get("suggested_loadout", []),
        results=final_status.get("results", []),
        write=write,
        notes=notes or [],
    )
    final_status["write_performed"] = bool(write_reports)
    final_status["paths_written"] = [
        path for report in write_reports for path in report.get("paths_written", [])
    ]
    final_status["sync_performed"] = bool(prepared["synced"] or any(report.get("sync_performed") for report in write_reports))
    final_status["sync_summary"] = next(
        (report.get("sync_summary") for report in reversed(write_reports) if report.get("sync_summary")),
        base.get("sync_summary"),
    )
    final_status["generated_sections"] = {
        key: value
        for report in write_reports
        for key, value in report.get("generated_sections", {}).items()
    }
    final_status["source_inputs"] = [
        item
        for report in write_reports
        for item in report.get("source_inputs", [])
    ]
    final_status["recent_artifacts"] = _collect_recent_artifacts(output_root)
    final_status["doc_highlights"] = _doc_highlights_payload(doc_bundle)
    final_status["source_priority"] = ["live_docs", "sidecar"]

    return final_status


def render_writing_session(session_data: dict) -> str:
    lines = [
        "",
        "=" * 60,
        f"  Writing Sidecar Session ({session_data['task']})",
        "=" * 60,
        f"  Project: {session_data['project_root']}",
        f"  State:   {session_data['state'].upper()}",
    ]
    if session_data.get("phase"):
        lines.append(f"  Phase:   {session_data['phase']}")
    if session_data.get("current_chapter"):
        lines.append(f"  Chapter: {session_data['current_chapter']}")
    if session_data.get("current_arc"):
        lines.append(f"  Arc:     {session_data['current_arc']}")
    if session_data.get("last_synced_at"):
        lines.append(f"  Synced:  {session_data['last_synced_at']}")

    if session_data.get("warnings"):
        lines.append("\n  Warnings:")
        for warning in session_data["warnings"]:
            lines.append(f"    - {warning}")

    if session_data.get("recommended_actions"):
        lines.append("\n  Recommended actions:")
        for action in session_data["recommended_actions"]:
            lines.append(f"    - {action}")

    if session_data.get("suggested_loadout"):
        lines.append("\n  Suggested loadout:")
        for item in session_data["suggested_loadout"]:
            lines.append(f"    - {item}")

    if session_data.get("recap_sections"):
        for title, items in session_data["recap_sections"].items():
            lines.append(f"\n  {title}:")
            if not items:
                lines.append("    - none")
                continue
            for item in items:
                lines.append(f"    - {item}")

    if session_data.get("paths_written"):
        lines.append("\n  Paths written:")
        for path in session_data["paths_written"]:
            lines.append(f"    - {path}")

    if session_data.get("results"):
        lines.append("\n  Sidecar evidence:")
        for packet in session_data["results"]:
            lines.append(f'    {packet["mode"]} -> "{packet["query"]}"')
            if not packet.get("results"):
                lines.append("      - no hits")
                continue
            for hit in packet["results"][:3]:
                lines.append(
                    f"      - {hit.get('room', '?')}: {hit.get('source_file', '?')} :: {_preview_text(hit.get('text', ''))}"
                )

    lines.extend(["", "=" * 60, ""])
    return "\n".join(lines)


def print_writing_session(session_data: dict):
    print(render_writing_session(session_data))


def maintain_writing_sidecar(
    vault_dir: str,
    kind: str,
    project: str | None = None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
    sync: str = "if-needed",
    slug: str | None = None,
    chapter: int | None = None,
    notes: Sequence[str] | None = None,
    write: bool = False,
    n_results: int = 3,
) -> dict:
    if kind not in MAINTAIN_KINDS:
        raise ValueError(f"Unknown writing maintain kind: {kind}")

    prepared = prepare_writing_sidecar(
        vault_dir=vault_dir,
        project=project,
        out_dir=out_dir,
        codex_home=codex_home,
        config_path=config_path,
        brainstorm_paths=brainstorm_paths,
        audit_paths=audit_paths,
        discarded_paths=discarded_paths,
        palace_path=palace_path,
        runtime_root=runtime_root,
        sync=sync,
        refresh_palace=False,
    )
    status = prepared["status"]
    project_root = Path(status["project_root"])
    doc_bundle = _load_live_doc_bundle(project_root)
    warnings = list(prepared["warnings"])
    clean_notes = _clean_note_list(notes or [])
    chapter_number = _resolve_chapter_number(project_root, doc_bundle, chapter)
    if chapter_number is None:
        raise ValueError(
            "Could not infer a chapter number for sidecar maintenance. Pass --chapter <n>."
        )

    artifacts = _build_maintenance_artifacts(
        kind=kind,
        status=status,
        doc_bundle=doc_bundle,
        notes=clean_notes,
        slug=slug,
        chapter_number=chapter_number,
        n_results=n_results,
        warnings=warnings,
    )

    paths_written: list[str] = []
    sync_performed = False
    sync_summary = prepared["sync_summary"]

    if write:
        for artifact in artifacts:
            artifact_path = Path(artifact["path"])
            _ensure_dir(artifact_path.parent)
            artifact_path.write_text(artifact["content"], encoding="utf-8")
            paths_written.append(str(artifact_path))

        if sync != "never":
            post = prepare_writing_sidecar(
                vault_dir=vault_dir,
                project=project,
                out_dir=out_dir,
                codex_home=codex_home,
                config_path=config_path,
                brainstorm_paths=brainstorm_paths,
                audit_paths=audit_paths,
                discarded_paths=discarded_paths,
                palace_path=palace_path,
                runtime_root=runtime_root,
                sync=sync,
                refresh_palace=False,
            )
            status = post["status"]
            sync_summary = post["sync_summary"]
            sync_performed = post["synced"]
            warnings.extend(post["warnings"])
        else:
            status = get_writing_sidecar_status(
                vault_dir=vault_dir,
                project=project,
                out_dir=out_dir,
                codex_home=codex_home,
                config_path=config_path,
                brainstorm_paths=brainstorm_paths,
                audit_paths=audit_paths,
                discarded_paths=discarded_paths,
                palace_path=palace_path,
                runtime_root=runtime_root,
            )

    source_inputs = _summarize_maintenance_sources(doc_bundle, artifacts, clean_notes)

    return {
        "project": status["project"],
        "project_root": status["project_root"],
        "vault_root": status["vault_root"],
        "kind": kind,
        "mode": "write" if write else "preview",
        "write_performed": write,
        "paths_written": paths_written,
        "sync_performed": sync_performed,
        "sync_summary": sync_summary,
        "state": status["state"],
        "stale": status["stale"],
        "reasons": status["stale_reasons"],
        "last_synced_at": status["last_synced_at"],
        "warnings": _unique_lines(warnings),
        "source_inputs": source_inputs,
        "generated_sections": {
            artifact["kind"]: list(artifact["sections"].keys()) for artifact in artifacts
        },
        "artifacts": artifacts,
    }


def render_writing_maintenance(report: dict) -> str:
    lines = [
        "",
        "=" * 60,
        f"  Writing Sidecar Maintain ({report['kind']})",
        "=" * 60,
        f"  Project: {report['project_root']}",
        f"  Mode:    {report['mode'].upper()}",
        f"  State:   {report['state'].upper()}",
    ]
    if report.get("last_synced_at"):
        lines.append(f"  Synced:  {report['last_synced_at']}")
    if report.get("warnings"):
        lines.append("\n  Warnings:")
        for warning in report["warnings"]:
            lines.append(f"    - {warning}")
    if report.get("paths_written"):
        lines.append("\n  Paths written:")
        for path in report["paths_written"]:
            lines.append(f"    - {path}")

    for artifact in report.get("artifacts", []):
        lines.append(f"\n  [{artifact['kind']}] {artifact['path']}")
        for title, items in artifact["sections"].items():
            lines.append(f"    {title}:")
            if not items:
                lines.append("      - none")
                continue
            for item in items:
                lines.append(f"      - {item}")
    lines.extend(["", "=" * 60, ""])
    return "\n".join(lines)


def print_writing_maintenance(report: dict):
    print(render_writing_maintenance(report))


def _build_prose_session_sections(doc_bundle: dict, results: list[dict]) -> dict[str, list[str]]:
    continuity_watch = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes", "story_so_far"),
            section_keywords=("threads carried forward", "continuity closeout", "locked decisions", "next start point"),
            keywords=("thread", "carry", "watch", "risk", "timeline", "continuity", "obligation"),
            max_items=5,
        )
        + _extract_story_memory_evidence(results, max_items=3)
    )
    if not continuity_watch:
        return {}
    return {"Continuity Watch": continuity_watch}


def _session_command(project_root: Path, task: str, *, write: bool = False) -> str:
    command = f'writing-sidecar session "{project_root}" --task {task}'
    if write:
        command += " --write"
    return command


def _build_session_recommended_actions(
    *,
    task: str,
    project_root: Path,
    doc_bundle: dict,
    phase: str | None,
    suggested_loadout: Sequence[str],
    results: list[dict],
    write: bool,
    notes: Sequence[str],
) -> list[str]:
    actions = []
    followup_task = _infer_followup_session_task(doc_bundle, phase)
    rejected_evidence = bool(notes or _extract_rejected_path_evidence(results, max_items=1))

    if suggested_loadout:
        actions.append("Open the suggested loadout before continuing.")

    if task == "startup":
        if not write:
            actions.append(f"Run `{_session_command(project_root, 'startup', write=True)}` once real work begins.")
        actions.append(f"Continue with `{_session_command(project_root, followup_task, write=True)}` when you move into the next real task.")
        actions.append("Use lower-level `search`, `context`, or `recap` only when the session packet is too broad or too thin.")
    elif task == "planning":
        if not write:
            actions.append(f"Run `{_session_command(project_root, 'planning', write=True)}` to checkpoint the current planning state.")
        actions.append("Keep live story-bible docs as canon; use sidecar hits only to explain prior decisions, pressure, and rejected options.")
        actions.append("Use `writing-sidecar search --mode planning` only when you need narrower follow-up evidence.")
    elif task == "prose":
        if not write:
            actions.append(f"Run `{_session_command(project_root, 'prose', write=True)}` when drafting starts or when the prose direction materially changes.")
        actions.append("Draft from live docs first and treat the continuity watch as advisory guardrails.")
        actions.append(f"Move to `{_session_command(project_root, 'audit')}` once the prose pass exists.")
    elif task == "audit":
        if not write:
            actions.append(f"Run `{_session_command(project_root, 'audit', write=True)}` to capture the audit state in sidecar-safe form.")
        actions.append(f"Move to `{_session_command(project_root, 'debug', write=True)}` when the dominant failure is clear.")
    elif task == "debug":
        if not write:
            actions.append(f"Run `{_session_command(project_root, 'debug', write=True)}` to preserve the repair pass.")
        if not rejected_evidence:
            actions.append("Add `--note \"...\"` if you reject a concrete structure and want it preserved in discarded_paths.")
        actions.append(f"Return to `{_session_command(project_root, 'audit')}` after the dominant failure is repaired.")
    elif task == "handoff":
        if not write:
            actions.append(f"Run `{_session_command(project_root, 'handoff', write=True)}` to refresh the handoff artifact before session end.")
        actions.append(f"Next session should start with `{_session_command(project_root, 'startup')}`.")
    elif task == "closeout":
        if not write:
            actions.append(f"Run `{_session_command(project_root, 'closeout', write=True)}` to archive the checkpoint, audit, and handoff bundle.")
        actions.append(f"Next session should start with `{_session_command(project_root, 'startup')}`.")

    return actions


def _perform_session_writes(
    *,
    task: str,
    vault_dir: str,
    project: str | None,
    out_dir: str | None,
    codex_home: str | None,
    config_path: str | None,
    brainstorm_paths,
    audit_paths,
    discarded_paths,
    palace_path: str | None,
    runtime_root: str | None,
    sync: str,
    notes: Sequence[str] | None,
    results: list[dict],
) -> list[dict]:
    kwargs = {
        "vault_dir": vault_dir,
        "project": project,
        "out_dir": out_dir,
        "codex_home": codex_home,
        "config_path": config_path,
        "brainstorm_paths": brainstorm_paths,
        "audit_paths": audit_paths,
        "discarded_paths": discarded_paths,
        "palace_path": palace_path,
        "runtime_root": runtime_root,
        "notes": notes,
        "write": True,
    }

    if task in {"startup", "planning", "prose"}:
        return [maintain_writing_sidecar(kind="checkpoint", sync=sync, **kwargs)]
    if task == "audit":
        return [maintain_writing_sidecar(kind="audit", sync=sync, **kwargs)]
    if task == "handoff":
        return [maintain_writing_sidecar(kind="handoff", sync=sync, **kwargs)]
    if task == "closeout":
        return [maintain_writing_sidecar(kind="closeout", sync=sync, **kwargs)]
    if task == "debug":
        reports = []
        should_write_discarded = bool(notes or _extract_rejected_path_evidence(results, max_items=1))
        reports.append(
            maintain_writing_sidecar(
                kind="audit",
                sync="never" if should_write_discarded else sync,
                **kwargs,
            )
        )
        if should_write_discarded:
            reports.append(
                maintain_writing_sidecar(
                    kind="discarded",
                    sync=sync,
                    **kwargs,
                )
            )
        return reports
    return []


def _clean_note_list(notes: Sequence[str]) -> list[str]:
    cleaned = []
    for note in notes:
        value = _clean_highlight_line(str(note or ""))
        if value:
            cleaned.append(value)
    return _unique_lines(cleaned)


def _resolve_chapter_number(
    project_root: Path,
    doc_bundle: dict,
    chapter_override: int | None,
) -> int | None:
    if chapter_override is not None:
        return int(chapter_override)

    for value in (
        _extract_field(doc_bundle, "chapter"),
        _extract_field(doc_bundle, "status"),
        _extract_field(doc_bundle, "next_action"),
    ):
        chapter_number = _extract_numeric_chapter(value)
        if chapter_number is not None:
            return chapter_number

    scan_roots = [
        project_root,
        project_root / "_story_bible" / "chapters",
        project_root / "logs" / "checkpoints",
        project_root / "logs" / "brainstorms",
        project_root / "logs" / "audits",
        project_root / "logs" / "discarded_paths",
    ]
    chapter_numbers = set()
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            number = _extract_numeric_chapter(path.name)
            if number is not None:
                chapter_numbers.add(number)
    return max(chapter_numbers) if chapter_numbers else None


def _extract_numeric_chapter(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(?:chapter[-\s_]*)?(\d+)", str(value), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_maintenance_artifacts(
    *,
    kind: str,
    status: dict,
    doc_bundle: dict,
    notes: list[str],
    slug: str | None,
    chapter_number: int,
    n_results: int,
    warnings: list[str],
) -> list[dict]:
    artifact_kinds = ["checkpoint", "audit", "handoff"]
    if kind == "closeout":
        if notes:
            artifact_kinds.append("discarded")
    else:
        artifact_kinds = [kind]

    return [
        _build_single_maintenance_artifact(
            artifact_kind=artifact_kind,
            status=status,
            doc_bundle=doc_bundle,
            notes=notes,
            slug=slug,
            chapter_number=chapter_number,
            n_results=n_results,
            warnings=warnings,
        )
        for artifact_kind in artifact_kinds
    ]


def _build_single_maintenance_artifact(
    *,
    artifact_kind: str,
    status: dict,
    doc_bundle: dict,
    notes: list[str],
    slug: str | None,
    chapter_number: int,
    n_results: int,
    warnings: list[str],
) -> dict:
    project_root = Path(status["project_root"])
    project_name = status["project"]
    date_stamp = datetime.now().astimezone().strftime("%Y-%m-%d")
    phase = _extract_phase(doc_bundle)
    current_status = _extract_field(doc_bundle, "status") or "TBD"
    next_action = _extract_field(doc_bundle, "next_action") or "TBD"
    working_title = _extract_field(doc_bundle, "working_title")

    query_plan = _select_maintain_queries(doc_bundle, project_name, artifact_kind)
    results = _run_sidecar_queries(
        status,
        query_plan,
        n_results=n_results,
        warnings=warnings,
        curated_for_context=True,
    )

    if artifact_kind == "checkpoint":
        chosen_slug = _artifact_slug(slug, fallback="session")
        path = _resolve_artifact_path(
            project_root / "logs" / "checkpoints",
            f"*_chapter-{chapter_number}_*_checkpoint.md",
            f"{date_stamp}_chapter-{chapter_number}_{chosen_slug}_checkpoint.md",
        )
        sections = _build_checkpoint_sections(doc_bundle, results, phase, notes)
        title = "Session Checkpoint"
        metadata = {
            "Project": project_name,
            "Chapter": f"{chapter_number}",
            "Date": date_stamp,
            "Context Mode": "startup",
        }
    elif artifact_kind == "audit":
        path = _resolve_artifact_path(
            project_root / "logs" / "audits",
            f"*_chapter-{chapter_number}_closeout_audit.md",
            f"{date_stamp}_chapter-{chapter_number}_closeout_audit.md",
        )
        sections = _build_audit_sections(doc_bundle, results, notes)
        title = "Chapter Closeout Audit"
        metadata = {
            "Project": project_name,
            "Chapter": f"{chapter_number}",
            "Title": working_title or "",
            "Date": date_stamp,
        }
    elif artifact_kind == "handoff":
        next_chapter = chapter_number + 1
        chosen_slug = _artifact_slug(
            slug or working_title or next_action,
            fallback="handoff",
        )
        path = _resolve_artifact_path(
            project_root / "logs" / "brainstorms",
            f"*_chapter-{next_chapter}_*_handoff.md",
            f"{date_stamp}_chapter-{next_chapter}_{chosen_slug}_handoff.md",
        )
        sections = _build_handoff_sections(doc_bundle, results, notes)
        title = "Chapter Handoff"
        metadata = {
            "Project": project_name,
            "Date": date_stamp,
            "Next Chapter": f"{next_chapter}",
        }
    else:
        chosen_slug = _artifact_slug(slug or next_action, fallback="discarded")
        discarded_support = _unique_lines(
            notes
            + _collect_keyword_evidence(
                doc_bundle,
                ("current_chapter_notes", "current_notes"),
                section_keywords=("open work", "chapter goals", "final checklist", "audit log"),
                keywords=("risk", "problem", "watch", "failed", "cut", "repeat", "avoid", "rejected"),
                max_items=5,
            )
            + _extract_rejected_path_evidence(results, max_items=4)
        )
        if not discarded_support:
            raise ValueError(
                "Discarded-path maintenance needs --note text or existing rejected-path evidence."
            )
        path = _resolve_artifact_path(
            project_root / "logs" / "discarded_paths",
            f"*_chapter-{chapter_number}_*_discarded.md",
            f"{date_stamp}_chapter-{chapter_number}_{chosen_slug}_discarded.md",
        )
        sections = _build_discarded_sections(doc_bundle, results, notes)
        title = "Discarded Path"
        metadata = {
            "Project": project_name,
            "Chapter": f"{chapter_number}",
            "Date": date_stamp,
        }

    content = _render_sidecar_artifact(title, metadata, sections)
    return {
        "kind": artifact_kind,
        "path": str(path),
        "title": title,
        "sections": sections,
        "content": content,
        "queries_run": query_plan,
        "results": results,
    }


def _select_maintain_queries(doc_bundle: dict, project: str, artifact_kind: str) -> list[dict]:
    if artifact_kind == "checkpoint":
        return _select_context_queries(doc_bundle, project, "startup")
    if artifact_kind == "audit":
        return [{"mode": "audit", "query": query} for query in _collect_mode_queries(doc_bundle, project, "audit")]
    if artifact_kind == "handoff":
        return _select_recap_queries(doc_bundle, project, "handoff")
    return [
        {
            "mode": "audit",
            "query": _pick_signal_query(
                doc_bundle,
                ("current_chapter_notes", "current_notes"),
                section_keywords=("open work", "chapter goals", "final checklist", "audit log"),
                field_names=("audit_status", "latest_score", "next_action"),
                keywords=("risk", "problem", "watch", "failed", "cut", "repeat"),
            )
            or _fallback_query(project, "audit"),
        },
        {
            "mode": "history",
            "query": _pick_signal_query(
                doc_bundle,
                ("current_chapter_notes", "current_notes", "story_so_far"),
                section_keywords=("threads carried forward", "locked decisions", "continuity closeout"),
                field_names=("status", "next_action"),
                keywords=("decision", "carry", "thread", "guardrail", "risk"),
            )
            or _fallback_query(project, "history"),
        },
    ]


def _build_checkpoint_sections(doc_bundle: dict, results: list[dict], phase: str | None, notes: list[str]) -> dict:
    session_state = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_notes", "current_chapter_notes"),
            field_names=("status", "phase", "arc", "chapter", "working_title", "next_action", "audit_status"),
            max_items=6,
        )
    )
    current_focus = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes"),
            section_keywords=("current focus", "what is actually ready", "chapter goals", "next start point", "open work"),
            max_items=5,
        )
    )
    carry_forward = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes", "story_so_far"),
            section_keywords=("threads carried forward", "locked decisions", "continuity closeout"),
            keywords=("decision", "carry", "watch", "risk", "guardrail", "thread"),
            max_items=4,
        )
        + _extract_story_memory_evidence(results, max_items=3)
    )
    return {
        "Session State": session_state,
        "Current Focus": current_focus,
        "Carry-Forward Threads": carry_forward,
        "Suggested Next Loadout": _derive_suggested_loadout(doc_bundle, phase),
        "Assistant Notes": notes,
        "Sources Used": _collect_artifact_sources(doc_bundle, results),
    }


def _build_audit_sections(doc_bundle: dict, results: list[dict], notes: list[str]) -> dict:
    audit_status = _extract_field(doc_bundle, "audit_status") or "IN_PROGRESS"
    latest_score = _extract_field(doc_bundle, "latest_score") or "TBD"
    status_text = _extract_field(doc_bundle, "status") or "TBD"
    next_action = _extract_field(doc_bundle, "next_action") or "Continue the audit/debug loop."
    issue_lines = _unique_lines(
        notes
        + _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes"),
            section_keywords=("open work", "chapter goals", "final checklist", "audit log"),
            keywords=("risk", "problem", "watch", "failed", "cut", "repeat"),
            max_items=5,
        )
        + _extract_rejected_path_evidence(results, max_items=4)
    )
    carry_forward = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes", "story_so_far"),
            section_keywords=("threads carried forward", "locked decisions", "continuity closeout"),
            keywords=("carry", "thread", "decision", "obligation", "watch"),
            max_items=5,
        )
        + _extract_story_memory_evidence(results, max_items=2)
    )
    return {
        "Final Result": [
            f"Final cold-audit score: {latest_score}",
            f"Result: {audit_status}",
            f"Status: {status_text}",
            f"Next practical step: {next_action}",
        ],
        "Audit Progression": notes or ["No extra audit progression notes were recorded in this pass."],
        "Main Problems That Had To Be Fixed": issue_lines,
        "What The Final Version Does Better": _section_from_docs(
            doc_bundle,
            ("current_notes", "current_chapter_notes"),
            section_keywords=("what is actually ready", "current focus"),
            keywords=("clear", "strong", "ready", "works", "better"),
            max_items=4,
        ),
        "Carry-Forward Threads Logged At Closeout": carry_forward,
        "Residual Non-Blocking Issues": issue_lines[:3],
        "Sources Used": _collect_artifact_sources(doc_bundle, results),
    }


def _build_handoff_sections(doc_bundle: dict, results: list[dict], notes: list[str]) -> dict:
    starting_position = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_notes", "current_chapter_notes"),
            section_keywords=("current focus", "what is actually ready", "cdlc status", "current phase"),
            field_names=("status", "phase", "arc", "chapter", "working_title"),
            max_items=6,
        )
    )
    opening_pressures = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes"),
            section_keywords=("next start point", "chapter goals", "open work", "threads carried forward"),
            keywords=("next", "pressure", "threat", "guard", "watch", "risk", "open"),
            max_items=5,
        )
        + _extract_story_memory_evidence(results, max_items=3)
    )
    guardrails = _unique_lines(
        notes
        + _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes"),
            section_keywords=("open work", "chapter goals", "final checklist", "threads carried forward"),
            keywords=("guardrail", "risk", "watch", "must", "avoid", "don't", "do not"),
            max_items=5,
        )
        + _extract_rejected_path_evidence(results, max_items=3)
    )
    best_material = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes"),
            section_keywords=("next start point", "current focus", "what is actually ready"),
            max_items=5,
        )
        + _extract_story_memory_evidence(results, max_items=3)
    )
    return {
        "Starting Position": starting_position,
        "Core Opening Pressures": opening_pressures,
        "Useful Scene Questions": notes,
        "Guardrails": guardrails,
        "Best Immediate Scene Material": best_material,
        "Sources Used": _collect_artifact_sources(doc_bundle, results),
    }


def _build_discarded_sections(doc_bundle: dict, results: list[dict], notes: list[str]) -> dict:
    rejected = _unique_lines(notes + _extract_rejected_path_evidence(results, max_items=4))
    why_rejected = _unique_lines(
        _collect_keyword_evidence(
            doc_bundle,
            ("current_chapter_notes", "current_notes"),
            section_keywords=("open work", "chapter goals", "final checklist", "audit log"),
            keywords=("risk", "problem", "watch", "failed", "cut", "repeat", "avoid"),
            max_items=5,
        )
        + _extract_rejected_path_evidence(results, max_items=4)
    )
    keep_instead = _unique_lines(
        _section_from_docs(
            doc_bundle,
            ("current_chapter_notes", "current_notes"),
            section_keywords=("next start point", "threads carried forward", "locked decisions"),
            keywords=("keep", "instead", "next", "carry", "decision", "thread"),
            max_items=5,
        )
        + _extract_story_memory_evidence(results, max_items=2)
    )
    retrieval_terms = _derive_retrieval_terms(notes, results)
    return {
        "Rejected Version": rejected,
        "Why It Was Rejected": why_rejected,
        "Keep Instead": keep_instead,
        "Retrieval Terms Worth Keeping": retrieval_terms,
        "Sources Used": _collect_artifact_sources(doc_bundle, results),
    }


def _derive_retrieval_terms(notes: list[str], results: list[dict], max_items: int = 5) -> list[str]:
    terms = []
    seen = set()
    for value in list(notes) + [packet.get("query", "") for packet in results]:
        condensed = _condense_query(value)
        normalized = _normalize_text(condensed)
        if not condensed or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(condensed)
        if len(terms) >= max_items:
            return terms
    return terms


def _collect_artifact_sources(doc_bundle: dict, results: list[dict], max_items: int = 8) -> list[str]:
    sources = []
    seen = set()
    for doc_name in ("current_notes", "current_chapter_notes", "story_so_far"):
        payload = doc_bundle.get(doc_name, {})
        if not payload.get("exists"):
            continue
        doc_path = Path(payload["path"])
        project_root = doc_path.parents[1] if "_story_bible" in payload["path"] else doc_path.parent
        entry = _normalize_project_source(payload["path"], project_root)
        normalized = _normalize_text(entry)
        if normalized not in seen:
            seen.add(normalized)
            sources.append(entry)
    for packet in results:
        for hit in packet.get("results", []):
            source = f"sidecar:{hit.get('room', '?')}:{hit.get('source_file', '?')}"
            normalized = _normalize_text(source)
            if normalized in seen:
                continue
            seen.add(normalized)
            sources.append(source)
            if len(sources) >= max_items:
                return sources
    return sources


def _summarize_maintenance_sources(doc_bundle: dict, artifacts: list[dict], notes: list[str]) -> dict:
    live_docs = {
        name: payload["path"]
        for name, payload in doc_bundle.items()
        if payload.get("exists")
    }
    queries_run = []
    query_seen = set()
    result_sources = []
    source_seen = set()
    for artifact in artifacts:
        for query in artifact.get("queries_run", []):
            key = (query.get("mode"), query.get("query"))
            if key in query_seen:
                continue
            query_seen.add(key)
            queries_run.append(query)
        for packet in artifact.get("results", []):
            for hit in packet.get("results", []):
                key = (hit.get("room"), hit.get("source_file"))
                if key in source_seen:
                    continue
                source_seen.add(key)
                result_sources.append({"room": hit.get("room"), "source_file": hit.get("source_file")})
    return {
        "live_docs": live_docs,
        "notes": notes,
        "queries_run": queries_run,
        "sidecar_sources": result_sources,
    }


def _artifact_slug(value: str | None, fallback: str) -> str:
    cleaned = _safe_name(_normalize_heading_key(value or fallback).replace(" ", "_"))
    return cleaned or fallback


def _resolve_artifact_path(directory: Path, glob_pattern: str, filename: str) -> Path:
    if directory.exists():
        matches = sorted(
            directory.glob(glob_pattern),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        if matches:
            return matches[0]
    return directory / filename


def _render_sidecar_artifact(title: str, metadata: dict[str, str], sections: dict[str, list[str]]) -> str:
    lines = [f"# {title}", ""]
    for label, value in metadata.items():
        lines.append(f"{label}: {value}")
    lines.append("")
    for heading, items in sections.items():
        lines.append(f"## {heading}")
        lines.append("")
        if not items:
            lines.append("- none")
        else:
            for item in items:
                lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _unique_lines(items: Sequence[str]) -> list[str]:
    unique = []
    seen = set()
    for item in items:
        cleaned = _clean_highlight_line(str(item or ""))
        normalized = _normalize_text(cleaned)
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(cleaned)
    return unique


def _normalize_project_source(path: str, project_root: Path) -> str:
    try:
        relative = Path(path).resolve().relative_to(project_root.resolve())
        return str(relative).replace("\\", "/")
    except Exception:
        return str(path)


def _load_live_doc_bundle(project_root: Path) -> dict:
    bundle = {}
    for name, relative_path in DOC_RELATIVE_PATHS.items():
        path = project_root / relative_path
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        structure = _parse_markdown_doc(text)
        bundle[name] = {
            "path": str(path),
            "exists": path.exists(),
            "text": text,
            "highlights": structure["highlights"],
            "fields": structure["fields"],
            "sections": structure["sections"],
        }
    return bundle


def _parse_markdown_doc(text: str, max_items: int = 8) -> dict:
    fields = {}
    sections = {"_root": []}
    current_section = "_root"
    in_code = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        if stripped.startswith("#"):
            current_section = _clean_highlight_line(stripped.lstrip("#").strip()) or "_root"
            sections.setdefault(current_section, [])
            continue
        for item in _extract_structured_line_items(stripped):
            cleaned = _clean_highlight_line(item)
            if not cleaned or len(cleaned) < 4 or _is_low_value_doc_line(cleaned):
                continue
            label, value = _split_labeled_line(cleaned)
            if label and value:
                field_key = _canonical_field_key(label)
                fields.setdefault(field_key, []).append(
                    {
                        "label": label,
                        "value": value,
                        "line": f"{label}: {value}",
                    }
                )
                sections.setdefault(current_section, []).append(f"{label}: {value}")
            else:
                sections.setdefault(current_section, []).append(cleaned)
    return {
        "fields": fields,
        "sections": sections,
        "highlights": _select_structured_highlights(fields, sections, max_items=max_items),
    }


def _extract_markdown_highlights(text: str, max_items: int = 8) -> list[str]:
    return _parse_markdown_doc(text, max_items=max_items)["highlights"]


def _extract_structured_line_items(stripped: str) -> list[str]:
    if re.fullmatch(r"[:\-\s|]+", stripped):
        return []
    if not stripped.startswith("|"):
        return [stripped]
    return _parse_table_row(stripped)


def _parse_table_row(stripped: str) -> list[str]:
    cells = [
        _clean_highlight_line(cell)
        for cell in stripped.strip().strip("|").split("|")
    ]
    cells = [cell for cell in cells if cell]
    if not cells:
        return []
    if all(re.fullmatch(r"[-:]+", cell.replace(" ", "")) for cell in cells):
        return []
    header_terms = {
        "file",
        "status",
        "thread",
        "notes",
        "date",
        "score",
        "result",
        "dominant problem",
        "words written",
        "pov",
        "location",
        "purpose",
    }
    normalized_cells = {_normalize_heading_key(cell) for cell in cells}
    if normalized_cells and normalized_cells.issubset(header_terms):
        return []
    return [" — ".join(cells[:3])]


def _clean_highlight_line(line: str) -> str:
    cleaned = re.sub(r"^\s*>+\s*", "", line)
    cleaned = re.sub(r"^\s*\[[ xX]\]\s+", "", cleaned)
    cleaned = re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" -")


def _is_low_value_doc_line(line: str) -> bool:
    lowered = _normalize_heading_key(line)
    if any(lowered.startswith(_normalize_heading_key(prefix)) for prefix in LOW_VALUE_LINE_PREFIXES):
        return True
    return any(_normalize_heading_key(fragment) in lowered for fragment in LOW_VALUE_LINE_SUBSTRINGS)


def _split_labeled_line(line: str) -> tuple[str | None, str | None]:
    match = re.match(r"^(?P<label>[A-Za-z][A-Za-z0-9 /'()_-]+):\s*(?P<value>.+)$", line)
    if not match:
        return None, None
    return match.group("label").strip(), match.group("value").strip()


def _normalize_heading_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _canonical_field_key(label: str) -> str:
    normalized = _normalize_heading_key(label)
    for field_name, labels in FIELD_LABELS.items():
        if any(_normalize_heading_key(candidate) == normalized for candidate in labels):
            return field_name
    return normalized.replace(" ", "_")


def _section_matches(title: str, keywords: Sequence[str]) -> bool:
    if not keywords:
        return True
    normalized_title = _normalize_heading_key(title)
    return any(_normalize_heading_key(keyword) in normalized_title for keyword in keywords)


def _select_structured_highlights(fields: dict, sections: dict, max_items: int = 8) -> list[str]:
    highlights = []
    seen = set()

    def add(item: str):
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        highlights.append(item)

    for field_name in STRUCTURED_HIGHLIGHT_FIELDS:
        for entry in fields.get(field_name, []):
            add(entry["line"])
            if len(highlights) >= max_items:
                return highlights

    for keyword in PREFERRED_SECTION_KEYWORDS:
        for title, items in sections.items():
            if not _section_matches(title, (keyword,)):
                continue
            for item in items:
                add(item)
                if len(highlights) >= max_items:
                    return highlights

    for items in sections.values():
        for item in items:
            add(item)
            if len(highlights) >= max_items:
                return highlights
    return highlights


def _iter_signal_candidates(
    doc_bundle: dict,
    doc_order: Sequence[str],
    *,
    section_keywords: Sequence[str] = (),
    field_names: Sequence[str] = (),
) -> Iterable[str]:
    seen = set()
    for doc_name in doc_order:
        payload = doc_bundle.get(doc_name, {})
        for field_name in field_names:
            for entry in payload.get("fields", {}).get(field_name, []):
                normalized = _normalize_text(entry["line"])
                if normalized in seen:
                    continue
                seen.add(normalized)
                yield entry["line"]
        section_items = payload.get("sections", {})
        yielded_titles = set()
        for keyword in section_keywords:
            for title, items in section_items.items():
                if title in yielded_titles or not _section_matches(title, (keyword,)):
                    continue
                yielded_titles.add(title)
                for item in items:
                    normalized = _normalize_text(item)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    yield item
        if not section_keywords:
            for title, items in section_items.items():
                for item in items:
                    normalized = _normalize_text(item)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    yield item
        for item in payload.get("highlights", []):
            normalized = _normalize_text(item)
            if normalized in seen:
                continue
            seen.add(normalized)
            yield item


def _collect_section_lines(
    doc_bundle: dict,
    doc_order: Sequence[str],
    *,
    section_keywords: Sequence[str] = (),
    field_names: Sequence[str] = (),
    keywords: Sequence[str] = (),
    max_items: int = 5,
    exclude: set[str] | None = None,
) -> list[str]:
    items = []
    seen = set(exclude or set())
    keyword_set = tuple(keyword.lower() for keyword in keywords)
    for candidate in _iter_signal_candidates(
        doc_bundle,
        doc_order,
        section_keywords=section_keywords,
        field_names=field_names,
    ):
        cleaned = _clean_highlight_line(candidate)
        if not cleaned:
            continue
        normalized = _normalize_text(cleaned)
        if normalized in seen:
            continue
        if keyword_set and not any(keyword in cleaned.lower() for keyword in keyword_set):
            continue
        seen.add(normalized)
        items.append(cleaned)
        if len(items) >= max_items:
            return items
    if items or not keywords:
        return items
    return _collect_section_lines(
        doc_bundle,
        doc_order,
        section_keywords=section_keywords,
        field_names=field_names,
        max_items=max_items,
        exclude=exclude,
    )


def _extract_field(doc_bundle: dict, field_name: str) -> str | None:
    canonical = _canonical_field_key(field_name)
    labels = FIELD_LABELS[field_name]
    for doc_name in ("current_chapter_notes", "current_notes", "story_so_far"):
        payload = doc_bundle.get(doc_name, {})
        for entry in payload.get("fields", {}).get(canonical, []):
            value = entry.get("value")
            if value:
                return value
        text = doc_bundle[doc_name]["text"]
        if not text:
            continue
        for raw_line in text.splitlines():
            cleaned = _clean_highlight_line(raw_line)
            lowered = cleaned.lower()
            for label in labels:
                prefix = f"{label.lower()}:"
                if lowered.startswith(prefix):
                    return cleaned[len(label) + 1 :].strip()
    return None


def _extract_phase(doc_bundle: dict) -> str | None:
    phase = _extract_field(doc_bundle, "phase")
    return phase.upper() if phase else None


def _select_context_queries(doc_bundle: dict, project: str, mode: str) -> list[dict]:
    if mode == "startup":
        planning_query = _pick_signal_query(
            doc_bundle,
            ("current_chapter_notes", "current_notes"),
            section_keywords=(
                "next start point",
                "threads carried forward",
                "chapter goals",
                "open work",
                "recommended next loadout",
            ),
            field_names=("next_action", "status"),
            keywords=(
                "atlantis",
                "chapter 2",
                "guardrail",
                "physician",
                "sphere",
                "guardian",
                "sponsorship",
                "medical",
                "protection",
                "mera",
            ),
        ) or _fallback_query(project, "planning")
        history_query = _pick_signal_query(
            doc_bundle,
            ("current_chapter_notes", "current_notes", "story_so_far"),
            section_keywords=("threads carried forward", "continuity closeout", "locked decisions"),
            field_names=("status", "audit_status"),
            keywords=(
                "sponsorship",
                "investigation",
                "timing",
                "search",
                "guardian",
                "decision",
                "thread",
                "carry",
                "arthur",
                "ciri",
                "bruce",
                "barry",
                "darkseid",
            ),
            exclude={planning_query},
        ) or _fallback_query(project, "history")
        return [
            {"mode": "planning", "query": planning_query},
            {"mode": "history", "query": history_query},
        ]

    return [
        {"mode": mode, "query": query}
        for query in _collect_mode_queries(doc_bundle, project, mode)
    ]


def _select_recap_queries(doc_bundle: dict, project: str, mode: str) -> list[dict]:
    if mode == "restart":
        return _select_context_queries(doc_bundle, project, "startup")
    if mode == "handoff":
        return [
            {
                "mode": "planning",
                "query": _pick_signal_query(
                    doc_bundle,
                    ("current_chapter_notes", "current_notes"),
                    section_keywords=("next start point", "chapter goals", "open work"),
                    field_names=("next_action",),
                )
                or _fallback_query(project, "planning"),
            },
            {
                "mode": "history",
                "query": _pick_signal_query(
                    doc_bundle,
                    ("current_chapter_notes", "current_notes", "story_so_far"),
                    section_keywords=("threads carried forward", "locked decisions", "continuity closeout"),
                    field_names=("status",),
                    keywords=("decision", "carry", "thread", "sponsorship", "search", "investigation"),
                )
                or _fallback_query(project, "history"),
            },
            {
                "mode": "audit",
                "query": _pick_signal_query(
                    doc_bundle,
                    ("current_chapter_notes", "current_notes"),
                    section_keywords=("open work", "chapter goals", "final checklist", "audit log"),
                    field_names=("audit_status", "latest_score"),
                    keywords=("risk", "problem", "watch", "failed", "cut", "repeat"),
                )
                or _fallback_query(project, "audit"),
            },
        ]
    return [
        {
            "mode": "history",
            "query": _pick_signal_query(
                doc_bundle,
                ("story_so_far", "current_notes", "current_chapter_notes"),
                section_keywords=("continuity closeout", "threads carried forward"),
                field_names=("status",),
                keywords=("timeline", "after", "before", "chronology", "status", "carry"),
            )
            or _fallback_query(project, "history"),
        },
        {
            "mode": "research",
            "query": _pick_signal_query(
                doc_bundle,
                ("story_so_far", "current_notes"),
                section_keywords=("locked decisions", "what is actually ready"),
                keywords=("world", "rule", "location", "reference", "canon"),
            )
            or _fallback_query(project, "research"),
        },
    ]


def _select_session_queries(doc_bundle: dict, project: str, task: str) -> list[dict]:
    if task == "prose":
        planning_query = _collect_mode_queries(doc_bundle, project, "planning")[0]
        history_query = _collect_mode_queries(doc_bundle, project, "history")[0]
        return [
            {"mode": "planning", "query": planning_query},
            {"mode": "history", "query": history_query},
        ]
    if task == "debug":
        audit_query = _collect_mode_queries(doc_bundle, project, "audit")[0]
        history_query = _collect_mode_queries(doc_bundle, project, "history")[0]
        return [
            {"mode": "audit", "query": audit_query},
            {"mode": "history", "query": history_query},
        ]
    raise ValueError(f"Unknown writing session query task: {task}")


def _collect_mode_queries(doc_bundle: dict, project: str, mode: str) -> list[str]:
    mode_specs = {
        "planning": {
            "doc_order": ("current_chapter_notes", "current_notes"),
            "section_keywords": (
                "next start point",
                "threads carried forward",
                "chapter goals",
                "open work",
                "recommended next loadout",
            ),
            "field_names": ("next_action", "status"),
            "keywords": ("next", "guardrail", "scene", "beat", "watch", "risk", "atlantis", "chapter 2"),
        },
        "audit": {
            "doc_order": ("current_chapter_notes", "current_notes"),
            "section_keywords": ("final checklist", "audit log", "open work", "chapter goals"),
            "field_names": ("audit_status", "latest_score"),
            "keywords": ("risk", "problem", "watch", "failed", "cut", "repeat"),
        },
        "history": {
            "doc_order": ("current_chapter_notes", "current_notes", "story_so_far"),
            "section_keywords": ("threads carried forward", "continuity closeout", "locked decisions"),
            "field_names": ("status",),
            "keywords": ("decision", "resolved", "carry", "status", "thread", "history"),
        },
        "research": {
            "doc_order": ("story_so_far", "current_notes"),
            "section_keywords": ("locked decisions", "what is actually ready"),
            "field_names": (),
            "keywords": ("world", "rule", "location", "reference", "canon"),
        },
    }
    spec = mode_specs[mode]
    queries = []
    seen = set()
    preferred = _pick_signal_query(
        doc_bundle,
        spec["doc_order"],
        section_keywords=spec["section_keywords"],
        field_names=spec["field_names"],
        keywords=spec["keywords"],
    )
    if preferred:
        seen.add(preferred)
        queries.append(preferred)
    secondary = _pick_signal_query(
        doc_bundle,
        spec["doc_order"],
        section_keywords=spec["section_keywords"],
        field_names=spec["field_names"],
        exclude=seen,
    )
    if secondary and secondary not in seen:
        queries.append(secondary)
    if not queries:
        queries.append(_fallback_query(project, mode))
    return queries


def _pick_signal_query(
    doc_bundle: dict,
    doc_order: Sequence[str],
    *,
    section_keywords: Sequence[str] = (),
    field_names: Sequence[str] = (),
    keywords: Sequence[str] = (),
    exclude: set[str] | None = None,
) -> str | None:
    exclude = exclude or set()
    keyword_set = tuple(keyword.lower() for keyword in keywords)
    fallback = None
    for item in _iter_signal_candidates(
        doc_bundle,
        doc_order,
        section_keywords=section_keywords,
        field_names=field_names,
    ):
        condensed = _condense_query(item)
        if not condensed or condensed in exclude:
            continue
        lowered = condensed.lower()
        if keyword_set and any(keyword in lowered for keyword in keyword_set):
            return condensed
        if fallback is None:
            fallback = condensed
    return fallback


def _condense_query(text: str) -> str:
    cleaned = _clean_highlight_line(text)
    if not cleaned or _is_low_value_doc_line(cleaned):
        return ""
    _, value = _split_labeled_line(cleaned)
    cleaned = value or cleaned
    cleaned = re.split(r"\s+[—-]\s+", cleaned, maxsplit=1)[0]
    cleaned = re.split(r"\s*(?:,|;|\bthen\b|\bbut\b)\s*", cleaned, maxsplit=1)[0]
    words = [word for word in cleaned.split() if not re.fullmatch(r"[`*_]+", word)]
    if words and words[0].lower() in QUERY_STOP_LEADS:
        words = words[1:]
    cleaned = " ".join(words).strip(" ,;:-")
    if len(cleaned.split()) > 12:
        cleaned = " ".join(cleaned.split()[:12])
    return cleaned[:160].rstrip(" ,;:")


def _fallback_query(project: str, mode: str) -> str:
    suffix = {
        "planning": "handoff",
        "audit": "audit",
        "history": "decision history",
        "research": "reference",
    }[mode]
    return f"{project} {suffix}"


def _run_sidecar_queries(
    status: dict,
    query_plan: list[dict],
    n_results: int,
    warnings: list[str],
    curated_for_context: bool = False,
) -> list[dict]:
    palace_path = Path(status["palace_path"])
    if not palace_path.exists():
        warnings.append(
            "No sidecar palace exists yet. Run writing-sidecar sync if this task depends on sidecar retrieval."
        )
        return []

    packets = []
    with _sidecar_runtime_environment(Path(status["runtime_root"])):
        for item in query_plan:
            packet = search_writing_sidecar(
                query=item["query"],
                palace_path=str(palace_path),
                wing=_project_wing(status["project"]),
                mode=item["mode"],
                n_results=n_results,
            )
            if packet.get("error"):
                warnings.append(f"Search error for {item['mode']}: {packet['error']}")
                continue
            if curated_for_context:
                packet = _curate_query_packet(packet)
            packets.append(packet)
    return packets


def _curate_query_packet(packet: dict) -> dict:
    results = list(packet.get("results", []))
    if not results:
        return packet

    deduped = []
    seen = set()
    for hit in results:
        preview = _preview_text(hit.get("text", ""), max_words=18)
        key = (hit.get("source_file"), _normalize_text(preview))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)

    if packet.get("mode") == "history" and any(hit.get("room") != "chat_process" for hit in deduped):
        preferred_rooms = {
            "checkpoints": 0,
            "audits": 1,
            "brainstorms": 2,
            "discarded_paths": 3,
            "archived_notes": 4,
            "chat_process": 5,
        }
        deduped = [
            hit
            for _, hit in sorted(
                enumerate(deduped),
                key=lambda item: (preferred_rooms.get(item[1].get("room"), 99), item[0]),
            )
        ]

    packet["results"] = deduped
    return packet


def _extract_recommended_loadout(doc_bundle: dict, derived_phase: str | None) -> list[str]:
    payload = doc_bundle.get("current_notes", {})
    for title, lines in payload.get("sections", {}).items():
        if not _section_matches(title, ("recommended next loadout",)):
            continue
        items = []
        collecting = derived_phase in {"BRAINDUMP", "SCRIPTING", "STAGING", "PROSE"}
        for line in lines:
            cleaned = _clean_highlight_line(line)
            lowered = _normalize_heading_key(cleaned)
            if cleaned.endswith(":"):
                if derived_phase in {"BRAINDUMP", "SCRIPTING", "STAGING"}:
                    collecting = "planning" in lowered and not any(
                        token in lowered for token in ("prose", "draft", "generation")
                    )
                elif derived_phase == "PROSE":
                    collecting = any(token in lowered for token in ("prose", "draft", "generation"))
                else:
                    collecting = False
                continue
            if collecting and cleaned not in items:
                items.append(cleaned)
        if items:
            return items
    return []


def _derive_target_phase(doc_bundle: dict, phase: str | None) -> str | None:
    status_text = _extract_field(doc_bundle, "status") or ""
    next_action = _extract_field(doc_bundle, "next_action") or ""
    combined = f"{status_text} {next_action}".lower()
    if any(token in combined for token in ("planning", "plan", "scene design", "sequencing", "structure")):
        return "SCRIPTING"
    if any(token in combined for token in ("draft", "write", "prose")):
        return "PROSE"
    return phase


def _derive_suggested_loadout(doc_bundle: dict, phase: str | None) -> list[str]:
    target_phase = _derive_target_phase(doc_bundle, phase)
    explicit = _extract_recommended_loadout(doc_bundle, target_phase)
    if explicit:
        return explicit
    return PHASE_LOADOUT.get(target_phase or "", PHASE_LOADOUT.get(phase or "", []))


def _derive_session_loadout(doc_bundle: dict, phase: str | None, task: str) -> list[str]:
    if task == "startup":
        return _derive_suggested_loadout(doc_bundle, phase)

    target_phase = {
        "planning": "SCRIPTING",
        "prose": "PROSE",
        "audit": "AUDIT",
        "debug": "DEBUG",
        "handoff": _derive_target_phase(doc_bundle, phase) or phase,
        "closeout": "COMPLETE",
    }.get(task, phase)
    explicit = _extract_recommended_loadout(doc_bundle, target_phase)
    if explicit:
        return explicit
    return PHASE_LOADOUT.get(target_phase or "", PHASE_LOADOUT.get(phase or "", []))


def _infer_followup_session_task(doc_bundle: dict, phase: str | None) -> str:
    target_phase = _derive_target_phase(doc_bundle, phase)
    if target_phase in {"BRAINDUMP", "SCRIPTING", "STAGING"}:
        return "planning"
    if target_phase == "PROSE":
        return "prose"
    if target_phase == "AUDIT":
        return "audit"
    if target_phase == "DEBUG":
        return "debug"
    if phase == "COMPLETE":
        return "closeout"
    return "planning"


def _collect_recent_artifacts(output_root: Path, limit: int = 5) -> list[dict]:
    if not output_root.exists():
        return []
    items = []
    for room in ("checkpoints", "brainstorms", "audits", "discarded_paths", "chat_process"):
        room_dir = output_root / room
        if not room_dir.exists():
            continue
        for path in room_dir.rglob("*"):
            if not path.is_file():
                continue
            stat = path.stat()
            items.append(
                {
                    "room": room,
                    "path": str(path.relative_to(output_root)),
                    "mtime": stat.st_mtime,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                }
            )
    items.sort(key=lambda item: item["mtime"], reverse=True)
    return items[:limit]


def _build_recap_sections(doc_bundle: dict, results: list[dict], phase: str | None, mode: str) -> dict:
    used = set()

    def reserve(items: list[str]) -> list[str]:
        kept = []
        for item in items:
            normalized = _normalize_text(item)
            if not normalized or normalized in used:
                continue
            used.add(normalized)
            kept.append(item)
        return kept

    if mode == "restart":
        where_we_are = reserve(
            _section_from_docs(
                doc_bundle,
                ("current_notes", "current_chapter_notes"),
                section_keywords=DOC_SECTION_HINTS["startup_where"],
                field_names=("status", "phase", "arc", "chapter", "working_title", "next_action"),
                max_items=6,
            )
        )
        must_not_forget = reserve(
            _section_from_docs(
                doc_bundle,
                ("current_chapter_notes", "current_notes", "story_so_far"),
                section_keywords=DOC_SECTION_HINTS["startup_memory"],
                keywords=("decision", "carry", "watch", "risk", "guardrail", "must", "thread"),
                max_items=5,
                exclude=used,
            )
            + _extract_story_memory_evidence(results, max_items=3)
        )
        return {
            "Where We Are": where_we_are,
            "Must Not Forget": must_not_forget,
            "Suggested Next Loadout": _derive_suggested_loadout(doc_bundle, phase),
        }
    if mode == "handoff":
        current_state = reserve(
            _section_from_docs(
                doc_bundle,
                ("current_notes", "current_chapter_notes"),
                section_keywords=DOC_SECTION_HINTS["handoff_state"],
                field_names=("status", "phase", "arc", "chapter", "working_title"),
                max_items=6,
            )
        )
        carry_forward = reserve(
            _section_from_docs(
                doc_bundle,
                ("current_chapter_notes", "current_notes", "story_so_far"),
                section_keywords=("threads carried forward", "locked decisions", "continuity closeout"),
                keywords=("decision", "resolved", "carry", "status", "thread"),
                max_items=5,
                exclude=used,
            )
        )
        active_risks = reserve(
            _section_from_docs(
                doc_bundle,
                ("current_chapter_notes", "current_notes"),
                section_keywords=DOC_SECTION_HINTS["handoff_risks"],
                keywords=("risk", "watch", "problem", "danger", "issue"),
                max_items=5,
                exclude=used,
            )
        )
        open_threads = reserve(
            _section_from_docs(
                doc_bundle,
                ("current_notes", "current_chapter_notes", "story_so_far"),
                section_keywords=("next start point", "threads carried forward", "open work"),
                keywords=("next", "open", "pending", "thread", "todo", "tbd"),
                max_items=5,
                exclude=used,
            )
        )
        return {
            "Current State": current_state,
            "Carry-Forward Decisions": carry_forward,
            "Active Risks": active_risks,
            "Open Threads": open_threads,
            "Rejected Paths": _extract_rejected_path_evidence(results, max_items=5),
        }
    timeline_facts = reserve(
        _section_from_docs(
            doc_bundle,
            ("story_so_far", "current_chapter_notes", "current_notes"),
            section_keywords=DOC_SECTION_HINTS["continuity_facts"],
            field_names=("status",),
            keywords=("timeline", "before", "after", "chronology", "state", "status", "carry"),
            max_items=5,
        )
    )
    unresolved = reserve(
        _section_from_docs(
            doc_bundle,
            ("current_notes", "current_chapter_notes"),
            section_keywords=("open work", "next start point", "threads carried forward"),
            keywords=("must", "need", "owe", "pending", "next", "unresolved"),
            max_items=5,
            exclude=used,
        )
    )
    return {
        "Timeline-Sensitive Facts": timeline_facts,
        "Unresolved Obligations": unresolved,
        "Continuity Risks": _extract_rejected_path_evidence(results, max_items=5),
    }


def _section_from_docs(
    doc_bundle: dict,
    doc_order: Sequence[str],
    *,
    section_keywords: Sequence[str] = (),
    field_names: Sequence[str] = (),
    keywords: Sequence[str] = (),
    max_items: int = 5,
    exclude: set[str] | None = None,
) -> list[str]:
    return _collect_section_lines(
        doc_bundle,
        doc_order,
        section_keywords=section_keywords,
        field_names=field_names,
        keywords=keywords,
        max_items=max_items,
        exclude=exclude,
    )


def _collect_keyword_evidence(
    doc_bundle: dict,
    doc_order: Sequence[str],
    *,
    section_keywords: Sequence[str] = (),
    field_names: Sequence[str] = (),
    keywords: Sequence[str] = (),
    max_items: int = 5,
) -> list[str]:
    items = []
    seen = set()
    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    for candidate in _iter_signal_candidates(
        doc_bundle,
        doc_order,
        section_keywords=section_keywords,
        field_names=field_names,
    ):
        cleaned = _clean_highlight_line(candidate)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered_keywords and not any(keyword in lowered for keyword in lowered_keywords):
            continue
        normalized = _normalize_text(cleaned)
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(cleaned)
        if len(items) >= max_items:
            return items
    return items


def _extract_story_memory_evidence(results: list[dict], max_items: int = 3) -> list[str]:
    items = []
    seen = set()
    for packet in results:
        for hit in packet.get("results", []):
            if hit.get("room") not in {
                "checkpoints",
                "brainstorms",
                "audits",
                "discarded_paths",
                "chat_process",
            }:
                continue
            summary = f"{hit.get('room')}: {_preview_text(hit.get('text', ''), max_words=14)}"
            normalized = _normalize_text(summary)
            if normalized in seen:
                continue
            seen.add(normalized)
            items.append(summary)
            if len(items) >= max_items:
                return items
    return items


def _extract_rejected_path_evidence(results: list[dict], max_items: int = 5) -> list[str]:
    items = []
    seen = set()
    for packet in results:
        for hit in packet.get("results", []):
            if hit.get("room") not in {"audits", "discarded_paths"}:
                continue
            summary = f"{hit.get('room')}: {_preview_text(hit.get('text', ''))}"
            normalized = _normalize_text(summary)
            if normalized in seen:
                continue
            seen.add(normalized)
            items.append(summary)
            if len(items) >= max_items:
                return items
    return items


def _preview_text(text: str, max_words: int = 20) -> str:
    cleaned = _clean_highlight_line(text)
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned
    return " ".join(words[:max_words]) + "..."


def scaffold_writing_sidecar(vault_dir: str, project: str, force: bool = False) -> dict:
    project_root = resolve_project_root(vault_dir, project)
    created_files = []
    overwritten_files = []
    skipped_files = []
    created_dirs = []

    directories = [
        project_root / "logs",
        project_root / "logs" / "checkpoints",
        project_root / "logs" / "audits",
        project_root / "logs" / "brainstorms",
        project_root / "logs" / "discarded_paths",
        project_root / "logs" / "templates",
    ]
    for directory in directories:
        if not directory.exists():
            _ensure_dir(directory)
            created_dirs.append(str(directory))
        else:
            _ensure_dir(directory)

    files = {
        project_root / "writing-sidecar.yaml": _default_writing_sidecar_config_text(),
        project_root / "logs" / "README.md": _default_logs_readme_text(project_root.name),
        project_root / "logs" / "templates" / "checkpoint_snapshot.md": _default_checkpoint_template_text(),
        project_root / "logs" / "templates" / "audit_snapshot.md": _default_audit_template_text(),
        project_root / "logs" / "templates" / "chapter_handoff.md": _default_handoff_template_text(),
        project_root / "logs" / "templates" / "discarded_path.md": _default_discarded_template_text(),
    }

    for path, content in files.items():
        if path.exists() and not force:
            skipped_files.append(str(path))
            continue
        if path.exists():
            overwritten_files.append(str(path))
        else:
            created_files.append(str(path))
        _ensure_dir(path.parent)
        path.write_text(content, encoding="utf-8")

    return {
        "project_root": str(project_root),
        "created_dirs": created_dirs,
        "created_files": created_files,
        "overwritten_files": overwritten_files,
        "skipped_files": skipped_files,
    }


def print_scaffold_summary(summary: dict):
    print(f"\n{'=' * 55}")
    print("  Writing Sidecar Init")
    print(f"{'=' * 55}")
    print(f"  Project: {summary['project_root']}")
    if summary["created_dirs"]:
        print("\n  Created directories:")
        for path in summary["created_dirs"]:
            print(f"    {path}")
    if summary["created_files"]:
        print("\n  Created files:")
        for path in summary["created_files"]:
            print(f"    {path}")
    if summary["overwritten_files"]:
        print("\n  Overwritten files:")
        for path in summary["overwritten_files"]:
            print(f"    {path}")
    if summary["skipped_files"]:
        print("\n  Left untouched:")
        for path in summary["skipped_files"]:
            print(f"    {path}")
    print(f"\n{'=' * 55}\n")


def _export_codex_chat_process(
    codex_root: Path,
    project_root: Path,
    vault_root: Path,
    project_terms: list,
    excluded_chat_terms: list,
    output_root: Path,
    summary: dict,
    dry_run: bool,
    planned_entries: list,
):
    sessions_root = codex_root / "sessions"
    if not sessions_root.exists():
        return

    room_dir = output_root / "chat_process"
    for rollout_path in sorted(sessions_root.rglob("*.jsonl")):
        if not _rollout_matches_project(
            rollout_path,
            project_root=project_root,
            vault_root=vault_root,
            project_terms=project_terms,
            excluded_chat_terms=excluded_chat_terms,
        ):
            continue
        try:
            transcript = normalize(str(rollout_path))
        except Exception:
            continue
        if not transcript.strip():
            continue

        summary["rooms"]["chat_process"] += 1
        relative = rollout_path.relative_to(sessions_root).with_suffix(".txt")
        filename = _safe_name("__".join(relative.parts))
        target_path = room_dir / filename
        planned_entries.append(
            {
                "room": "chat_process",
                "source_path": str(rollout_path.resolve()),
                "exported_path": str(target_path.resolve()),
                "source_kind": "codex_rollout",
            }
        )
        if dry_run:
            continue

        _ensure_dir(target_path.parent)
        target_path.write_text(transcript, encoding="utf-8")


def _rollout_matches_project(
    rollout_path: Path,
    project_root: Path,
    vault_root: Path,
    project_terms: list,
    excluded_chat_terms: list,
) -> bool:
    project_norm = _normalized_path(project_root)
    vault_norm = _normalized_path(vault_root)
    session_within_vault = False
    mentions_project = False
    mentions_excluded = False
    try:
        with open(rollout_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = entry.get("payload", {})
                if not isinstance(payload, dict):
                    continue

                session_cwd = payload.get("cwd")
                if isinstance(session_cwd, str) and session_cwd.strip():
                    session_norm = _normalized_path(Path(session_cwd))
                    if _path_matches_root(session_norm, project_norm):
                        return True
                    if _path_matches_root(session_norm, vault_norm):
                        session_within_vault = True

                if session_within_vault:
                    if _payload_mentions_project(
                        payload,
                        project_root=project_root,
                        project_terms=project_terms,
                    ):
                        mentions_project = True
                    if excluded_chat_terms and _payload_mentions_terms(payload, excluded_chat_terms):
                        mentions_excluded = True
    except OSError:
        return False
    return session_within_vault and mentions_project and not mentions_excluded


def _copy_tree_if_present(
    source_dir: Path,
    room_name: str,
    source_kind: str,
    output_root: Path,
    project_root: Path,
    summary: dict,
    dry_run: bool,
    planned_entries: list,
):
    if not source_dir.exists():
        return

    room_dir = output_root / room_name
    for source_path in sorted(source_dir.rglob("*")):
        if not source_path.is_file():
            continue
        if source_path.name.startswith("."):
            continue
        if _should_skip_live_file(source_path, project_root):
            summary["skipped_live_files"].append(str(source_path))
            continue

        summary["rooms"][room_name] += 1
        target_path = room_dir / source_path.relative_to(source_dir)
        planned_entries.append(
            {
                "room": room_name,
                "source_path": str(source_path.resolve()),
                "exported_path": str(target_path.resolve()),
                "source_kind": source_kind,
            }
        )
        if dry_run:
            continue

        _ensure_dir(target_path.parent)
        shutil.copy2(source_path, target_path)


def _copy_opt_in_paths(
    raw_paths: list,
    room_name: str,
    source_kind: str,
    output_root: Path,
    project_root: Path,
    summary: dict,
    dry_run: bool,
    planned_entries: list,
):
    room_dir = output_root / room_name
    for raw_path in raw_paths:
        source_path = Path(raw_path).expanduser().resolve()
        if not source_path.exists():
            summary["skipped_missing_paths"].append(str(source_path))
            continue

        if source_path.is_file():
            if source_path.name.startswith("."):
                continue
            if _should_skip_live_file(source_path, project_root):
                summary["skipped_live_files"].append(str(source_path))
                continue
            summary["rooms"][room_name] += 1
            target_path = room_dir / _safe_name(source_path.name)
            planned_entries.append(
                {
                    "room": room_name,
                    "source_path": str(source_path.resolve()),
                    "exported_path": str(target_path.resolve()),
                    "source_kind": source_kind,
                }
            )
            if dry_run:
                continue
            _ensure_dir(target_path.parent)
            shutil.copy2(source_path, target_path)
            continue

        source_label = _safe_name(source_path.name)
        export_root = room_dir if source_label == room_name else room_dir / source_label
        for nested_path in sorted(source_path.rglob("*")):
            if not nested_path.is_file():
                continue
            if nested_path.name.startswith("."):
                continue
            if _should_skip_live_file(nested_path, project_root):
                summary["skipped_live_files"].append(str(nested_path))
                continue
            summary["rooms"][room_name] += 1
            target_path = export_root / nested_path.relative_to(source_path)
            planned_entries.append(
                {
                    "room": room_name,
                    "source_path": str(nested_path.resolve()),
                    "exported_path": str(target_path.resolve()),
                    "source_kind": source_kind,
                }
            )
            if dry_run:
                continue
            _ensure_dir(target_path.parent)
            shutil.copy2(nested_path, target_path)


def _merge_opt_in_paths(base_dir: Path, config_paths: list, cli_paths: list) -> list:
    merged = []
    seen = set()
    for raw_path in list(config_paths or []) + list(cli_paths or []):
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).resolve()
        else:
            candidate = candidate.resolve()
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            merged.append(key)
    return merged


def _load_writing_export_config(project_root: Path, config_path: str = None):
    candidate = None
    if config_path:
        candidate = Path(config_path).expanduser().resolve()
    else:
        candidate = _find_project_config_path(project_root)

    if candidate is None:
        return {}, None
    if not candidate.exists():
        raise FileNotFoundError(f"Writing sidecar config not found: {candidate}")

    with open(candidate, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("Writing sidecar config must be a mapping")
    return data, candidate


def resolve_vault_root(vault_dir: str, project_root: Path) -> Path:
    """Infer the vault root even when the caller passes a direct project path."""
    base_path = Path(vault_dir).expanduser().resolve()
    if base_path.is_file():
        base_path = base_path.parent
    if base_path == project_root or project_root in base_path.parents:
        return project_root.parent
    return base_path


def _project_slug(project: str) -> str:
    return _safe_name(project.lower().replace(" ", "_").replace("-", "_"))


def _project_wing(project: str) -> str:
    return f"{_project_slug(project)}_writing_sidecar"


def _build_project_terms(project: str, project_root: Path, extra_terms: list) -> list:
    terms = {
        project,
        project_root.name,
        project_root.name.replace("-", " "),
        project_root.name.replace("_", " "),
        project_root.name.replace("-", "_"),
    }
    for term in extra_terms or []:
        if isinstance(term, str) and term.strip():
            terms.add(term.strip())
    return sorted(terms)


def _build_term_list(extra_terms: list) -> list:
    terms = set()
    for term in extra_terms or []:
        if isinstance(term, str) and term.strip():
            terms.add(term.strip())
    return sorted(terms)


def _write_state_manifest(context: dict, summary: dict, planned_entries: list):
    synced_at = _utcnow_iso()
    tracked_inputs = []
    for entry in sorted(
        planned_entries,
        key=lambda item: (item["room"], item["source_kind"], item["source_path"], item["exported_path"]),
    ):
        source_path = Path(entry["source_path"])
        tracked = dict(entry)
        tracked.update(_describe_file(source_path))
        tracked_inputs.append(tracked)

    manifest = {
        "version": STATE_VERSION,
        "project": context["project"],
        "project_root": str(context["project_root"]),
        "vault_root": str(context["vault_root"]),
        "output_root": str(context["output_root"]),
        "palace_path": str(context["palace_path"]),
        "runtime_root": str(context["runtime_root"]),
        "config": _describe_optional_file(context["loaded_config_path"]),
        "synced_at": synced_at,
        "room_counts": dict(summary["rooms"]),
        "tracked_inputs": tracked_inputs,
    }

    context["manifest_path"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary["last_synced_at"] = synced_at


def _load_state_manifest(manifest_path: Path):
    manifest_path = manifest_path.expanduser().resolve()
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _describe_file(path: Path) -> dict:
    path = path.expanduser().resolve()
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": _sha256_file(path),
    }


def _describe_optional_file(path: Path | None):
    if not path:
        return None
    path = Path(path).expanduser().resolve()
    if not path.exists():
        return {
            "path": str(path),
            "size": None,
            "mtime": None,
            "sha256": None,
        }
    described = _describe_file(path)
    described["path"] = str(path)
    return described


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mine_exported_sidecar(
    output_root: Path,
    project: str,
    palace_path: Path,
    runtime_root: Path,
    refresh_palace: bool = False,
):
    output_root = output_root.resolve()
    palace_path = palace_path.expanduser().resolve()
    runtime_root = runtime_root.expanduser().resolve()

    try:
        palace_path.relative_to(output_root)
    except ValueError:
        pass
    else:
        raise ValueError("Palace path must be outside the exported sidecar directory")

    try:
        runtime_root.relative_to(output_root)
    except ValueError:
        pass
    else:
        raise ValueError("Runtime root must be outside the exported sidecar directory")

    if refresh_palace and palace_path.exists():
        shutil.rmtree(palace_path)

    with _sidecar_runtime_environment(runtime_root):
        _ensure_dir(palace_path)
        mine(
            project_dir=str(output_root),
            palace_path=str(palace_path),
            wing_override=_project_wing(project),
            agent="writing_sidecar",
            limit=0,
            dry_run=False,
            respect_gitignore=True,
            include_ignored=[],
        )


def _payload_mentions_project(payload: dict, project_root: Path, project_terms: list) -> bool:
    project_norm = _normalized_path(project_root)
    project_texts = {
        project_norm,
        project_norm.replace("\\", "/"),
        *[_normalize_text(term) for term in project_terms],
    }

    for value in _iter_payload_strings(payload):
        normalized = _normalize_text(value)
        if not normalized:
            continue
        if project_norm in normalized or project_norm.replace("\\", "/") in normalized:
            return True
        if any(term and term in normalized for term in project_texts):
            return True

        candidate_paths = re.findall(r"[A-Za-z]:[\\/][^\"'\r\n]+", value)
        for candidate in candidate_paths:
            if _path_matches_root(_normalized_path(Path(candidate)), project_norm):
                return True

    return False


def _payload_mentions_terms(payload: dict, terms: list) -> bool:
    normalized_terms = [_normalize_text(term) for term in terms if isinstance(term, str) and term.strip()]
    if not normalized_terms:
        return False

    for value in _iter_payload_strings(payload):
        if _looks_like_path(value):
            continue
        normalized = _normalize_text(value)
        if not normalized:
            continue
        if any(term and term in normalized for term in normalized_terms):
            return True

    return False


def _iter_payload_strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_payload_strings(item)
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _iter_payload_strings(nested)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9:/\\._-]+", " ", value.lower()).strip()


def _path_matches_root(candidate_norm: str, root_norm: str) -> bool:
    return candidate_norm == root_norm or candidate_norm.startswith(root_norm + os.sep)


def _should_skip_live_file(path: Path, project_root: Path) -> bool:
    if path.name in LIVE_GATEWAY_FILES:
        return True

    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return False

    if len(relative.parts) == 1 and path.match("Chapter *.txt"):
        return True

    if relative.parts[:1] == ("_story_bible",):
        if len(relative.parts) == 2 and relative.name in LIVE_NOTES_FILES:
            return True
        if len(relative.parts) == 2 and relative.suffix.lower() == ".md":
            return True

    return False


def _normalized_path(path: Path) -> str:
    return str(path.expanduser().resolve()).rstrip("\\/").lower()


def _looks_like_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("\\\\"))


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "export"


def _default_writing_sidecar_config_text() -> str:
    return """chat_project_terms:
  # Add project-specific phrases that often appear in vault-root chats.
  # - Arthur sponsorship

chat_exclude_terms:
  # Add tooling/admin phrases that should never attach a chat to the project.
  # - mempalace

# Archived chapter notes from _story_bible/chapters and checkpoint logs from logs/checkpoints
# are already ingested automatically.
brainstorms: []
audits: []
discarded_paths: []
"""


def _default_logs_readme_text(project_name: str) -> str:
    return f"""# Logs

This folder stores sidecar-safe process memory for `{project_name}`.

Use it for:
- structured checkpoints
- archived audits
- brainstorm bundles
- discarded scene paths or rejected structural options
- chapter handoff notes that should stay searchable

Workflow:
- use `logs/templates/` when creating new sidecar artifacts
- keep startup / planning / closeout snapshots in `logs/checkpoints/`
- update these files during chapter closeout and handoff, not in live canon docs
- run `writing-sidecar sync <vault> --project {project_name}` after meaningful log changes

Do not use it for:
- source-of-truth canon
- current chapter scratch work
- the live story bible

Recommended vault `.gitignore` entries:
- `.mempalace-sidecar-runtime/`
- `.palaces/`
- `.sidecars/`

Naming rules:
- checkpoints: `YYYY-MM-DD_chapter-<n>_<slug>_checkpoint.md`
- audits: `YYYY-MM-DD_chapter-<n>_closeout_audit.md`
- handoffs: `YYYY-MM-DD_chapter-<n+1>_<slug>_handoff.md`
- discarded paths: `YYYY-MM-DD_chapter-<n>_<slug>_discarded.md`
"""


def _default_checkpoint_template_text() -> str:
    return """# Session Checkpoint

Project:
Chapter:
Date:
Context Mode:

## Session State

- Phase:
- Status:
- Next Action:

## Current Focus

- 
- 

## Carry-Forward Threads

- 
- 

## Suggested Next Loadout

- 
- 

## Assistant Notes

- 

## Sources Used

- 
"""


def _default_audit_template_text() -> str:
    return """# Chapter Closeout Audit

Project:
Chapter:
Title:
Date:

## Final Result

- Final cold-audit score:
- Result:
- Status:
- Next practical step:

## Audit Progression

| Score | Result | Dominant problem |
|------:|--------|------------------|

## Main Problems That Had To Be Fixed

1.
2.
3.

## What The Final Version Does Better

- 
- 
- 

## Carry-Forward Threads Logged At Closeout

- 
- 
- 

## Residual Non-Blocking Issues

- 
- 

## Sources Used

- 
"""


def _default_handoff_template_text() -> str:
    return """# Chapter Handoff

Project:
Date:
Next Chapter:

## Starting Position

- 

## Core Opening Pressures

1.
2.
3.

## Useful Scene Questions

- 
- 
- 

## Guardrails

- 
- 
- 

## Best Immediate Scene Material

- 
- 
- 

## Sources Used

- 
"""


def _default_discarded_template_text() -> str:
    return """# Discarded Path

Project:
Chapter:
Date:

## Rejected Version

- 

## Why It Was Rejected

- 
- 

## Keep Instead

- 
- 

## Retrieval Terms Worth Keeping

- 
- 
- 

## Sources Used

- 
"""


def _ensure_dir(path: Path):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        if os.name != "nt":
            raise
        literal_path = str(path).replace("'", "''")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"New-Item -ItemType Directory -Path '{literal_path}' -Force | Out-Null",
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def _write_export_gitignore(output_root: Path):
    gitignore_path = output_root / ".gitignore"
    gitignore_path.write_text(
        f"entities.json\nmempalace.yaml\n{STATE_FILENAME}\n",
        encoding="utf-8",
    )


def _write_sidecar_config(output_root: Path, project: str):
    config_path = output_root / "mempalace.yaml"
    config = {
        "wing": _project_wing(project),
        "rooms": [
            {
                "name": room,
                "description": ROOM_DESCRIPTIONS[room],
                "keywords": [room, room.replace("_", " ")],
            }
            for room in FIXED_ROOMS
        ],
    }
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)


@contextmanager
def _sidecar_runtime_environment(runtime_root: Path):
    runtime_root = runtime_root.expanduser().resolve()
    home_root = runtime_root / "home"
    cache_root = runtime_root / "cache"
    tmp_root = runtime_root / "tmp"
    chroma_cache_root = cache_root / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"

    for path in (runtime_root, home_root, cache_root, tmp_root, chroma_cache_root):
        _ensure_dir(path)

    env_updates = {
        "HOME": str(home_root),
        "USERPROFILE": str(home_root),
        "HOMEDRIVE": home_root.drive or "C:",
        "HOMEPATH": str(home_root).replace(home_root.drive or "C:", "", 1) or "\\",
        "TMP": str(tmp_root),
        "TEMP": str(tmp_root),
        "TMPDIR": str(tmp_root),
        "XDG_CACHE_HOME": str(cache_root),
        "HF_HOME": str(cache_root / "huggingface"),
        "TRANSFORMERS_CACHE": str(cache_root / "huggingface" / "transformers"),
        "CHROMA_CACHE_DIR": str(cache_root / "chroma"),
    }
    previous_env = {key: os.environ.get(key) for key in env_updates}
    previous_tempdir = tempfile.tempdir
    previous_download_path = None

    try:
        for key, value in env_updates.items():
            os.environ[key] = value
        tempfile.tempdir = str(tmp_root)
        try:
            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
        except Exception:
            pass
        try:
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

            previous_download_path = ONNXMiniLM_L6_V2.DOWNLOAD_PATH
            ONNXMiniLM_L6_V2.DOWNLOAD_PATH = str(chroma_cache_root)
        except Exception:
            pass
        yield runtime_root
    finally:
        try:
            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
        except Exception:
            pass
        try:
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

            if previous_download_path is not None:
                ONNXMiniLM_L6_V2.DOWNLOAD_PATH = previous_download_path
        except Exception:
            pass
        tempfile.tempdir = previous_tempdir
        for key, old_value in previous_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def doctor_writing_sidecar(
    vault_dir: str,
    project: str | None = None,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
) -> dict:
    context = _prepare_writing_context(
        vault_dir=vault_dir,
        project=project,
        out_dir=out_dir,
        codex_home=codex_home,
        config_path=config_path,
        brainstorm_paths=brainstorm_paths,
        audit_paths=audit_paths,
        discarded_paths=discarded_paths,
        palace_path=palace_path,
        runtime_root=runtime_root,
    )

    version = get_installed_mempalace_version()
    checks = []

    if version is None:
        checks.append(
            {
                "name": "mempalace_installed",
                "status": "fail",
                "detail": "MemPalace is not installed.",
            }
        )
    else:
        checks.append(
            {
                "name": "mempalace_installed",
                "status": "ok",
                "detail": f"MemPalace {version} is installed.",
            }
        )
        try:
            ensure_supported_mempalace_version()
        except Exception as exc:
            checks.append(
                {
                    "name": "mempalace_version",
                    "status": "fail",
                    "detail": str(exc),
                }
            )
        else:
            checks.append(
                {
                    "name": "mempalace_version",
                    "status": "ok",
                    "detail": f"Supported MemPalace version detected ({version}, expected {SUPPORTED_MEMPALACE_SPEC}).",
                }
            )

    codex_root = context["codex_root"]
    if codex_root.exists():
        checks.append(
            {
                "name": "codex_home",
                "status": "ok",
                "path": str(codex_root),
                "detail": "Codex home was found.",
            }
        )
    else:
        checks.append(
            {
                "name": "codex_home",
                "status": "warn",
                "path": str(codex_root),
                "detail": "Codex home was not found. Chat-process export will be empty until this exists.",
            }
        )

    for name, path in (
        ("output_root", context["output_root"]),
        ("palace_path", context["palace_path"]),
        ("runtime_root", context["runtime_root"]),
    ):
        ok, detail = _check_writable_path(path)
        checks.append(
            {
                "name": name,
                "status": "ok" if ok else "fail",
                "path": str(path),
                "detail": detail,
            }
        )

    report = {
        "project": project,
        "project_root": str(context["project_root"]),
        "vault_root": str(context["vault_root"]),
        "output_root": str(context["output_root"]),
        "palace_path": str(context["palace_path"]),
        "runtime_root": str(context["runtime_root"]),
        "codex_home": str(codex_root),
        "config_path": str(context["loaded_config_path"]) if context["loaded_config_path"] else None,
        "mempalace_version": version,
        "supported_spec": SUPPORTED_MEMPALACE_SPEC,
        "checks": checks,
        "ok": not any(item["status"] == "fail" for item in checks),
    }
    return report


def print_doctor_report(report: dict):
    print(f"\n{'=' * 55}")
    print("  Writing Sidecar Doctor")
    print(f"{'=' * 55}")
    print(f"  Project: {report['project_root']}")
    print(f"  Vault:   {report['vault_root']}")
    print(f"  Output:  {report['output_root']}")
    print(f"  Palace:  {report['palace_path']}")
    print(f"  Runtime: {report['runtime_root']}")
    print(f"  Codex:   {report['codex_home']}")
    print(f"  Version: {report.get('mempalace_version') or 'not installed'}")
    print(f"  Target:  {report['supported_spec']}")

    print("\n  Checks:")
    for item in report["checks"]:
        status = item["status"].upper()
        label = item["name"]
        detail = item.get("detail", "")
        path = item.get("path")
        if path:
            print(f"    {status:5} {label:20} {path}")
            if detail:
                print(f"          {detail}")
        else:
            print(f"    {status:5} {label:20} {detail}")

    print(f"\n  Result: {'PASS' if report['ok'] else 'FAIL'}")
    print(f"\n{'=' * 55}\n")


def _check_writable_path(path: Path) -> tuple[bool, str]:
    path = path.expanduser().resolve()
    target = path if path.exists() else path.parent
    try:
        _ensure_dir(target)
        probe_dir = path if path.exists() and path.is_dir() else target
        probe = probe_dir / f".writing-sidecar-probe-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, "Writable."
    except Exception as exc:
        return False, f"Not writable: {exc}"
