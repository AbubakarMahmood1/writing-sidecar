from __future__ import annotations

import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

HEALTH_DIRNAME = "health"
HEALTH_LATEST_FILENAME = "latest.json"
HEALTH_HISTORY_FILENAME = "history.jsonl"
HEALTH_HISTORY_LIMIT = 200
HEALTH_SUMMARY_WINDOW = 50
HEALTH_MIN_SAMPLES = 5
BACKEND_REVIEW_REASONS = {
    "sync_latency_review",
    "query_latency_review",
    "corpus_size_review",
}

_HEALTH_COMMAND_DEPTH: ContextVar[int] = ContextVar("writing_sidecar_health_command_depth", default=0)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def health_dir(output_root: Path) -> Path:
    return Path(output_root).expanduser().resolve() / HEALTH_DIRNAME


def health_latest_path(output_root: Path) -> Path:
    return health_dir(output_root) / HEALTH_LATEST_FILENAME


def health_history_path(output_root: Path) -> Path:
    return health_dir(output_root) / HEALTH_HISTORY_FILENAME


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _load_json_document(path: Path) -> dict | None:
    path = Path(path).expanduser().resolve()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_history(path: Path) -> list[dict]:
    path = Path(path).expanduser().resolve()
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    events.append(payload)
    except OSError:
        return []
    return events


def _write_history(path: Path, events: list[dict]):
    _ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")


def _command_family_metrics() -> dict:
    return {
        "sync": {"sample_count": 0, "median_ms": None, "p95_ms": None},
        "query": {"sample_count": 0, "median_ms": None, "p95_ms": None},
    }


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return int((ordered[mid - 1] + ordered[mid]) / 2)


def _family_metrics(window: list[dict], family: str) -> dict:
    values = [
        int(event.get("duration_ms", 0))
        for event in window
        if event.get("command_family") == family and event.get("duration_ms") is not None
    ]
    if not values:
        return {"sample_count": 0, "median_ms": None, "p95_ms": None}
    return {
        "sample_count": len(values),
        "median_ms": _median(values),
        "p95_ms": _p95(values),
    }


def _default_health_summary(output_root: Path, *, project=None, project_root=None, vault_root=None) -> dict:
    summary_path = health_latest_path(output_root)
    return {
        "project": project,
        "project_root": str(project_root) if project_root else None,
        "vault_root": str(vault_root) if vault_root else None,
        "updated_at": None,
        "health_state": "unknown",
        "backend_review_due": False,
        "recommended_backend_action": "keep_current_backend",
        "health_reasons": [],
        "last_health_check_at": None,
        "health_sample_count": 0,
        "health_summary_path": str(summary_path),
        "health_metrics": {
            "window_size": 0,
            "tracked_input_count": 0,
            "room_total": 0,
            "room_counts": {},
            "latest_fact_preview_op_count": 0,
            "latest_fact_conflict_count": 0,
            "command_families": _command_family_metrics(),
        },
    }


def _evaluate_latency_reason(metrics: dict, *, family: str) -> str | None:
    median_ms = metrics.get("median_ms")
    p95_ms = metrics.get("p95_ms")
    if family == "sync":
        if (median_ms is not None and median_ms >= 60000) or (p95_ms is not None and p95_ms >= 120000):
            return "sync_latency_review"
        if (median_ms is not None and median_ms >= 30000) or (p95_ms is not None and p95_ms >= 60000):
            return "sync_latency_watch"
        return None
    if (median_ms is not None and median_ms >= 10000) or (p95_ms is not None and p95_ms >= 20000):
        return "query_latency_review"
    if (median_ms is not None and median_ms >= 5000) or (p95_ms is not None and p95_ms >= 10000):
        return "query_latency_watch"
    return None


def _build_health_summary(output_root: Path, *, project, project_root, vault_root, events: list[dict]) -> dict:
    summary = _default_health_summary(
        output_root,
        project=project,
        project_root=project_root,
        vault_root=vault_root,
    )
    if not events:
        return summary

    window = events[-HEALTH_SUMMARY_WINDOW:]
    latest = window[-1]
    command_families = _command_family_metrics()
    command_families["sync"] = _family_metrics(window, "sync")
    command_families["query"] = _family_metrics(window, "query")
    sync_churn = sum(1 for event in window[-10:] if event.get("sync_performed"))

    reasons: list[str] = []
    for family in ("sync", "query"):
        reason = _evaluate_latency_reason(command_families[family], family=family)
        if reason:
            reasons.append(reason)

    tracked_input_count = int(latest.get("tracked_input_count") or 0)
    room_total = int(latest.get("room_total") or 0)
    latest_fact_preview_op_count = int(latest.get("fact_preview_op_count") or 0)
    latest_fact_conflict_count = int(latest.get("fact_conflict_count") or 0)

    if tracked_input_count >= 2500 or room_total >= 10000:
        reasons.append("corpus_size_review")
    elif tracked_input_count >= 1000 or room_total >= 5000:
        reasons.append("corpus_size_watch")

    if latest_fact_preview_op_count > 250:
        reasons.append("fact_noise_review")
    elif latest_fact_preview_op_count > 150:
        reasons.append("fact_noise_watch")

    if sync_churn >= 6:
        reasons.append("stale_churn_review")
    elif sync_churn >= 3:
        reasons.append("stale_churn_watch")

    if len(window) < HEALTH_MIN_SAMPLES:
        health_state = "unknown"
    elif any(reason.endswith("_review") for reason in reasons):
        health_state = "review"
    elif any(reason.endswith("_watch") for reason in reasons):
        health_state = "watch"
    else:
        health_state = "clean"

    backend_review_due = any(reason in BACKEND_REVIEW_REASONS for reason in reasons)
    summary.update(
        {
            "project": project,
            "project_root": str(project_root),
            "vault_root": str(vault_root),
            "updated_at": _utcnow_iso(),
            "health_state": health_state,
            "backend_review_due": backend_review_due if len(window) >= HEALTH_MIN_SAMPLES else False,
            "recommended_backend_action": "review_backend"
            if len(window) >= HEALTH_MIN_SAMPLES and backend_review_due
            else "keep_current_backend",
            "health_reasons": reasons if len(window) >= HEALTH_MIN_SAMPLES else [],
            "last_health_check_at": latest.get("timestamp"),
            "health_sample_count": len(window),
            "health_summary_path": str(health_latest_path(output_root)),
            "health_metrics": {
                "window_size": len(window),
                "tracked_input_count": tracked_input_count,
                "room_total": room_total,
                "room_counts": dict(latest.get("room_counts") or {}),
                "latest_fact_preview_op_count": latest_fact_preview_op_count,
                "latest_fact_conflict_count": latest_fact_conflict_count,
                "command_families": command_families,
            },
        }
    )
    return summary


def load_health_summary(output_root: Path, *, project=None, project_root=None, vault_root=None) -> dict:
    output_root = Path(output_root).expanduser().resolve()
    payload = _load_json_document(health_latest_path(output_root))
    if not payload:
        return _default_health_summary(
            output_root,
            project=project,
            project_root=project_root,
            vault_root=vault_root,
        )
    payload.setdefault("project", project)
    payload.setdefault("project_root", str(project_root) if project_root else None)
    payload.setdefault("vault_root", str(vault_root) if vault_root else None)
    payload.setdefault("updated_at", None)
    payload.setdefault("health_state", "unknown")
    payload.setdefault("backend_review_due", False)
    payload.setdefault("recommended_backend_action", "keep_current_backend")
    payload.setdefault("health_reasons", [])
    payload.setdefault("last_health_check_at", None)
    payload.setdefault("health_sample_count", 0)
    payload.setdefault("health_summary_path", str(health_latest_path(output_root)))
    metrics = payload.setdefault("health_metrics", {})
    metrics.setdefault("window_size", 0)
    metrics.setdefault("tracked_input_count", 0)
    metrics.setdefault("room_total", 0)
    metrics.setdefault("room_counts", {})
    metrics.setdefault("latest_fact_preview_op_count", 0)
    metrics.setdefault("latest_fact_conflict_count", 0)
    command_families = metrics.setdefault("command_families", {})
    for family, defaults in _command_family_metrics().items():
        command_families.setdefault(family, defaults)
    return payload


def command_family(command: str, *, sync_performed: bool = False) -> str:
    if command in {"export", "sync"}:
        return "sync"
    if command == "maintain":
        return "sync" if sync_performed else "maintenance"
    if command in {"search", "context", "recap", "verify", "session", "bundle", "routine", "automate"}:
        return "query"
    return "other"


def record_health_event(
    *,
    output_root: Path,
    project: str,
    project_root: Path,
    vault_root: Path,
    event: dict,
) -> dict:
    output_root = Path(output_root).expanduser().resolve()
    history_path = health_history_path(output_root)
    latest_path = health_latest_path(output_root)
    events = _load_history(history_path)
    events.append(event)
    events = events[-HEALTH_HISTORY_LIMIT:]
    _write_history(history_path, events)
    summary = _build_health_summary(
        output_root,
        project=project,
        project_root=project_root,
        vault_root=vault_root,
        events=events,
    )
    _ensure_dir(latest_path.parent)
    latest_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


@contextmanager
def health_command_scope():
    depth = _HEALTH_COMMAND_DEPTH.get()
    token = _HEALTH_COMMAND_DEPTH.set(depth + 1)
    try:
        yield depth == 0
    finally:
        _HEALTH_COMMAND_DEPTH.reset(token)


def begin_health_command() -> tuple[object, bool]:
    depth = _HEALTH_COMMAND_DEPTH.get()
    token = _HEALTH_COMMAND_DEPTH.set(depth + 1)
    return token, depth == 0


def end_health_command(token):
    _HEALTH_COMMAND_DEPTH.reset(token)


def describe_health_reason(reason: str) -> str:
    mapping = {
        "sync_latency_watch": "sync latency crossed the watch threshold",
        "sync_latency_review": "sync latency crossed the review threshold",
        "query_latency_watch": "query latency crossed the watch threshold",
        "query_latency_review": "query latency crossed the review threshold",
        "corpus_size_watch": "sidecar corpus size crossed the watch threshold",
        "corpus_size_review": "sidecar corpus size crossed the review threshold",
        "fact_noise_watch": "fact preview noise crossed the watch threshold",
        "fact_noise_review": "fact preview noise crossed the review threshold",
        "stale_churn_watch": "sync churn crossed the watch threshold",
        "stale_churn_review": "sync churn crossed the review threshold",
    }
    return mapping.get(reason, reason.replace("_", " "))
