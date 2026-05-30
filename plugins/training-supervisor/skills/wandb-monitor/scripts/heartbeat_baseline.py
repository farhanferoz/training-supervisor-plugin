"""Adaptive heartbeat verdict for wandb-monitor.

Replaces fixed wall-clock thresholds (10 min / 30 min) with an adaptive
formula: STALE iff (run_age > warmup) AND (gap_now > K * baseline), where
K is set by the aggressiveness profile and baseline = median inter-beat
interval over recent history (with a 30 s floor).

The classify() function is pure and unit-tested; the CLI wraps a wandb.Api()
call to fetch history for a real run.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Iterable

MULTIPLIERS = {
    "paranoid": float("inf"),
    "conservative": 20.0,
    "balanced": 10.0,
    "aggressive": 5.0,
}
MIN_BASELINE_S = 30.0
MIN_HISTORY_ROWS = 5
WARMUP_S = 300.0  # 5 min


@dataclass(frozen=True)
class Verdict:
    verdict: str            # OK | STALE | WARMUP | INSUFFICIENT_HISTORY | TERMINAL
    baseline_s: float
    multiplier: float
    threshold_s: float
    gap_now_s: float


def _compute_intervals(timestamps: list[float]) -> list[float]:
    """Return consecutive inter-beat intervals from a sorted timestamp list.

    Correctly handles lists shorter than 51 entries (the original
    ``zip(ts[-51:-1], ts[-50:])`` pattern clamped both slices to the same
    range when len < 51, producing zero-length intervals).
    """
    if len(timestamps) < 2:
        return []
    recent = timestamps[-51:]   # at most the 51 most-recent entries
    return [b - a for a, b in zip(recent[:-1], recent[1:])]


def classify(
    history_intervals_s: Iterable[float],
    run_age_s: float,
    gap_now_s: float,
    aggressiveness: str,
    run_state: str = "running",
) -> Verdict:
    """Compute the heartbeat verdict.

    Parameters
    ----------
    history_intervals_s
        Inter-beat intervals (seconds) over recent history (oldest first or
        newest first, doesn't matter — we take the median).
    run_age_s
        Seconds since the run started.
    gap_now_s
        Seconds since the last beat (now - heartbeat_at).
    aggressiveness
        One of paranoid / conservative / balanced / aggressive. Sets K.
    run_state
        W&B run state string (e.g. "running", "finished", "crashed",
        "failed", "completed").  Terminal states return TERMINAL immediately
        so a finished run is never mis-classified as STALE.
    """
    if aggressiveness not in MULTIPLIERS:
        msg = f"unknown aggressiveness '{aggressiveness}'"
        raise ValueError(msg)
    k = MULTIPLIERS[aggressiveness]

    # Terminal states: the run ended intentionally or by error — no verdict
    # about staleness is meaningful.
    _TERMINAL_STATES = {"finished", "crashed", "failed", "completed"}
    if run_state in _TERMINAL_STATES:
        # Use MIN_BASELINE_S as a sensible placeholder; gap_now may be inf.
        return Verdict("TERMINAL", MIN_BASELINE_S, k, k * MIN_BASELINE_S, gap_now_s)

    intervals = list(history_intervals_s)
    if len(intervals) < MIN_HISTORY_ROWS:
        return Verdict(
            "INSUFFICIENT_HISTORY", MIN_BASELINE_S, k,
            k * MIN_BASELINE_S, gap_now_s,
        )

    baseline = max(MIN_BASELINE_S, statistics.median(intervals))
    threshold = k * baseline

    if run_age_s < WARMUP_S:
        return Verdict("WARMUP", baseline, k, threshold, gap_now_s)
    if gap_now_s > threshold:
        return Verdict("STALE", baseline, k, threshold, gap_now_s)
    return Verdict("OK", baseline, k, threshold, gap_now_s)


def _fetch_and_classify(run_id: str, entity: str, project: str,
                        aggressiveness: str) -> Verdict:
    """Live path: query W&B for history, then classify."""
    import wandb
    api = wandb.Api()
    run = api.run(f"{entity}/{project}/{run_id}")
    history = run.scan_history(keys=["_timestamp"], page_size=200)
    timestamps = [float(row["_timestamp"]) for row in history
                  if row.get("_timestamp") is not None]
    timestamps.sort()
    intervals = _compute_intervals(timestamps)
    if run.heartbeat_at:
        from datetime import datetime, timezone
        if hasattr(run.heartbeat_at, "timestamp"):
            hb_at = float(run.heartbeat_at.timestamp())
        else:
            # W&B SDK returns a string like "2025-05-30T12:34:56.000000Z"
            dt = datetime.fromisoformat(
                str(run.heartbeat_at).replace("Z", "+00:00")
            )
            hb_at = dt.astimezone(timezone.utc).timestamp()
    else:
        hb_at = 0.0
    now = time.time()
    run_age = now - timestamps[0] if timestamps else 0.0
    gap_now = now - hb_at if hb_at else float("inf")
    run_state = (run.state or "running").lower()
    return classify(intervals, run_age, gap_now, aggressiveness,
                    run_state=run_state)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wandb-monitor.heartbeat_baseline")
    p.add_argument("--run-id", required=True)
    p.add_argument("--entity", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--aggressiveness", required=True,
                   choices=tuple(MULTIPLIERS.keys()))
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    v = _fetch_and_classify(args.run_id, args.entity, args.project,
                            args.aggressiveness)
    print(f"{v.verdict} baseline={v.baseline_s:.1f}s K={v.multiplier} "
          f"threshold={v.threshold_s:.1f}s gap_now={v.gap_now_s:.1f}s")
    return 0 if v.verdict in ("OK", "WARMUP", "INSUFFICIENT_HISTORY", "TERMINAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
