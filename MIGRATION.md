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
- startup no longer needs to be a manual `status` + `search` ritual unless you want lower-level control
- sidecar-safe writeback is now explicit and preview-first instead of being a doc-only habit
- JSON output is now stable enough for assistant glue through `--format json`

## Recommended transition

1. Keep your existing `writing-sidecar.yaml` as-is.
2. Install `writing-sidecar`.
3. Run `writing-sidecar doctor <vault> --project <name>`.
4. Run `writing-sidecar context <vault> --project <name> --mode startup`.
5. When actual work begins, run `writing-sidecar maintain <vault> --project <name> --kind checkpoint --write`.
6. Use `writing-sidecar search ...` only for targeted follow-up retrieval.
7. Switch automation, docs, and habits from `mempalace writing-*` to `writing-sidecar *`.

Examples:

```bash
writing-sidecar context C:/vault --project Witcher-DC --mode startup
writing-sidecar recap C:/vault --project Witcher-DC --mode restart
writing-sidecar maintain C:/vault --project Witcher-DC --kind closeout --write
writing-sidecar projects C:/vault --format json
```
