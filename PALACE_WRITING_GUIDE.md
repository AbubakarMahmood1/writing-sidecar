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

- start with `writing-sidecar routine --name start-work` when entering a sidecar-enabled project
- use `writing-sidecar routine --name move-to-prose` before moving into prose
- use `writing-sidecar routine --name repair-cycle` when audit/debug work starts
- use `writing-sidecar routine --name session-end|chapter-end --write` at real transitions
- use `writing-sidecar session --task braindump|scripting|staging|prose|audit|debug|handoff|closeout --write` for phase-local work
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
- use `writing-sidecar verify --scope chapter|handoff|timeline` before continuity-sensitive transitions
- use lower-level `bundle`, `session`, `verify`, `recap`, `search`, or `maintain` only when you need narrower control than the routine flow

## Startup-first flow

Recommended order:

1. `writing-sidecar doctor <vault-or-project> --project <name>`
2. `writing-sidecar routine <vault-or-project> --project <name> --name start-work`
3. `writing-sidecar session <vault-or-project> --project <name> --task braindump|scripting|staging|prose --write` for phase-local work
4. `writing-sidecar routine <vault-or-project> --project <name> --name move-to-prose` before prose starts
5. `writing-sidecar routine <vault-or-project> --project <name> --name repair-cycle`
6. `writing-sidecar routine <vault-or-project> --project <name> --name session-end|chapter-end --write`
7. use `bundle`, `search`, `verify`, `recap`, or `maintain` only when you need narrower control

## JSON output

If another tool or assistant layer needs machine-readable output, use `--format json` on:

- `status`
- `session`
- `context`
- `recap`
- `projects`
- `doctor`
- `verify`
- `maintain`
- `bundle`
- `routine`

Visible helper output is available on:

- `session --out <path>`
- `context --out <path>`
- `recap --out <path>`
- `verify --out <path>`
- `bundle --out <path>`
- `routine --out <path>`
