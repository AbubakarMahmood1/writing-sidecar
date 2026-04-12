from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .mempalace_adapter import MempalaceCompatibilityError, search as raw_search
from .workflow import (
    CONTEXT_MODES,
    MAINTAIN_KINDS,
    RECAP_MODES,
    SEARCH_MODE_ROOMS,
    _ensure_dir,
    _project_wing,
    _sidecar_runtime_environment,
    build_writing_context,
    build_writing_recap,
    doctor_writing_sidecar,
    export_writing_corpus,
    get_writing_sidecar_status,
    list_writing_projects,
    maintain_writing_sidecar,
    print_doctor_report,
    print_export_summary,
    print_scaffold_summary,
    print_writing_context,
    print_writing_maintenance,
    print_writing_projects,
    print_writing_recap,
    print_writing_search_results,
    print_writing_status,
    render_writing_recap,
    scaffold_writing_sidecar,
    search_writing_sidecar,
)


def _shared_project_args(
    parser: argparse.ArgumentParser,
    include_query: bool = False,
    require_project: bool = False,
    include_sidecar_out: bool = True,
):
    parser.add_argument("dir", help="Vault root, project directory, or a path inside one project")
    parser.add_argument(
        "--project",
        required=require_project,
        help="Project name (optional when the input path already resolves to one sidecar-enabled project)",
    )
    if include_sidecar_out:
        parser.add_argument(
            "--out",
            default=None,
            help="Output directory (default: <vault>/.sidecars/<project>)",
        )
    parser.add_argument(
        "--codex-home",
        default=None,
        help="Codex home directory to scan for rollout JSONL (default: ~/.codex)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional writing-sidecar YAML config with extra paths and chat match terms",
    )
    parser.add_argument(
        "--brainstorms",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the brainstorms room; repeat as needed",
    )
    parser.add_argument(
        "--audits",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the audits room; repeat as needed",
    )
    parser.add_argument(
        "--discarded-paths",
        action="append",
        default=[],
        help="Opt-in file or directory to export into the discarded_paths room; repeat as needed",
    )
    parser.add_argument(
        "--sidecar-palace",
        default=None,
        help="Palace directory for the sidecar (default: <vault>/.palaces/<project>)",
    )
    parser.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime/cache directory for sidecar work (default: <vault>/.mempalace-sidecar-runtime/<project>)",
    )
    if include_query:
        parser.add_argument("--query", required=True, help="Search query")


def _add_format_arg(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )


def _emit_json(data: dict):
    print(json.dumps(data, indent=2))


def _write_rendered_output(path: str, content: str):
    output_path = Path(path).expanduser().resolve()
    _ensure_dir(output_path.parent)
    output_path.write_text(content, encoding="utf-8")


def _print_prepare_feedback(prepared: dict, *, show_status: bool = False):
    if prepared["synced"] and prepared.get("sync_summary"):
        print_export_summary(prepared["sync_summary"], dry_run=False)
        return

    if prepared["warnings"]:
        for warning in prepared["warnings"]:
            print(f"  Warning: {warning}\n")
    else:
        print("  Sidecar is current; skipping rebuild.\n")

    if show_status:
        print_writing_status(prepared["status"])


def _prepare_from_args(args) -> dict:
    status = get_writing_sidecar_status(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
    )
    should_sync = args.refresh_palace or args.sync == "always" or (
        args.sync == "if-needed" and status["stale"]
    )
    summary = None
    warnings = []

    if should_sync:
        summary = export_writing_corpus(
            vault_dir=args.dir,
            project=args.project,
            out_dir=args.out,
            codex_home=args.codex_home,
            config_path=args.config,
            brainstorm_paths=args.brainstorms,
            audit_paths=args.audits,
            discarded_paths=args.discarded_paths,
            mine_after_export=True,
            palace_path=args.sidecar_palace,
            runtime_root=args.runtime_root,
            refresh_palace=args.refresh_palace,
            dry_run=False,
        )
        status = get_writing_sidecar_status(
            vault_dir=args.dir,
            project=args.project,
            out_dir=args.out,
            codex_home=args.codex_home,
            config_path=args.config,
            brainstorm_paths=args.brainstorms,
            audit_paths=args.audits,
            discarded_paths=args.discarded_paths,
            palace_path=args.sidecar_palace,
            runtime_root=args.runtime_root,
        )
    elif args.sync == "never" and status["stale"]:
        warnings.append("sidecar is stale; skipping rebuild because --sync never was used.")

    return {
        "status": status,
        "sync_summary": summary,
        "synced": summary is not None,
        "warnings": warnings,
    }


def cmd_init(args):
    summary = scaffold_writing_sidecar(args.dir, args.project, force=args.force)
    print_scaffold_summary(summary)


def cmd_status(args):
    status = get_writing_sidecar_status(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
    )
    if args.format == "json":
        _emit_json(status)
        return
    print_writing_status(status)


def cmd_export(args):
    summary = export_writing_corpus(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        mine_after_export=args.mine,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
        refresh_palace=args.refresh_palace,
        dry_run=args.dry_run,
    )
    print_export_summary(summary, dry_run=args.dry_run)


def cmd_search(args):
    prepared = _prepare_from_args(args)
    status = prepared["status"]
    palace_path = Path(status["palace_path"])
    if not palace_path.exists():
        print(f"\n  No palace found at {palace_path}")
        print("  Run writing-sidecar sync or use --sync always/if-needed to build it first.")
        raise SystemExit(1)

    with _sidecar_runtime_environment(Path(status["runtime_root"])):
        results = search_writing_sidecar(
            query=args.query,
            palace_path=str(palace_path),
            wing=_project_wing(status["project"]),
            mode=args.mode,
            n_results=args.results,
        )

    if results.get("error"):
        print(f"\n  Search error: {results['error']}")
        raise SystemExit(1)

    if args.format == "json":
        _emit_json(
            {
                "status": status,
                "synced": prepared["synced"],
                "sync_summary": prepared["sync_summary"],
                "warnings": prepared["warnings"],
                "search": results,
            }
        )
        return

    _print_prepare_feedback(prepared, show_status=False)
    print_writing_search_results(results)


def cmd_sync(args):
    prepared = _prepare_from_args(args)
    status = prepared["status"]
    _print_prepare_feedback(prepared, show_status=not args.query)
    if not args.query:
        return

    palace_path = Path(status["palace_path"])
    if not palace_path.exists():
        print(f"\n  No palace found at {palace_path}")
        print("  Run writing-sidecar sync without --sync never, or use --sync always.")
        raise SystemExit(1)

    with _sidecar_runtime_environment(Path(status["runtime_root"])):
        if args.mode:
            results = search_writing_sidecar(
                query=args.query,
                palace_path=str(palace_path),
                wing=_project_wing(status["project"]),
                mode=args.mode,
                n_results=args.results,
            )
            if results.get("error"):
                print(f"\n  Search error: {results['error']}")
                raise SystemExit(1)
            print_writing_search_results(results)
            return
        raw_search(
            query=args.query,
            palace_path=str(palace_path),
            wing=_project_wing(status["project"]),
            room=args.room,
            n_results=args.results,
        )


def cmd_doctor(args):
    report = doctor_writing_sidecar(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
    )
    if args.format == "json":
        _emit_json(report)
    else:
        print_doctor_report(report)
    if not report["ok"]:
        raise SystemExit(1)


def cmd_context(args):
    context_data = build_writing_context(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
        sync=args.sync,
        refresh_palace=args.refresh_palace,
        mode=args.mode,
        n_results=args.results,
    )
    if args.format == "json":
        _emit_json(context_data)
        return
    if context_data.get("synced") and context_data.get("sync_summary"):
        print_export_summary(context_data["sync_summary"], dry_run=False)
    print_writing_context(context_data)


def cmd_recap(args):
    recap_data = build_writing_recap(
        vault_dir=args.dir,
        project=args.project,
        out_dir=args.sidecar_out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
        sync=args.sync,
        refresh_palace=args.refresh_palace,
        mode=args.mode,
        n_results=args.results,
    )
    if args.format == "json":
        rendered = json.dumps(recap_data, indent=2)
        print(rendered)
    else:
        rendered = render_writing_recap(recap_data)
        if recap_data.get("synced") and recap_data.get("sync_summary"):
            print_export_summary(recap_data["sync_summary"], dry_run=False)
        print(rendered)
    if args.out:
        _write_rendered_output(args.out, rendered)


def cmd_projects(args):
    report = list_writing_projects(args.dir)
    if args.format == "json":
        _emit_json(report)
        return
    print_writing_projects(report)


def cmd_maintain(args):
    report = maintain_writing_sidecar(
        vault_dir=args.dir,
        kind=args.kind,
        project=args.project,
        out_dir=args.out,
        codex_home=args.codex_home,
        config_path=args.config,
        brainstorm_paths=args.brainstorms,
        audit_paths=args.audits,
        discarded_paths=args.discarded_paths,
        palace_path=args.sidecar_palace,
        runtime_root=args.runtime_root,
        sync=args.sync,
        slug=args.slug,
        chapter=args.chapter,
        notes=args.note,
        write=args.write,
    )
    if args.format == "json":
        _emit_json(report)
        return
    if report.get("sync_performed") and report.get("sync_summary"):
        print_export_summary(report["sync_summary"], dry_run=False)
    print_writing_maintenance(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="writing-sidecar — standalone CDLC sidecar for MemPalace-backed process memory.",
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Scaffold sidecar files for a writing project")
    p_init.add_argument("dir", help="Vault root or project directory")
    p_init.add_argument("--project", required=True, help="Project name (for example: Witcher-DC)")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing scaffold files")

    p_export = sub.add_parser("export", help="Build a writing-process sidecar corpus")
    _shared_project_args(p_export, require_project=True)
    p_export.add_argument("--mine", action="store_true", help="Mine the exported sidecar after export")
    p_export.add_argument(
        "--refresh-palace",
        action="store_true",
        help="If used with --mine, rebuild the target palace directory before mining",
    )
    p_export.add_argument("--dry-run", action="store_true", help="Show what would be exported")

    p_status = sub.add_parser("status", help="Show whether a writing sidecar is current or stale")
    _shared_project_args(p_status)
    _add_format_arg(p_status)

    p_search = sub.add_parser("search", help="Search a writing sidecar by intent")
    _shared_project_args(p_search, include_query=True)
    p_search.add_argument(
        "--mode",
        choices=sorted(SEARCH_MODE_ROOMS.keys()),
        default="planning",
        help="Intent mode used to prioritize sidecar rooms (default: planning)",
    )
    p_search.add_argument(
        "--sync",
        choices=["always", "if-needed", "never"],
        default="if-needed",
        help="When to rebuild the sidecar before search (default: if-needed)",
    )
    p_search.add_argument(
        "--refresh-palace",
        action="store_true",
        help="If a rebuild happens, recreate the target palace from scratch first",
    )
    p_search.add_argument("--results", type=int, default=5, help="Number of search results to show")
    _add_format_arg(p_search)

    p_sync = sub.add_parser("sync", help="Export and mine a writing sidecar, then optionally search")
    _shared_project_args(p_sync)
    p_sync.add_argument(
        "--sync",
        choices=["always", "if-needed", "never"],
        default="if-needed",
        help="When to rebuild the sidecar before any optional search (default: if-needed)",
    )
    p_sync.add_argument("--refresh-palace", action="store_true", help="Rebuild the target palace before mining")
    p_sync.add_argument("--query", default=None, help="Optional search query to run after sync")
    p_sync.add_argument(
        "--mode",
        choices=sorted(SEARCH_MODE_ROOMS.keys()),
        default=None,
        help="Intent-aware search mode for the optional post-sync query",
    )
    p_sync.add_argument("--room", default=None, help="Optional room filter for the post-sync search")
    p_sync.add_argument("--results", type=int, default=5, help="Number of post-sync search results to show")

    p_doctor = sub.add_parser("doctor", help="Verify MemPalace compatibility and sidecar path health")
    _shared_project_args(p_doctor)
    _add_format_arg(p_doctor)

    p_context = sub.add_parser("context", help="Build a compact startup/context packet for assistants")
    _shared_project_args(p_context)
    p_context.add_argument(
        "--mode",
        choices=CONTEXT_MODES,
        default="startup",
        help="Context intent mode (default: startup)",
    )
    p_context.add_argument(
        "--sync",
        choices=["always", "if-needed", "never"],
        default="if-needed",
        help="When to rebuild the sidecar before context retrieval (default: if-needed)",
    )
    p_context.add_argument("--refresh-palace", action="store_true", help="Rebuild the target palace before mining")
    p_context.add_argument("--results", type=int, default=3, help="Number of hits per context query")
    _add_format_arg(p_context)

    p_recap = sub.add_parser("recap", help="Generate a deterministic restart or handoff recap")
    _shared_project_args(p_recap, include_sidecar_out=False)
    p_recap.add_argument(
        "--sidecar-out",
        default=None,
        help="Optional sidecar output directory override (default: <vault>/.sidecars/<project>)",
    )
    p_recap.add_argument(
        "--mode",
        choices=RECAP_MODES,
        default="restart",
        help="Recap mode (default: restart)",
    )
    p_recap.add_argument(
        "--sync",
        choices=["always", "if-needed", "never"],
        default="if-needed",
        help="When to rebuild the sidecar before recap retrieval (default: if-needed)",
    )
    p_recap.add_argument("--refresh-palace", action="store_true", help="Rebuild the target palace before mining")
    p_recap.add_argument("--results", type=int, default=3, help="Number of hits per recap query")
    p_recap.add_argument("--out", default=None, help="Optional output path for the rendered recap")
    _add_format_arg(p_recap)

    p_projects = sub.add_parser("projects", help="List sidecar-enabled projects in a vault")
    p_projects.add_argument("dir", help="Vault root or a path inside one project")
    _add_format_arg(p_projects)

    p_maintain = sub.add_parser("maintain", help="Preview or write deterministic sidecar artifacts")
    _shared_project_args(p_maintain)
    p_maintain.add_argument(
        "--kind",
        required=True,
        choices=MAINTAIN_KINDS,
        help="Artifact kind to preview or write",
    )
    p_maintain.add_argument(
        "--sync",
        choices=["always", "if-needed", "never"],
        default="if-needed",
        help="When to sync the sidecar before/after maintenance (default: if-needed)",
    )
    p_maintain.add_argument("--write", action="store_true", help="Actually write the generated artifact(s)")
    p_maintain.add_argument(
        "--note",
        action="append",
        default=[],
        help="Additional assistant/human note to merge into the generated artifact; repeat as needed",
    )
    p_maintain.add_argument(
        "--slug",
        default=None,
        help="Optional slug override for checkpoint, handoff, or discarded artifact filenames",
    )
    p_maintain.add_argument(
        "--chapter",
        type=int,
        default=None,
        help="Optional chapter number override when inference fails",
    )
    _add_format_arg(p_maintain)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return

    handlers = {
        "init": cmd_init,
        "status": cmd_status,
        "export": cmd_export,
        "search": cmd_search,
        "sync": cmd_sync,
        "doctor": cmd_doctor,
        "context": cmd_context,
        "recap": cmd_recap,
        "projects": cmd_projects,
        "maintain": cmd_maintain,
    }

    try:
        handlers[args.command](args)
    except FileNotFoundError as exc:
        print(f"\n  Error: {exc}")
        raise SystemExit(1)
    except ValueError as exc:
        print(f"\n  Error: {exc}")
        raise SystemExit(1)
    except MempalaceCompatibilityError as exc:
        print(f"\n  Compatibility error: {exc}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        raise SystemExit(130)


if __name__ == "__main__":
    main(sys.argv[1:])
