# Palace Writing Guide

## Story Bible vs Sidecar

Use the story bible for:

- canon
- current state
- chapter planning that is still live
- active rules and constraints

Use the sidecar for:

- archived AI chats
- structured checkpoints
- brainstorm bundles
- audits and criticism
- rejected structures
- historical chapter-planning residue

If the sidecar disagrees with a live story-bible file, the live doc wins.

## Room meanings

- `chat_process`: normalized AI conversations tied to the project
- `checkpoints`: structured startup / planning / closeout snapshots
- `brainstorms`: exploratory ideas and future-facing planning
- `audits`: criticism, review passes, and diagnostic notes
- `discarded_paths`: rejected structures, cut branches, and things not chosen
- `research`: external or internal reference material safe to archive
- `archived_notes`: historical chapter notes and archived planning residue

## Search modes

- `planning`: `checkpoints` -> `brainstorms` -> `discarded_paths` -> `audits` -> `chat_process`
- `audit`: `audits` -> `discarded_paths` -> `checkpoints` -> `chat_process` -> `archived_notes`
- `history`: `checkpoints` -> `audits` -> `brainstorms` -> `discarded_paths` -> `chat_process`
- `research`: `research` -> `archived_notes`

## Practical AI behavior

- start with `writing-sidecar session --task startup` when entering a sidecar-enabled project
- once real work begins, prefer `writing-sidecar session --task braindump|scripting|staging|prose|audit|debug|handoff|closeout --write`
- keep `planning` only as a compatibility umbrella when you want a broad pre-prose packet
- use `writing-sidecar status` when you only need raw health / staleness
- if stale and the task needs process memory, run `writing-sidecar sync`
- use `writing-sidecar search --mode planning` only when `session` or `context` did not give enough planning signal
- use `writing-sidecar search --mode audit` for “what failed / what should stay cut”
- use `writing-sidecar search --mode history` for “what did we already decide”
- use `writing-sidecar search --mode research` for reference-heavy retrieval
- use `writing-sidecar recap --mode restart` after a long break
- use `writing-sidecar recap --mode handoff` before handing work to another assistant or another session
- use `writing-sidecar recap --mode continuity` when the main risk is drift, obligations, or timeline confusion
- use lower-level `maintain` only when you need narrower control than `session --task ... --write`

## Startup-first flow

Recommended order:

1. `writing-sidecar doctor <vault-or-project> --project <name>`
2. `writing-sidecar session <vault-or-project> --project <name> --task startup`
3. `writing-sidecar session <vault-or-project> --project <name> --task braindump|scripting|staging|prose|audit|debug|handoff|closeout --write`
4. `writing-sidecar search ...` only if you need narrower follow-up evidence
5. `writing-sidecar recap ...` only when you are recovering from a break, doing a handoff, or checking continuity risk

## JSON output

If another tool or assistant layer needs machine-readable output, use `--format json` on:

- `status`
- `session`
- `context`
- `recap`
- `projects`
- `doctor`
- `maintain`

Visible helper output is available on:

- `session --out <path>`
- `context --out <path>`
- `recap --out <path>`
