# training-supervisor-plugin: SLURM/W&B Adoption Patches — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt the upstream `training-supervisor` plugin (t2ance/training-monitor-plugin) to support remote SLURM training jobs monitored via W&B, with adaptive heartbeat detection, local cron scheduling, and a default state path that does not pollute user repos.

**Architecture:** Six patches applied as separate commits on the fork's `master`, in dependency order. Three are heavyweight (slurm-monitor skill with generic collector contract; supervisor-team cron path; config-fix registry). Three are light (heartbeat formula; state-path default; permissions overlay template). Five are PR-candidates back to upstream; the cron-path patch stays fork-only because upstream's design assumes Claude Code's cloud-side `CronCreate`.

**Tech Stack:** Markdown SKILL.md files (prompt skills), Bash + Python helper scripts (new in this plan), JSON for permissions snippets, `~/bin/wbcheck` + `~/bin/sjob` as out-of-plugin user helpers the slurm-monitor wraps.

---

## Scope and Non-Goals

**In scope:** Five patches enumerated in Phase A–E below, plus the documentation, tests, and supervisor-doctor registry updates each requires.

**Out of scope (this plan):**
- Building a SLURM monitor *application* — we wrap existing `~/bin/sjob` and `~/bin/wbcheck`, not reimplement.
- Modifying upstream's qualitative-first philosophy (no fabricated thresholds in judgment phases; preserve threshold-free Phase 3 sub-agent).
- Live `scancel` or live `relaunch_with_fix` smoke tests on real SLURM jobs — plan documents the paths but does not exercise destructive operations.
- Brainstorming or design exploration — that's done. Decisions captured in this plan are the result of validation work in `~/.claude-job-monitor/smoke-tests/lx51s8bj_20260530_1409.txt` and the marketplace bug-fix already committed as `a1df8fd`.
- Building collectors for non-W&B metric trackers (TensorBoard, MLflow, custom JSON loggers). Phase B ships a *contract* and a default W&B implementation; user-supplied collectors that match the contract drop in.

---

## File Structure

Files in the fork that will be created (`+`) or modified (`~`) by this plan:

```
plugins/training-supervisor/
├── README.md                                                            ~  (E5)
├── .claude-plugin/plugin.json                                           ~  (B5; version bump)
├── agents/quality-reviewer.md                                              (unchanged)
├── skills/
│   ├── training-supervisor/
│   │   ├── SKILL.md                                                     ~  (A1; State Protocol section)
│   │   ├── phases/
│   │   │   ├── 0-contract.md                                               (unchanged)
│   │   │   ├── 1-predict.md                                                (unchanged)
│   │   │   ├── 2-collect.md                                             ~  (B6; document slurm-monitor as collector option)
│   │   │   ├── 3-analyze.md                                                (unchanged)
│   │   │   ├── 4-audit.md                                                  (unchanged)
│   │   │   ├── 5-act.md                                                 ~  (B7; document scancel-over-ssh as STOP path under authority gate)
│   │   │   └── 6-persist.md                                             ~  (A2; default state path -> ~/.claude-job-monitor/)
│   │   └── dispatch/
│   │       ├── ralph.md                                                 ~  (B8; spawn slurm-monitor collector when relevant)
│   │       └── team.md                                                  ~  (B8; same)
│   ├── slurm-monitor/                                                   +  (Phase B)
│   │   ├── SKILL.md                                                     +  (B1)
│   │   ├── CONTRACT.md                                                  +  (B1b; generic collector contract)
│   │   ├── scripts/
│   │   │   ├── collect.py                                               +  (B2; default collector; delegates if JOB_MONITOR_COLLECTOR set)
│   │   │   ├── scancel_safe.sh                                          +  (B3; STOP path)
│   │   │   ├── ssh_probe.sh                                             +  (B4; cluster reachability check)
│   │   │   └── test_collect.py                                          +  (B2-test)
│   │   ├── fixes/                                                       +  (Phase F)
│   │   │   ├── registry.yaml                                            +  (F1; default fix table)
│   │   │   └── README.md                                                +  (F1; how to override per-project)
│   │   └── scripts/relaunch_with_fix.sh                                 +  (F2; consults registry, writes next_action.sh)
│   │   └── scripts/test_relaunch_with_fix.py                            +  (F2-test)
│   ├── wandb-monitor/
│   │   ├── SKILL.md                                                     ~  (C1; adaptive heartbeat)
│   │   └── scripts/                                                     +  (C2)
│   │       ├── heartbeat_baseline.py                                    +  (C2)
│   │       └── test_heartbeat_baseline.py                               +  (C2-test)
│   ├── supervisor-doctor/SKILL.md                                       ~  (B5; register slurm-monitor + E2)
│   └── supervisor-team/
│       ├── SKILL.md                                                     ~  (D1; local-cron path alongside cloud)
│       └── scripts/                                                     +  (D2-D3)
│           ├── install_local_cron.sh                                    +  (D2)
│           ├── uninstall_local_cron.sh                                  +  (D2)
│           └── cron_dispatch.sh                                         +  (D3; the per-cycle entrypoint)
└── templates/
    └── permissions.snippet.json                                         +  (E1)

PATCH_PLAN.md                                                            ~  (this file)
```

Where applicable, scripts live under `<skill>/scripts/` mirroring the upstream `iterate-pr` skill convention (referenced in our research: bundled scripts adjacent to the skill that invokes them).

---

## Phase Ordering and Dependencies

```
A. State path (foundation)        — touched by every other patch
  ↓
B. slurm-monitor skill            — adds the collector contract + STOP path; references A
  ↓
C. Adaptive heartbeat             — improves wandb-monitor; independent of B
  ↓
D. Local cron                     — references A (state for reconciliation) and C (heartbeat already adapted)
  ↓
E. Permissions overlay            — references the file paths from B, C, D
  ↓
F. Config-fix registry            — extends B's STOP path with safe auto-fixes; references B's anti-loop infrastructure
```

A is first because state-path strings appear in multiple files; doing it first means later patches reference the new path naturally. B is next because it's the heaviest new code — best to land while context is fresh. C–E are smaller and can be parallelised by separate agents if desired. F lands last because it builds on B's `scancel_safe.sh` and the anti-loop fingerprint.

PR-candidate split (open after each phase is merged on the fork):
- A → upstream PR
- B → upstream PR (new skill + generic collector contract; may need design discussion)
- C → upstream PR (replaces fixed thresholds with adaptive)
- D → **fork-only** (upstream design assumes CronCreate)
- E → upstream PR (template; doctor doc bit)
- F → upstream PR (default registry is autocast-flavoured but mechanism is generic)

---

## Phase A: Default State Path → `~/.claude-job-monitor/`

**Why this patch:** Current default is `monitoring-logs/` relative to CWD, which lands inside whatever repo the user is in when the supervisor runs. State should live in a stable user-level directory.

**Files modified:**
- `plugins/training-supervisor/skills/training-supervisor/SKILL.md` — State Protocol section.
- `plugins/training-supervisor/skills/training-supervisor/phases/6-persist.md` — paths in tier-state table.
- Any other reference to `monitoring-logs/` across the plugin (grep before editing).

### Task A1: Update State Protocol in core SKILL.md

**Files:**
- Modify: `plugins/training-supervisor/skills/training-supervisor/SKILL.md` (State Protocol section, near top of doc — appears around line ~80 in upstream master).

- [x] **Step 1: Grep for the current path**

```bash
cd ~/dev/training-supervisor-plugin && \
  grep -rn 'monitoring-logs' plugins/ | tee /tmp/A1_before.txt
```

Expected: list of every occurrence. Save for verification.

- [x] **Step 2: Edit the State Protocol table in SKILL.md**

Replace the existing State Protocol block (the table with `Read previous state | monitoring-logs/jobs/<job-id>.json` etc.) with:

```markdown
## State Protocol

All cross-session information is stored in files, not in context.

| Operation | Path |
|-----------|------|
| Read previous state | `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/<job-id>.json` |
| Write current state | `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/<job-id>.json` |
| Session logs | `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/` |
| Global pitfalls | `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/pitfalls.md` |

The state directory defaults to `~/.claude-job-monitor/` so monitoring state does
not land inside whatever repository the supervisor is running against. Override
by exporting `TRAINING_SUPERVISOR_STATE_DIR` before invoking the skill, or by
adding a `state_dir:` key to the project profile written by `supervisor-doctor`.

Create the directory tree on first write (`mkdir -p`); do not assume it exists.

Job ID = training config path + model path (stable across restarts). PIDs are NOT stable identifiers.
```

- [x] **Step 3: Verify the edit**

```bash
grep -n 'TRAINING_SUPERVISOR_STATE_DIR\|monitoring-logs' \
  plugins/training-supervisor/skills/training-supervisor/SKILL.md
```

Expected: the env-var form appears in the 4 table rows; no surviving `monitoring-logs/` references inside the State Protocol section.

### Task A2: Update phases/6-persist.md

**Files:**
- Modify: `plugins/training-supervisor/skills/training-supervisor/phases/6-persist.md`

- [x] **Step 1: Replace `monitoring-logs/jobs/...` with the env-var form**

Replace the inline `monitoring-logs/jobs/<job-id>.json` and `monitoring-logs/<timestamp>/6-summary.md` references with `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/<job-id>.json` and `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/6-summary.md` respectively.

Also replace `monitoring-logs/pitfalls.md` with the env-var form.

- [x] **Step 2: Verify**

```bash
grep -n 'monitoring-logs\|TRAINING_SUPERVISOR_STATE_DIR' \
  plugins/training-supervisor/skills/training-supervisor/phases/6-persist.md
```

Expected: zero `monitoring-logs/` occurrences; three or four `TRAINING_SUPERVISOR_STATE_DIR` occurrences.

### Task A3: Sweep remaining references

**Files:**
- Modify: any other file under `plugins/training-supervisor/` that mentions `monitoring-logs/`.

- [x] **Step 1: Find remaining references**

```bash
grep -rln 'monitoring-logs' plugins/ | tee /tmp/A3_remaining.txt
```

Expected: each remaining file is small enough to patch with one or two edits. Likely candidates: `dispatch/team.md`, `dispatch/ralph.md`, possibly `supervisor-team/SKILL.md`.

- [x] **Step 2: Replace each with the env-var form**

Edit each file from `/tmp/A3_remaining.txt`. Pattern: `monitoring-logs/<path>` → `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<path>` for session-scoped logs, or `${...}/jobs/...` etc. matching the table above.

- [x] **Step 3: Verify zero remaining references**

```bash
grep -rln 'monitoring-logs' plugins/
```

Expected: empty.

### Task A4: Commit Phase A

- [x] **Step 1: Diff review**

```bash
cd ~/dev/training-supervisor-plugin && git diff plugins/
```

Expected: only state-path-related substitutions; no unrelated whitespace or rewording.

- [x] **Step 2: Commit**

```bash
git add plugins/
git commit -m "State path: default to \$HOME/.claude-job-monitor/, env-overridable

Replace the hardcoded relative path 'monitoring-logs/' (which would land state
inside whatever repo the supervisor is run against) with
\${TRAINING_SUPERVISOR_STATE_DIR:-\$HOME/.claude-job-monitor}/. Users can
override via TRAINING_SUPERVISOR_STATE_DIR; default puts state in a stable
user-level location that survives across projects.

Touches the State Protocol table in the core SKILL.md, phases/6-persist.md
gate-log path references, and any dispatch/* or domain-skill text that named
the old path. Skill behaviour is unchanged otherwise.

PR candidate for upstream."
```

**Acceptance criteria for Phase A:**
- `grep -rln 'monitoring-logs' plugins/` returns empty.
- A single commit on master with subject starting `State path:`.
- Diff is purely the path substitution — no other prose change.

---

## Phase B: New `slurm-monitor` Domain Skill

**Why this patch:** Phase 2 collectors (GPU/Process/Log) assume local training. For remote SLURM, those collectors have nothing to gather; instead the supervisor needs to call `~/bin/sjob` over SSH for SLURM status and `~/bin/wbcheck` for W&B trajectories. The Phase 5 STOP path needs `scancel` over SSH gated by the authority level.

This patch is a **peer of `k8s-monitor`** — applies when the user's training is SLURM-scheduled. The `supervisor-doctor` registry needs an entry to surface it conditionally.

**Files created:**
- `plugins/training-supervisor/skills/slurm-monitor/SKILL.md`
- `plugins/training-supervisor/skills/slurm-monitor/scripts/collect.py`
- `plugins/training-supervisor/skills/slurm-monitor/scripts/scancel_safe.sh`
- `plugins/training-supervisor/skills/slurm-monitor/scripts/ssh_probe.sh`
- `plugins/training-supervisor/skills/slurm-monitor/scripts/test_collect.py`

**Files modified:**
- `plugins/training-supervisor/.claude-plugin/plugin.json` (bump version 0.2.0 → 0.3.0)
- `plugins/training-supervisor/skills/supervisor-doctor/SKILL.md` (registry + context-signal table entry)
- `plugins/training-supervisor/skills/training-supervisor/phases/2-collect.md` (mention slurm-monitor)
- `plugins/training-supervisor/skills/training-supervisor/phases/5-act.md` (mention scancel-over-ssh as STOP)
- `plugins/training-supervisor/skills/training-supervisor/dispatch/ralph.md`
- `plugins/training-supervisor/skills/training-supervisor/dispatch/team.md`

### Task B1: Write `slurm-monitor` SKILL.md

**Files:**
- Create: `plugins/training-supervisor/skills/slurm-monitor/SKILL.md`

- [x] **Step 1: Create the skill directory**

```bash
mkdir -p ~/dev/training-supervisor-plugin/plugins/training-supervisor/skills/slurm-monitor/scripts
```

- [x] **Step 2: Write SKILL.md**

Content (full file):

````markdown
---
name: slurm-monitor
description: Heuristics for monitoring training jobs running on a SLURM cluster, including remote-cluster cases reached over SSH. Replaces the default Phase 2 GPU/Process/Log collectors with SLURM-aware ones (sjob via SSH for status, wbcheck for W&B trajectories), and exposes scancel as a Phase 5 STOP mechanism gated by authority level. Peer of k8s-monitor.
---

# SLURM Training Monitor

Heuristics for monitoring training jobs scheduled by SLURM, including the common
case where the cluster is reached over SSH from a user's local machine. This
skill is the SLURM peer of `k8s-monitor`: it replaces the default Phase 2
local-process collectors (which assume nvidia-smi + local PID + tail-able log
file) with collectors that probe the remote cluster, and it provides a
`scancel` path for Phase 5 STOP actions.

Use these heuristics to inform your reasoning about SLURM evidence, not as
rigid rules.

**Dependencies (checked by `supervisor-doctor`):**
- `ssh` configured with cert/key access to the cluster login host.
- `~/bin/sjob` helper (or equivalent `sacct`/`squeue`/`scontrol` access).
- `~/bin/wbcheck` helper (or direct `wandb.Api()` access if the user prefers).
- The `wandb-monitor` skill installed alongside (this skill does not duplicate
  W&B heuristics; it pulls them via `wandb-monitor`).

## When this skill applies

Activate `slurm-monitor` (alongside `wandb-monitor`) when any of these hold:

| Signal | Implication |
|--------|-------------|
| `squeue -u $USER` returns rows on the cluster host | SLURM is the scheduler |
| Training command goes through `sbatch` or `salloc` | SLURM job |
| User mentions a cluster login host, Isambard, ALCF, Perlmutter, etc. | Likely SLURM |
| Repo has `slurm_scripts/` or `*.sbatch` files | SLURM-scheduled training |

If detection is ambiguous, ask the user via `supervisor-doctor` whether their
training is SLURM-scheduled — do not assume.

## Evidence Collection (Phase 2 replacement)

Instead of the default GPU/Process/Log collectors, dispatch a `slurm-monitor`
collector that runs:

```bash
"${CLAUDE_SKILL_ROOT}/scripts/collect.py" \
  --job-id "<slurm_job_id>" \
  --wandb-run "<wandb_run_id>" \
  --ref-run "<reference_run_id_or_empty>" \
  --ssh-host "${SLURM_SSH_HOST:-$(awk '/^Host /{print $2; exit}' ~/.ssh/config_clifton 2>/dev/null)}" \
  --epochs 0,5,10,20,30,40,60,80,100
```

`collect.py` returns a structured markdown bundle with:
- **SLURM state**: from `sjob <id> status` (RUNNING / PENDING / FAILED / COMPLETED).
- **Time budget**: elapsed vs. timelimit; projected finish at current rate.
- **W&B trajectories**: matched-epoch table from `wbcheck`, grouped by family
  (loss / accuracy / calibration / health). See `wandb-monitor` for what each
  family means.
- **Heartbeat**: latest W&B beat vs. baseline (see `wandb-monitor` for the
  adaptive-multiplier formula).
- **Cluster reachability**: pass/fail from `ssh_probe.sh`. If FAIL, mark the
  whole evidence bundle as PARTIAL — the supervisor must not infer health from
  a stale snapshot.

The default Phase 2 GPU/Process/Log collectors should be SKIPPED when this
skill applies — they have nothing to gather locally for a remote SLURM job.
The dispatch files (`ralph.md`, `team.md`) check the active domain skills and
spawn this collector instead.

## STOP Action (Phase 5 replacement)

When Phase 3 returns STOP and the authority level permits a destructive action,
the supervisor calls:

```bash
"${CLAUDE_SKILL_ROOT}/scripts/scancel_safe.sh" \
  --job-id "<slurm_job_id>" \
  --ssh-host "<host>" \
  --reason "<one-line stop reason from Phase 5 gate log>" \
  --authority "<paranoid|conservative|balanced|aggressive>"
```

`scancel_safe.sh`:
- Refuses to act when `authority=paranoid` (returns an error; STOP must come
  from the user).
- Refuses to act when `authority=conservative` AND the stop reason category is
  `stagnant` (only `loss_nan`, `nccl_hang`, `crashed` qualify under
  conservative).
- Calls `ssh <host> scancel <job_id>` for `balanced` / `aggressive` under any
  reason from the upstream Phase 5 ontology.
- Always records the action + reason + authority + exit status into the gate
  log at `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<ts>/5-act.md`.

## Authority Mapping (cross-ref with supervisor-doctor)

| Authority | Auto-cancel hard failures (NaN / NCCL hang / crashed) | Auto-cancel stagnant | Auto-relaunch transient | Anti-loop cap (per fingerprint) |
|---|---|---|---|---|
| paranoid | NO | NO | NO | 0 |
| conservative | YES | NO (propose) | NO (propose) | 1 |
| balanced | YES | propose | YES | 2 |
| aggressive | YES | YES | YES (from fix registry) | 3 |

Stagnation detection uses the relative-to-reference signal from `wandb-monitor`
(matched-epoch accuracy metric worse than reference by margin δ over N epochs);
the precise thresholds are deferred to the per-experiment policy block in the
config — `slurm-monitor` does not bake numbers in.

## Anti-Loop Protocol

Before relaunching after a STOP, the supervisor:

1. Computes a failure fingerprint:
   `sha256(experiment_name + resolved_config_hash + failure_class)`.
2. Reads `${STATE_DIR}/jobs/<job-id>.json` → `strategy.relaunch_attempts[fingerprint]`.
3. If `attempts >= anti_loop_cap[authority]`, REFUSES to relaunch; raises a
   "two failed retries with the same config + failure mode" notice and stops.
4. Otherwise increments the counter, records the new launch, persists.

Persistence write is the supervisor's responsibility (Phase 6), not this
skill's. The skill returns the fingerprint and a recommended next-step
descriptor; the orchestrator decides whether to honour it.
````

- [x] **Step 3: Verify the file**

```bash
test -f plugins/training-supervisor/skills/slurm-monitor/SKILL.md && \
  head -3 plugins/training-supervisor/skills/slurm-monitor/SKILL.md
```

Expected: file exists, frontmatter has `name: slurm-monitor` and `description:` line.

### Task B1b: Write the generic collector contract

**Files:**
- Create: `plugins/training-supervisor/skills/slurm-monitor/CONTRACT.md`

**Why:** The skill ships `collect.py` as the default collector (wraps wbcheck + sjob + heartbeat_baseline.py), but users on other metric trackers (TensorBoard, MLflow, custom JSON loggers) need a way to plug their own. CONTRACT.md defines the interface so any conforming CLI can be dropped in via the `JOB_MONITOR_COLLECTOR` env var.

- [x] **Step 1: Write CONTRACT.md**

Content:

````markdown
# Progress-Check Collector Contract

A **collector** is a CLI program that takes job-identity arguments and emits
a structured markdown bundle describing the job's current state, progress,
and heartbeat. The slurm-monitor skill ships `scripts/collect.py` as the
default (wraps `~/bin/wbcheck` + `~/bin/sjob` + `heartbeat_baseline.py`),
but any program matching this contract can replace it.

**Use case:** Drop in a TensorBoard scraper, MLflow client, or custom JSON
log reader without modifying the skill.

## How to plug in a custom collector

Set the `JOB_MONITOR_COLLECTOR` environment variable to the absolute path of
your script (in `~/.claude/settings.json` env block, your shell rc, or
supervisor-doctor's profile yaml):

```bash
export JOB_MONITOR_COLLECTOR=/home/me/bin/my-collector.sh
```

The skill's dispatch then invokes `$JOB_MONITOR_COLLECTOR` with the standard
args (below). If unset, the default `collect.py` is used.

## Input arguments (all required unless noted)

```
--job-id <STR>             Scheduler-specific job identifier (e.g. SLURM jobid).
--run-id <STR>             Metric-tracker run identifier (e.g. W&B run id).
--ref-run <STR|empty>      Reference run for matched-epoch comparison; "" if none.
--ssh-host <STR|empty>     Cluster login host for remote scheduler queries; "" if local.
--epochs <CSV>             Comma-separated epoch ladder (e.g. 0,5,10,20,40).
--aggressiveness <PROFILE> One of paranoid|conservative|balanced|aggressive.
                           Used by the collector's heartbeat-verdict subcall.
--since <ISO|empty>        Wall-clock cutoff for incremental signal; "" if first cycle.
```

## Required output sections (markdown to stdout)

Every collector MUST emit these four top-level sections in this order. Extra
sections are allowed at the end. All field values are markdown — code blocks
welcome for tabular content. The header MUST include a contract-version
marker so the supervisor can detect collectors written against an older
contract after a future bump.

```markdown
# collector evidence — <job_id> / <run_id>
> contract: v1

> If reachability failed (cluster unreachable, run not found, etc.), prefix
> the body with: `> **PARTIAL** — <one-line reason>`

## job state
- state: RUNNING|PENDING|FAILED|COMPLETED|UNKNOWN
- elapsed: <duration string, e.g. "13h47m">
- timelimit: <duration string or "unknown">
- reachable: true|false

## progress
- last_step: <int or "unknown">
- trajectory:
```
<matched-epoch markdown table, columns = epochs, rows = run-and-metric,
 grouped by family with subheaders [loss], [accuracy], [calibration],
 [health], [other]. wbcheck's output format is the reference shape.>
```

## heartbeat
- verdict: OK|STALE|WARMUP|INSUFFICIENT_HISTORY
- baseline_s: <float>
- threshold_s: <float>
- gap_now_s: <float>

## run state
- run: running|finished|crashed|failed
```

## Exit codes

- `0` — collector ran successfully (regardless of job health).
- non-zero — collector itself errored (e.g., dependencies missing, network
  failure for the collector's own infrastructure). The orchestrator treats
  this as a Phase 2 partial failure and proceeds with a degraded bundle.

## Validation

Run `scripts/validate_collector.sh <your-collector>` to check your CLI emits
all required sections. (Future ticket — for now, eyeball against the example
output of the default `collect.py`.)
````

- [x] **Step 2: Verify**

```bash
test -f plugins/training-supervisor/skills/slurm-monitor/CONTRACT.md && \
  grep -c '^## ' plugins/training-supervisor/skills/slurm-monitor/CONTRACT.md
```

Expected: file exists; at least 5 second-level headings.

### Task B2: Write `collect.py` (TDD)

**Files:**
- Create: `plugins/training-supervisor/skills/slurm-monitor/scripts/collect.py`
- Test: `plugins/training-supervisor/skills/slurm-monitor/scripts/test_collect.py`

This script is the Phase 2 collector entrypoint. It's TDD-friendly because the
output format is well-specified (structured markdown). Mock subprocess calls
to `sjob` and `wbcheck`.

- [x] **Step 1: Write the failing test**

Content of `test_collect.py`:

```python
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
            if args[:len(prefix)] == prefix:
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
```

- [x] **Step 2: Run the test to verify it fails**

```bash
cd ~/dev/training-supervisor-plugin && \
  python -m pytest plugins/training-supervisor/skills/slurm-monitor/scripts/test_collect.py -v
```

Expected: ImportError or ModuleNotFoundError for `collect` — file does not exist yet.

- [x] **Step 3: Write minimal `collect.py` to pass**

Content of `collect.py`:

```python
"""Phase 2 evidence collector for slurm-monitor.

Calls ~/bin/sjob (over SSH if --ssh-host is given) for SLURM state, and
~/bin/wbcheck for W&B matched-epoch trajectories. Returns a structured
markdown bundle the supervisor's Phase 3 sub-agent reads as evidence.

This is invoked by the supervisor's dispatch (see dispatch/ralph.md and
team.md) when slurm-monitor is in the active-skills set. Run standalone for
debugging:

    python collect.py --job-id 12345 --wandb-run abc12345 \\
        --ssh-host login.example --epochs 0,5,10,20
"""
from __future__ import annotations

import argparse
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
    cmd = ["sjob", job_id, sub] if ssh_host is None else \
          ["ssh", ssh_host, "sjob", job_id, sub]
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
    import os
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
```

- [x] **Step 4: Run the test to verify it passes**

```bash
python -m pytest plugins/training-supervisor/skills/slurm-monitor/scripts/test_collect.py -v
```

Expected: 3 passed.

- [x] **Step 5: Smoke against a live run (read-only)**

```bash
python plugins/training-supervisor/skills/slurm-monitor/scripts/collect.py \
  --job-id 4896750 --wandb-run lx51s8bj --ref-run 68qcze3w \
  --ssh-host u6eo.aip2.isambard --epochs 0,5,10,20,30
```

Expected: markdown report with `## SLURM state` showing RUNNING (or whatever the live state is), `## W&B trajectories` showing matched-epoch table from wbcheck, `## Cluster reachability` both OK.

### Task B3: Write `scancel_safe.sh`

**Files:**
- Create: `plugins/training-supervisor/skills/slurm-monitor/scripts/scancel_safe.sh`

This is the only destructive path in this skill. It's gated by authority level.
**Do not smoke-test against live jobs in this plan.**

- [x] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# scancel_safe.sh — Phase 5 STOP path for slurm-monitor.
#
# Gated by authority level. Records every action to the gate log. Refuses to
# act under paranoid; restricts under conservative. Used by the supervisor's
# Phase 5 only when Phase 3 has returned STOP.
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --job-id N --ssh-host HOST --reason "TEXT" --authority LEVEL [--reason-class CLASS]

Required:
  --job-id N         SLURM job id to cancel.
  --ssh-host HOST    Cluster login host.
  --reason "TEXT"    One-line stop reason for the audit log.
  --authority LEVEL  paranoid | conservative | balanced | aggressive

Optional:
  --reason-class C   One of: loss_nan, nccl_hang, crashed, stagnant, other.
                     Required when LEVEL=conservative. Defaults to "other".
  --state-dir DIR    Defaults to \$TRAINING_SUPERVISOR_STATE_DIR or ~/.claude-job-monitor.
  --dry-run          Print the command that would run; do not execute.
EOF
}

JOB_ID="" SSH_HOST="" REASON="" AUTHORITY="" REASON_CLASS="other"
STATE_DIR="${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}"
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --job-id) JOB_ID="$2"; shift 2 ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        --reason) REASON="$2"; shift 2 ;;
        --authority) AUTHORITY="$2"; shift 2 ;;
        --reason-class) REASON_CLASS="$2"; shift 2 ;;
        --state-dir) STATE_DIR="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
    esac
done

for v in JOB_ID SSH_HOST REASON AUTHORITY; do
    [[ -n "${!v}" ]] || { echo "missing --${v,,}" >&2; exit 2; }
done

case "$AUTHORITY" in
    paranoid)
        echo "scancel_safe: REFUSED (authority=paranoid) job=$JOB_ID reason=$REASON" >&2
        exit 3 ;;
    conservative)
        case "$REASON_CLASS" in
            loss_nan|nccl_hang|crashed) ;;
            *)
                echo "scancel_safe: REFUSED (authority=conservative, reason_class=$REASON_CLASS not in allowed set) job=$JOB_ID" >&2
                exit 3 ;;
        esac ;;
    balanced|aggressive) ;;
    *) echo "scancel_safe: unknown authority '$AUTHORITY'" >&2; exit 2 ;;
esac

ts="$(date -u +%Y%m%dT%H%M%SZ)"
log_dir="$STATE_DIR/sessions/$ts"
mkdir -p "$log_dir"
log_path="$log_dir/5-act.md"

cmd=(ssh "$SSH_HOST" scancel "$JOB_ID")
if [[ "$DRY_RUN" -eq 1 ]]; then
    rc=0
    out="(dry-run — would have executed: ${cmd[*]})"
else
    out="$("${cmd[@]}" 2>&1 || true)"
    rc=$?
fi

cat >>"$log_path" <<EOF
## scancel_safe.sh — $(date -u +%Y-%m-%dT%H:%M:%SZ)

- job_id: $JOB_ID
- ssh_host: $SSH_HOST
- reason_class: $REASON_CLASS
- authority: $AUTHORITY
- reason: $REASON
- command: ${cmd[*]}
- exit_status: $rc
- stdout/stderr:
\`\`\`
$out
\`\`\`
EOF

echo "scancel_safe: logged to $log_path (rc=$rc)"
exit "$rc"
```

- [x] **Step 2: Make it executable + verify shellcheck-clean**

```bash
chmod +x plugins/training-supervisor/skills/slurm-monitor/scripts/scancel_safe.sh
which shellcheck >/dev/null 2>&1 && \
  shellcheck plugins/training-supervisor/skills/slurm-monitor/scripts/scancel_safe.sh
```

Expected: no shellcheck warnings, or shellcheck not installed (skip).

- [x] **Step 3: Verify gating with --dry-run + state-dir override**

```bash
TMPDIR="$(mktemp -d)" && \
  plugins/training-supervisor/skills/slurm-monitor/scripts/scancel_safe.sh \
    --job-id 999 --ssh-host nonexistent.example --reason "smoke" \
    --authority paranoid --state-dir "$TMPDIR" --dry-run
echo "rc=$? (expect 3)"
```

Expected: rc=3, message "REFUSED (authority=paranoid)".

- [x] **Step 4: Verify gating for conservative + non-allowed reason**

```bash
TMPDIR="$(mktemp -d)" && \
  plugins/training-supervisor/skills/slurm-monitor/scripts/scancel_safe.sh \
    --job-id 999 --ssh-host nonexistent.example --reason "smoke" \
    --authority conservative --reason-class stagnant --state-dir "$TMPDIR" --dry-run
echo "rc=$? (expect 3)"
```

Expected: rc=3, message "REFUSED (authority=conservative ...)".

- [x] **Step 5: Verify dry-run succeeds under balanced + crashed**

```bash
TMPDIR="$(mktemp -d)" && \
  plugins/training-supervisor/skills/slurm-monitor/scripts/scancel_safe.sh \
    --job-id 999 --ssh-host nonexistent.example --reason "smoke" \
    --authority balanced --reason-class crashed --state-dir "$TMPDIR" --dry-run && \
  cat "$TMPDIR"/sessions/*/5-act.md
```

Expected: rc=0, gate log written with `dry-run` marker. **Do not run without --dry-run against a real job in this plan.**

### Task B4: Write `ssh_probe.sh`

**Files:**
- Create: `plugins/training-supervisor/skills/slurm-monitor/scripts/ssh_probe.sh`

- [x] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# ssh_probe.sh — quick reachability check for the cluster login host.
# Used by the doctor + collect.py to surface "cert expired" / "host down" early.
set -euo pipefail
host="${1:?usage: ssh_probe.sh <host>}"
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    "$host" 'true' 2>&1
```

- [x] **Step 2: chmod + smoke**

```bash
chmod +x plugins/training-supervisor/skills/slurm-monitor/scripts/ssh_probe.sh
plugins/training-supervisor/skills/slurm-monitor/scripts/ssh_probe.sh u6eo.aip2.isambard
echo "rc=$?"
```

Expected: rc=0 if cert healthy; rc≠0 with the SSH failure message if cert expired. Use the failure path as the docs example.

### Task B5: Register the skill in supervisor-doctor + bump plugin version

**Files:**
- Modify: `plugins/training-supervisor/skills/supervisor-doctor/SKILL.md`
- Modify: `plugins/training-supervisor/.claude-plugin/plugin.json`

- [x] **Step 1: Add slurm-monitor row to the Dependency Registry table**

In `supervisor-doctor/SKILL.md`, find the `## Dependency Registry` table and add a row immediately above the `wandb-monitor` row:

```markdown
| `slurm-monitor` | SLURM job state + remote-cluster STOP path | `ssh` to the cluster login host; `~/bin/sjob` and `~/bin/wbcheck` (or equivalents) | (user-installed) |
```

- [x] **Step 2: Add a Context Signals row**

In the `### Context Signals to Check` table, add:

```markdown
| sbatch / salloc / squeue in shell history, slurm_scripts/ in repo, sacct on PATH | SLURM-scheduled training → need `slurm-monitor` | `command -v sbatch sacct squeue >/dev/null 2>&1`, `ls slurm_scripts/ *.sbatch 2>/dev/null` |
```

- [x] **Step 3: Bump plugin.json version**

In `plugins/training-supervisor/.claude-plugin/plugin.json`, change `"version": "0.2.0"` to `"version": "0.3.0"`.

- [x] **Step 4: Verify the doctor registry block is consistent**

```bash
grep -n 'slurm-monitor\|wandb-monitor\|k8s-monitor' \
  plugins/training-supervisor/skills/supervisor-doctor/SKILL.md | head -20
```

Expected: slurm-monitor appears in both the Dependency Registry table and the Context Signals table.

### Task B6: Update phases/2-collect.md

**Files:**
- Modify: `plugins/training-supervisor/skills/training-supervisor/phases/2-collect.md`

- [x] **Step 1: Add a "When slurm-monitor is active" subsection**

Append after the existing collector formats:

```markdown
## When `slurm-monitor` is active (remote SLURM training)

If the active domain-skill set includes `slurm-monitor`, the default GPU /
Process / Log collectors have nothing to collect (training is remote, no local
PID, no local nvidia-smi). Replace them with one `slurm-monitor` collector:

```
Agent(prompt: "Collect SLURM + W&B evidence. Run
  ${CLAUDE_SKILL_ROOT}/scripts/collect.py with the job_id, wandb_run, ref_run,
  and ssh_host from the per-job state. Return the script's stdout verbatim.")
```

`wandb-monitor` heuristics still apply for interpreting the W&B trajectory
bundle the script emits. `k8s-monitor` is mutually exclusive with
`slurm-monitor`; doctor will not enable both.
```

- [x] **Step 2: Verify**

```bash
grep -n 'slurm-monitor' plugins/training-supervisor/skills/training-supervisor/phases/2-collect.md
```

Expected: at least one occurrence inside the new section.

### Task B7: Update phases/5-act.md

**Files:**
- Modify: `plugins/training-supervisor/skills/training-supervisor/phases/5-act.md`

- [x] **Step 1: Add a "STOP execution when slurm-monitor is active" note**

In the `### If STOP (autonomous)` section, append:

```markdown
**When `slurm-monitor` is active**, "Kill: stop the training process" means
calling `${CLAUDE_SKILL_ROOT}/scripts/scancel_safe.sh` with the configured
authority level. That script refuses to act under `paranoid` and restricts
the allowed `reason_class` set under `conservative`. The authority level
comes from the per-job state's `policy.authority` field; if absent, default
to `conservative`. The script logs every invocation (including refused ones)
into the Phase 5 gate log.
```

- [x] **Step 2: Verify**

```bash
grep -n 'scancel_safe\|slurm-monitor' plugins/training-supervisor/skills/training-supervisor/phases/5-act.md
```

Expected: the new paragraph is present.

### Task B8: Update dispatch/ralph.md and dispatch/team.md

**Files:**
- Modify: `plugins/training-supervisor/skills/training-supervisor/dispatch/ralph.md`
- Modify: `plugins/training-supervisor/skills/training-supervisor/dispatch/team.md`

- [x] **Step 1: Add a slurm-monitor branch in each dispatch's Phase 2 section**

In each file's `## Phase 2: Collect` block, add immediately after the existing
collector list:

```markdown
**If `slurm-monitor` is in the active domain-skill set**: SKIP the default
GPU / Process / Log collectors and spawn one slurm-monitor collector instead
(see `phases/2-collect.md` → "When `slurm-monitor` is active"). The
`Resource Collector` may still run if a local checkpoint mirror is configured.
```

- [x] **Step 2: Verify**

```bash
grep -n 'slurm-monitor' \
  plugins/training-supervisor/skills/training-supervisor/dispatch/ralph.md \
  plugins/training-supervisor/skills/training-supervisor/dispatch/team.md
```

Expected: at least one occurrence per file.

### Task B9: Commit Phase B

- [x] **Step 1: Diff review**

```bash
cd ~/dev/training-supervisor-plugin && \
  git status && git diff --stat
```

Expected: 1 new directory (`skills/slurm-monitor/`) with 5 files; modifications to
plugin.json + supervisor-doctor + phases/2-collect + phases/5-act + dispatch/{ralph,team}.

- [x] **Step 2: Commit**

```bash
git add plugins/
git commit -m "Add slurm-monitor domain skill (peer of k8s-monitor)

For training jobs scheduled by SLURM and reached over SSH, the default Phase
2 collectors (nvidia-smi, local PID, local log tail) have nothing to gather.
slurm-monitor replaces them with sjob status + wbcheck W&B trajectories,
both pulled from the user's own ~/bin/ helpers. The skill ships scripts/:

- collect.py    — Phase 2 evidence collector (unit-tested)
- scancel_safe.sh — Phase 5 STOP path, gated by authority level
- ssh_probe.sh  — quick reachability check for the cluster login host

scancel_safe.sh refuses to act under authority=paranoid, restricts the
reason_class under conservative (only loss_nan / nccl_hang / crashed
qualify), and always writes an audit entry into the Phase 5 gate log.

Touches:
- supervisor-doctor SKILL.md: new entries in Dependency Registry + Context
  Signals tables so the wizard surfaces slurm-monitor when SLURM is detected.
- phases/2-collect.md, phases/5-act.md: how to spawn the collector and how
  STOP maps to scancel_safe.
- dispatch/{ralph,team}.md: skip default GPU/Process/Log collectors when
  slurm-monitor is active.
- plugin.json: version bump 0.2.0 -> 0.3.0.

PR candidate for upstream."
```

**Acceptance criteria for Phase B:**
- `python -m pytest plugins/training-supervisor/skills/slurm-monitor/scripts/test_collect.py -v` passes (3/3).
- `collect.py` runs end-to-end against the live `lx51s8bj` / job 4896750 and emits a non-PARTIAL bundle.
- `scancel_safe.sh --dry-run` returns rc=3 under paranoid, rc=3 under conservative+stagnant, rc=0 under balanced+crashed.
- `supervisor-doctor` registry + context-signal tables list slurm-monitor (verifiable by `grep slurm-monitor plugins/training-supervisor/skills/supervisor-doctor/SKILL.md` returning at least two hits — one per table). Running the wizard end-to-end is a Task-V2 concern, not a Phase B gate.
- Commit subject starts `Add slurm-monitor`.

---

## Phase C: Adaptive Heartbeat (wandb-monitor)

**Why this patch:** Upstream `wandb-monitor` uses fixed thresholds (`> 10 min stale = warning`, `> 30 min = critical`). Real-world heartbeat intervals span 15 s (fast LLM step) to 5 min (long RL rollout), so fixed thresholds fire too late on fast jobs and too early on slow ones. Adaptive formula: `K × median_inter_beat_interval` over the last N=50 history rows, with a 30 s floor and 5 min warm-up grace.

**Files modified:**
- `plugins/training-supervisor/skills/wandb-monitor/SKILL.md` — Health Thresholds + Heartbeat-Based Stall Detection sections.

**Files created:**
- `plugins/training-supervisor/skills/wandb-monitor/scripts/heartbeat_baseline.py`
- `plugins/training-supervisor/skills/wandb-monitor/scripts/test_heartbeat_baseline.py`

### Task C1: Edit wandb-monitor SKILL.md

**Files:**
- Modify: `plugins/training-supervisor/skills/wandb-monitor/SKILL.md`

- [x] **Step 1: Replace the Health Thresholds table**

Find the `## Health Thresholds` section and replace its table with:

```markdown
| Condition | Severity | Meaning |
|-----------|----------|---------|
| Gradients > 10 | Critical | Exploding gradients |
| Gradients > 5 | Warning | Spiky gradients |
| Gradients < 0.0001 | Warning | Vanishing gradients |
| Heartbeat stale > K × baseline (see below) | Critical | Job likely stalled or crashed |
| Run state = `crashed` | Critical | Job crashed, check logs |
| Run state = `failed` | Critical | Job failed, check exit code |

The two old fixed-time heartbeat rows (`> 10 min` warning, `> 30 min` critical)
are replaced by the adaptive formula in the next section.
```

- [x] **Step 2: Replace (or extend) the Heartbeat-Based Stall Detection section**

Find `## Heartbeat-Based Stall Detection` (or its end-of-file location) and replace its body with:

````markdown
## Heartbeat-Based Stall Detection

Real-world inter-beat intervals vary by job type — a fast LLM step pushes
metrics every ~15 s, an RL rollout might be quiet for ~5 min between syncs.
Fixed wallclock thresholds either fire too late on fast jobs or too early on
slow ones. Use an **adaptive multiplier against the run's own observed
baseline**.

### Formula

```
baseline = median inter-beat interval over the last N=50 history rows
          (with a 30 s floor; if the run has fewer than ~5 rows, use 30 s)
gap_now  = now - heartbeat_at
warmup   = 5 min — skip the check entirely during a run's first 5 min,
           since W&B sync warm-up is genuinely slow on some clusters
verdict  = STALE iff (run age > warmup) AND (gap_now > K * baseline)
```

The script `scripts/heartbeat_baseline.py` computes this. Call it with:

```bash
"${CLAUDE_SKILL_ROOT}/scripts/heartbeat_baseline.py" \
  --run-id "<wandb_run_id>" --entity "<entity>" --project "<project>" \
  --aggressiveness "<paranoid|conservative|balanced|aggressive>"
```

It prints one of `OK`, `STALE`, `WARMUP`, or `INSUFFICIENT_HISTORY` and exits
with rc=0 (OK/WARMUP/INSUFFICIENT_HISTORY) or rc=1 (STALE).

### Multiplier table

| Aggressiveness | K | Effective trigger on a baseline-60s run |
|---|---|---|
| `paranoid` | ∞ (never auto-cancel; verdict will always say OK as long as `gap_now < ∞`) | n/a |
| `conservative` | 20 | 20 min |
| `balanced` | 10 | 10 min |
| `aggressive` | 5 | 5 min |

(For a baseline-15s run, those become 5 / 2.5 / 1.25 min respectively; for a
baseline-300s run, they become 100 / 50 / 25 min.)

### Quiet-by-design exception

Some training phases (eval pass, checkpoint save, dataloader epoch boundary)
are quiet by design. When `phases/1-predict.md`'s prediction template includes
`expected_phase ∈ {eval, checkpoint, ...}` AND the predicted phase duration is
not yet exceeded, the heartbeat check is **suspended** for the remainder of
the predicted phase — verdict returns `EXPECTED_QUIET` and the supervisor
does not treat it as STALE.

### Recommended Phase 2 wiring

Have the wandb-monitor collector call `heartbeat_baseline.py` for every
running W&B run in scope. Treat its verdict as one signal among many in the
Phase 3 evidence bundle; never let it alone trigger STOP.
````

- [x] **Step 3: Verify the edit**

```bash
grep -n 'K × baseline\|adaptive\|heartbeat_baseline' \
  plugins/training-supervisor/skills/wandb-monitor/SKILL.md
```

Expected: multiple references — table, formula, script invocation.

### Task C2: Write heartbeat_baseline.py + tests (TDD)

**Files:**
- Create: `plugins/training-supervisor/skills/wandb-monitor/scripts/heartbeat_baseline.py`
- Test: `plugins/training-supervisor/skills/wandb-monitor/scripts/test_heartbeat_baseline.py`

- [x] **Step 1: Make scripts dir**

```bash
mkdir -p ~/dev/training-supervisor-plugin/plugins/training-supervisor/skills/wandb-monitor/scripts
```

- [x] **Step 2: Write failing test**

Content of `test_heartbeat_baseline.py`:

```python
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
```

- [x] **Step 3: Run failing test**

```bash
python -m pytest plugins/training-supervisor/skills/wandb-monitor/scripts/test_heartbeat_baseline.py -v
```

Expected: ImportError for `heartbeat_baseline`.

- [x] **Step 4: Write minimal `heartbeat_baseline.py`**

```python
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
    verdict: str            # OK | STALE | WARMUP | INSUFFICIENT_HISTORY
    baseline_s: float
    multiplier: float
    threshold_s: float
    gap_now_s: float


def classify(
    history_intervals_s: Iterable[float],
    run_age_s: float,
    gap_now_s: float,
    aggressiveness: str,
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
    """
    if aggressiveness not in MULTIPLIERS:
        msg = f"unknown aggressiveness '{aggressiveness}'"
        raise ValueError(msg)
    k = MULTIPLIERS[aggressiveness]

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
    import time
    import wandb
    api = wandb.Api()
    run = api.run(f"{entity}/{project}/{run_id}")
    history = run.scan_history(keys=["_timestamp"], page_size=200)
    timestamps = [float(row["_timestamp"]) for row in history
                  if row.get("_timestamp") is not None]
    if len(timestamps) < 2:
        intervals: list[float] = []
    else:
        timestamps.sort()
        intervals = [b - a for a, b in zip(timestamps[-51:-1], timestamps[-50:])]
    hb_at = float(run.heartbeat_at.timestamp()) if run.heartbeat_at else 0.0
    now = time.time()
    run_age = now - timestamps[0] if timestamps else 0.0
    gap_now = now - hb_at if hb_at else float("inf")
    return classify(intervals, run_age, gap_now, aggressiveness)


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
    return 0 if v.verdict in ("OK", "WARMUP", "INSUFFICIENT_HISTORY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 5: Run tests, verify pass**

```bash
python -m pytest plugins/training-supervisor/skills/wandb-monitor/scripts/test_heartbeat_baseline.py -v
```

Expected: 7 passed.

- [x] **Step 6: Smoke against the live K=64 run**

```bash
python plugins/training-supervisor/skills/wandb-monitor/scripts/heartbeat_baseline.py \
  --run-id lx51s8bj --entity turing-core --project autocast \
  --aggressiveness balanced
```

Expected: prints `OK baseline=...s K=10.0 threshold=...s gap_now=...s` (the run is healthy and actively beating).

### Task C3: Commit Phase C

- [x] **Step 1: Diff review + commit**

```bash
cd ~/dev/training-supervisor-plugin && git diff --stat
git add plugins/training-supervisor/skills/wandb-monitor/
git commit -m "wandb-monitor: adaptive heartbeat (K x baseline)

Replace the fixed wall-clock heartbeat thresholds (>10 min warning,
>30 min critical) with an adaptive formula using the run's own observed
inter-beat baseline. Fixed thresholds fire too late on fast jobs (15s/beat
LLM training) and too early on slow ones (5min/beat RL rollouts). Adaptive
multiplier covers both:

  baseline = median inter-beat interval over last N=50 rows (>= 30s floor)
  STALE iff (run_age > 5min warmup) AND (gap_now > K * baseline)

K maps to the aggressiveness profile:
  paranoid     ∞   (never STALE)
  conservative 20  (~20min on a 60s-baseline run)
  balanced     10  (~10min on a 60s-baseline run)
  aggressive    5  (~5min on a 60s-baseline run)

Quiet-by-design phases (eval, checkpoint) are exempted via the predict-phase
prediction — covered in SKILL.md prose.

Ships scripts/heartbeat_baseline.py with a pure classify() function + CLI
wrapper that calls wandb.Api(). Seven unit tests cover the verdict matrix
including paranoid-never-stale, warmup grace, and baseline floor.

PR candidate for upstream."
```

**Acceptance criteria for Phase C:**
- 7/7 tests pass.
- Live `heartbeat_baseline.py` invocation against `lx51s8bj` returns OK on `balanced`.
- The Health Thresholds + Heartbeat-Based Stall Detection sections in SKILL.md no longer reference `10 min` / `30 min` as fixed thresholds.

---

## Phase D: Local-cron path for supervisor-team

**Why this patch:** Upstream `supervisor-team` uses Claude Code's `CronCreate` (cloud-side scheduled remote agents). A cloud agent cannot SSH into Isambard (cert lives on the user's laptop). So we add a local-cron path: a `crontab` or `systemd-user` timer that invokes `claude --print` with a baked prompt.

Plus reconciliation: laptops sleep, missed cycles need to be skipped not retroactively fired.

**Files modified:**
- `plugins/training-supervisor/skills/supervisor-team/SKILL.md`

**Files created:**
- `plugins/training-supervisor/skills/supervisor-team/scripts/install_local_cron.sh`
- `plugins/training-supervisor/skills/supervisor-team/scripts/uninstall_local_cron.sh`
- `plugins/training-supervisor/skills/supervisor-team/scripts/cron_dispatch.sh`

### Task D1: Edit supervisor-team SKILL.md to add a local-cron path

**Files:**
- Modify: `plugins/training-supervisor/skills/supervisor-team/SKILL.md`

- [x] **Step 1: Find the existing "Set up cron" step**

```bash
grep -n 'Set up cron\|CronCreate' \
  plugins/training-supervisor/skills/supervisor-team/SKILL.md
```

- [x] **Step 2: Insert a Q-A pair to choose scheduler before Step 3**

In `### Step 1: Collect user preferences`, append a sixth question:

```markdown
6. **Scheduler**: How should the periodic loop be driven?
   - **Cloud (CronCreate)** — Claude Code's hosted scheduled remote agents
     (default upstream path). Best when the monitoring environment has no
     filesystem-local state to reach (e.g., everything goes through the W&B
     API and no SSH is needed).
   - **Local cron / systemd-user timer** — A real cron entry on the user's
     machine invoking `claude --print` with a baked prompt. Required when
     the monitoring loop needs filesystem-local credentials the cloud agent
     does not have (SSH certs, kubectl context, VPN-only services). The
     loop is skipped while the laptop is asleep — missed cycles are not
     retroactively fired.
```

- [x] **Step 3: Replace Step 3 ("Set up cron") with a branch**

Replace the existing `### Step 3: Set up cron` content with:

```markdown
### Step 3: Set up the scheduler

Branch on the user's Q6 answer.

#### 3a. If Q6 = Cloud (CronCreate)

Use **CronCreate** to schedule a recurring job at the user's requested
frequency (Q3). Pick an off-round minute (`:23`, `:47`) to avoid API
contention. The cron prompt body is the teammate-instruction template from
Step 2, embedded verbatim. (See the original upstream procedure.)

#### 3b. If Q6 = Local cron / systemd-user timer

Run the helper:

```bash
"${CLAUDE_SKILL_ROOT}/scripts/install_local_cron.sh" \
  --frequency "<Q3 value, e.g. 30m, 1h>" \
  --prompt-file "${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/cron_prompt.txt"
```

The helper:
1. Writes the Step-2 teammate-instruction template to `cron_prompt.txt`.
2. Installs a `crontab -e` entry (or `systemd --user` timer if available) that
   runs `cron_dispatch.sh` at the requested interval.
3. Verifies the entry was installed (`crontab -l` / `systemctl --user list-timers`).

`cron_dispatch.sh`:
- Invokes `CCAGE_DISABLE=1 claude --print < cron_prompt.txt`.
- Captures stdout to `${STATE_DIR}/sessions/<ts>/cron_output.log`.
- Sends a `SendMessage`-style shutdown signal not applicable in local mode —
  the `claude --print` subprocess exits after one pass, so no lifecycle
  management is needed.
- Skips its execution silently if the laptop just woke up
  (`uptime | awk '{ print $3 }'` < 60 s) — missed cycles are not retroactively
  fired.

To remove the loop:

```bash
"${CLAUDE_SKILL_ROOT}/scripts/uninstall_local_cron.sh"
```
```

- [x] **Step 4: Verify**

```bash
grep -n 'install_local_cron\|Q6\|systemd' \
  plugins/training-supervisor/skills/supervisor-team/SKILL.md
```

Expected: the new section's references are present; the upstream `CronCreate`
path remains for users on Q6=Cloud.

### Task D2: Write install_local_cron.sh + uninstall_local_cron.sh

**Files:**
- Create: `plugins/training-supervisor/skills/supervisor-team/scripts/install_local_cron.sh`
- Create: `plugins/training-supervisor/skills/supervisor-team/scripts/uninstall_local_cron.sh`

- [x] **Step 1: install_local_cron.sh**

```bash
#!/usr/bin/env bash
# install_local_cron.sh — install a local cron entry (or systemd-user timer)
# that runs the supervisor-team dispatch every <frequency>.
set -euo pipefail

FREQUENCY=""
PROMPT_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --frequency) FREQUENCY="$2"; shift 2 ;;
        --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
        -h|--help) sed -n '2,5p' "$0" >&2; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
[[ -n "$FREQUENCY" && -n "$PROMPT_FILE" ]] || { sed -n '2,5p' "$0" >&2; exit 2; }
[[ -f "$PROMPT_FILE" ]] || { echo "prompt file not found: $PROMPT_FILE" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
DISPATCH="$HERE/cron_dispatch.sh"
chmod +x "$DISPATCH"

# Translate user-friendly frequency to cron syntax.
case "$FREQUENCY" in
    *m) mins="${FREQUENCY%m}";        spec="*/$mins * * * *" ;;
    *h) hours="${FREQUENCY%h}";       spec="0 */$hours * * *" ;;
    *)  echo "unsupported frequency '$FREQUENCY' (use Nm or Nh)" >&2; exit 2 ;;
esac

LINE="$spec $DISPATCH $PROMPT_FILE  # training-supervisor-team"

# Prefer systemd --user timer if available; fall back to crontab.
if command -v systemctl >/dev/null 2>&1 && systemctl --user --version >/dev/null 2>&1; then
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    cat >"$UNIT_DIR/training-supervisor-team.service" <<EOF
[Unit]
Description=training-supervisor-team one-shot dispatch
After=network-online.target
[Service]
Type=oneshot
ExecStart=$DISPATCH $PROMPT_FILE
EOF
    cat >"$UNIT_DIR/training-supervisor-team.timer" <<EOF
[Unit]
Description=training-supervisor-team periodic dispatch
[Timer]
OnBootSec=2min
OnUnitActiveSec=$FREQUENCY
Persistent=false
[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now training-supervisor-team.timer
    echo "Installed systemd-user timer: training-supervisor-team.timer ($FREQUENCY)"
    systemctl --user list-timers training-supervisor-team.timer || true
    exit 0
fi

# Crontab fallback.
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
crontab -l 2>/dev/null | grep -v 'training-supervisor-team' > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab "$TMP"
echo "Installed crontab entry: $LINE"
crontab -l | grep training-supervisor-team
```

- [x] **Step 2: uninstall_local_cron.sh**

```bash
#!/usr/bin/env bash
# uninstall_local_cron.sh — remove the local cron/timer entries.
set -euo pipefail

if command -v systemctl >/dev/null 2>&1 && \
   systemctl --user list-timers training-supervisor-team.timer >/dev/null 2>&1; then
    systemctl --user disable --now training-supervisor-team.timer 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/training-supervisor-team.service"
    rm -f "$HOME/.config/systemd/user/training-supervisor-team.timer"
    systemctl --user daemon-reload
    echo "Removed systemd-user timer."
fi

TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
if crontab -l 2>/dev/null | grep -q 'training-supervisor-team'; then
    crontab -l | grep -v 'training-supervisor-team' > "$TMP"
    crontab "$TMP"
    echo "Removed crontab entry."
fi
echo "Done."
```

- [x] **Step 3: chmod + smoke (dry path)**

```bash
chmod +x plugins/training-supervisor/skills/supervisor-team/scripts/{install,uninstall}_local_cron.sh
# Dry verify the help path:
plugins/training-supervisor/skills/supervisor-team/scripts/install_local_cron.sh --help; \
  echo "rc=$?"
```

Expected: rc=0, prints usage lines.

**Do NOT run the install for real in this plan task.** Real install is a
user action — the user decides when to enable the loop.

### Task D3: Write cron_dispatch.sh

**Files:**
- Create: `plugins/training-supervisor/skills/supervisor-team/scripts/cron_dispatch.sh`

- [x] **Step 1: Write**

```bash
#!/usr/bin/env bash
# cron_dispatch.sh — one-shot dispatch entrypoint for the local-cron path.
# Invoked by cron or by the systemd-user timer; runs `claude --print` with
# the supervisor-team teammate prompt and logs output to the state dir.
set -euo pipefail

PROMPT_FILE="${1:?usage: cron_dispatch.sh <prompt_file>}"
STATE_DIR="${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}"

# Skip if the system just woke up (uptime < 60 s) — missed cycles are not
# retroactively fired. /proc/uptime is Linux-only; on other OSes (macOS etc.)
# the wake-skip is disabled (uptime check returns 999999 → never skipped).
if [[ -r /proc/uptime ]]; then
    uptime_s="$(awk '{ print int($1) }' /proc/uptime)"
else
    uptime_s=999999
fi
if [[ "$uptime_s" -lt 60 ]]; then
    echo "cron_dispatch: uptime ${uptime_s}s < 60s; skipping post-wake cycle"
    exit 0
fi

ts="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="$STATE_DIR/sessions/$ts"
mkdir -p "$out_dir"

# CCAGE_DISABLE bypasses the ccage per-project wrapper; the cron entrypoint
# always wants the default global config dir.
rc=0
CCAGE_DISABLE=1 claude --print --output-format=text < "$PROMPT_FILE" \
    >"$out_dir/cron_output.log" 2>&1 || rc=$?
echo "cron_dispatch: log -> $out_dir/cron_output.log (rc=${rc})"
exit "${rc}"
```

- [x] **Step 2: chmod + dry-run smoke**

```bash
chmod +x plugins/training-supervisor/skills/supervisor-team/scripts/cron_dispatch.sh

# Smoke: feed it a trivial prompt file, with state dir overridden to a tmp.
TMP="$(mktemp -d)"
echo "List all skills with 'supervisor' in their name. Just names, one per line." > "$TMP/prompt.txt"
TRAINING_SUPERVISOR_STATE_DIR="$TMP" \
  plugins/training-supervisor/skills/supervisor-team/scripts/cron_dispatch.sh "$TMP/prompt.txt"
cat "$TMP"/sessions/*/cron_output.log
```

Expected: cron_output.log contains the supervisor skill names; exit 0.

### Task D4: Commit Phase D

- [x] **Step 1: Diff review + commit**

```bash
cd ~/dev/training-supervisor-plugin && git diff --stat
git add plugins/training-supervisor/skills/supervisor-team/
git commit -m "supervisor-team: add local cron / systemd-user timer path

Upstream supervisor-team uses CronCreate (Claude Code's cloud-side scheduled
remote agents). A cloud agent cannot reach local-machine resources like SSH
certs, kubectl contexts, or VPN-only services. For those cases, we ship a
local-cron path that installs a crontab entry (or systemd-user timer when
available) running 'claude --print' on a baked teammate prompt.

scripts/:
- install_local_cron.sh   — install crontab/timer at user-chosen frequency
- uninstall_local_cron.sh — remove it
- cron_dispatch.sh        — one-shot entrypoint; skips its execution if
                            system uptime < 60s (don't retroactively fire
                            missed cycles after a laptop wake).

supervisor-team SKILL.md gains a Q6 (Scheduler: cloud / local) and a
Step-3 branch. Cloud path is unchanged — local is opt-in.

Fork-only (upstream design assumes CronCreate)."
```

**Acceptance criteria for Phase D:**
- `install_local_cron.sh --help` returns rc=0 with usage.
- `cron_dispatch.sh` smoke with a trivial prompt file writes a log and exits 0.
- supervisor-team SKILL.md has both 3a (Cloud) and 3b (Local) branches.

---

## Phase E: Permissions Overlay

**Why this patch:** The smoke test (F4–F8 in `~/.claude-job-monitor/smoke-tests/lx51s8bj_20260530_1409.txt`) confirmed that `claude --print` runs in a tight sandbox that blocks `~/bin/wbcheck`, `~/bin/sjob`, state-dir reads, and gate-log writes by default. For the cron loop to run unattended, those permissions must be pre-granted via `settings.json`. We ship a ready-to-paste template plus a doctor-report addendum.

**Files modified:**
- `plugins/training-supervisor/skills/supervisor-doctor/SKILL.md`
- `plugins/training-supervisor/README.md`

**Files created:**
- `plugins/training-supervisor/templates/permissions.snippet.json`

### Task E1: Write the permissions snippet

**Files:**
- Create: `plugins/training-supervisor/templates/permissions.snippet.json`

- [x] **Step 1: Create the file**

```bash
mkdir -p ~/dev/training-supervisor-plugin/plugins/training-supervisor/templates
```

Content of `permissions.snippet.json`:

```json
{
  "_comment": "Merge these blocks into your ~/.claude/settings.json (or .claude/settings.json) to let the training-supervisor cron loop run unattended. Replace <SSH_HOST> with your cluster login host (e.g. u6eo.aip2.isambard). Replace ~/bin paths if your helpers live elsewhere.",
  "permissions": {
    "allow": [
      "Bash(~/bin/wbcheck:*)",
      "Bash(~/bin/sjob:*)",
      "Bash(ssh <SSH_HOST>:*)",
      "Read(~/.claude-job-monitor/**)",
      "Write(~/.claude-job-monitor/**)",
      "Read(${CLAUDE_SKILL_ROOT}/**)",
      "Bash(${CLAUDE_SKILL_ROOT}/scripts/*.py:*)",
      "Bash(${CLAUDE_SKILL_ROOT}/scripts/*.sh:*)"
    ]
  }
}
```

- [x] **Step 2: Verify valid JSON**

```bash
python -c "import json; json.load(open('plugins/training-supervisor/templates/permissions.snippet.json'))"
echo "rc=$?"
```

Expected: rc=0, no output (JSON parses).

### Task E2: Add doctor-report addendum

**Files:**
- Modify: `plugins/training-supervisor/skills/supervisor-doctor/SKILL.md`

- [x] **Step 1: Append a step after `### 5. Choose Monitoring Mode`**

Insert a new section `### 6. Permissions Overlay (for unattended loops)`:

```markdown
### 6. Permissions Overlay (for unattended loops)

If the user selected Q6=Local from supervisor-team, point them at the
permissions template so the cron loop's `claude --print` invocation isn't
blocked by per-call approval prompts:

```
${CLAUDE_SKILL_ROOT}/templates/permissions.snippet.json
```

The template's `permissions.allow` entries should be merged into the user's
`~/.claude/settings.json`. Replace `<SSH_HOST>` with the cluster login host
from supervisor-doctor's environment detection.

Recommend running the `fewer-permission-prompts` skill once the loop has been
running for a session, to catch any additional read-only operations the
supervisor calls that the snippet didn't anticipate.

If the user kept Q6=Cloud (CronCreate), the cloud agent inherits Claude Code
defaults and does not need this overlay.
```

**First grep the current step count** before renumbering — do not assume:

```bash
grep -n '^### ' plugins/training-supervisor/skills/supervisor-doctor/SKILL.md
```

If the upstream still has Steps 1–6 with Step 6 being "Save Profile", insert
the new "Permissions Overlay" as Step 6 and renumber the old Step 6 → Step 7.
If upstream has reorganised, place the new section logically and renumber
accordingly. The point is the *content* (a permissions-overlay reminder
after monitoring-mode choice), not the ordinal.

- [x] **Step 2: Verify**

```bash
grep -n 'Permissions Overlay\|permissions.snippet' \
  plugins/training-supervisor/skills/supervisor-doctor/SKILL.md
```

Expected: the new section + reference to the snippet template are present.

### Task E3: Update README.md

**Files:**
- Modify: `plugins/training-supervisor/README.md`

- [x] **Step 1: Add a Skills row for slurm-monitor and bump version reference**

In the existing `## Skills` table, add a row:

```markdown
| `slurm-monitor` | SLURM job state + remote STOP path; peer of `k8s-monitor`. Use when training is `sbatch`-scheduled. | Yes |
```

In `## External Dependencies`, add a row:

```markdown
| SLURM monitoring | `ssh` to the cluster login host; `~/bin/sjob`, `~/bin/wbcheck` user helpers | (user-installed) |
```

- [x] **Step 2: Add a "Unattended loops" section near `## Usage`**

```markdown
## Unattended loops (permissions overlay)

Running `supervisor-team` with Q6=Local invokes `claude --print` in a sandbox
that blocks helpers outside the working directory by default. Merge the
permissions snippet into your settings.json once to make the loop quiet:

```bash
# Inspect the template:
cat ${CLAUDE_SKILL_ROOT}/templates/permissions.snippet.json

# Recommended: paste its permissions.allow entries (after substituting your
# cluster SSH host) into ~/.claude/settings.json under "permissions.allow".
# Then run /fewer-permission-prompts after one loop cycle to catch any
# read-only operations the template missed.
```
```

- [x] **Step 3: Verify**

```bash
grep -n 'slurm-monitor\|permissions.snippet\|unattended' \
  plugins/training-supervisor/README.md
```

Expected: each appears at least once.

### Task E4: Commit Phase E

- [x] **Step 1: Diff review + commit**

```bash
cd ~/dev/training-supervisor-plugin && git diff --stat
git add plugins/training-supervisor/templates plugins/training-supervisor/README.md \
        plugins/training-supervisor/skills/supervisor-doctor/SKILL.md
git commit -m "Add permissions.snippet.json template + doctor report addendum

For the local-cron path (supervisor-team Q6=Local), 'claude --print' runs
in a sandbox that blocks ~/bin helpers, state-dir reads, and gate-log writes
by default. Without pre-granted permissions, every cycle hits per-call
approval prompts — incompatible with an unattended loop.

Ship a templates/permissions.snippet.json with the minimum allow-list
needed (Bash on ~/bin/wbcheck, ~/bin/sjob, ssh <host>; Read+Write on
~/.claude-job-monitor; Read on \$CLAUDE_SKILL_ROOT). Substitute <SSH_HOST>
before merging into ~/.claude/settings.json.

supervisor-doctor SKILL.md grows a Step 6 (Permissions Overlay) that points
users at the template when they chose local cron in supervisor-team.

README.md documents the new slurm-monitor row in the Skills table and a
short Unattended loops section.

PR candidate (template is generic; doctor doc bit is generic too)."
```

**Acceptance criteria for Phase E:**
- `permissions.snippet.json` parses as JSON.
- Doctor SKILL.md references the template via `${CLAUDE_SKILL_ROOT}/templates/permissions.snippet.json`.
- README.md lists slurm-monitor in the Skills table.

---

## Phase F: Config-Fix Registry + relaunch_with_fix.sh

**Why this patch:** With Phases A–E in place, the supervisor can stop a broken
job autonomously (under `balanced`/`aggressive` authority + the safe failure
classes). But common config-fixable bugs — OOM at the chosen batch size,
transient NCCL hang, isolated node crash — still need the user to manually
relaunch with the right override. Phase F ships a small registry of safe,
well-known fixes and a script that proposes (or autonomously runs) the
relaunch.

The registry is **data**, not code. Default contents target the autocast
stack (Hydra + Lightning), but the file path is overridable so any project
can supply its own fixes. The actual relaunch command template lives in the
supervisor-doctor profile so non-autocast users can use this without
modifying the script.

**Files created:**
- `plugins/training-supervisor/skills/slurm-monitor/fixes/registry.yaml`
- `plugins/training-supervisor/skills/slurm-monitor/fixes/README.md`
- `plugins/training-supervisor/skills/slurm-monitor/scripts/relaunch_with_fix.sh`
- `plugins/training-supervisor/skills/slurm-monitor/scripts/test_relaunch_with_fix.py`

**Files modified:**
- `plugins/training-supervisor/skills/slurm-monitor/SKILL.md` — add a "Known-Fixes Registry" section + update the Anti-Loop Protocol fingerprint.
- `plugins/training-supervisor/skills/training-supervisor/phases/5-act.md` — chain `relaunch_with_fix.sh` after a successful `scancel_safe.sh` under `aggressive`; surface via AskUserQuestion under `balanced`.

### Task F1: Write `fixes/registry.yaml` + `fixes/README.md`

**Files:**
- Create: `plugins/training-supervisor/skills/slurm-monitor/fixes/registry.yaml`
- Create: `plugins/training-supervisor/skills/slurm-monitor/fixes/README.md`

- [x] **Step 1: Make the dir + write registry.yaml**

```bash
mkdir -p ~/dev/training-supervisor-plugin/plugins/training-supervisor/skills/slurm-monitor/fixes
```

Content of `registry.yaml`:

```yaml
# version: 1
# Default known-fixes registry. Project-specific Hydra paths are autocast-
# flavoured (datamodule.batch_size, +trainer.accumulate_grad_batches,
# optimizer.min_lr_ratio). Users on other stacks copy this file, edit the
# hydra_overrides templates, and point at it via JOB_MONITOR_FIX_REGISTRY.

fixes:
  oom:
    - id: oom_halve_batch
      description: "Halve datamodule.batch_size and double accumulate_grad_batches to preserve effective batch."
      risk: safe
      requires:
        - "batch_size >= 2"
      hydra_overrides:
        - "datamodule.batch_size={{ batch_size // 2 }}"
        - "+trainer.accumulate_grad_batches={{ accumulate * 2 if accumulate else 2 }}"

  nccl_timeout:
    - id: nccl_resubmit
      description: "Resubmit with same config. Most NCCL timeouts are transient (node flake or upstream comms blip)."
      risk: safe
      hydra_overrides: []

  crashed:
    - id: crashed_resubmit
      description: "Resubmit with same config. SLURM-FAIL after fit (#381 class) is typically transient."
      risk: safe
      hydra_overrides: []

  loss_nan:
    - id: loss_nan_escalate
      description: "Loss diverged. Cannot be auto-fixed reliably — could be bad init, LR, data, mixed precision overflow. Escalate to user."
      risk: escalate
      hydra_overrides: []

  stagnant:
    - id: stagnant_raise_lr_floor
      description: "Loss flat through the last N epochs; raise the cosine LR floor so the schedule doesn't anneal to 0 mid-descent."
      risk: proposed
      requires:
        - "current_min_lr_ratio < 0.1"
      hydra_overrides:
        - "optimizer.min_lr_ratio=0.1"
```

- [x] **Step 2: Write `fixes/README.md`**

Content:

````markdown
# Known-Fixes Registry

Data file describing safe, well-known fixes the supervisor can apply when a
job fails with a specific `failure_class`. Driven by `relaunch_with_fix.sh`.

## Schema

```yaml
version: 1
fixes:
  <failure_class>:
    - id: <unique_fix_id>            # used in the anti-loop fingerprint
      description: <one-line text>   # shown to the user if proposed
      risk: safe | proposed | escalate
      requires: [<jinja-style condition>, ...]   # optional; ALL must hold to apply
      hydra_overrides:                            # passed verbatim to relaunch
        - "<hydra_override_with_{{ template }}>"
        - ...
```

## Risk levels

- **safe** — apply autonomously under `aggressive` authority. Propose (via
  AskUserQuestion) under `balanced`. Refuse under `paranoid` /
  `conservative`.
- **proposed** — never autonomous. Surface via AskUserQuestion under
  `balanced` / `aggressive`. Refuse under `paranoid` / `conservative`.
- **escalate** — no auto-fix. Always surface to the user with the
  description as the prompt.

## Template substitution

The `hydra_overrides` field supports `{{ ... }}` substitutions filled in by
`relaunch_with_fix.sh`. Variables are pulled from the previous run's
config (via `wandb.Api().run().config`):

- `batch_size`    — `datamodule.batch_size` (or `batch_size`, `data.batch_size`)
- `accumulate`    — `trainer.accumulate_grad_batches` (default 1)
- `lr`            — `optimizer.lr` (default unset)
- `current_min_lr_ratio` — `optimizer.min_lr_ratio` (default 0)

Substitutions are evaluated as Python expressions inside the braces. Keep
them simple — arithmetic only, no function calls or imports.

## Overriding the default registry

Point `JOB_MONITOR_FIX_REGISTRY` at your own copy:

```bash
export JOB_MONITOR_FIX_REGISTRY=/path/to/my-project-fixes.yaml
```

Or set it in supervisor-doctor's profile under `.claude/`.

## Anti-loop interaction

`relaunch_with_fix.sh` updates the per-job anti-loop counter on success.
Fingerprint = sha256(`experiment + failure_class + fix_id`). Applying a
*different* fix for the same failure resets the count for that
`(failure_class, fix_id)` pair, but the supervisor still surfaces
"this is the third fix attempt overall" to the user.
````

- [x] **Step 3: Verify YAML parses**

```bash
python -c "import yaml; print(len(yaml.safe_load(open(
  'plugins/training-supervisor/skills/slurm-monitor/fixes/registry.yaml'
))['fixes']))"
```

Expected: `5` (five failure classes: oom, nccl_timeout, crashed, loss_nan, stagnant).

### Task F2: Write `relaunch_with_fix.sh` + tests (TDD)

**Files:**
- Create: `plugins/training-supervisor/skills/slurm-monitor/scripts/relaunch_with_fix.sh`
- Test: `plugins/training-supervisor/skills/slurm-monitor/scripts/test_relaunch_with_fix.py`

This is a bash entrypoint that calls a small Python helper (inline or as a
sibling). The Python is unit-testable; the bash is thin glue.

- [x] **Step 1: Write the failing test**

Content of `test_relaunch_with_fix.py`:

```python
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
```

- [x] **Step 2: Run failing test**

```bash
python -m pytest plugins/training-supervisor/skills/slurm-monitor/scripts/test_relaunch_with_fix.py -v
```

Expected: ImportError for `rendered`.

- [x] **Step 3: Write `rendered.py` (the fix-selection helper)**

Create `plugins/training-supervisor/skills/slurm-monitor/scripts/rendered.py`:

```python
"""Fix selection + Hydra-override rendering for relaunch_with_fix.sh.

Pure functions; no side effects (no subprocess, no W&B calls). The bash
wrapper handles I/O (read run config from W&B, write the next_action.sh
file).
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Any

import yaml

AUTHORITY_AUTONOMOUS = {"aggressive"}
AUTHORITY_PROPOSE = {"balanced", "aggressive"}


@dataclass
class FixVerdict:
    id: str
    description: str
    risk: str               # safe | proposed | escalate
    action: str             # autonomous | propose | escalate | refused
    hydra_overrides: list[str]


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _config_get(flat: dict[str, Any], *paths: str, default: Any = None) -> Any:
    for p in paths:
        if p in flat:
            return flat[p]
    return default


def _render(template: str, env: dict[str, Any]) -> str:
    """Replace each {{ expr }} with the result of eval(expr, env)."""
    out: list[str] = []
    i = 0
    while i < len(template):
        if template[i:i+2] == "{{":
            j = template.index("}}", i + 2)
            expr = template[i+2:j].strip()
            out.append(str(eval(expr, {"__builtins__": {}}, env)))  # noqa: S307
            i = j + 2
        else:
            out.append(template[i]); i += 1
    return "".join(out)


def _check_requires(req: list[str], env: dict[str, Any]) -> bool:
    ops = {">=": operator.ge, "<=": operator.le, ">": operator.gt,
           "<": operator.lt, "==": operator.eq, "!=": operator.ne}
    for cond in req:
        for sym, op in ops.items():
            if sym in cond:
                lhs_s, rhs_s = (s.strip() for s in cond.split(sym, 1))
                lhs = env.get(lhs_s)
                try:
                    rhs = float(rhs_s)
                except ValueError:
                    rhs = env.get(rhs_s)
                if lhs is None or not op(float(lhs), float(rhs)):
                    return False
                break
        else:
            # condition didn't contain a known operator; treat as truthy lookup
            if not env.get(cond.strip()):
                return False
    return True


def select_fix(
    *, registry_path: str, failure_class: str,
    run_config: dict[str, Any], authority: str,
) -> FixVerdict | None:
    """Pick the first applicable fix; render its overrides; classify action."""
    with open(registry_path) as f:
        reg = yaml.safe_load(f) or {}
    fixes = reg.get("fixes", {}).get(failure_class, [])

    flat = _flatten(run_config)
    env = {
        "batch_size": _config_get(flat,
            "datamodule.batch_size", "data.batch_size", "batch_size", default=0),
        "accumulate": _config_get(flat,
            "trainer.accumulate_grad_batches", "accumulate_grad_batches",
            default=1),
        "lr": _config_get(flat, "optimizer.lr", "optimizer.learning_rate",
            "learning_rate", default=None),
        "current_min_lr_ratio": _config_get(flat,
            "optimizer.min_lr_ratio", default=0.0),
    }

    for entry in fixes:
        if not _check_requires(entry.get("requires", []), env):
            continue
        risk = entry["risk"]
        if risk == "escalate":
            action = "escalate"
        elif risk == "safe" and authority in AUTHORITY_AUTONOMOUS:
            action = "autonomous"
        elif risk in ("safe", "proposed") and authority in AUTHORITY_PROPOSE:
            action = "propose"
        else:
            action = "refused"

        rendered_overrides = [_render(t, env) for t in entry.get("hydra_overrides", [])]
        return FixVerdict(
            id=entry["id"], description=entry["description"], risk=risk,
            action=action, hydra_overrides=rendered_overrides,
        )
    return None
```

- [x] **Step 4: Run tests, verify pass**

```bash
python -m pytest plugins/training-supervisor/skills/slurm-monitor/scripts/test_relaunch_with_fix.py -v
```

Expected: 6 passed.

- [x] **Step 5: Add the `rendered.py` CLI (`__main__`) block**

Append to `rendered.py` (after `select_fix`):

```python
def _read_run_config(wandb_run: str) -> dict[str, Any]:
    """Fetch the failed run's config from W&B. Returns {} on failure."""
    try:
        import wandb
        api = wandb.Api()
        # Caller is expected to pass entity/project via $WANDB_ENTITY /
        # $WANDB_PROJECT or as a fully-qualified id "entity/project/run_id".
        run = api.run(wandb_run)
        cfg = dict(run.config)
    except Exception as exc:  # noqa: BLE001
        print(f"rendered: WARN — could not read W&B config: {exc}",
              file=sys.stderr)
        return {}
    return cfg


def _write_next_action(
    *, path: str, template: str, ssh_host: str, overrides: list[str],
) -> None:
    """Render the relaunch_template and write an executable next_action.sh."""
    body = template.replace("{HOST}", ssh_host) \
                   .replace("{OVERRIDES}", " ".join(overrides))
    with open(path, "w") as f:
        f.write("#!/usr/bin/env bash\n# relaunch generated by rendered.py\n"
                "set -euo pipefail\n" + body + "\n")
    import os
    os.chmod(path, 0o755)


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    import os
    p = argparse.ArgumentParser(prog="slurm-monitor.rendered")
    p.add_argument("--registry", required=True)
    p.add_argument("--wandb-run", required=True)
    p.add_argument("--failure-class", required=True)
    p.add_argument("--authority", required=True)
    p.add_argument("--ssh-host", required=True)
    p.add_argument("--relaunch-template", required=True)
    p.add_argument("--next-action", required=True)
    p.add_argument("--log-dir", required=True)
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    cfg = _read_run_config(args.wandb_run)
    verdict = select_fix(
        registry_path=args.registry, failure_class=args.failure_class,
        run_config=cfg, authority=args.authority,
    )
    log_path = os.path.join(args.log_dir, "fix_decision.md")
    if verdict is None:
        with open(log_path, "w") as f:
            f.write(f"# fix_decision\n\nNo applicable fix for "
                    f"failure_class={args.failure_class!r} under "
                    f"authority={args.authority!r}.\n")
        return 0

    _write_next_action(
        path=args.next_action, template=args.relaunch_template,
        ssh_host=args.ssh_host, overrides=verdict.hydra_overrides,
    )
    if verdict.action == "autonomous":
        # Marker file the bash wrapper checks before exec'ing next_action.sh.
        open(os.path.join(args.log_dir, ".autonomous"), "w").close()
    with open(log_path, "w") as f:
        f.write(
            f"# fix_decision\n\n"
            f"- id: {verdict.id}\n"
            f"- risk: {verdict.risk}\n"
            f"- action: {verdict.action}\n"
            f"- description: {verdict.description}\n"
            f"- hydra_overrides: {verdict.hydra_overrides}\n"
            f"- next_action: {args.next_action}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
```

- [x] **Step 6: Write the bash wrapper**

Create `relaunch_with_fix.sh`:

```bash
#!/usr/bin/env bash
# relaunch_with_fix.sh — propose or autonomously execute a job relaunch
# after a STOP, consulting the fix registry.
#
# Reads the failed job's config from W&B (via rendered.py's _read_run_config),
# looks up applicable fixes for the given failure_class, and writes a
# next_action.sh file with the proposed relaunch command. Under aggressive +
# safe-risk, also EXECUTES next_action.sh. Otherwise the file is left for the
# orchestrator to surface to the user.
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --wandb-run RUN --failure-class CLASS --authority LEVEL \\
          --ssh-host HOST --relaunch-template TEMPLATE \\
          [--registry PATH] [--state-dir DIR]

Required:
  --wandb-run         W&B run id (fully-qualified entity/project/id, or just
                      id if WANDB_ENTITY + WANDB_PROJECT are exported).
  --failure-class     oom|nccl_timeout|crashed|loss_nan|stagnant
  --authority         paranoid|conservative|balanced|aggressive
  --ssh-host          Cluster login host for the relaunch.
  --relaunch-template Bash command template. Use {HOST} and {OVERRIDES} as
                      placeholders. NO default — every project's relaunch
                      command differs; set this explicitly or via env var
                      \$JOB_MONITOR_RELAUNCH_TEMPLATE. Example for autocast:
                        'ssh {HOST} autocast epd --mode slurm {OVERRIDES}'

Optional:
  --registry          Fix registry path. Default: \$JOB_MONITOR_FIX_REGISTRY,
                      else \$CLAUDE_SKILL_ROOT/fixes/registry.yaml.
  --state-dir         State dir. Default: \$TRAINING_SUPERVISOR_STATE_DIR or
                      ~/.claude-job-monitor.
EOF
}

WANDB_RUN="" FAILURE_CLASS="" AUTHORITY="" SSH_HOST=""
REGISTRY="" STATE_DIR=""
RELAUNCH_TEMPLATE="${JOB_MONITOR_RELAUNCH_TEMPLATE:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --wandb-run) WANDB_RUN="$2"; shift 2 ;;
        --failure-class) FAILURE_CLASS="$2"; shift 2 ;;
        --authority) AUTHORITY="$2"; shift 2 ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        --registry) REGISTRY="$2"; shift 2 ;;
        --state-dir) STATE_DIR="$2"; shift 2 ;;
        --relaunch-template) RELAUNCH_TEMPLATE="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
for v in WANDB_RUN FAILURE_CLASS AUTHORITY SSH_HOST; do
    [[ -n "${!v}" ]] || { echo "missing --${v,,}" >&2; usage >&2; exit 2; }
done
if [[ -z "$RELAUNCH_TEMPLATE" ]]; then
    echo "missing --relaunch-template (no default; set explicitly or via" \
         "\$JOB_MONITOR_RELAUNCH_TEMPLATE — every project's relaunch CLI is" \
         "different)" >&2
    usage >&2
    exit 2
fi

REGISTRY="${REGISTRY:-${JOB_MONITOR_FIX_REGISTRY:-$(dirname "$0")/../fixes/registry.yaml}}"
STATE_DIR="${STATE_DIR:-${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}}"

HERE="$(cd "$(dirname "$0")" && pwd)"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
log_dir="$STATE_DIR/sessions/$ts"
mkdir -p "$log_dir"
next_action="$log_dir/next_action.sh"

# Call the Python helper to select and render the fix.
python "$HERE/rendered.py" \
    --registry "$REGISTRY" \
    --wandb-run "$WANDB_RUN" \
    --failure-class "$FAILURE_CLASS" \
    --authority "$AUTHORITY" \
    --ssh-host "$SSH_HOST" \
    --relaunch-template "$RELAUNCH_TEMPLATE" \
    --next-action "$next_action" \
    --log-dir "$log_dir"
rc=$?

# Under aggressive + a safe fix, rendered.py writes a .autonomous marker
# file; we then execute next_action.sh. Otherwise the file is left for the
# orchestrator to surface via AskUserQuestion.
if [[ -f "$log_dir/.autonomous" && "$rc" -eq 0 ]]; then
    "$next_action" 2>&1 | tee -a "$log_dir/relaunch_output.log"
fi
exit "$rc"
```

- [x] **Step 7: chmod + dry smoke**

```bash
chmod +x plugins/training-supervisor/skills/slurm-monitor/scripts/relaunch_with_fix.sh
plugins/training-supervisor/skills/slurm-monitor/scripts/relaunch_with_fix.sh --help
echo "rc=$? (expect 0)"

# Missing-template error path:
plugins/training-supervisor/skills/slurm-monitor/scripts/relaunch_with_fix.sh \
  --wandb-run x --failure-class oom --authority aggressive --ssh-host h
echo "rc=$? (expect 2 — no template set)"
```

Expected: first call rc=0 with usage; second rc=2 with "missing --relaunch-template" message.

**Do NOT execute against a live run.** Like `scancel_safe.sh`, the
end-to-end smoke is reserved for the user's explicit go-ahead.

### Task F3: Update slurm-monitor SKILL.md

**Files:**
- Modify: `plugins/training-supervisor/skills/slurm-monitor/SKILL.md`

- [x] **Step 1: Add a "Known-Fixes Registry" section**

Append after the "Anti-Loop Protocol" section:

```markdown
## Known-Fixes Registry (Phase 5 follow-on)

After a successful STOP (via `scancel_safe.sh`), the orchestrator consults
`fixes/registry.yaml` and runs `scripts/relaunch_with_fix.sh` if the
failure class has an applicable fix.

The registry maps `failure_class -> [fix, ...]`. Each fix has a `risk`:
- `safe` — autonomous under `aggressive`; proposed under `balanced`.
- `proposed` — never autonomous; proposed under `balanced`/`aggressive`.
- `escalate` — always surfaces to the user, never auto-applied.

See `fixes/README.md` for the schema and the template substitution rules.
The default registry targets autocast (Hydra paths
`datamodule.batch_size`, `+trainer.accumulate_grad_batches`,
`optimizer.min_lr_ratio`); override via `JOB_MONITOR_FIX_REGISTRY` to use
your own paths.
```

- [x] **Step 2: Update the Anti-Loop Protocol — fingerprint + aggregate cap**

Replace the existing fingerprint line:

```
1. Computes a failure fingerprint:
   `sha256(experiment_name + resolved_config_hash + failure_class)`.
```

with:

```
1. Computes a failure fingerprint:
   `sha256(experiment_name + failure_class + fix_id)`. The fix_id comes from
   the Phase 5 fix-registry lookup (or "_no_fix" if STOP without auto-fix).
   This means: applying a *different* fix for the same failure class starts
   a fresh counter for that (failure_class, fix_id) pair; applying the same
   fix twice does not.
2. Also maintains an aggregate counter
   `aggregate_attempts[experiment_name + failure_class]` (no fix_id) so that
   a registry with multiple fixes per failure class cannot cycle through
   them indefinitely. Cap = `2 × anti_loop_cap[authority]` (e.g., balanced
   = 4 aggregate attempts max across all fixes for that failure class).
   When the aggregate cap is hit, the supervisor refuses any further fix
   attempt for that (experiment, failure_class) until the user resets the
   counter (delete the entry from `${STATE_DIR}/jobs/<job-id>.json` or call
   `scripts/reset_counter.sh`).
```

### Task F4: Update phases/5-act.md

**Files:**
- Modify: `plugins/training-supervisor/skills/training-supervisor/phases/5-act.md`

- [x] **Step 1: Extend the STOP path documentation**

In the `### If STOP (autonomous)` section (already updated for slurm-monitor
in Task B7), add at the end:

```markdown
**After `scancel_safe.sh` succeeds AND slurm-monitor is active**, chain
`scripts/relaunch_with_fix.sh` with the same `--authority` and the failure
class from Phase 3. The script writes a `next_action.sh` proposal. Under
`aggressive` + a `safe`-risk fix, it auto-executes; under `balanced` or for
a `proposed` fix, the orchestrator surfaces the proposal via
AskUserQuestion. Under `paranoid` or for `escalate`-class fixes (loss_nan),
the registry returns nothing — surface a plain "STOPped; needs human
review" message.
```

### Task F5: Commit Phase F

- [x] **Step 1: Diff review + commit**

```bash
cd ~/dev/training-supervisor-plugin && git diff --stat
git add plugins/training-supervisor/skills/slurm-monitor/ \
        plugins/training-supervisor/skills/training-supervisor/phases/5-act.md
git commit -m "Add config-fix registry (Phase F) for safe auto-fixes after STOP

When the supervisor cancels a job because of a known-safe failure (OOM,
NCCL timeout, crashed), v0.3 left the user to manually relaunch with the
right Hydra override. Phase F ships a small registry of well-defined fixes
and a script that proposes (or executes under aggressive authority) the
relaunch.

Registry (fixes/registry.yaml) maps failure_class -> ordered fix list:
  oom        -> oom_halve_batch (safe; halve bs, double grad accum)
  nccl_timeout -> nccl_resubmit (safe; same config retry)
  crashed    -> crashed_resubmit (safe; same config retry)
  loss_nan   -> loss_nan_escalate (escalate; never auto)
  stagnant   -> stagnant_raise_lr_floor (proposed; bump min_lr_ratio to 0.1)

relaunch_with_fix.sh:
  - Reads the failed run's config from W&B to substitute template vars
    (batch_size, accumulate, current_min_lr_ratio).
  - Writes the proposed relaunch command to a next_action.sh file.
  - Under aggressive + safe-risk, executes it directly via ssh.
  - Under balanced or proposed-risk, leaves next_action.sh for the
    orchestrator to surface via AskUserQuestion.
  - Refuses under paranoid; refuses under conservative for non-safe risks.

Anti-loop fingerprint widens to (experiment + failure_class + fix_id) so
applying a different fix resets that counter, but the same fix can't loop.

Default registry targets autocast Hydra paths
(datamodule.batch_size, +trainer.accumulate_grad_batches,
optimizer.min_lr_ratio). Users on other stacks point
JOB_MONITOR_FIX_REGISTRY at their own copy.

Six unit tests cover the verdict matrix (autonomous / propose / escalate /
refused) across authority levels and a representative subset of fixes.

PR candidate for upstream (mechanism is generic; default registry happens
to be Hydra-shaped)."
```

**Acceptance criteria for Phase F:**
- `python -m pytest plugins/training-supervisor/skills/slurm-monitor/scripts/test_relaunch_with_fix.py -v` passes (6/6).
- `registry.yaml` parses; 5 failure classes covered.
- `relaunch_with_fix.sh --help` returns rc=0.
- SKILL.md's Anti-Loop Protocol section now references the `(experiment, failure_class, fix_id)` fingerprint.
- No live `relaunch` exercised end-to-end in this plan.

---

## End-to-End Validation Pass

After all five phases land on `master`, re-run the smoke flow that previously
hit F1–F8 and verify each failure mode is addressed.

### Task V1: Push the fork

- [ ] **Step 1: Push all commits**

```bash
cd ~/dev/training-supervisor-plugin && git push origin master
```

Expected: 5 new commits land on the fork's master.

### Task V2: Re-run /supervisor-doctor against the active environment

- [ ] **Step 1: From the autocast-private CWD**

```bash
cd ~/dev/turing/autocast-private
CCAGE_DISABLE=1 claude --print --output-format=text \
  "Use training-supervisor:supervisor-doctor. Context: same as the prior run (~/.claude-job-monitor/smoke-tests/lx51s8bj_*.txt). Identify which skills now apply with the new slurm-monitor available." \
  > ~/.claude-job-monitor/smoke-tests/doctor_post_patches.txt
cat ~/.claude-job-monitor/smoke-tests/doctor_post_patches.txt
```

Expected: report now lists `slurm-monitor` as `[OK]` (or `[MISSING]` with the install command). Capability list mentions SLURM-aware Phase 2 collectors.

### Task V3: Re-run /training-supervisor with permissions pre-granted

> **MANUAL STEP REQUIRED — do not automate.** Step 1 below requires the user
> to edit `~/.claude/settings.json` themselves. Subagents executing this plan
> must pause here and surface the request, not attempt to modify the file.

- [ ] **Step 1: Merge permissions snippet into the user's settings.json**

User action — paste the `permissions.allow` entries from
`plugins/training-supervisor/templates/permissions.snippet.json` into
`~/.claude/settings.json`, substituting `<SSH_HOST>=u6eo.aip2.isambard`.

If the executing agent reaches this task and the snippet has not yet been
merged (check by grepping `~/.claude/settings.json` for `~/bin/wbcheck`),
STOP and ask the user to do the merge before proceeding to Step 2.

- [ ] **Step 2: Re-run the smoke**

```bash
CCAGE_DISABLE=1 claude --print --output-format=text \
  "Use training-supervisor:training-supervisor. DISPATCH_MODE: ralph. Authority OBSERVE-ONLY. Target lx51s8bj, ref 68qcze3w. Use slurm-monitor + wandb-monitor. Job id 4896750, ssh host u6eo.aip2.isambard. Smoke test — report which phases ran cleanly." \
  > ~/.claude-job-monitor/smoke-tests/supervisor_post_patches.txt 2>&1
tail -80 ~/.claude-job-monitor/smoke-tests/supervisor_post_patches.txt
```

Expected: Phases 0–6 all run; Phase 2 collector emits the slurm-monitor evidence bundle; Phase 5 records "OBSERVE-ONLY — would have proposed/stopped, no action taken." F1–F8 no longer block.

### Task V4: Prep the upstream PRs (optional follow-up)

For each PR-candidate phase (A, B, C, E, F):

- [ ] Cherry-pick its commit onto a branch off `upstream/master`.
- [ ] Push the branch to the fork.
- [ ] Open a PR to `t2ance/training-monitor-plugin`.

Order: A first (state-path foundation), B second (slurm-monitor + generic collector contract — biggest, may need design discussion), C third (heartbeat — straightforward improvement), E fourth (template + doctor — small), F fifth (config-fix registry — generic mechanism, autocast-flavoured default).

D stays on the fork.

---

## Risks and Open Questions

- **`ccage` vs CLAUDE_CONFIG_DIR.** Patch D's `cron_dispatch.sh` sets `CCAGE_DISABLE=1` so the cron entrypoint always uses the global config dir (`~/.claude/`). If a teammate uses ccage and wants per-project state, they'd need to set `CLAUDE_CONFIG_DIR` explicitly inside the cron prompt. Documented in supervisor-team SKILL.md.
- **`scancel_safe.sh` and `relaunch_with_fix.sh` are untested against a live job in this plan.** First real cancel + relaunch are gated on the user's explicit go-ahead; the scripts' logic is paper-reviewed and unit-tested but not exercised end-to-end.
- **Adaptive heartbeat assumes `_timestamp` is logged on every history row.** Almost universally true for W&B, but if a project's training script writes its own custom step axis without `_timestamp`, the baseline calc falls back to `INSUFFICIENT_HISTORY`. Documented in SKILL.md.
- **Template substitution uses `eval` inside a restricted namespace.** Phase F's `rendered.py._render` evaluates Hydra-override templates with `__builtins__: {}`, so the worst a hostile registry can do is arithmetic. Still: only trust registries you wrote yourself or audited. Documented in `fixes/README.md`.
- **Default fix registry is Hydra-shaped (autocast-flavoured).** Non-autocast projects MUST point `JOB_MONITOR_FIX_REGISTRY` at their own override before enabling autonomous fixes — otherwise the registry's Hydra paths won't match their CLI. Doctor's report flags this in Phase E's "Permissions Overlay" step.
- **Generic collector contract requires user-side scripts to match the markdown shape exactly.** If a user-supplied collector emits a different section ordering or skips `## heartbeat`, the supervisor's Phase 3 sub-agent will receive a malformed bundle. Future: ship `scripts/validate_collector.sh` that lints a user-collector against the contract (deferred — flagged in CONTRACT.md).
- **Upstream PR acceptance is not guaranteed.** Phases A / B / C / E / F are PR candidates but t2ance may want changes. Plan does not block on upstream merge — the fork carries them in the meantime.

---

## Glossary

- **Authority level**: `paranoid | conservative | balanced | aggressive` — chosen by the user at supervisor-team setup; gates destructive actions in `scancel_safe.sh`.
- **Failure class**: `loss_nan | nccl_hang | crashed | stagnant | other` — the reason a STOP decision was reached; constrains which authority levels permit auto-cancel.
- **Fingerprint**: `sha256(experiment_name + failure_class + fix_id)` — used for anti-loop bookkeeping per (failure, fix) pair in the per-job state. A second `aggregate_attempts[experiment + failure_class]` counter caps total fix attempts per failure class at `2 × anti_loop_cap[authority]` so a future registry with multiple fixes per class can't loop indefinitely.
- **K (multiplier)**: Adaptive-heartbeat multiplier from the aggressiveness table. ∞ / 20 / 10 / 5.
- **Reference run**: a finished W&B run of the same experiment used as the matched-epoch baseline (e.g., K=32 `68qcze3w` is our drifting baseline).
