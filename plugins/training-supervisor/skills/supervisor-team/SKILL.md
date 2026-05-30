---
name: supervisor-team
description: Cron-based team monitoring loop. Creates a fresh teammate each cycle to run training-supervisor, then shuts it down. Team lead only manages lifecycle.
---

# Monitor Team

Orchestrates a periodic monitoring loop using teammates. Each cycle, the team lead
creates a fresh teammate that executes one monitoring pass (using /training-supervisor),
then terminates. The team lead does not interpret results or make decisions -- all
autonomy belongs to the teammate.

## Execution Model

```
cron trigger -> team lead creates teammate -> teammate runs /training-supervisor once
-> teammate exits -> team lead confirms shutdown -> wait for next trigger
```

Roles:
- **Team lead (you)**: lifecycle only -- create, wait, shutdown. No analysis,
  no reactions to report content.
- **Teammate**: one-shot operator. Runs /training-supervisor skill, then exits.
  Authority and behavior determined by user preferences collected at setup.

## CRITICAL: Team management and teammate creation

### Team reuse rule

You can only lead **one team at a time**. Handle this as follows:

1. **No team exists** → Use **TeamCreate** to create one (e.g., "training-supervisor"),
   then spawn the teammate into it.
2. **A team already exists AND was created by this skill** → **Reuse it.** Spawn
   the new teammate into the existing team by passing `team_name: <existing_team>`
   to the Agent tool. Do NOT refuse, do NOT try to create a second team.
3. **A team already exists but is unrelated** → Follow the user's Q5 preference:
   - If user chose **"Reuse existing team"**: add the teammate to it anyway.
   - If user chose **"Skip the cycle"**: silently skip this monitoring cycle.
   In either case, NEVER refuse or block. Either reuse or skip -- no errors.

### How to create the teammate

You MUST use the **Agent tool** with these parameters:
- `name`: a descriptive name (e.g., "monitor-cycle-1")
- `team_name`: the name of your current team (required for SendMessage/shutdown)
- `mode`: "dontAsk"
- `run_in_background`: true
- `prompt`: the teammate instructions generated in Step 2

This creates a teammate that is addressable via SendMessage for shutdown.

Do NOT use plain subagents, do NOT run the monitoring procedure yourself.
The whole point is delegation: you create a teammate, the teammate does ALL
the work, you only manage its lifecycle.

## Procedure

### Step 1: Collect user preferences

Before setting anything up, ask the user these 5 questions (use AskUserQuestion,
all in one call):

1. **Monitoring target**: What training job(s) should we monitor?
   (e.g., local GPU training, a K8s job, a specific process name or log path)

2. **Work mode**:
   - Fully autonomous -- teammate diagnoses and acts on its own, never asks
     questions. Best when the user is away.
   - Human-in-the-loop -- teammate reports findings and asks for approval
     before making changes. Best when the user is actively working.

3. **Monitoring frequency**: How often should we check?
   (e.g., every 30 minutes, every hour, every 2 hours)

4. **Authority level**:
   - Observe and report only -- no changes to training.
   - Full authority -- teammate may restart, adjust config, kill processes.

5. **Team conflict behavior**: If an unrelated team already exists when a cron
   cycle fires (you can only lead one team at a time), what should happen?
   - **Reuse existing team** -- add the monitoring teammate to whatever team
     is currently active, even if it was created for a different purpose.
     Tradeoff: the teammate runs in a "dirty" context, but monitoring is
     never skipped. Best when uptime matters more than isolation.
   - **Skip the cycle** -- do not spawn a teammate if the current team is
     unrelated. The monitoring cycle is silently dropped. Best when you want
     a clean separation and prefer to miss a check rather than mix contexts.

### Step 2: Generate cron prompt from preferences

Build the teammate instructions based on the user's answers. The prompt MUST
include all of the following:

**From Q1 (target):**
> You are responsible for monitoring [user's description of the training job].

**From Q2 (work mode):**
- If autonomous: "Do not ask the user or team lead any questions. Diagnose and
  act on your own."
- If human-in-the-loop: "When you find issues that require intervention, ask
  the user directly (via AskUserQuestion) for approval before making changes.
  Do not report to the team lead -- it only manages your lifecycle."

**From Q4 (authority):**
- If observe-only: "You may only observe and report. Do not stop, restart, or
  modify any training processes or configuration."
- If full authority: "You have full authority. You may start, stop, or restart
  processes and change training config at your own judgment."

**Always included (one-shot lifecycle):**
> DISPATCH_MODE: team
> Use the /training-supervisor skill.
> You are one step in a periodic monitoring loop controlled by the team lead.
> The team lead creates a fresh instance of you every cycle. Your job is to
> complete one monitoring pass, handle any issues you find, then exit. Do not
> loop, do not wait for the next cycle, do not persist. When done, exit.

**If `slurm-monitor` is in the active domain-skill set**: SKIP the default
GPU / Process / Log collectors and spawn one slurm-monitor collector instead
(see `phases/2-collect.md` → "When `slurm-monitor` is active"). The
`Resource Collector` may still run if a local checkpoint mirror is configured.

### Step 3: Set up cron

Use **CronCreate** to schedule a recurring job at the user's requested frequency
(from Q3). Pick an off-round minute (e.g., :23, :47) to avoid API contention.

The cron prompt tells you (team lead) what to do each cycle. It should contain:
1. Team management instructions based on Q5 preference (see below).
2. The full teammate instructions from Step 2 (embedded verbatim).
3. A reminder to use the Agent tool with `team_name`, `mode: dontAsk`,
   `run_in_background: true`.
4. A reminder to shutdown the teammate when it finishes.

**From Q5 (team conflict behavior) -- include in cron prompt:**
- If user chose "Reuse existing team":
  > If a team already exists, reuse it -- pass its name as team_name to the
  > Agent tool. If no team exists, create one with TeamCreate first. Never
  > refuse or skip a cycle due to an existing team.
- If user chose "Skip the cycle":
  > If a team already exists that was NOT created by this monitoring skill,
  > skip this cycle silently -- do not spawn a teammate. If no team exists,
  > create one with TeamCreate. If the existing team IS the monitoring team,
  > reuse it normally.

Example cron prompt structure:
```
[Team management instruction from Q5]

Create a new teammate using the Agent tool (team_name: <your_team>,
mode: dontAsk, run_in_background: true) with these instructions:

[teammate instructions from Step 2]

When the teammate completes, send it a shutdown request via SendMessage.
```

### Step 4: Trigger first cycle immediately

If no team exists yet, use **TeamCreate** to create one (e.g., "training-supervisor").
Then use the **Agent tool** to spawn the first teammate right away (with
`team_name`, mode dontAsk, run_in_background true, and instructions from Step 2).
Do not wait for the first cron tick.

### Step 5: On teammate completion

When the teammate sends a report, idle notification, or terminated message:
1. Send a shutdown request via **SendMessage** (structured shutdown_request).
2. If no response after 2 attempts, stop retrying -- it will time out.
3. Do not analyze, summarize, or react to the report content.

### Step 6: On next cron trigger

Use the **Agent tool** again to create a brand new teammate with `team_name`
set to your existing team. Do NOT attempt to create a new team -- reuse the
existing one. If the team was deleted between cycles, create a new one first
with TeamCreate. Each monitoring cycle is independent. No state is carried in
context -- cross-session state lives in `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/*.json` (managed
by /training-supervisor inside the teammate).
