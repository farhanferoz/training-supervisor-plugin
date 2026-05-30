# Phase 0: Contract

## Goal

Two things happen in this phase: (1) discover what we're supervising, and (2) agree with the reviewer on what this pass will focus on.

## Job Discovery

Before writing any contract, establish WHAT we are supervising.

### Subsequent sessions (per-job state exists)

Read job targets from `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/<job-id>.json`:
- PID, log path, config path, checkpoint dir
- Verify targets are still valid:
  ```bash
  ps -p <PID> -o pid --no-headers 2>/dev/null || echo "DEAD"
  test -f <log_path> && echo "EXISTS" || echo "MISSING"
  ```
- If PID is dead: check if job completed (log says "Training complete") or crashed. Update state accordingly.
- If paths moved: search for new locations.

### First session (no per-job state)

Discover what's running:
```bash
# Find training processes
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
ps aux | grep -E "python.*train|torchrun|deepspeed" | grep -v grep

# Find config and log files (search from project directory)
find . -maxdepth 3 -name "*.yaml" -o -name "*.json" | head -20
find . -maxdepth 3 -name "*.log" -newer <1-hour-ago> | head -10
```

Record discovered targets:
- PID(s) and which GPUs they use
- Training config path
- Log file path
- Checkpoint directory
- Training type (infer from config: SFT, GRPO, etc.)

**Discovery is METADATA** (what process, which GPUs, where are logs), not training DATA (metrics, loss values). It does not violate the prediction-first principle.

## Contract Proposal

Write a contract proposal with these sections:

### Job Targets

The discovered job targets. Phase 2 collectors use these as input.

```
Job: [name derived from config/model path]
PID: [pid]
GPUs: [list]
Config: [path]
Log: [path]
Checkpoint dir: [path]
Training type: [SFT/GRPO/etc.]
```

### Focus Areas

Based on per-job state and pitfalls, list what this pass should prioritize:

- **From previous session**: what was the status? what anomalies were found? what strategy was chosen?
- **From pitfalls**: what mistakes should we avoid repeating?
- **From strategy.evaluate_after**: is there a pending hypothesis that needs evaluation this session?

If first session (no prior state): focus areas come from the training config and initial observations. State: "First session -- deriving focus from training config."

### Acceptance Criteria

What must the supervision report contain for the reviewer to APPROVE:

- Which evidence sources MUST be checked (e.g., "must verify GPU 3 status -- it showed anomalies last session")
- Which domain skills MUST be loaded (e.g., "GRPO training -- grpo-monitor required")
- Any specific claims that MUST be spot-checked

### Pass Definition

What counts as a "complete" supervision pass:

- All relevant evidence categories collected (GPU, logs, processes, resources, domain as applicable)
- Metric trajectories described qualitatively
- Holistic judgment made: CONTINUE or STOP
- Comparison against predictions completed

## Negotiation

Send the proposal to the reviewer. The reviewer may:
- Accept as-is
- Add focus areas the monitor missed
- Strengthen acceptance criteria
- Flag pitfalls the monitor forgot to account for

Dispatch determines the mechanism (Team multi-round vs Agent single-round). Regardless of mechanism, the goal is agreement -- not rubber-stamping.

## First Session

If no per-job state exists:
- Focus areas: "Initial assessment -- understand what training is trying to achieve, observe current trajectory"
- Acceptance criteria: "Must read training config, describe metric trajectories qualitatively, make a holistic judgment"
- Pass definition: same as default

## Gate Log Format

Record in `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/0-contract.md`:

```
CONTRACT: [job name] -- [session timestamp]
---
Job targets:
  PID: [pid]
  GPUs: [list]
  Config: [path]
  Log: [path]
  Checkpoint dir: [path]
  Training type: [type]

Focus areas:
- [list]

Acceptance criteria:
- [list]

Pass definition:
- [list]

Reviewer modifications:
- [what the reviewer added/changed, or "none"]

Agreement: [AGREED / AGREED WITH MODIFICATIONS]
---
```
