from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .mempalace_adapter import MempalaceCompatibilityError, search as raw_search
from .workflow import (
    SEARCH_MODE_ROOMS,
    _project_wing,
    _sidecar_runtime_environment,
    doctor_writing_sidecar,
    export_writing_corpus,
    get_writing_sidecar_status,
    print_doctor_report,
    print_export_summary,
    print_scaffold_summary,
    print_writing_search_results,
    print_writing_status,
    scaffold_writing_sidecar,
    search_writing_sidecar,
)


def _shared_project_args(parser: argparse.ArgumentParser, include_query: bool = False):
    parser.add_argument("dir", help="Vault root or project directory")
    parser.add_argument("--project", required=True, help="Project name (for example: Witcher-DC)")
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


def _maybe_sync(args, *, require_query_mode: bool = False):
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
        print_export_summary(summary, dry_run=False)
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
    else:
        if args.sync == "never" and status["stale"]:
            print("  Warning: sidecar is stale; skipping rebuild because --sync never was used.\n")
        else:
            print("  Sidecar is current; skipping rebuild.\n")
        if not require_query_mode:
            print_writing_status(status)
    return status


def cmd_search(args):
    status = _maybe_sync(args, require_query_mode=True)
    if args.sync == "never" and status["stale"]:
        print("  Warning: sidecar is stale; searching existing palace because --sync never was used.\n")
    palace_path = Path(status["palace_path"])
    if not palace_path.exists():
        print(f"\n  No palace found at {palace_path}")
        print("  Run writing-sidecar sync or use --sync always/if-needed to build it first.")
        raise SystemExit(1)
    with _sidecar_runtime_environment(Path(status["runtime_root"])):
        results = search_writing_sidecar(
            query=args.query,
            palace_path=str(palace_path),
            wing=_project_wing(args.project),
            mode=args.mode,
            n_results=args.results,
        )
    if results.get("error"):
        print(f"\n  Search error: {results['error']}")
        raise SystemExit(1)
    print_writing_search_results(results)


def cmd_sync(args):
    status = _maybe_sync(args)
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
                wing=_project_wing(args.project),
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
            wing=_project_wing(args.project),
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
    print_doctor_report(report)
    if not report["ok"]:
        raise SystemExit(1)


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
    _shared_project_args(p_export)
    p_export.add_argument("--mine", action="store_true", help="Mine the exported sidecar after export")
    p_export.add_argument(
        "--refresh-palace",
        action="store_true",
        help="If used with --mine, rebuild the target palace directory before mining",
    )
    p_export.add_argument("--dry-run", action="store_true", help="Show what would be exported")

    p_status = sub.add_parser("status", help="Show whether a writing sidecar is current or stale")
    _shared_project_args(p_status)

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
    }

    try:
        handlers[args.command](args)
    except FileNotFoundError as exc:
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
