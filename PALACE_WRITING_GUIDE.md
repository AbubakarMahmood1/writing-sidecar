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

Quick chooser:

- `automate`: default entrypoint when you want the tool to choose the next move
- `routine`: one named work routine like `start-work` or `move-to-prose`
- `bundle`: the raw transition packet when you want the lower-level stack directly
- `session`: the exact phase-local packet for `braindump`, `scripting`, `staging`, `prose`, `audit`, `debug`, `handoff`, or `closeout`
- `verify`: continuity check before risky transitions

- start with `writing-sidecar automate --name recommended` when entering a sidecar-enabled project
- if you want recurring Codex help, run `writing-sidecar automate --mode suggested-create --name recommended`; this emits a suggestion packet only
- use `writing-sidecar automate --name move-to-prose` before moving into prose
- use `writing-sidecar automate --name repair-cycle` when audit/debug work starts
- use `writing-sidecar automate --name session-end|chapter-end` at real transitions
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
- treat fact previews as secondary guidance: `verify` and `session` can surface proposed adds/updates/deletes, but accepted facts only land on explicit write-capable commands
- use lower-level `routine`, `bundle`, `session`, `verify`, `recap`, `search`, or `maintain` only when you need narrower control than the automate flow

## Startup-first flow

Recommended order:

1. `writing-sidecar doctor <vault-or-project> --project <name>`
2. `writing-sidecar automate <vault-or-project> --project <name> --name recommended`
3. `writing-sidecar automate <vault-or-project> --project <name> --mode suggested-create --name recommended` when you want a Codex automation suggestion packet
4. `writing-sidecar session <vault-or-project> --project <name> --task braindump|scripting|staging|prose --write` for phase-local work
5. `writing-sidecar routine <vault-or-project> --project <name> --name move-to-prose|repair-cycle|session-end|chapter-end` when you want the lower-level packet directly
6. `writing-sidecar bundle <vault-or-project> --project <name> --name startup|pre-prose|audit-loop|handoff|closeout` only when you want the transition primitive directly
7. use `search`, `verify`, `recap`, or `maintain` only when you need narrower control

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
- `automate`

`automate --mode helper` keeps the immediate V9 helper shape. `automate --mode suggested-create` adds Codex automation suggestion fields without creating or editing an automation.

The internal fact layer stays review-first:

- preview commands surface fact deltas and conflicts
- write-capable commands can persist accepted facts into the sidecar-owned fact snapshot and log
- live docs remain the source of truth

Visible helper output is available on:

- `session --out <path>`
- `context --out <path>`
- `recap --out <path>`
- `verify --out <path>`
- `bundle --out <path>`
- `routine --out <path>`
- `automate --out <path>`
