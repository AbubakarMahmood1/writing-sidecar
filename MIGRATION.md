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
- startup no longer needs to be a manual `status` + `search` ritual unless you want lower-level control
- sidecar-safe writeback is now explicit and preview-first instead of being a doc-only habit
- JSON output is now stable enough for assistant glue through `--format json`
- `context`, `recap`, and `session` can now write their rendered packets to explicit files with `--out`

## Recommended transition

1. Keep your existing `writing-sidecar.yaml` as-is.
2. Install `writing-sidecar`.
3. Run `writing-sidecar doctor <vault> --project <name>`.
4. Run `writing-sidecar session <vault> --project <name> --task startup`.
5. When actual work begins, run `writing-sidecar session <vault> --project <name> --task braindump|scripting|staging|prose|audit|debug|handoff|closeout --write`.
6. Treat `planning` as a broad compatibility umbrella, not the preferred long-term phase name.
7. Use `writing-sidecar search ...` only for targeted follow-up retrieval.
8. Switch automation, docs, and habits from `mempalace writing-*` to `writing-sidecar *`.

Lower-level commands still exist when you want narrower control:
- `context`
- `recap`
- `maintain`

Examples:

```bash
writing-sidecar session C:/vault --project Witcher-DC --task startup
writing-sidecar session C:/vault --project Witcher-DC --task scripting --write --out C:/vault/.sidecar-packets/scripting.txt
writing-sidecar recap C:/vault --project Witcher-DC --mode restart
writing-sidecar maintain C:/vault --project Witcher-DC --kind closeout --write
writing-sidecar projects C:/vault --format json
```
