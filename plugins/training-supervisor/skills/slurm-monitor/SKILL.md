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
3. Reads `${STATE_DIR}/jobs/<job-id>.json` → `strategy.relaunch_attempts[fingerprint]`.
4. If `attempts >= anti_loop_cap[authority]`, REFUSES to relaunch; raises a
   "two failed retries with the same config + failure mode" notice and stops.
5. Otherwise increments the counter, records the new launch, persists.

Persistence write is the supervisor's responsibility (Phase 6), not this
skill's. The skill returns the fingerprint and a recommended next-step
descriptor; the orchestrator decides whether to honour it.

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
