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
from typing import Iterable

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
    "planning": ("brainstorms", "discarded_paths", "audits", "chat_process"),
    "audit": ("audits", "discarded_paths", "chat_process", "archived_notes"),
    "history": ("chat_process", "audits", "brainstorms", "discarded_paths"),
    "research": ("research", "archived_notes"),
}
FIXED_ROOMS = (
    "chat_process",
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
    "brainstorms": "Idea dumps, alternatives, and exploratory notes.",
    "audits": "Review passes, criticism, and structured analysis.",
    "discarded_paths": "Cut scenes, abandoned branches, and paths not chosen.",
    "research": "Reference material and research notes safe to archive.",
    "archived_notes": "Archived chapter notes and historical planning material.",
}


def resolve_project_root(vault_dir: str, project: str) -> Path:
    """Resolve a project path from either a vault root or a direct project path."""
    base_path = Path(vault_dir).expanduser().resolve()
    if not base_path.exists():
        raise FileNotFoundError(f"Vault path not found: {base_path}")

    direct_match = base_path.name.lower() == project.lower()
    candidate = base_path / project

    if direct_match and base_path.is_dir():
        return base_path
    if candidate.is_dir():
        return candidate.resolve()

    raise FileNotFoundError(
        f"Could not resolve project '{project}' from {base_path}. "
        "Pass the vault root or the project directory itself."
    )


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
    project: str,
    out_dir: str = None,
    codex_home: str = None,
    config_path: str = None,
    brainstorm_paths=None,
    audit_paths=None,
    discarded_paths=None,
    palace_path: str = None,
    runtime_root: str = None,
) -> dict:
    project_root = resolve_project_root(vault_dir, project)
    vault_root = resolve_vault_root(vault_dir, project_root)
    output_root = (
        Path(out_dir).expanduser().resolve()
        if out_dir
        else default_output_dir(vault_root, project).resolve()
    )
    codex_root = Path(codex_home).expanduser().resolve() if codex_home else DEFAULT_CODEX_HOME
    target_palace = (
        Path(palace_path).expanduser().resolve()
        if palace_path
        else default_palace_dir(vault_root, project).resolve()
    )
    sidecar_runtime_root = (
        Path(runtime_root).expanduser().resolve()
        if runtime_root
        else default_runtime_dir(vault_root, project).resolve()
    )
    writing_config, loaded_config_path = _load_writing_export_config(project_root, config_path)
    config_base_dir = loaded_config_path.parent if loaded_config_path else project_root
    project_terms = _build_project_terms(
        project,
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
        "project": project,
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
    project: str,
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
        _write_sidecar_config(context["output_root"], project)
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
                project=project,
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
    project: str,
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
        "project": project,
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
        "stale_reasons": [],
    }

    if manifest is None:
        status["stale_reasons"].append({"reason": "manifest_missing"})
        if not context["palace_path"].exists():
            status["stale_reasons"].append({"reason": "palace_missing"})
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

    status["stale"] = bool(status["stale_reasons"])
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

    if not status["built"]:
        print("  Status:  NOT BUILT")
    else:
        print(f"  Status:  {'STALE' if status['stale'] else 'CLEAN'}")

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


def search_writing_sidecar(query: str, palace_path: str, wing: str, mode: str, n_results: int = 5) -> dict:
    if mode not in SEARCH_MODE_ROOMS:
        raise ValueError(f"Unknown writing-search mode: {mode}")

    merged = []
    seen = set()
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
            merged.append(hit)
            if len(merged) >= n_results:
                return {
                    "query": query,
                    "wing": wing,
                    "mode": mode,
                    "room_order": list(rooms),
                    "results": merged,
                }

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


def scaffold_writing_sidecar(vault_dir: str, project: str, force: bool = False) -> dict:
    project_root = resolve_project_root(vault_dir, project)
    created_files = []
    overwritten_files = []
    skipped_files = []
    created_dirs = []

    directories = [
        project_root / "logs",
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
        for filename in DEFAULT_WRITING_CONFIG_FILENAMES:
            auto_candidate = project_root / filename
            if auto_candidate.exists():
                candidate = auto_candidate.resolve()
                break

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
    if base_path == project_root:
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

# Archived chapter notes from _story_bible/chapters are already ingested automatically.
brainstorms: []
audits: []
discarded_paths: []
"""


def _default_logs_readme_text(project_name: str) -> str:
    return f"""# Logs

This folder stores sidecar-safe process memory for `{project_name}`.

Use it for:
- archived audits
- brainstorm bundles
- discarded scene paths or rejected structural options
- chapter handoff notes that should stay searchable

Workflow:
- use `logs/templates/` when creating new sidecar artifacts
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
    project: str,
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
