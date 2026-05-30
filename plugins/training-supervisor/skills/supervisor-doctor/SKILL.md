---
name: supervisor-doctor
description: Interactive setup wizard for the training-supervisor plugin. Goal-driven — the agent determines which dependencies are needed by checking project context and asking the user only when the context is ambiguous. Installs missing dependencies and reports available capabilities.
---

# Monitor Doctor

Set up the training-supervisor plugin for the user's environment. The goal is to determine which domain skills and external dependencies are needed, install what is missing, and report available capabilities.

## Goal

Determine which entries in the Dependency Registry below apply to the user's situation. For each applicable entry, check if its dependencies are installed. Offer to install what is missing. Report the final capability state.

## Strategy

**Do NOT follow a fixed questionnaire.** Instead:

1. **Check context first.** Read the project directory, look at running processes, check installed packages. Many answers are already available without asking.
2. **Ask only when ambiguous.** If the context makes the answer clear, skip the question. If the user already stated their setup (e.g., "I'm running GRPO on K8s with W&B"), extract the answers directly — do not re-ask.
3. **Ask efficiently.** If multiple things are unclear, batch them into a single AskUserQuestion call. Do not ask one question at a time if you can ask several at once.
4. **Be adaptive.** If the user's first message already provides enough information to determine all dependencies, go straight to checking and installing. Zero questions is a valid outcome.

### Context Signals to Check

| Signal | What it tells you | How to check |
|--------|------------------|-------------|
| RL/GRPO/PPO keywords in config or code | GRPO/RL training → need `grpo-monitor` | `grep -ri "grpo\|ppo\|rloo\|reward\|kl_loss" <project_dir>` |
| Multiple GPU processes or torchrun/deepspeed in command | Distributed training → need `distributed-monitor` | `ps aux \| grep -E "torchrun\|deepspeed\|accelerate"`, `nvidia-smi` showing multiple GPUs used |
| sbatch / salloc / squeue in shell history, slurm_scripts/ in repo, sacct on PATH | SLURM-scheduled training → need `slurm-monitor` | `command -v sbatch sacct squeue >/dev/null 2>&1`, `ls slurm_scripts/ *.sbatch 2>/dev/null` |
| K8s YAML files, kubectl available, namespace references | Kubernetes infra → need `k8s-monitor` | `ls *.yaml *k8s* 2>/dev/null`, `kubectl version --client 2>/dev/null` |
| wandb imported in code, wandb dir exists, WANDB_API_KEY set | W&B tracking → need `wandb-monitor` | `grep -ri "import wandb\|wandb.init" <project_dir>`, `ls wandb/ 2>/dev/null`, `echo $WANDB_API_KEY` |
| tensorboard logs, SummaryWriter in code | TensorBoard tracking (no dedicated skill yet) | `grep -ri "SummaryWriter\|tensorboard" <project_dir>`, `ls runs/ tb_logs/ 2>/dev/null` |

## Dependency Registry

This is the complete list of domain skills and their external dependencies. The agent uses this registry to determine what to check and install.

| Skill | What it provides | External dependencies | Install commands |
|-------|-----------------|----------------------|-----------------|
| `training-supervisor` | Core monitoring orchestrator | `nvidia-smi` | (pre-installed on GPU machines) |
| `grpo-monitor` | RL metrics, generation quality, phase time | none | — |
| `distributed-monitor` | NCCL diagnostics, process hierarchy, stragglers | none | — |
| `slurm-monitor` | SLURM job state + remote-cluster STOP path | `ssh` to the cluster login host; `~/bin/sjob` and `~/bin/wbcheck` (or equivalents) | (user-installed) |
| `k8s-monitor` | Pod anomalies, scheduling escalation | `kubectl` with cluster access | `curl -LO https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl && chmod +x kubectl && mv kubectl ~/.local/bin/` |
| `wandb-monitor` | Heartbeat stall detection, metric keys, health thresholds | `wandb-primary` skill + `wandb` Python package + authentication | `npx skills add wandb/skills` then `pip install wandb` then `wandb login` |

## Procedure

### 1. Determine Applicable Skills

Using the context signals and any information the user has provided, determine which rows in the Dependency Registry apply. If anything is ambiguous, ask the user using AskUserQuestion.

### 2. Check Dependencies

For each applicable row, check whether its external dependencies are installed. Run the check commands and collect results into three categories:
- **Installed**: dependency is present and working
- **Missing**: dependency is absent but needed
- **Not needed**: dependency is for a skill that does not apply

### 3. Offer Installation

If there are missing dependencies, present them to the user via AskUserQuestion (multi-select). Each option should show the dependency name and its install command. The user selects which ones to install.

For each selected dependency:
- Execute the install command
- Verify it succeeded
- If it fails, report the error and continue

For each skipped dependency:
- Mark the corresponding capability as DEGRADED
- Explain what the user will miss

### 4. Report Capabilities

Present the final state:

```
Monitor Doctor — Setup Complete
================================
Environment: [detected/stated training setup summary]

Skills:
  [OK]  training-supervisor (core)
  [OK/--]  grpo-monitor
  [OK/--]  distributed-monitor
  [OK/--]  k8s-monitor
  [OK/--]  wandb-monitor

Dependencies:
  [OK/MISSING/--] nvidia-smi
  [OK/MISSING/--] kubectl
  [OK/MISSING/--] wandb-primary skill
  [OK/MISSING/--] wandb package
  [OK/MISSING/--] wandb auth

Capabilities:
  [OK/DEGRADED/OFF] [capability] — [reason if not OK]
  ...
================================
```

### 5. Choose Monitoring Mode

Ask the user which monitoring mode to use (AskUserQuestion):

**Team mode (`/supervisor-team`)**:
Each monitoring cycle creates a fresh teammate with clean context. The main agent
only manages lifecycle (create, wait, shutdown). More robust context isolation
but more complex architecture.

**Ralph mode (`/supervisor-ralph`)**:
The main agent executes monitoring directly. Context stays clean via auto-compact
between passes. Simpler architecture, easier user intervention, but requires
auto-compact window configuration.

If the user selects Ralph mode:

1. Check if `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is set in the current session.
   If not, instruct the user to restart Claude Code with:
   ```
   CLAUDE_CODE_AUTO_COMPACT_WINDOW=100000 claude
   ```
   This only affects the current session. Do NOT suggest adding it to shell
   profile -- it would degrade non-monitoring sessions.

2. The PreCompact hook is bundled with this plugin (hooks/hooks.json) and activates
   automatically. No manual hook configuration needed.

### 6. Permissions Overlay (for unattended loops)

If the user selected Q6=Local from supervisor-team, point them at the
permissions template so the cron loop's `claude --print` invocation isn't
blocked by per-call approval prompts:

```
plugins/training-supervisor/templates/permissions.snippet.json
```

The template's `permissions.allow` entries should be merged into the user's
`~/.claude/settings.json`.  Two substitutions are required:

- Replace `<SSH_HOST>` with the cluster login host from supervisor-doctor's
  environment detection (e.g. `u6eo.aip2.isambard`).
- The skill-path entries use `*/training-supervisor/skills/...` glob patterns
  that match the plugin's resolved absolute path without any shell expansion.
  No further substitution is needed for those entries.

Recommend running the `fewer-permission-prompts` skill once the loop has been
running for a session, to catch any additional read-only operations the
supervisor calls that the snippet didn't anticipate.

If the user kept Q6=Cloud (CronCreate), the cloud agent inherits Claude Code
defaults and does not need this overlay.

### 7. Save Profile (optional)

If the project has a `.claude/` directory, offer to save the environment profile:

```json
{
  "training_type": "grpo",
  "infrastructure": "k8s",
  "metric_trackers": ["wandb"],
  "skills_to_load": ["grpo-monitor", "k8s-monitor", "wandb-monitor"],
  "monitoring_mode": "ralph"
}
```

This allows `training-supervisor` to automatically load the right domain skills in future sessions.
