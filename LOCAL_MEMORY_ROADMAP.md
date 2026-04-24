# Local Memory Roadmap

`writing-sidecar` stays local-only. Ideas from Supermemory, Hindsight, or similar tools are only eligible when they can be implemented without a hosted API dependency and without making extracted memory more authoritative than the live story bible.

## Borrowed Now

- Retrieval budget: `search --budget quick|normal|deep` separates search depth from final result count, mirroring Hindsight-style budget control without adopting its backend.
- Local keyword lane: `--budget deep` blends filename/title/text keyword hits with vector hits so obvious handoff, chapter, and named-thread lookups are not lost to semantic ranking.

## Worth Stealing Next

- Stable document IDs for sidecar exports so long-running session/chapter artifacts can be updated without duplicate memory buildup.
- Named retrieval profiles, such as `profile`, `query`, and `full`, mapped onto writing-sidecar's existing context/search modes.
- Per-turn or per-command retrieval cache so multi-step workflows do not repeat identical local searches.
- Curated mental-model style packets for durable summaries like current chapter state, ARGUS doctrine, Ciri power logic, and discarded paths.
- Stricter tag vocabulary for project, chapter, phase, room, and artifact type.

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
