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
