# Migration

The standalone CLI replaces the fork-only `mempalace writing-*` commands.

## Command mapping

| Old | New |
|---|---|
| `mempalace writing-init ...` | `writing-sidecar init ...` |
| `mempalace writing-status ...` | `writing-sidecar status ...` |
| `mempalace writing-export ...` | `writing-sidecar export ...` |
| `mempalace writing-search ...` | `writing-sidecar search ...` |
| `mempalace writing-sync ...` | `writing-sidecar sync ...` |

## What stays the same

- `writing-sidecar.yaml`
- `.writing-sidecar-state.json`
- default output/palace/runtime paths
- fixed sidecar rooms
- sync modes: `always`, `if-needed`, `never`
- Codex rollout matching rules
- intent-aware search modes: `planning`, `audit`, `history`, `research`

## What changes

- the writing-specific workflow no longer depends on a long-lived MemPalace fork
- the CLI entrypoint is now `writing-sidecar`
- MemPalace is treated as a pinned engine dependency instead of the home of writing logic
- after parity, the fork should stop being the feature-development home for writing-sidecar behavior
- v2 adds `writing-sidecar context`, `writing-sidecar recap`, and `writing-sidecar projects`
- v3 adds `writing-sidecar maintain` and the `checkpoints` room
- v4 adds `writing-sidecar session` as the default assistant workflow entrypoint
- v5 adds phase-accurate `session` tasks for `braindump`, `scripting`, and `staging`
- v6 adds `writing-sidecar verify` as the explicit continuity guard and cached continuity state for `doctor` / `projects`
- v7 adds `writing-sidecar bundle` as the preferred transition-level workflow entrypoint
- startup no longer needs to be a manual `status` + `search` ritual unless you want lower-level control
- sidecar-safe writeback is now explicit and preview-first instead of being a doc-only habit
- JSON output is now stable enough for assistant glue through `--format json`
- `context`, `recap`, `session`, and `verify` can now write their rendered packets to explicit files with `--out`
- `bundle` can also write its rendered packet to an explicit file with `--out`

## Recommended transition

1. Keep your existing `writing-sidecar.yaml` as-is.
2. Install `writing-sidecar`.
3. Run `writing-sidecar doctor <vault> --project <name>`.
4. Run `writing-sidecar bundle <vault> --project <name> --name startup`.
5. Run `writing-sidecar bundle <vault> --project <name> --name pre-prose` before prose starts.
6. When actual work begins, run `writing-sidecar session <vault> --project <name> --task braindump|scripting|staging|prose --write`.
7. Run `writing-sidecar bundle <vault> --project <name> --name audit-loop` during audit/debug transitions.
8. Run `writing-sidecar bundle <vault> --project <name> --name handoff|closeout --write` at real transitions.
9. Treat `planning` as a broad compatibility umbrella, not the preferred long-term phase name.
10. Use `writing-sidecar verify ...`, `search ...`, `recap ...`, or `maintain ...` only for narrower control.
11. Switch automation, docs, and habits from `mempalace writing-*` to `writing-sidecar *`.

Lower-level commands still exist when you want narrower control:
- `context`
- `recap`
- `verify`
- `session`
- `maintain`

Examples:

```bash
writing-sidecar bundle C:/vault --project Witcher-DC --name startup
writing-sidecar bundle C:/vault --project Witcher-DC --name pre-prose --out C:/vault/.sidecar-packets/pre-prose.txt
writing-sidecar bundle C:/vault --project Witcher-DC --name audit-loop
writing-sidecar session C:/vault --project Witcher-DC --task scripting --write --out C:/vault/.sidecar-packets/scripting.txt
writing-sidecar verify C:/vault --project Witcher-DC --scope chapter
writing-sidecar projects C:/vault --format json
```
