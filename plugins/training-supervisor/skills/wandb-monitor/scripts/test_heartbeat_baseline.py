"""Unit tests for adaptive heartbeat verdict."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import heartbeat_baseline as hb  # noqa: E402


def test_insufficient_history():
    verdict = hb.classify(
        history_intervals_s=[10.0, 12.0],  # < 5 rows
        run_age_s=600.0, gap_now_s=120.0, aggressiveness="balanced",
    )
    assert verdict.verdict == "INSUFFICIENT_HISTORY"


def test_warmup_grace():
    verdict = hb.classify(
        history_intervals_s=[60.0] * 50,
        run_age_s=120.0,  # 2 min < 5 min warmup
        gap_now_s=1200.0, aggressiveness="balanced",
    )
    assert verdict.verdict == "WARMUP"


def test_ok_when_gap_within_multiplier():
    verdict = hb.classify(
        history_intervals_s=[60.0] * 50,
        run_age_s=3600.0, gap_now_s=300.0,  # 5×, balanced K=10
        aggressiveness="balanced",
    )
    assert verdict.verdict == "OK"
    assert verdict.baseline_s == 60.0
    assert verdict.multiplier == 10.0


def test_stale_when_gap_exceeds_multiplier():
    verdict = hb.classify(
        history_intervals_s=[60.0] * 50,
        run_age_s=3600.0, gap_now_s=601.0,  # 10× + 1, balanced K=10
        aggressiveness="balanced",
    )
    assert verdict.verdict == "STALE"


def test_paranoid_never_stale():
    verdict = hb.classify(
        history_intervals_s=[60.0] * 50,
        run_age_s=3600.0, gap_now_s=86400.0,  # 1 day
        aggressiveness="paranoid",
    )
    assert verdict.verdict == "OK"


def test_aggressive_more_sensitive_than_balanced():
    intervals = [60.0] * 50
    age, gap = 3600.0, 301.0  # 5× + 1
    bal = hb.classify(intervals, age, gap, "balanced")
    agg = hb.classify(intervals, age, gap, "aggressive")
    assert bal.verdict == "OK"
    assert agg.verdict == "STALE"


def test_baseline_floor():
    verdict = hb.classify(
        history_intervals_s=[1.0] * 50,  # very fast inter-beats
        run_age_s=3600.0, gap_now_s=29.0,
        aggressiveness="balanced",  # K=10 -> floor 30s -> threshold 300s
    )
    # 29 s is below the 300 s threshold (floor=30 × K=10), so OK
    assert verdict.verdict == "OK"
    assert verdict.baseline_s == 30.0  # floored


# ---------------------------------------------------------------------------
# zip-self slice bug regression
# ---------------------------------------------------------------------------

def test_short_history_intervals_are_nonzero():
    """Short timestamp lists must produce nonzero intervals (zip-self slice bug).

    The original zip(ts[-51:-1], ts[-50:]) clamped both slices to identical
    ranges for len < 51, producing all-zero intervals and flooring the baseline
    at 30 s regardless of actual cadence.  The fixed _compute_intervals helper
    correctly pairs consecutive entries.
    """
    timestamps = [t * 60.0 for t in range(10)]  # 10 entries, 60s apart
    intervals = hb._compute_intervals(timestamps)
    assert len(intervals) == 9
    assert all(i == 60.0 for i in intervals), f"expected all 60.0, got {intervals}"


def test_compute_intervals_empty_for_single_timestamp():
    assert hb._compute_intervals([1234567890.0]) == []


def test_compute_intervals_empty_for_empty_list():
    assert hb._compute_intervals([]) == []


def test_compute_intervals_large_history_uses_recent_50():
    """With > 51 timestamps, _compute_intervals uses only the 51 most recent."""
    # 100 entries at 60 s intervals; the 51 most-recent produce 50 intervals.
    timestamps = [t * 60.0 for t in range(100)]
    intervals = hb._compute_intervals(timestamps)
    assert len(intervals) == 50
    assert all(i == 60.0 for i in intervals)


# ---------------------------------------------------------------------------
# Finished-run TERMINAL verdict
# ---------------------------------------------------------------------------

def test_finished_run_returns_terminal_not_stale():
    """A finished run with a large gap must return TERMINAL, not STALE."""
    v = hb.classify(
        history_intervals_s=[60.0] * 50,
        run_age_s=3600.0,
        gap_now_s=86400.0,   # 1 day — would be STALE for a running job
        aggressiveness="balanced",
        run_state="finished",
    )
    assert v.verdict == "TERMINAL"


def test_crashed_run_returns_terminal():
    v = hb.classify(
        history_intervals_s=[60.0] * 50,
        run_age_s=3600.0, gap_now_s=99999.0,
        aggressiveness="aggressive",
        run_state="crashed",
    )
    assert v.verdict == "TERMINAL"


def test_running_run_still_uses_gap_logic():
    """run_state='running' (default) must not short-circuit to TERMINAL."""
    v = hb.classify(
        history_intervals_s=[60.0] * 50,
        run_age_s=3600.0, gap_now_s=601.0,
        aggressiveness="balanced",
        run_state="running",
    )
    assert v.verdict == "STALE"
