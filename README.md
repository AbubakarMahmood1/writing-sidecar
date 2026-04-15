# Writing Sidecar

`writing-sidecar` is a standalone companion package for CDLC writing projects that use [MemPalace](https://github.com/milla-jovovich/mempalace) as the mining and retrieval engine.

It keeps process memory separate from canon:

- `writing-sidecar` handles project-aware export, staleness checks, intent-aware search, startup context, recap generation, deterministic continuity verification, scaffolding, and runtime isolation.
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
writing-sidecar automate <vault-or-project> --project Witcher-DC --name recommended
writing-sidecar automate <vault-or-project> --project Witcher-DC --mode suggested-create --name recommended
writing-sidecar routine <vault-or-project> --project Witcher-DC --name start-work
writing-sidecar session <vault-or-project> --project Witcher-DC --task scripting
writing-sidecar context <vault-or-project> --project Witcher-DC
writing-sidecar search <vault-or-project> --project Witcher-DC --query "Arthur sponsorship"
writing-sidecar recap <vault-or-project> --project Witcher-DC --mode restart
writing-sidecar verify <vault-or-project> --project Witcher-DC --scope chapter
writing-sidecar maintain <vault-or-project> --project Witcher-DC --kind checkpoint --write
writing-sidecar sync <vault-or-project> --project Witcher-DC --query "Arthur sponsorship"
writing-sidecar doctor <vault-or-project> --project Witcher-DC
writing-sidecar projects <vault>
```

Structured output is available on:

- `status --format json`
- `session --format json`
- `context --format json`
- `recap --format json`
- `projects --format json`
- `doctor --format json`
- `verify --format json`
- `bundle --format json`
- `routine --format json`
- `automate --format json`

## What It Does

- exports sidecar-safe process memory into fixed rooms
- tracks state in `.writing-sidecar-state.json`
- rebuilds only when inputs actually changed
- searches by intent instead of dumping all rooms together
- exports Codex-ready helper packets and suggested-create automation packets through deterministic `automate` output
- packages common work sessions with deterministic `routine` runbooks
- packages transition moments with deterministic `bundle` runbooks
- runs a phase-aware assistant workflow with `session`
- builds a compact startup packet for assistants with `context`
- generates deterministic restart / handoff / continuity recaps with `recap`
- verifies continuity drift against live docs, trackers, timeline files, and sidecar carry-forward memory with `verify`
- keeps a secondary fact layer for deterministic fact previews, drift checks, and explicit reconciliation on write-capable commands
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

Tool-owned continuity cache:

- `.sidecars/<project>/.writing-sidecar-verify.json`

Tool-owned fact layer:

- `.sidecars/<project>/facts/reconcile_preview.json`
- `.sidecars/<project>/facts/facts_snapshot.json`
- `.sidecars/<project>/facts/fact_log.jsonl`

## Scope

`writing-sidecar` is process memory only.

The fact layer is secondary and reviewable. Live docs still win, sidecar artifacts stay evidence, and accepted facts never rewrite canon docs.

It is not:

- a canon/state authority
- a story-bible replacement
- a knowledge graph for character truth

## Fork status

Once this package becomes your normal entrypoint, treat `mempalace-fork` as a compatibility/reference branch, not the place where new writing features should keep landing.

## Docs

- [Migration from `mempalace writing-*`](./MIGRATION.md)
- [Palace Writing Guide](./PALACE_WRITING_GUIDE.md)
- [Post-V10 Stabilization](./POST_V10_STABILIZATION.md)

## Recommended Codex Flow

Use `automate` as the default Codex-facing helper layer. Use `automate --mode suggested-create` only when you want a Codex automation suggestion packet; it does not create or edit an automation by itself. Keep `routine` for lower-level workflow packets, `bundle` for transition primitives, and `session` for phase-local work.

Quick chooser:

- `automate`: "tell me the best next move"
- `routine`: "package one common work routine for me"
- `bundle`: "show me the raw transition stack"
- `session`: "give me the packet for the exact phase I am in"
- `verify`: "check continuity before I trust the next move"

1. `writing-sidecar doctor <vault-or-project> --project <name>` only when setup confidence is low
2. `writing-sidecar automate <vault-or-project> --project <name> --name recommended`
3. `writing-sidecar automate <vault-or-project> --project <name> --mode suggested-create --name recommended` when you want recurring Codex help for that project
4. `writing-sidecar session <vault-or-project> --project <name> --task braindump|scripting|staging|prose --write` for phase-local work
5. `writing-sidecar routine <vault-or-project> --project <name> --name move-to-prose|repair-cycle|session-end|chapter-end` when you want the lower-level workflow packet directly
6. `writing-sidecar bundle <vault-or-project> --project <name> --name startup|pre-prose|audit-loop|handoff|closeout` only when you want the transition primitive directly
7. use `verify`, `recap`, `search`, or `maintain` only when you need narrower control

Examples:

```bash
writing-sidecar automate C:/vault --project Witcher-DC --name recommended
writing-sidecar automate C:/vault --project Witcher-DC --mode suggested-create --name recommended
writing-sidecar automate C:/vault --project Witcher-DC --mode suggested-create --name move-to-prose
writing-sidecar automate C:/vault --project Witcher-DC --mode suggested-create --name repair-cycle
writing-sidecar session C:/vault --project Witcher-DC --task scripting --write
writing-sidecar verify C:/vault --project Witcher-DC --scope timeline
writing-sidecar projects C:/vault --format json
```

Recommended Codex operating loop:

1. `writing-sidecar automate <vault-or-project> --project <name> --name recommended`
2. `writing-sidecar automate <vault-or-project> --project <name> --mode suggested-create --name recommended` when you want a Codex automation suggestion packet
3. `writing-sidecar session <vault-or-project> --project <name> --task braindump|scripting|staging|prose --write` for phase-local work
4. `writing-sidecar routine <vault-or-project> --project <name> --name move-to-prose|repair-cycle|session-end|chapter-end` for lower-level transition packets
5. `writing-sidecar bundle <vault-or-project> --project <name> --name startup|pre-prose|audit-loop|handoff|closeout` only when you want the transition primitive directly
6. treat `planning` as a compatibility umbrella, not the preferred long-term phase task
7. keep live story-bible docs as canon and treat sidecar output as process memory only

## JSON contract

When you use `--format json`, v10.x keeps these top-level keys stable where they apply:

- `project`
- `project_root`
- `vault_root`
- `state`
- `stale`
- `reasons`
- `last_synced_at`

Command-specific payload keys remain stable too:

- `status`: `room_counts`, `config_path`, `manifest_path`, `palace_path`, `runtime_root`
- `session`: `task`, `operative_phase`, `suggested_loadout`, `doc_loadout`, `file_targets`, `continuity_watch`, `phase_guardrails`, `done_criteria`, `recommended_actions`, `recommended_commands`, `artifact_targets`, `write_performed`, `sync_performed`, `queries_run`, `results`, `recap_sections`, `warnings`, `verification_scope`, `continuity_state`, `finding_counts`, `top_findings`, `recommended_repairs`, `fact_layer_state`, `fact_counts`, `fact_ops_preview`, `fact_conflicts`, `fact_highlights`, `last_fact_sync_at`, `fact_layer_ready`
- `context`: `mode`, `queries_run`, `results`, `warnings`, `suggested_loadout`, `recent_artifacts`
- `recap`: `mode`, `sections`, `queries_run`, `results`, `warnings`
- `projects`: `count`, `projects`, including per-project `operative_phase`, `next_action`, `assistant_ready`, `last_checkpoint_at`, `continuity_state`, `last_verified_at`, `finding_counts`, `verification_stale`, `recommended_entrypoint`, `recommended_routine`, `recommended_automate_command`, `recommended_automation_command`, `recommended_schedule_profile`, `fact_layer_ready`, `last_fact_sync_at`
- `doctor`: `checks`, `workflow_checks`, `assistant_ready`, `ok`, `supported_spec`, `mempalace_version`, `continuity_state`, `last_verified_at`, `finding_counts`, `verification_stale`, `recommended_entrypoint`, `recommended_routine`, `recommended_automate_command`, `recommended_automation_command`, `recommended_schedule_profile`, `fact_layer_ready`, `last_fact_sync_at`
- `verify`: `scope`, `state`, `verified_at`, `finding_counts`, `findings`, `recommended_actions`, `query_packets`, `source_snapshot`, `cache_path`, `fact_layer_state`, `fact_counts`, `fact_ops_preview`, `fact_conflicts`, `fact_highlights`, `last_fact_sync_at`, `fact_layer_ready`
- `maintain`: `kind`, `mode`, `write_performed`, `paths_written`, `sync_performed`, `warnings`, `source_inputs`, `generated_sections`, `fact_layer_state`, `fact_counts`, `fact_ops_preview`, `fact_conflicts`, `fact_highlights`, `last_fact_sync_at`, `fact_layer_ready`, `fact_write_performed`, `fact_paths_written`
- `bundle`: `bundle`, `verify_mode`, `operative_phase`, `continuity_state`, `finding_counts`, `top_findings`, `doc_loadout`, `file_targets`, `artifact_targets`, `recap_sections`, `steps`, `recommended_actions`, `recommended_commands`, `write_performed`, `paths_written`, `sync_performed`, `warnings`, `fact_layer_state`, `fact_counts`, `fact_conflicts`, `fact_highlights`, `last_fact_sync_at`, `fact_layer_ready`
- `routine`: `routine`, `verify_mode`, `operative_phase`, `continuity_state`, `finding_counts`, `top_findings`, `doc_loadout`, `file_targets`, `artifact_targets`, `recap_sections`, `steps`, `recommended_actions`, `recommended_commands`, `write_performed`, `paths_written`, `sync_performed`, `warnings`, `fact_layer_state`, `fact_counts`, `fact_conflicts`, `fact_highlights`, `last_fact_sync_at`, `fact_layer_ready`
- `automate` helper mode: `target`, `name`, `routine`, `operative_phase`, `continuity_state`, `finding_counts`, `top_findings`, `doc_loadout`, `file_targets`, `artifact_targets`, `entry_command`, `write_variant_command`, `prompt`, `expected_outputs`, `recommended_actions`, `recommended_commands`, `warnings`, `fact_layer_state`, `fact_counts`, `fact_conflicts`, `fact_highlights`, `last_fact_sync_at`, `fact_layer_ready`
- `automate` suggested-create mode adds: `automation_name`, `automation_prompt`, `automation_rrule`, `automation_cwds`, `automation_status`, `schedule_profile`

Visible helper output is also supported on:

- `session --out <path>`
- `context --out <path>`
- `recap --out <path>`
- `verify --out <path>`
- `bundle --out <path>`
- `routine --out <path>`
- `automate --out <path>`

## Maintenance Rule

- MemPalace is the retrieval/mining engine.
- `writing-sidecar` is the writing-specific orchestrator.
- `mempalace-fork` is now legacy/reference only, not the home for new sidecar features.
