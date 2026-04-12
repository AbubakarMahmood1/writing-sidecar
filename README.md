# Writing Sidecar

`writing-sidecar` is a standalone companion package for CDLC writing projects that use [MemPalace](https://github.com/milla-jovovich/mempalace) as the mining and retrieval engine.

It keeps process memory separate from canon:

- `writing-sidecar` handles project-aware export, staleness checks, intent-aware search, startup context, recap generation, scaffolding, and runtime isolation.
- MemPalace handles transcript normalization, mining, and semantic search.
- Your story bible stays the source of truth.

## Install

Tested target:

- Python `3.11` or `3.12`
- MemPalace `>=3.1,<3.2`

```bash
pip install mempalace
pip install "git+https://github.com/AbubakarMahmood1/writing-sidecar.git"
```

If you want exact parity with your local forked MemPalace checkout while testing:

```bash
pip install -e /path/to/mempalace-fork
pip install -e /path/to/writing-sidecar[dev]
```

Windows note:

- Python `3.14` is not a supported install target for v1
- a clean install may still pull a `chroma-hnswlib` build path through MemPalace/Chroma
- on Windows, use Python `3.11` or `3.12` unless you intentionally want to manage native build-tool fallout yourself
- if you still hit the native build path, either install the needed C++ build tools or reuse an environment where MemPalace's existing dependencies already work
- `writing-sidecar doctor` checks runtime health after install, but it cannot bypass native wheel/build issues during `pip install`

## Commands

```bash
writing-sidecar init <vault-or-project> --project Witcher-DC
writing-sidecar status <vault-or-project> --project Witcher-DC
writing-sidecar export <vault-or-project> --project Witcher-DC
writing-sidecar context <vault-or-project> --project Witcher-DC
writing-sidecar search <vault-or-project> --project Witcher-DC --query "Arthur sponsorship"
writing-sidecar recap <vault-or-project> --project Witcher-DC --mode restart
writing-sidecar maintain <vault-or-project> --project Witcher-DC --kind checkpoint --write
writing-sidecar sync <vault-or-project> --project Witcher-DC --query "Arthur sponsorship"
writing-sidecar doctor <vault-or-project> --project Witcher-DC
writing-sidecar projects <vault>
```

Structured output is available on:

- `status --format json`
- `context --format json`
- `recap --format json`
- `projects --format json`
- `doctor --format json`

## What It Does

- exports sidecar-safe process memory into fixed rooms
- tracks state in `.writing-sidecar-state.json`
- rebuilds only when inputs actually changed
- searches by intent instead of dumping all rooms together
- builds a compact startup packet for assistants with `context`
- generates deterministic restart / handoff / continuity recaps with `recap`
- auto-resolves the project when the input path is already inside one sidecar-enabled project
- isolates Chroma/ONNX caches under a vault-local runtime directory

Default project paths:

- `.sidecars/<project>`
- `.palaces/<project>`
- `.mempalace-sidecar-runtime/<project>`

Fixed rooms:

- `chat_process`
- `checkpoints`
- `brainstorms`
- `audits`
- `discarded_paths`
- `research`
- `archived_notes`

## Scope

`writing-sidecar` is process memory only.

It is not:

- a canon/state authority
- a story-bible replacement
- a knowledge graph for character truth

## Fork status

Once this package becomes your normal entrypoint, treat `mempalace-fork` as a compatibility/reference branch, not the place where new writing features should keep landing.

## Docs

- [Migration from `mempalace writing-*`](./MIGRATION.md)
- [Palace Writing Guide](./PALACE_WRITING_GUIDE.md)

## Recommended Codex Flow

For normal project startup:

1. `writing-sidecar doctor <vault-or-project> --project <name>`
2. `writing-sidecar context <vault-or-project> --project <name> --mode startup`
3. `writing-sidecar search ...` only when you need a tighter follow-up query
4. do the normal writing task

Examples:

```bash
writing-sidecar context C:/vault --project Witcher-DC --mode startup
writing-sidecar recap C:/vault --project Witcher-DC --mode restart
writing-sidecar maintain C:/vault --project Witcher-DC --kind checkpoint --write
writing-sidecar projects C:/vault --format json
```

Recommended Codex operating loop:

1. `writing-sidecar context <vault-or-project> --project <name> --mode startup`
2. `writing-sidecar maintain <vault-or-project> --project <name> --kind checkpoint --write`
3. do the actual writing / planning / audit work
4. use `search` only for narrower follow-up evidence
5. before handoff or closeout, use `maintain --kind handoff|audit|closeout`

## JSON contract

When you use `--format json`, v2 keeps these top-level keys stable where they apply:

- `project`
- `project_root`
- `vault_root`
- `state`
- `stale`
- `reasons`
- `last_synced_at`

Command-specific payload keys remain stable too:

- `status`: `room_counts`, `config_path`, `manifest_path`, `palace_path`, `runtime_root`
- `context`: `mode`, `queries_run`, `results`, `warnings`, `suggested_loadout`, `recent_artifacts`
- `recap`: `mode`, `sections`, `queries_run`, `results`, `warnings`
- `projects`: `count`, `projects`
- `doctor`: `checks`, `ok`, `supported_spec`, `mempalace_version`
- `maintain`: `kind`, `mode`, `write_performed`, `paths_written`, `sync_performed`, `warnings`, `source_inputs`, `generated_sections`

## Maintenance Rule

- MemPalace is the retrieval/mining engine.
- `writing-sidecar` is the writing-specific orchestrator.
- `mempalace-fork` is now legacy/reference only, not the home for new sidecar features.
