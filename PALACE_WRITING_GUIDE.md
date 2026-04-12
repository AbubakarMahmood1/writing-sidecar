# Palace Writing Guide

## Story Bible vs Sidecar

Use the story bible for:

- canon
- current state
- chapter planning that is still live
- active rules and constraints

Use the sidecar for:

- archived AI chats
- brainstorm bundles
- audits and criticism
- rejected structures
- historical chapter-planning residue

If the sidecar disagrees with a live story-bible file, the live doc wins.

## Room meanings

- `chat_process`: normalized AI conversations tied to the project
- `brainstorms`: exploratory ideas and future-facing planning
- `audits`: criticism, review passes, and diagnostic notes
- `discarded_paths`: rejected structures, cut branches, and things not chosen
- `research`: external or internal reference material safe to archive
- `archived_notes`: historical chapter notes and archived planning residue

## Search modes

- `planning`: `brainstorms` -> `discarded_paths` -> `audits` -> `chat_process`
- `audit`: `audits` -> `discarded_paths` -> `chat_process` -> `archived_notes`
- `history`: `chat_process` -> `audits` -> `brainstorms` -> `discarded_paths`
- `research`: `research` -> `archived_notes`

## Practical AI behavior

- start with `writing-sidecar context --mode startup` when entering a sidecar-enabled project
- use `writing-sidecar status` when you only need raw health / staleness
- if stale and the task needs process memory, run `writing-sidecar sync`
- use `writing-sidecar search --mode planning` only when `context` did not give enough planning signal
- use `writing-sidecar search --mode audit` for “what failed / what should stay cut”
- use `writing-sidecar search --mode history` for “what did we already decide”
- use `writing-sidecar search --mode research` for reference-heavy retrieval
- use `writing-sidecar recap --mode restart` after a long break
- use `writing-sidecar recap --mode handoff` before handing work to another assistant or another session
- use `writing-sidecar recap --mode continuity` when the main risk is drift, obligations, or timeline confusion

## Startup-first flow

Recommended order:

1. `writing-sidecar doctor <vault-or-project> --project <name>`
2. `writing-sidecar context <vault-or-project> --project <name> --mode startup`
3. `writing-sidecar search ...` only if you need narrower follow-up evidence
4. `writing-sidecar recap ...` only when you are recovering from a break, doing a handoff, or checking continuity risk

## JSON output

If another tool or assistant layer needs machine-readable output, use `--format json` on:

- `status`
- `context`
- `recap`
- `projects`
- `doctor`
