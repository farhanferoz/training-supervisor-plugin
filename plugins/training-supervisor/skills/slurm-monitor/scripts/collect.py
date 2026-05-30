"""Phase 2 evidence collector for slurm-monitor.

Calls ~/bin/sjob (over SSH if --ssh-host is given) for SLURM state, and
~/bin/wbcheck for W&B matched-epoch trajectories. Returns a structured
markdown bundle the supervisor's Phase 3 sub-agent reads as evidence.

This is invoked by the supervisor's dispatch (see supervisor-ralph/SKILL.md and
supervisor-team/SKILL.md) when slurm-monitor is in the active-skills set. Run
standalone for debugging:

    python collect.py --job-id 12345 --wandb-run abc12345 \\
        --ssh-host login.example --epochs 0,5,10,20

Pass --ssh-host '' (empty string) or omit it to run sjob locally (no SSH).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Iterable


def _run(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a subprocess; return (rc, stdout, stderr). Empty stdout on failure."""
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def _sjob(job_id: str, sub: str, ssh_host: str | None) -> tuple[int, str, str]:
    """Invoke ~/bin/sjob, optionally via ssh.

    If ssh_host is None or empty string, runs sjob locally (no SSH hop).

    The ``--`` separator is passed to ssh to prevent a hostname that begins
    with ``-`` from being interpreted as an option flag (hostname-option
    injection, H-new).
    """
    if not job_id.isdigit():
        msg = f"job_id must be digits; got {job_id!r}"
        raise ValueError(msg)
    if ssh_host:
        if ssh_host.startswith("-"):
            msg = f"ssh_host must not start with '-' (got {ssh_host!r}); this would be interpreted as an ssh option"
            raise ValueError(msg)
        cmd = ["ssh", "--", ssh_host, "sjob", job_id, sub]
    else:
        cmd = ["sjob", job_id, sub]
    return _run(cmd)


def _wbcheck(
    wandb_run: str, ref_run: str | None, epochs: Iterable[int],
) -> tuple[int, str, str]:
    argv: list[str] = ["wbcheck", wandb_run]
    if ref_run:
        argv += ["--ref", ref_run]
    if epochs:
        argv += ["--epochs", ",".join(str(e) for e in epochs)]
    return _run(argv, timeout=60)


def _heartbeat(
    wandb_run: str, ssh_host: str | None, aggressiveness: str = "balanced",
) -> dict[str, str]:
    """Invoke heartbeat_baseline.py as a subprocess; parse its one-line stdout.

    Returns a dict with keys: verdict, baseline_s, threshold_s, gap_now_s.
    On subprocess failure, returns INSUFFICIENT_HISTORY defaults.
    """
    here = os.path.dirname(__file__)
    hb_script = os.path.join(
        here, "..", "..", "wandb-monitor", "scripts", "heartbeat_baseline.py"
    )
    # heartbeat_baseline.py requires --entity/--project/--run-id; we can
    # attempt to parse entity/project/run from a fully-qualified wandb_run id
    # (entity/project/run) or fall back to defaults if the format differs.
    parts = wandb_run.split("/")
    if len(parts) == 3:
        entity, project, run_id = parts
    else:
        # Cannot determine entity/project — return safe defaults.
        return {
            "verdict": "INSUFFICIENT_HISTORY",
            "baseline_s": "n/a",
            "threshold_s": "n/a",
            "gap_now_s": "n/a",
        }
    rc, out, _ = _run(
        [sys.executable, hb_script,
         "--run-id", run_id, "--entity", entity, "--project", project,
         "--aggressiveness", aggressiveness],
        timeout=60,
    )
    if rc not in (0, 1) or not out.strip():
        return {
            "verdict": "INSUFFICIENT_HISTORY",
            "baseline_s": "n/a",
            "threshold_s": "n/a",
            "gap_now_s": "n/a",
        }
    # Expected format: "OK baseline=30.0s K=10.0 threshold=300.0s gap_now=12.3s"
    line = out.strip().split("\n")[0]
    tokens = line.split()
    verdict = tokens[0] if tokens else "INSUFFICIENT_HISTORY"

    def _extract(key: str) -> str:
        for tok in tokens:
            if tok.startswith(key + "="):
                return tok.split("=", 1)[1].rstrip("s")
        return "n/a"

    return {
        "verdict": verdict,
        "baseline_s": _extract("baseline"),
        "threshold_s": _extract("threshold"),
        "gap_now_s": _extract("gap_now"),
    }


def _parse_run_state(wb_out: str) -> str:
    """Extract run state from wbcheck output (line containing state=<value>)."""
    m = re.search(r"\bstate=(\w+)", wb_out)
    if m:
        raw = m.group(1).lower()
        # Normalise to CONTRACT.md vocabulary.
        mapping = {
            "running": "running",
            "finished": "finished",
            "crashed": "crashed",
            "failed": "failed",
        }
        return mapping.get(raw, raw)
    return "unknown"


def _parse_elapsed(status_out: str) -> str:
    """Extract Elapsed field from sjob status output."""
    m = re.search(r"\bElapsed\b.*?\n(.+)", status_out)
    if m:
        fields = m.group(1).split("|")
        # sjob status header: JobID|JobName|State|Elapsed|Start|End|Timelimit|ExitCode
        if len(fields) >= 4:
            return fields[3].strip()
    # Fallback: look for HH:MM:SS pattern.
    m2 = re.search(r"\d{2}:\d{2}:\d{2}", status_out)
    if m2:
        return m2.group(0)
    return "unknown"


def _parse_timelimit(status_out: str) -> str:
    """Extract Timelimit field from sjob status output."""
    m = re.search(r"\bElapsed\b.*?\n(.+)", status_out)
    if m:
        fields = m.group(1).split("|")
        if len(fields) >= 7:
            return fields[6].strip()
    return "unknown"


def _parse_state(status_out: str) -> str:
    """Extract State field from sjob status output."""
    m = re.search(r"\bElapsed\b.*?\n(.+)", status_out)
    if m:
        fields = m.group(1).split("|")
        if len(fields) >= 3:
            return fields[2].strip()
    for word in ("RUNNING", "PENDING", "FAILED", "COMPLETED", "CANCELLED"):
        if word in status_out:
            return word
    return "UNKNOWN"


def collect(
    *, job_id: str, wandb_run: str, ref_run: str | None,
    ssh_host: str | None, epochs: list[int],
) -> str:
    """Produce a CONTRACT.md v1-compliant markdown evidence bundle.

    ssh_host=None (or empty string) means local mode — sjob is invoked
    without an SSH hop.
    """
    if not job_id:
        msg = "job_id is required"
        raise ValueError(msg)
    if not wandb_run:
        msg = "wandb_run is required"
        raise ValueError(msg)

    # Normalise empty string to None (local mode).
    ssh_host = ssh_host or None

    rc_status, status_out, _ = _sjob(job_id, "status", ssh_host)
    rc_when, when_out, _ = _sjob(job_id, "when", ssh_host)
    ssh_reachable = rc_status == 0
    rc_wb, wb_out, _ = _wbcheck(wandb_run, ref_run, epochs)

    state = _parse_state(status_out) if ssh_reachable else "UNKNOWN"
    elapsed = _parse_elapsed(status_out) if ssh_reachable else "unknown"
    timelimit = _parse_timelimit(status_out) if ssh_reachable else "unknown"

    hb = _heartbeat(wandb_run, ssh_host)
    run_state = _parse_run_state(wb_out) if rc_wb == 0 else "unknown"

    lines: list[str] = []
    lines.append(f"# collector evidence — {job_id} / {wandb_run}")
    lines.append("> contract: v1")
    lines.append("")
    if not ssh_reachable:
        lines.append("> **PARTIAL** — cluster unreachable; SLURM evidence missing.")
        lines.append("")

    lines.append("## job state")
    lines.append(f"- state: {state}")
    lines.append(f"- elapsed: {elapsed}")
    lines.append(f"- timelimit: {timelimit}")
    lines.append(f"- reachable: {'true' if ssh_reachable else 'false'}")
    lines.append("")

    lines.append("## progress")
    lines.append("- last_step: unknown")
    lines.append("- trajectory:")
    lines.append("```")
    lines.append(wb_out.strip() or "(wbcheck unavailable)")
    lines.append("```")
    lines.append("")

    lines.append("## heartbeat")
    lines.append(f"- verdict: {hb['verdict']}")
    lines.append(f"- baseline_s: {hb['baseline_s']}")
    lines.append(f"- threshold_s: {hb['threshold_s']}")
    lines.append(f"- gap_now_s: {hb['gap_now_s']}")
    lines.append("")

    lines.append("## run state")
    lines.append(f"- run: {run_state}")
    lines.append("")

    # Extra section: time budget (from sjob when).
    lines.append("## time budget")
    lines.append("```")
    lines.append(when_out.strip() or "(no output)")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # If JOB_MONITOR_COLLECTOR is set, exec it with the same argv and exit
    # with its return code. This is the generic-collector hook documented in
    # CONTRACT.md: any conforming CLI can replace the built-in path.
    custom = os.environ.get("JOB_MONITOR_COLLECTOR")
    if custom:
        rc = subprocess.run(
            [custom, *(argv if argv is not None else sys.argv[1:])],
            check=False,
        ).returncode
        return rc

    p = argparse.ArgumentParser(prog="slurm-monitor.collect")
    p.add_argument("--job-id", required=True)
    p.add_argument("--wandb-run", required=True)
    p.add_argument("--ref-run", default=None)
    p.add_argument("--ssh-host", default=None,
                   help="Cluster login host. Pass empty string or omit for local mode.")
    p.add_argument("--epochs", default="0,5,10,20,30,40,60,80,100",
                   type=lambda s: [int(x) for x in s.split(",")])
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    ssh_host = args.ssh_host or None
    print(collect(
        job_id=args.job_id, wandb_run=args.wandb_run, ref_run=args.ref_run,
        ssh_host=ssh_host, epochs=args.epochs,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
