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

## Recommended transition

1. Keep your existing `writing-sidecar.yaml` as-is.
2. Install `writing-sidecar`.
3. Run `writing-sidecar doctor <vault> --project <name>`.
4. Run `writing-sidecar status <vault> --project <name>`.
5. Switch automation, docs, and habits from `mempalace writing-*` to `writing-sidecar *`.
