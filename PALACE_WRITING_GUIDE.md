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

- check `writing-sidecar status` before relying on sidecar memory
- if stale and the task needs process memory, run `writing-sidecar sync`
- use `planning` for “what are our best options”
- use `audit` for “what failed / what should stay cut”
- use `history` for “what did we already decide”
- use `research` for reference-heavy retrieval

