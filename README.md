# Writing Sidecar

`writing-sidecar` is a standalone companion package for CDLC writing projects that use [MemPalace](https://github.com/milla-jovovich/mempalace) as the mining and retrieval engine.

It keeps process memory separate from canon:

- `writing-sidecar` handles project-aware export, staleness checks, intent-aware search, scaffolding, and runtime isolation.
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
writing-sidecar search <vault-or-project> --project Witcher-DC --query "Arthur sponsorship"
writing-sidecar sync <vault-or-project> --project Witcher-DC --query "Arthur sponsorship"
writing-sidecar doctor <vault-or-project> --project Witcher-DC
```

## What It Does

- exports sidecar-safe process memory into fixed rooms
- tracks state in `.writing-sidecar-state.json`
- rebuilds only when inputs actually changed
- searches by intent instead of dumping all rooms together
- isolates Chroma/ONNX caches under a vault-local runtime directory

Default project paths:

- `.sidecars/<project>`
- `.palaces/<project>`
- `.mempalace-sidecar-runtime/<project>`

Fixed rooms:

- `chat_process`
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

## Maintenance Rule

- MemPalace is the retrieval/mining engine.
- `writing-sidecar` is the writing-specific orchestrator.
- `mempalace-fork` is now legacy/reference only, not the home for new sidecar features.
