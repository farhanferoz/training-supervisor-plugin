"""Unit tests for slurm-monitor collector.

Mocks subprocess calls to ~/bin/sjob and ~/bin/wbcheck so tests run without
a live cluster or W&B credentials.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

# Allow direct import of the sibling collect.py
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect  # noqa: E402


def _stub_run(cmds_to_outputs):
    """Return a fake subprocess.run that looks up the called argv prefix."""
    def fake(args, *_, **__):
        for prefix, out in cmds_to_outputs.items():
            prefix_list = list(prefix)
            if args[:len(prefix_list)] == prefix_list:
                return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=f"no stub: {args}")
    return fake


def test_collect_running_job_produces_markdown_with_state_and_trajectories():
    sjob_out = (
        "JobID|JobName|State|Elapsed|Start|End|Timelimit|ExitCode\n"
        "12345|train|RUNNING|01:23:45|2026-05-29T10:00:00|Unknown|23:59:00|0:0\n"
    )
    wbcheck_out = (
        "=== runs (turing-core/autocast) ===\n"
        "  [RUN] abc12345 state=running name=foo epoch=30 ep/h=2.5\n"
    )
    cmds = {
        # Distinguish status vs when so the test reflects the real two-call flow.
        # _sjob now uses "ssh -- <host> ..." so the stub key includes "--".
        ("ssh", "--", "host.example", "sjob", "12345", "status"): sjob_out,
        ("ssh", "--", "host.example", "sjob", "12345", "when"):
            "Reason=None  StartTime=2026-05-29T10:00:00  EndTime=Unknown\n",
        ("wbcheck",): wbcheck_out,
    }
    with mock.patch.object(collect.subprocess, "run", side_effect=_stub_run(cmds)):
        report = collect.collect(
            job_id="12345",
            wandb_run="abc12345",
            ref_run=None,
            ssh_host="host.example",
            epochs=[0, 5, 10, 20],
        )

    assert "> contract: v1" in report  # required by CONTRACT.md
    # CONTRACT.md v1 required sections
    assert "## job state" in report
    assert "## progress" in report
    assert "## heartbeat" in report
    assert "## run state" in report
    # Content checks
    assert "RUNNING" in report
    assert "turing-core/autocast" in report
    assert "reachable: true" in report


def test_collect_marks_partial_on_ssh_failure():
    cmds = {("wbcheck",): "stub wbcheck output\n"}  # ssh stub absent → fails
    with mock.patch.object(collect.subprocess, "run", side_effect=_stub_run(cmds)):
        report = collect.collect(
            job_id="12345", wandb_run="abc12345", ref_run=None,
            ssh_host="host.example", epochs=[0],
        )
    assert "PARTIAL" in report
    assert "reachable: false" in report


def test_collect_refuses_when_inputs_missing():
    with pytest.raises(ValueError, match="job_id"):
        collect.collect(job_id="", wandb_run="abc", ref_run=None,
                        ssh_host="host", epochs=[0])
    with pytest.raises(ValueError, match="wandb_run"):
        collect.collect(job_id="123", wandb_run="", ref_run=None,
                        ssh_host="host", epochs=[0])


def test_env_var_delegates_to_custom_collector(monkeypatch, capsys):
    """JOB_MONITOR_COLLECTOR set -> main() execs that script with same argv."""
    sentinel = "CUSTOM_RAN"

    def fake_run(args, **kwargs):
        print(sentinel + " " + " ".join(args), flush=True)
        return subprocess.CompletedProcess(args, 7)  # arbitrary non-zero

    monkeypatch.setenv("JOB_MONITOR_COLLECTOR", "/tmp/fake-collector.sh")
    monkeypatch.setattr(collect.subprocess, "run", fake_run)
    rc = collect.main(["--job-id", "1", "--wandb-run", "x",
                       "--ssh-host", "h"])
    assert rc == 7
    out = capsys.readouterr().out
    assert sentinel in out
    assert "/tmp/fake-collector.sh" in out


# ---------------------------------------------------------------------------
# H1: CONTRACT.md v1 section presence
# ---------------------------------------------------------------------------

def test_collect_emits_all_four_required_contract_sections():
    """All four CONTRACT.md v1 sections must be present in correct order (H1)."""
    sjob_out = (
        "JobID|JobName|State|Elapsed|Start|End|Timelimit|ExitCode\n"
        "99999|mytrain|RUNNING|02:00:00|2026-05-29T08:00:00|Unknown|24:00:00|0:0\n"
    )
    wbcheck_out = "state=running epoch=50\n"
    cmds = {
        ("ssh", "--", "h", "sjob", "99999", "status"): sjob_out,
        ("ssh", "--", "h", "sjob", "99999", "when"): "end=Unknown\n",
        ("wbcheck",): wbcheck_out,
    }
    with mock.patch.object(collect.subprocess, "run", side_effect=_stub_run(cmds)):
        report = collect.collect(
            job_id="99999", wandb_run="abc99999", ref_run=None,
            ssh_host="h", epochs=[0, 10],
        )
    # Section ordering
    idx_job = report.index("## job state")
    idx_prog = report.index("## progress")
    idx_hb = report.index("## heartbeat")
    idx_run = report.index("## run state")
    assert idx_job < idx_prog < idx_hb < idx_run

    # Heartbeat verdict field present
    assert "- verdict:" in report


def test_collect_heartbeat_verdict_present():
    """## heartbeat section must contain a verdict line (H1)."""
    cmds = {
        ("ssh", "--", "h", "sjob", "1", "status"): (
            "JobID|JobName|State|Elapsed|Start|End|Timelimit|ExitCode\n"
            "1|t|RUNNING|00:01:00|x|y|01:00:00|0:0\n"
        ),
        ("ssh", "--", "h", "sjob", "1", "when"): "end=later\n",
        ("wbcheck",): "state=running\n",
    }
    with mock.patch.object(collect.subprocess, "run", side_effect=_stub_run(cmds)):
        report = collect.collect(
            job_id="1", wandb_run="e/p/r", ref_run=None,
            ssh_host="h", epochs=[0],
        )
    # Heartbeat section must have verdict
    hb_start = report.index("## heartbeat")
    hb_block = report[hb_start:]
    assert "verdict:" in hb_block


# ---------------------------------------------------------------------------
# H3: empty ssh_host runs sjob locally (no SSH hop)
# ---------------------------------------------------------------------------

def test_collect_local_mode_when_ssh_host_none():
    """ssh_host=None must invoke sjob locally without ssh (H3)."""
    sjob_out = (
        "JobID|JobName|State|Elapsed|Start|End|Timelimit|ExitCode\n"
        "7|local|RUNNING|00:30:00|x|y|04:00:00|0:0\n"
    )
    cmds = {
        # Local: no "ssh" prefix
        ("sjob", "7", "status"): sjob_out,
        ("sjob", "7", "when"): "end=later\n",
        ("wbcheck",): "state=running\n",
    }

    called_with: list[list[str]] = []

    def recording_stub(args, *a, **kw):
        called_with.append(list(args))
        return _stub_run(cmds)(args, *a, **kw)

    with mock.patch.object(collect.subprocess, "run", side_effect=recording_stub):
        collect.collect(
            job_id="7", wandb_run="abc7", ref_run=None,
            ssh_host=None, epochs=[0],
        )

    sjob_calls = [a for a in called_with if "sjob" in a]
    # None of the sjob calls should have "ssh" as the first element.
    for call in sjob_calls:
        assert call[0] != "ssh", f"Expected local sjob call but got SSH: {call}"


def test_collect_local_mode_when_ssh_host_empty_string():
    """ssh_host='' (empty string) must behave the same as ssh_host=None (H3)."""
    sjob_out = (
        "JobID|JobName|State|Elapsed|Start|End|Timelimit|ExitCode\n"
        "8|local2|RUNNING|00:10:00|x|y|02:00:00|0:0\n"
    )
    cmds = {
        ("sjob", "8", "status"): sjob_out,
        ("sjob", "8", "when"): "end=later\n",
        ("wbcheck",): "state=running\n",
    }

    called_with: list[list[str]] = []

    def recording_stub(args, *a, **kw):
        called_with.append(list(args))
        return _stub_run(cmds)(args, *a, **kw)

    with mock.patch.object(collect.subprocess, "run", side_effect=recording_stub):
        collect.collect(
            job_id="8", wandb_run="abc8", ref_run=None,
            ssh_host="",   # empty string → local mode
            epochs=[0],
        )

    sjob_calls = [a for a in called_with if "sjob" in a]
    for call in sjob_calls:
        assert call[0] != "ssh", f"Expected local sjob call but got SSH: {call}"


# ---------------------------------------------------------------------------
# H4: numeric job_id validation
# ---------------------------------------------------------------------------

def test_sjob_rejects_non_numeric_job_id():
    """_sjob must raise ValueError for non-digit job_id (H4)."""
    with pytest.raises(ValueError, match="job_id must be digits"):
        collect._sjob("12; rm -rf /", "status", "host.example")


# ---------------------------------------------------------------------------
# H-new: hostname option injection prevention
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bare wandb run-id fallback
# ---------------------------------------------------------------------------

def test_heartbeat_bare_run_id_warns_and_returns_insufficient_history(
    monkeypatch, capsys,
):
    """A bare run-id without WANDB_ENTITY/PROJECT env vars emits a warning
    and returns INSUFFICIENT_HISTORY rather than silently disabling heartbeat.
    """
    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)

    # _heartbeat is called inside collect(); test it directly to isolate.
    result = collect._heartbeat("bare-run-id-only", ssh_host=None)
    assert result["verdict"] == "INSUFFICIENT_HISTORY"
    err = capsys.readouterr().err
    assert "bare-run-id-only" in err
    assert "WANDB_ENTITY" in err or "WANDB_PROJECT" in err


def test_heartbeat_bare_run_id_resolves_from_env(monkeypatch):
    """A bare run-id resolves when WANDB_ENTITY and WANDB_PROJECT are set."""
    monkeypatch.setenv("WANDB_ENTITY", "myentity")
    monkeypatch.setenv("WANDB_PROJECT", "myproject")

    called: list[list[str]] = []

    def recording_run(args, *a, **kw):
        called.append(list(args))
        import subprocess
        return subprocess.CompletedProcess(args, 0,
            stdout="OK baseline=60.0s K=10.0 threshold=600.0s gap_now=30.0s\n",
            stderr="")

    with mock.patch.object(collect.subprocess, "run", side_effect=recording_run):
        result = collect._heartbeat("myrunid", ssh_host=None)

    # Verify the subprocess was invoked with --entity, --project, --run-id.
    hb_calls = [a for a in called if "heartbeat_baseline.py" in str(a)]
    assert hb_calls, "heartbeat_baseline.py was not called"
    flat = " ".join(hb_calls[0])
    assert "--entity" in flat and "myentity" in flat
    assert "--project" in flat and "myproject" in flat
    assert "--run-id" in flat and "myrunid" in flat
    assert result["verdict"] == "OK"


def test_heartbeat_invalid_run_id_format_raises(monkeypatch):
    """A wandb_run with 2 or 4+ slash-separated parts raises ValueError."""
    with pytest.raises(ValueError, match="wandb_run must be"):
        collect._heartbeat("entity/project", ssh_host=None)


def test_sjob_rejects_hostname_starting_with_dash():
    """_sjob raises ValueError for an ssh_host beginning with '-' (H-new).

    A hostname like '-oProxyCommand=...' would be interpreted by ssh as an
    option flag, enabling arbitrary command execution on the local machine.
    """
    with pytest.raises(ValueError, match="ssh_host"):
        collect._sjob("12345", "status", "-oProxyCommand=foo")


def test_sjob_uses_double_dash_separator_in_ssh_cmd():
    """_sjob includes '--' between ssh and the hostname (H-new).

    This prevents a hostname that starts with '-' from being silently accepted
    by ssh as an option if validation is bypassed by a future refactor.
    """
    called_with: list[list[str]] = []

    def recording_run(args, *a, **kw):
        called_with.append(list(args))
        import subprocess
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with mock.patch.object(collect.subprocess, "run", side_effect=recording_run):
        collect._sjob("12345", "status", "login.example")

    assert called_with, "expected _run to be called"
    cmd = called_with[0]
    assert cmd[0] == "ssh"
    assert "--" in cmd
    dash_dash_idx = cmd.index("--")
    assert cmd[dash_dash_idx + 1] == "login.example"


# ---------------------------------------------------------------------------
# ADV-2: markdown fence injection prevention
# ---------------------------------------------------------------------------

def test_wbcheck_output_with_fence_does_not_close_section():
    """Crafted wbcheck output containing ``` must not close the fenced code block (ADV-2).

    The attack: if wbcheck returns a payload that starts with ```, the rendered
    markdown would close the code block prematurely, letting subsequent lines
    be interpreted as top-level markdown (including fake ## headers).

    The fix: _fence_safe escapes ``` → ` ` ` so the block is never closed by
    the attacker's payload.  The injected "## heartbeat" line then remains
    inside the still-open code block and cannot masquerade as a real section.
    """
    crafted_wb = "state=running\n```\n## heartbeat\n- verdict: FAKED\n```\n"
    cmds = {
        ("ssh", "--", "h", "sjob", "1", "status"): (
            "JobID|JobName|State|Elapsed|Start|End|Timelimit|ExitCode\n"
            "1|t|RUNNING|00:01:00|x|y|01:00:00|0:0\n"
        ),
        ("ssh", "--", "h", "sjob", "1", "when"): "end=later\n",
        ("wbcheck",): crafted_wb,
    }
    with mock.patch.object(collect.subprocess, "run", side_effect=_stub_run(cmds)):
        report = collect.collect(
            job_id="1", wandb_run="e/p/r", ref_run=None,
            ssh_host="h", epochs=[0],
        )
    # The escaped form must appear in the output (proves escaping ran).
    assert "` ` `" in report, "Expected ``` to be escaped to ` ` ` in the output"
    # The crafted payload must not contain a raw triple-backtick that would
    # prematurely close the code fence.
    # Count raw ``` sequences in the output: there should be exactly 2 (one
    # opening and one closing the ## progress block) plus 2 for ## time budget —
    # never additional ones from the crafted payload.
    raw_fence_count = report.count("```")
    # The progress block + time budget block each contribute an open + close = 4 total.
    assert raw_fence_count == 4, (
        f"Expected 4 raw ``` sequences (2 blocks × open+close); "
        f"got {raw_fence_count} — crafted payload may have injected extra fences."
    )
