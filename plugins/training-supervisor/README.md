# Training Monitor Plugin

Prediction-first monitoring for ML/DL training jobs. Phase-based execution with procedure/dispatch separation. Derives judgment criteria from training artifacts, not hardcoded rules.

For installation and update instructions, see the [top-level README](../../README.md).

## Migration from upstream / older versions

In versions before the `monitoring-logs/` → `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/` rename, state was written to a `monitoring-logs/` directory in the working directory. If you have an existing `monitoring-logs/` directory, migrate it once with:

```bash
mv monitoring-logs "${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}"
```

The PreCompact hook will emit a warning to stderr if it detects `monitoring-logs/` is present but the canonical state directory is not.

## Skills

| Skill | Description | Standalone? |
|-------|-------------|-------------|
| `training-supervisor` | Core monitoring procedure. Single-agent executes the full pipeline for one job, spawns a reviewer sub-agent for audit. | Yes |
| `grpo-monitor` | GRPO/RL training: reward, KL, entropy, generation quality, phase time balance. | Yes |
| `distributed-monitor` | Multi-GPU/multi-process: NCCL, process hierarchy, straggler detection. | Yes |
| `k8s-monitor` | Kubernetes: kubectl collection, pod anomalies, scheduling escalation ladder. | Yes |
| `wandb-monitor` | W&B monitoring: heartbeat stall detection, metric key variations, health thresholds, run comparison. | Yes |
| `supervisor-team` | Cron-based team monitoring loop. Creates a fresh teammate each cycle to run training-supervisor. Collects user preferences (target, mode, frequency, authority, team conflict) at setup. | Yes |
| `supervisor-doctor` | Interactive setup wizard. Detects environment, checks dependencies, installs missing ones. | Yes |
| `slurm-monitor` | SLURM job state + remote STOP path; peer of `k8s-monitor`. Use when training is `sbatch`-scheduled. | Yes |

## Agents

| Agent | Spawned by | Purpose |
|-------|------------|---------|
| `quality-reviewer` | `training-supervisor` executor | Sub-agent for adversarial process review. Checks reasoning process and logical coherence, spot-checks one load-bearing claim. |

## Step Files

| Step | File | Description |
|------|------|-------------|
| 1 | `steps/1-predict.md` | Write predictions before reading evidence |
| 2 | `steps/2-collect.md` | Collect all evidence in parallel |
| 3 | `steps/3-compare.md` | Compare predictions vs actuals |
| 4 | `steps/4-metrics.md` | Derive criteria and analyze metrics |
| 5 | `steps/5-resources.md` | Check GPU, memory, disk resources |
| 6 | `steps/6-review.md` | Reviewer sub-agent audit |
| 7 | `steps/7-troubleshoot.md` | Systematic root cause analysis (conditional) |
| 8 | `steps/8-strategy.md` | Strategic next-step hypotheses |

## External Dependencies

The plugin works out of the box for single-GPU PyTorch training with log file output. Additional features require external dependencies:

| Feature | Requires | Install |
|---------|----------|---------|
| W&B monitoring | `wandb-primary` skill + `wandb` package | `npx skills add wandb/skills` then `pip install wandb && wandb login` |
| K8s monitoring | `kubectl` with cluster access | See [Kubernetes docs](https://kubernetes.io/docs/tasks/tools/) |
| GPU monitoring (baseline) | `nvidia-smi` | Pre-installed on GPU machines |
| SLURM monitoring | `ssh` to the cluster login host; `~/bin/sjob`, `~/bin/wbcheck` user helpers | (user-installed) |

Run `/supervisor-doctor` to check what is installed and install what is missing interactively.

## Unattended loops (permissions overlay)

Running `supervisor-team` with Q6=Local invokes `claude --print` in a sandbox
that blocks helpers outside the working directory by default. For unattended
operation, merge the permissions snippet into your settings.json once to make
the loop quiet:

```bash
# Inspect the template:
cat ${CLAUDE_SKILL_ROOT}/templates/permissions.snippet.json

# Recommended: paste its permissions.allow entries (after substituting your
# cluster SSH host) into ~/.claude/settings.json under "permissions.allow".
# Then run /fewer-permission-prompts after one loop cycle to catch any
# read-only operations the template missed.
```

## Usage

### Monitor running training jobs

```
/training-supervisor
```

The executor will:
1. Write predictions before reading any data
2. Collect evidence and compare against predictions
3. Analyze metrics using derived criteria
4. Check resources
5. Spawn a reviewer sub-agent for adversarial audit
6. Troubleshoot anomalies (if any)
7. Propose strategic next steps
8. Write per-job state for cross-session continuity

### Set up periodic monitoring with a team

```
/supervisor-team
```

The skill will ask for your preferences (what to monitor, work mode, frequency,
authority level), then set up a cron-based loop that creates a fresh teammate
each cycle to run `/training-supervisor`.

### Use domain skills standalone

```
/grpo-monitor          # GRPO/RL monitoring knowledge
/distributed-monitor   # Multi-GPU monitoring knowledge
/k8s-monitor           # Kubernetes monitoring knowledge
/wandb-monitor         # W&B monitoring knowledge
```

## Architecture

```
executor (single agent per job)
├── Steps 1-5: predict, collect, compare, metrics, resources
├── Step 6: spawns quality-reviewer sub-agent for adversarial audit
├── Step 7: troubleshoot (conditional, on anomalies)
├── Step 8: strategize (propose hypotheses to user)
└── Step 9: write per-job state to disk
```

- **Main agent** does not read SKILL.md. It spawns one executor per job.
- **Each executor** reads SKILL.md, executes the full procedure for one job, writes results to files, then finishes.
- **Cross-session state** goes through per-job state files on disk, never through any agent's context.
- **TodoList (TaskCreate/TaskUpdate)** is used as an anti-skip mechanism -- all steps registered before work begins.

Baseline: single-GPU, single-process PyTorch. Domain skills extend to GRPO, distributed, K8s, W&B.
