# Post-V10 Stabilization

`writing-sidecar` is frozen at the V10 feature line.

This is not the point to start V11 planning. This is the point to:

- keep the standalone product shape stable
- clean up sidecar adoption branch sprawl
- use the tool in real work
- collect concrete friction
- review upstream MemPalace only when it helps the sidecar stack

## Repo Roles

- `writing-sidecar` is the product home.
- `mempalace-fork` is the engine compatibility and upstream-watch layer.
- `writing-vault` is the adoption and workspace layer.

## Freeze Baseline

Checked on `2026-04-15`:

- `python -m pytest -q` in the standalone repo: `55 passed`
- `python -m writing_sidecar --help` works and exposes the V10 surface
- `writing-sidecar doctor` on `Witcher-DC` reports `assistant_ready: true`
- `writing-sidecar verify --scope chapter` on `Witcher-DC` reports `warn` with `0 error / 2 warn / 0 info`
- template-path smoke stays in the expected `not_built` / warning state instead of failing hard

Working rule for this phase:

- no new commands
- no new product pillars
- only V10.x fixes inside these buckets:
  - confusing commands
  - noisy output
  - docs gaps
  - bad recommendations
  - slow paths
  - continuity false positives

## Branch Policy

### `writing-sidecar`

- keep `main` only
- use short-lived fix branches later only if a real V10.x bug appears

### `mempalace-fork`

- keep `main` as the fork/upstream sync line
- keep `private/writing-cdlc-sidecar` as the legacy reference branch
- do not put new writing workflow features here

### `writing-vault`

- keep `main`
- keep `codex/sidecar-v10-adoption`
- older sidecar adoption branches are superseded by V10 and can be pruned
- do not mix this cleanup with unrelated story-project cleanup
- do not rewrite history

### `mempalace-main`

- treat it as a plain directory snapshot, not a repo
- decide later whether to archive or delete it as filesystem cleanup

## Initial Stabilization Backlog

These are the first concrete items worth watching before any post-V10 planning.

### V10.x candidates

1. `doctor --format json` currently reports `"project": null` when you point it directly at a project root like `Witcher-DC`.
2. Command choice still has cognitive overhead across `automate`, `routine`, `bundle`, and `session`. If real use keeps tripping on this, fix it with a compact docs/UX pass, not with more commands.

### Project-hygiene items

1. `Witcher-DC` has no checkpoint artifact yet under `logs/checkpoints/`.
2. `Witcher-DC` has active carry-forward pressure living in sidecar artifacts that is not yet visible enough in the live current docs.

### Watch item

1. Re-check whether the `carry_forward_gap` warning on `Witcher-DC` stays useful after the live docs are refreshed. If it remains noisy after that, treat it as a continuity-heuristic tuning issue.

## Upstream-Watch Workflow

Use this manually about once per month, and also before any engine-compatibility fix.

Run it in `mempalace-fork`:

```powershell
git fetch upstream
git rev-list --left-right --count origin/main...upstream/main
git log --oneline --left-right --cherry-pick --no-merges origin/main...upstream/main
```

Only consider upstream intake when it falls into one of these categories:

- install/setup improvements
- mining/search/index stability fixes
- bugfixes that reduce sidecar friction
- compatibility or packaging fixes

Ignore upstream changes that add scope without helping the sidecar.

If something looks worth taking:

1. create a short-lived sync branch in `mempalace-fork`
2. bring in the candidate change there
3. validate `writing-sidecar` against it
4. merge only if it clearly improves the sidecar stack

Baseline on `2026-04-15`:

- `origin/main...upstream/main` in `mempalace-fork`: `0 0`
- current fork main is aligned with upstream main

## Exit Criteria

Do not plan V11 until all of this is true:

- at least a few real usage cycles happened
- the friction list is concrete and reproducible
- each item is classified as either:
  - `V10.x fix`
  - `future idea`
- there is no vague backlog full of "maybe later" product drift

If the issues stay local, fix them as V10.x. If they demand new concepts or deeper engine work, that is the first real signal that a post-V10 plan might be justified.
