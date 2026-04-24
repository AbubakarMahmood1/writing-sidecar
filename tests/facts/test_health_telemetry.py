from __future__ import annotations

from pathlib import Path

from writing_sidecar.health import load_health_summary, record_health_event


def _emit_health_event(
    output_root: Path,
    *,
    command: str = "verify",
    command_family: str = "query",
    duration_ms: int = 1000,
    sync_performed: bool = False,
    write_performed: bool = False,
    tracked_input_count: int = 10,
    room_total: int = 20,
    room_counts: dict | None = None,
    fact_preview_op_count: int = 0,
    fact_conflict_count: int = 0,
):
    return record_health_event(
        output_root=output_root,
        project="Demo",
        project_root=output_root.parent,
        vault_root=output_root.parents[1],
        event={
            "timestamp": "2026-04-15T12:00:00+00:00",
            "command": command,
            "command_family": command_family,
            "duration_ms": duration_ms,
            "sync_performed": sync_performed,
            "write_performed": write_performed,
            "state": "clean",
            "stale": False,
            "continuity_state": "clean",
            "fact_layer_state": "preview_only",
            "fact_preview_op_count": fact_preview_op_count,
            "fact_conflict_count": fact_conflict_count,
            "tracked_input_count": tracked_input_count,
            "room_counts": room_counts or {"checkpoints": 10, "brainstorms": 10},
            "room_total": room_total,
            "palace_available": True,
            "manifest_present": True,
        },
    )


def test_health_summary_stays_unknown_until_five_samples(tmp_path):
    output_root = tmp_path / ".sidecars" / "demo"

    for _ in range(4):
        summary = _emit_health_event(output_root)

    assert summary["health_state"] == "unknown"
    assert summary["backend_review_due"] is False
    assert summary["health_sample_count"] == 4


def test_sync_latency_review_sets_backend_review_due(tmp_path):
    output_root = tmp_path / ".sidecars" / "demo"

    for _ in range(5):
        summary = _emit_health_event(
            output_root,
            command="sync",
            command_family="sync",
            duration_ms=125000,
            sync_performed=True,
        )

    assert summary["health_state"] == "review"
    assert "sync_latency_review" in summary["health_reasons"]
    assert summary["backend_review_due"] is True
    assert summary["recommended_backend_action"] == "review_backend"


def test_query_latency_watch_stays_watch_without_backend_review(tmp_path):
    output_root = tmp_path / ".sidecars" / "demo"

    for _ in range(5):
        summary = _emit_health_event(
            output_root,
            command="verify",
            command_family="query",
            duration_ms=7000,
        )

    assert summary["health_state"] == "watch"
    assert "query_latency_watch" in summary["health_reasons"]
    assert summary["backend_review_due"] is False
    assert summary["health_metrics"]["command_families"]["query"]["median_ms"] == 7000


def test_single_slow_sync_sample_does_not_trigger_backend_review(tmp_path):
    output_root = tmp_path / ".sidecars" / "demo"

    _emit_health_event(
        output_root,
        command="sync",
        command_family="sync",
        duration_ms=125000,
        sync_performed=True,
    )
    for _ in range(4):
        summary = _emit_health_event(
            output_root,
            command="verify",
            command_family="query",
            duration_ms=1000,
        )

    assert summary["health_state"] == "clean"
    assert "sync_latency_review" not in summary["health_reasons"]
    assert summary["backend_review_due"] is False


def test_single_slow_query_sample_does_not_trigger_backend_review(tmp_path):
    output_root = tmp_path / ".sidecars" / "demo"

    _emit_health_event(
        output_root,
        command="search",
        command_family="query",
        duration_ms=95000,
    )
    for _ in range(4):
        summary = _emit_health_event(
            output_root,
            command="verify",
            command_family="query",
            duration_ms=1000,
        )

    assert summary["health_state"] == "clean"
    assert "query_latency_review" not in summary["health_reasons"]
    assert summary["health_metrics"]["command_families"]["query"]["p95_ms"] is None
    assert summary["backend_review_due"] is False


def test_fact_noise_review_does_not_trigger_backend_review(tmp_path):
    output_root = tmp_path / ".sidecars" / "demo"

    for _ in range(5):
        summary = _emit_health_event(
            output_root,
            fact_preview_op_count=300,
        )

    assert summary["health_state"] == "review"
    assert "fact_noise_review" in summary["health_reasons"]
    assert summary["backend_review_due"] is False
    assert summary["recommended_backend_action"] == "keep_current_backend"


def test_stale_churn_review_does_not_trigger_backend_review(tmp_path):
    output_root = tmp_path / ".sidecars" / "demo"

    for _ in range(6):
        summary = _emit_health_event(
            output_root,
            command="sync",
            command_family="sync",
            duration_ms=1000,
            sync_performed=True,
        )

    assert summary["health_state"] == "review"
    assert "stale_churn_review" in summary["health_reasons"]
    assert summary["backend_review_due"] is False


def test_corpus_size_review_triggers_backend_review(tmp_path):
    output_root = tmp_path / ".sidecars" / "demo"

    for _ in range(5):
        summary = _emit_health_event(
            output_root,
            tracked_input_count=2600,
            room_total=12000,
        )

    loaded = load_health_summary(output_root)
    assert summary["health_state"] == "review"
    assert "corpus_size_review" in summary["health_reasons"]
    assert summary["backend_review_due"] is True
    assert loaded["health_state"] == "review"
