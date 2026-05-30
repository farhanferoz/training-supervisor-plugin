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
        ("ssh", "host.example", "sjob", "12345", "status"): sjob_out,
        ("ssh", "host.example", "sjob", "12345", "when"):
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
    assert "## SLURM state" in report
    assert "RUNNING" in report
    assert "## W&B trajectories" in report
    assert "turing-core/autocast" in report
    assert "## Cluster reachability" in report


def test_collect_marks_partial_on_ssh_failure():
    cmds = {("wbcheck",): "stub wbcheck output\n"}  # ssh stub absent → fails
    with mock.patch.object(collect.subprocess, "run", side_effect=_stub_run(cmds)):
        report = collect.collect(
            job_id="12345", wandb_run="abc12345", ref_run=None,
            ssh_host="host.example", epochs=[0],
        )
    assert "PARTIAL" in report
    assert "Cluster reachability" in report


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
