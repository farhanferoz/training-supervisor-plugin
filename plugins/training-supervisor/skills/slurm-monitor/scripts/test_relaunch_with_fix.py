"""Unit tests for the relaunch_with_fix.sh fix-selection + rendering logic.

We test the embedded Python helper directly (sibling file rendered.py).
The bash wrapper is smoke-tested separately in Step 5.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# C1: safe evaluator security regression tests
# ---------------------------------------------------------------------------

def test_safe_eval_dunder_traversal_raises():
    """Dunder attribute traversal via __class__ must be rejected (C1 RCE PoC)."""
    with pytest.raises(ValueError):
        rendered._render("{{ batch_size.__class__ }}", {"batch_size": 1})


def test_safe_eval_subscript_raises():
    """Subscript access must be rejected."""
    with pytest.raises(ValueError):
        rendered._render("{{ batch_size[0] }}", {"batch_size": 1})


def test_safe_eval_call_raises():
    """Function calls must be rejected."""
    with pytest.raises(ValueError):
        rendered._render("{{ open('x') }}", {"batch_size": 1})


def test_safe_eval_pow_raises():
    """Exponentiation (** / Pow) must be rejected to prevent exponent overflow."""
    with pytest.raises(ValueError):
        rendered._render("{{ 2 ** 64 }}", {})


def test_safe_eval_unmatched_brace_raises():
    """Unmatched '{{' must raise ValueError with a clear message."""
    with pytest.raises(ValueError, match="unmatched"):
        rendered._render("{{ batch_size // 2", {"batch_size": 8})


def test_oom_halve_batch_still_renders_correctly():
    """Functionality preserved: oom_halve_batch renders correct values (C1 regression)."""
    fix = rendered.select_fix(
        registry_path=str(HERE.parent / "fixes" / "registry.yaml"),
        failure_class="oom",
        run_config={"datamodule": {"batch_size": 8},
                    "trainer": {"accumulate_grad_batches": 1}},
        authority="aggressive",
    )
    assert fix is not None
    assert fix.id == "oom_halve_batch"
    assert "datamodule.batch_size=4" in fix.hydra_overrides
    assert "+trainer.accumulate_grad_batches=2" in fix.hydra_overrides


def test_ifexp_allowed_in_safe_eval():
    """IfExp (ternary) is required by the oom template and must be allowed."""
    result = rendered._render(
        "{{ accumulate * 2 if accumulate else 2 }}", {"accumulate": 1}
    )
    assert result == "2"


# ---------------------------------------------------------------------------
# C2: shlex-quote shell-injection regression test
# ---------------------------------------------------------------------------

def test_write_next_action_shlex_quotes_overrides(tmp_path):
    """Override containing shell metacharacter is quoted, not injected (C2)."""
    next_action = tmp_path / "next_action.sh"
    rendered._write_next_action(
        path=str(next_action),
        template="ssh {HOST} autocast epd {OVERRIDES}",
        ssh_host="login.example",
        overrides=["datamodule.batch_size=32; echo INJECT"],
    )
    body = next_action.read_text()
    # The semicolon must be inside quotes, not a bare shell statement separator.
    assert "echo INJECT" not in body.split("'")[0]  # not before first quote
    assert "'datamodule.batch_size=32; echo INJECT'" in body


# ---------------------------------------------------------------------------
# C2-v2: double-quoting for remote shell safety
# ---------------------------------------------------------------------------

def test_write_next_action_quotes_for_remote_shell(tmp_path):
    """Override with shell metacharacter is safe across both quoting layers (C2-v2).

    The semicolon must appear inside a quoted context in the generated script
    so the remote shell never sees it as a statement separator.  Specifically:
    shlex.split() on the ssh invocation line should yield the full override
    string as a single token.
    """
    import shlex
    next_action = tmp_path / "next_action.sh"
    rendered._write_next_action(
        path=str(next_action),
        template="ssh {HOST} autocast epd --mode slurm {OVERRIDES}",
        ssh_host="login.example",
        overrides=["datamodule.batch_size=32; touch /tmp/INJECTED"],
    )
    body = next_action.read_text()
    # Strip the preamble (shebang + comment + set line) to get the ssh line.
    ssh_line = [ln for ln in body.splitlines() if ln.startswith("ssh")][0]
    tokens = shlex.split(ssh_line)
    # tokens: ["ssh", "--", "login.example", "<full remote cmd with override>"]
    # The remote cmd string must contain the override as one token (no split).
    remote_cmd = tokens[-1]
    # The full override value including the semicolon must appear inside the
    # remote cmd (which is passed as a single quoted argument to ssh).
    assert "datamodule.batch_size=32; touch /tmp/INJECTED" in remote_cmd
    # The ssh invocation must use -- to guard against hostname option injection.
    assert "--" in tokens


def test_write_next_action_rejects_dash_hostname(tmp_path):
    """_write_next_action rejects a hostname starting with '-' (H-new)."""
    next_action = tmp_path / "next_action.sh"
    with pytest.raises(ValueError, match="ssh_host"):
        rendered._write_next_action(
            path=str(next_action),
            template="ssh {HOST} autocast epd {OVERRIDES}",
            ssh_host="-oProxyCommand=touch /tmp/pwned",
            overrides=[],
        )


# ---------------------------------------------------------------------------
# C1: risk-value validation
# ---------------------------------------------------------------------------

def test_select_fix_rejects_unknown_risk_value(tmp_path):
    """select_fix must raise ValueError if a registry entry has an unknown risk."""
    bad_registry = tmp_path / "bad.yaml"
    bad_registry.write_text(textwrap.dedent("""\
        fixes:
          oom:
            - id: test_bad_risk
              description: "test"
              risk: dangerous
              hydra_overrides: []
    """))
    with pytest.raises(ValueError, match="unknown risk"):
        rendered.select_fix(
            registry_path=str(bad_registry),
            failure_class="oom",
            run_config={"datamodule": {"batch_size": 8}},
            authority="aggressive",
        )


# ---------------------------------------------------------------------------
# ADV-1: string-repetition DoS cap + non-numeric arithmetic guard
# ---------------------------------------------------------------------------

def test_safe_eval_rejects_oversized_string_result():
    """String repetition producing a result > _MAX_RESULT_LEN raises ValueError (ADV-1)."""
    # "A" * 5000 would produce a 5000-char string; cap is 4096.
    with pytest.raises(ValueError, match="template result too large"):
        rendered._safe_eval("batch_size * 5000", {"batch_size": "A" * 10})


def test_safe_eval_rejects_string_arithmetic():
    """String * int arithmetic raises ValueError, not producing a large string (ADV-1)."""
    # "AAA" * 2 would silently produce "AAAAAA" — guard catches it as TypeError or size.
    with pytest.raises(ValueError):
        rendered._safe_eval('x * 2', {"x": "AAA" * 2000})


# ---------------------------------------------------------------------------
# Residual MEDs: _check_requires None guard + registry version warning
# ---------------------------------------------------------------------------

def test_check_requires_returns_false_when_env_missing():
    """_check_requires returns False when the rhs env var is missing (None guard)."""
    # "batch_size >= unknown" — 'unknown' is not in env, so rhs=None → False.
    assert not rendered._check_requires(["batch_size >= unknown"], {"batch_size": 4})


def test_check_requires_returns_false_when_lhs_missing():
    """_check_requires returns False when the lhs env var is missing (None guard)."""
    assert not rendered._check_requires(["missing_key >= 0"], {})
