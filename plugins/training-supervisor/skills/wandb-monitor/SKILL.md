---
name: wandb-monitor
description: Heuristics for monitoring training via Weights & Biases. Heartbeat patterns, metric key variations, cross-source validation, health thresholds. Reference knowledge, not rules. Depends on wandb-primary skill (wandb/skills) for API access.
---

# W&B Training Monitor

Heuristics for monitoring training jobs via Weights & Biases. This skill provides **reference knowledge** about W&B-specific patterns (heartbeat behavior, metric key naming, cross-source validation). For W&B API patterns (how to call the SDK), it depends on the `wandb-primary` skill from `wandb/skills`.

Use these heuristics to inform your reasoning about W&B data, not as rigid rules.

**Dependency**: `wandb-primary` skill must be installed (`npx skills add wandb/skills`) and `wandb` Python package must be available with valid authentication.

## W&B Evidence Collection

### Heartbeat Sync Check

```bash
# Quick local check: is W&B syncing?
stat --format='%Y' <wandb_dir>/latest-run/*.wandb && date +%s
```

If the wandb file's mtime is >10min behind current time, W&B sync may be stalled.

### Python API Collection

```python
import wandb
api = wandb.Api()

# Get run by ID
run = api.run("entity/project/run_id")

# Key properties for monitoring
run.state        # running | finished | failed | crashed | canceled
run.heartbeat_at # last heartbeat timestamp — primary stall indicator
run.summary      # final/current metrics
run.config       # hyperparameters

# Get metric history (use wandb-primary patterns for efficient access)
history = list(run.scan_history(keys=["train/loss", "train/grad_norm"], page_size=1000))
```

### Run Overview

```python
# List all running jobs for an entity
runs = api.runs("entity/project", filters={"state": "running"})
for run in runs:
    print(f"{run.name}: step {run.summary.get('_step', '?')}, heartbeat {run.heartbeat_at}")
```

## Metric Key Variations

Different training frameworks log to W&B with different key names. When collecting metrics, check all common variants:

| Metric | Common Key Variants |
|--------|-------------------|
| Loss | `train/loss`, `loss`, `train_loss`, `training_loss` |
| Gradients | `train/grad_norm`, `grad_norm`, `gradient_norm` |
| Steps | `train/global_step`, `global_step`, `step`, `_step` |
| Eval | `eval/loss`, `eval_loss`, `eval/accuracy`, `eval_acc` |
| Learning rate | `train/lr`, `lr`, `learning_rate` |

When a metric key is not found, try all variants before concluding the metric is not logged.

## Health Thresholds

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

### Quiet-by-design phases (operational note)

Some training phases (eval pass, checkpoint save, dataloader epoch boundary)
are quiet by design. When the supervisor's Phase 1 prediction includes such
a phase, the orchestrator should DISCOUNT a STALE verdict from heartbeat
during the predicted phase duration — this is enforced at the orchestrator
level, not in `classify()` itself. (Future work: a dedicated `EXPECTED_QUIET`
verdict; not currently implemented.)

### Recommended Phase 2 wiring

Have the wandb-monitor collector call `heartbeat_baseline.py` for every
running W&B run in scope. Treat its verdict as one signal among many in the
Phase 3 evidence bundle; never let it alone trigger STOP.

## W&B Cross-Source Validation

| Source A | Source B | If they disagree |
|----------|----------|------------------|
| Log file step count | W&B step count | Logging bug or W&B sync delay |
| Step N log metrics | W&B step N metrics | Log parsing error or W&B batching |
| Process alive (ps) | W&B heartbeat stale | W&B sync issue or true stall — check GPU power to disambiguate |
| W&B `run.state` | Process status | State update delay — W&B state lags by up to 60s |

## Run Comparison

When investigating whether a training run is behaving normally, compare against previous runs:

```python
# Get finished runs for comparison baseline
baseline_runs = api.runs("entity/project", filters={"state": "finished"}, order="-created_at")

# Compare loss at same step
current_loss = current_run.summary.get("train/loss")
baseline_losses = [r.summary.get("train/loss") for r in baseline_runs[:3]]
```

Key comparison points:
- Loss at same step count: is current run within 2x of baseline?
- Step time: is current run within 1.5x of baseline?
- GPU memory: is current run using significantly more than baseline? (potential memory leak)
