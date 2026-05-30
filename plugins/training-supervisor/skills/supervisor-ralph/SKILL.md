---
name: supervisor-ralph
description: Cron-based monitoring loop using main agent directly. Each cycle the main agent executes /training-supervisor itself. Context stays clean via auto-compact with monitoring-aware PreCompact instructions. Simpler alternative to supervisor-team.
---

# Monitor Ralph

Orchestrates a periodic monitoring loop where the main agent directly executes
the training-supervisor skill each cycle. Unlike supervisor-team (which delegates to
teammates), this mode runs everything in the main agent's context. Context
management relies on auto-compact with a PreCompact hook that preserves
monitoring state across compaction boundaries.

## When to Use This vs supervisor-team

| Concern | supervisor-ralph | supervisor-team |
|---------|--------------|--------------|
| Context isolation | Approximate (auto-compact) | Full (fresh teammate) |
| Architecture complexity | Low (no team management) | High (create/shutdown teammates) |
| User intervention | Easy (direct TUI access) | Hard (must enter teammate session) |
| Failure modes | Mid-pass compact (mitigated by gate logs) | Zombie teammates, shutdown failures |

## Prerequisites

Start the Claude Code session with a reduced auto-compact window so compaction
fires frequently, preventing context rot from accumulated passes. 100K keeps
the context lean -- if a pass exceeds this, the PreCompact hook and gate logs
handle mid-pass recovery:

```bash
CLAUDE_CODE_AUTO_COMPACT_WINDOW=100000 claude
```

This only affects the current session. Do NOT set it globally in your shell
profile -- it would degrade the experience for non-monitoring sessions.

The plugin's PreCompact hook (hooks/hooks.json) activates automatically when
the plugin is enabled. No additional hook configuration needed.

## Procedure

### Step 1: Collect user preferences

Ask the user these 4 questions (use AskUserQuestion, all in one call):

1. **Monitoring target**: What training job(s) should we monitor?
   (e.g., local GPU training, a K8s job, a specific process name or log path)

2. **Work mode**:
   - Fully autonomous -- diagnose and act on your own, never ask questions.
   - Human-in-the-loop -- report findings and ask for approval before changes.

3. **Monitoring frequency**: How often should we check?
   (e.g., every 30 minutes, every hour, every 2 hours)

4. **Authority level**:
   - Observe and report only -- no changes to training.
   - Full authority -- may restart, adjust config, kill processes.

### Step 2: Set up cron

Use **CronCreate** to schedule a recurring job at the user's requested frequency
(from Q3). Pick an off-round minute (e.g., :17, :43) to avoid API contention.

The cron prompt tells you (main agent) what to do each cycle. It should contain:
1. The monitoring target from Q1.
2. Work mode instructions from Q2.
3. Authority level from Q4.
4. `DISPATCH_MODE: ralph` and a reminder to use the /training-supervisor skill.

**If `slurm-monitor` is in the active domain-skill set**: SKIP the default
GPU / Process / Log collectors and spawn one slurm-monitor collector instead
(see `phases/2-collect.md` → "When `slurm-monitor` is active"). The
`Resource Collector` may still run if a local checkpoint mirror is configured.

Example cron prompt:
```
You are monitoring [target from Q1].
[Work mode instruction from Q2]
[Authority instruction from Q4]

DISPATCH_MODE: ralph
Use the /training-supervisor skill to execute one complete monitoring pass.
All cross-session state is in ${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/ -- read it first.
When the pass is complete, stop and wait for the next cron trigger.
```

### Step 3: Verify auto-compact configuration

Check that `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is set:

```bash
echo $CLAUDE_CODE_AUTO_COMPACT_WINDOW
```

If not set, inform the user:
> Auto-compact window is not configured. For Ralph mode, set it to at least
> 100000 (100K tokens) to keep context lean:
> `CLAUDE_CODE_AUTO_COMPACT_WINDOW=100000 claude`
> Add this to your shell profile for persistence.

### Step 4: Trigger first cycle immediately

Execute the /training-supervisor skill directly with DISPATCH_MODE: ralph.
Do not wait for the first cron tick. This validates the setup end-to-end.

### Step 5: Ongoing operation

Each cron trigger executes the /training-supervisor skill in your (main agent)
context. Between passes, auto-compact fires and compresses the previous pass
into a recovery-oriented summary (handled by the PreCompact hook).

The monitoring loop is:
```
cron fires -> read job state from ${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/ -> run /training-supervisor
-> gate logs written at each step -> pass completes -> wait for next cron
-> auto-compact fires (between passes) -> summary preserves recovery context
-> next cron fires -> read summary + job state -> run /training-supervisor -> ...
```

If auto-compact fires mid-pass (because the pass exceeded the window):
1. The PreCompact hook ensures the summary preserves which step you were on.
2. After compaction, read the gate logs (${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/) to see
   which steps completed.
3. Check the task list to find in-progress tasks.
4. Resume from where you left off.

## Context Recovery Protocol

After any compaction, before continuing work:

1. Read the compact summary (it is your only context).
2. Read the per-job state file (${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/<job-id>.json).
3. List the current session's gate logs (${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/).
4. Check the task list for in-progress tasks.
5. Resume the monitoring procedure from the appropriate step.
