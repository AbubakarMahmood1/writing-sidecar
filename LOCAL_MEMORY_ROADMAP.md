# Local Memory Roadmap

`writing-sidecar` stays local-only. Ideas from Supermemory, Hindsight, or similar tools are only eligible when they can be implemented without a hosted API dependency and without making extracted memory more authoritative than the live story bible.

## Borrowed Now

- Retrieval budget: `search --budget quick|normal|deep` separates search depth from final result count, mirroring Hindsight-style budget control without adopting its backend.
- Local keyword lane: `--budget deep` blends filename/title/text keyword hits with vector hits so obvious handoff, chapter, and named-thread lookups are not lost to semantic ranking.
- Stable sidecar document IDs: exported inputs now get deterministic manifest-level `document_id` values based on project, room, source kind, and stable source path so content edits do not create a new identity inside sidecar state.
- Named retrieval profiles: `search --profile query|profile|full` now maps common intent levels onto existing mode and budget knobs without adding a new backend.
- Query-batch cache: repeated sidecar searches inside a single helper query batch are deep-copied from a local cache instead of hitting the backend twice.
- Fixed document-tag vocabulary: manifest entries now carry local-only `project`, `room`, `source_kind`, and `source_scope` tags for future filters without making extracted memory authoritative.

## Worth Stealing Next

- Curated mental-model style packets for durable summaries like current chapter state, ARGUS doctrine, Ciri power logic, and discarded paths.
- Backend upsert wiring if MemPalace exposes a safe local ID hook; until then, stable IDs stay sidecar-side rather than forcing a migration.

## Deferred Lab Notes

### Backend Upsert Discovery

Goal: learn whether MemPalace can safely reuse sidecar `document_id` values during local mining so updated exported files replace prior memory instead of accumulating duplicates.

Before changing behavior:

- Inspect the installed/forked MemPalace miner and Chroma write path for an explicit local document ID, update, delete, or replace hook.
- Confirm whether chunk IDs are derived from file paths, content hashes, Chroma-generated IDs, or caller-provided IDs.
- Check whether room, wing, source file, and sidecar manifest metadata can be passed through without schema breakage.
- If no clean hook exists, do not patch storage casually; treat it as a separate migration design with backup, duplicate cleanup, and rollback notes.

Safe green-light condition:

- A local-only hook exists and can be tested with a fixture proving the same exported source updates in place or removes stale chunks.

Blocked condition:

- Upsert requires changing MemPalace's storage lifecycle, Chroma schema assumptions, or existing mined data without a migration/rollback plan.

### Curated Mental-Model Packets

Goal: produce durable assistant-facing packets for repeated story concepts without letting extracted sidecar memory outrank the live story bible.

Before building packets:

- Decide the exact first packet names, probably `current chapter board`, `ARGUS doctrine`, `Ciri power logic`, and `discarded paths`.
- Define packet location under sidecar-owned paths only, not live canon docs.
- Require source references back to live docs, checkpoints, audits, or handoffs.
- Mark packets as advisory/process memory and stale when their source files change.
- Prefer manual or explicit write commands first; do not auto-update canon or silently rewrite mental models.

Safe green-light condition:

- The packet format makes authority obvious: live story bible first, curated packet second, raw sidecar retrieval third.

Blocked condition:

- The packet would summarize unresolved canon as settled fact, hide sources, or become an automatic replacement for rereading live docs.

## Migration Triggers

- Repeated sidecar health state above `CLEAN` with backend review due.
- Known recent material fails routine retrieval sanity checks.
- Duplicate or stale memory becomes common enough to affect chapter planning.
- Chroma latency or repair churn repeats across enough samples to stop being a blip.
- The sidecar starts requiring manual babysitting during normal writing sessions.

## Not Allowed By Default

- Cloud memory APIs for story or user-process memory.
- Hosted profile extraction as source of truth.
- Automatic canon edits from extracted facts.
- Backend migration for novelty alone.
