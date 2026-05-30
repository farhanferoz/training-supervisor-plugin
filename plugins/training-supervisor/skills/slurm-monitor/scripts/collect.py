"""Phase 2 evidence collector for slurm-monitor.

Calls ~/bin/sjob (over SSH if --ssh-host is given) for SLURM state, and
~/bin/wbcheck for W&B matched-epoch trajectories. Returns a structured
markdown bundle the supervisor's Phase 3 sub-agent reads as evidence.

This is invoked by the supervisor's dispatch (see supervisor-ralph/SKILL.md and
supervisor-team/SKILL.md) when slurm-monitor is in the active-skills set. Run
standalone for debugging:

    python collect.py --job-id 12345 --wandb-run abc12345 \\
        --ssh-host login.example --epochs 0,5,10,20
"""
from __future__ import annotations

import argparse
import os
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
    """Invoke ~/bin/sjob, optionally via ssh."""
    if ssh_host is None:
        cmd = ["sjob", job_id, sub]
    else:
        cmd = ["ssh", ssh_host, "sjob", job_id, sub]
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


def collect(
    *, job_id: str, wandb_run: str, ref_run: str | None,
    ssh_host: str, epochs: list[int],
) -> str:
    """Produce a markdown evidence bundle for one SLURM job + W&B run."""
    if not job_id:
        msg = "job_id is required"
        raise ValueError(msg)
    if not wandb_run:
        msg = "wandb_run is required"
        raise ValueError(msg)

    rc_status, status_out, _ = _sjob(job_id, "status", ssh_host)
    rc_when, when_out, _ = _sjob(job_id, "when", ssh_host)
    ssh_reachable = rc_status == 0
    rc_wb, wb_out, _ = _wbcheck(wandb_run, ref_run, epochs)

    lines: list[str] = []
    lines.append(f"# slurm-monitor evidence — job {job_id} / wandb {wandb_run}")
    lines.append("> contract: v1")
    lines.append("")
    if not ssh_reachable:
        lines.append("> **PARTIAL** — cluster unreachable; SLURM evidence missing.")
        lines.append("")
    lines.append("## SLURM state")
    lines.append("```")
    lines.append(status_out.strip() or "(no output — see Cluster reachability)")
    lines.append("```")
    lines.append("")
    lines.append("## Time budget")
    lines.append("```")
    lines.append(when_out.strip() or "(no output)")
    lines.append("```")
    lines.append("")
    lines.append("## W&B trajectories")
    lines.append("```")
    lines.append(wb_out.strip() or "(wbcheck unavailable)")
    lines.append("```")
    lines.append("")
    lines.append("## Cluster reachability")
    lines.append(f"- ssh status: {'OK' if ssh_reachable else 'FAIL (PARTIAL evidence)'}")
    lines.append(f"- wbcheck status: {'OK' if rc_wb == 0 else f'FAIL (rc={rc_wb})'}")
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
    p.add_argument("--ssh-host", required=True)
    p.add_argument("--epochs", default="0,5,10,20,30,40,60,80,100",
                   type=lambda s: [int(x) for x in s.split(",")])
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    print(collect(
        job_id=args.job_id, wandb_run=args.wandb_run, ref_run=args.ref_run,
        ssh_host=args.ssh_host, epochs=args.epochs,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
