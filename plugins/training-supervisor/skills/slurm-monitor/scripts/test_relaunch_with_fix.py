"""Unit tests for the relaunch_with_fix.sh fix-selection + rendering logic.

We test the embedded Python helper directly (sibling file rendered.py).
The bash wrapper is smoke-tested separately in Step 5.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rendered  # noqa: E402 — sibling module (see Step 3)


def test_oom_halve_batch_renders():
    fix = rendered.select_fix(
        registry_path=str(HERE.parent / "fixes" / "registry.yaml"),
        failure_class="oom",
        run_config={"datamodule": {"batch_size": 8},
                    "trainer": {"accumulate_grad_batches": 1}},
        authority="aggressive",
    )
    assert fix.id == "oom_halve_batch"
    assert fix.risk == "safe"
    assert fix.action == "autonomous"
    assert "datamodule.batch_size=4" in fix.hydra_overrides
    assert "+trainer.accumulate_grad_batches=2" in fix.hydra_overrides


def test_oom_balanced_propose():
    fix = rendered.select_fix(
        registry_path=str(HERE.parent / "fixes" / "registry.yaml"),
        failure_class="oom",
        run_config={"datamodule": {"batch_size": 8},
                    "trainer": {"accumulate_grad_batches": 1}},
        authority="balanced",
    )
    assert fix.action == "propose"


def test_loss_nan_always_escalates():
    for auth in ("paranoid", "conservative", "balanced", "aggressive"):
        fix = rendered.select_fix(
            registry_path=str(HERE.parent / "fixes" / "registry.yaml"),
            failure_class="loss_nan",
            run_config={}, authority=auth,
        )
        assert fix.risk == "escalate"
        assert fix.action == "escalate"


def test_stagnant_requires_check():
    # Fix should be skipped if current_min_lr_ratio is already 0.1.
    fix = rendered.select_fix(
        registry_path=str(HERE.parent / "fixes" / "registry.yaml"),
        failure_class="stagnant",
        run_config={"optimizer": {"min_lr_ratio": 0.1}},
        authority="aggressive",
    )
    assert fix is None or fix.id != "stagnant_raise_lr_floor"


def test_paranoid_never_autonomous():
    fix = rendered.select_fix(
        registry_path=str(HERE.parent / "fixes" / "registry.yaml"),
        failure_class="crashed",
        run_config={},
        authority="paranoid",
    )
    assert fix is None or fix.action != "autonomous"


def test_oom_requires_batch_size_at_least_2():
    fix = rendered.select_fix(
        registry_path=str(HERE.parent / "fixes" / "registry.yaml"),
        failure_class="oom",
        run_config={"datamodule": {"batch_size": 1}},
        authority="aggressive",
    )
    # batch_size=1 fails requires; fix should be skipped.
    assert fix is None
