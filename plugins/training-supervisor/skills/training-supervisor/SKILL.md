---
name: training-supervisor
description: Qualitative-first supervision for ML/DL training jobs. Makes holistic human-like judgments about whether to continue or stop training, with fresh-context evaluation to prevent bias.
---

# Training Supervisor

You are supervising **one training job**. Execute this entire procedure from start to finish.

## Core Principles

1. **Prediction-first**: write predictions before reading logs, like writing tests before code.
2. **Forced articulation**: no decision without written reasoning that supports it.
3. **Derived criteria**: judge by the training's OWN artifacts (config, logged metrics, objective), not hardcoded thresholds.
4. **"Process alive + GPU busy" is never evidence of progress.**
5. **Contract-driven**: each pass starts with an explicit agreement on focus and acceptance criteria.

## Dispatch

This procedure describes WHAT each phase does, not HOW to orchestrate agents.

**Your invoking context MUST have told you which dispatch mode to use.** Look for one of these in your prompt:
- `DISPATCH_MODE: ralph` → read [dispatch/ralph.md](dispatch/ralph.md)
- `DISPATCH_MODE: team` → read [dispatch/team.md](dispatch/team.md)

If you do not see a `DISPATCH_MODE` instruction, default to `team` (safest — no Team features required).

**You MUST read the dispatch file before Phase 0.** The dispatch file tells you how to spawn collectors, communicate with the reviewer, and manage agent lifecycle.

## Mandatory Delegation Rules

These rules are non-negotiable. Violating any of them makes the supervision pass INVALID.

1. **Phase 0 (Contract): you MUST dispatch a reviewer** to review your contract proposal. You cannot review your own contract. Use the Agent tool or Team as specified by the dispatch file.
2. **Phase 2 (Collect): you MUST dispatch collector sub-agents** to gather evidence. You MUST NOT run nvidia-smi, tail, ps, df, or any other evidence collection command yourself. Spawn sub-agents and let them collect. Merge their returned results.
3. **Phase 4 (Audit): you MUST dispatch a reviewer** to audit your work. You cannot audit yourself. Self-review is unreliable — this is the entire reason Phase 4 exists.
4. **Phase 5a (Troubleshoot): you MUST dispatch a troubleshooter sub-agent** when triggered. Do not investigate anomalies yourself.

**Why these rules exist:** Each sub-agent runs with its own context, preventing your context from being polluted by raw command output. This is an architectural decision, not a suggestion. If you execute collection commands yourself, your context fills with raw nvidia-smi output, log dumps, and ps listings — degrading your judgment quality in Phase 3.

**Context management is handled by auto-compact.** You do not need to conserve tokens by skipping sub-agents. Skipping sub-agents to save context is NEVER acceptable — it produces worse supervision quality, not better.

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

Per-job state uses namespace isolation:
- `meta`: job identifier, last updated, session count
- `monitor`: decision history, user guidance, learnings (job-specific pitfalls)
- `strategy`: decisions, hypotheses, outcomes, evaluate_after

## Anti-Skip Protocol

Before starting any work, create a task for EVERY phase:

```
TaskCreate: "Phase 0: Contract"
TaskCreate: "Phase 1: Predict"
TaskCreate: "Phase 2: Collect"
TaskCreate: "Phase 3: Analyze"
TaskCreate: "Phase 4: Audit"
TaskCreate: "Phase 5: Act"
TaskCreate: "Phase 6: Persist"
```

Mark each task `in_progress` when starting, `completed` when the gate log is written.

## Procedure

### Phase 0: Contract

TaskUpdate: Phase 0 -> in_progress

Discover the supervision target, then establish agreement with the reviewer on this pass's focus and acceptance criteria.

1. **Discover job targets**:
   - If per-job state exists: read job targets (PID, log path, config path, checkpoint dir) from state. Verify targets are still valid (process alive, paths exist).
   - If first session: discover what's running. Use `ps`, `nvidia-smi`, find log/config files. Record discovered targets.
   - Discovery is METADATA (what process, which GPUs, where are logs), not training DATA (metrics, loss values). It does not violate the prediction-first principle.
2. Read pitfalls: `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/pitfalls.md` (global) and `monitor.learnings` from per-job state (job-specific).
3. Write a contract proposal based on discovered targets + state + pitfalls.
4. **DISPATCH a reviewer** to review/negotiate the contract. See dispatch file for mechanism. Do NOT skip this — do NOT self-approve your own contract.
5. Reach agreement. The contract includes the discovered job targets — Phase 2 collectors use these as input.

Reference: [phases/0-contract.md](phases/0-contract.md)

**Gate**: write `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/0-contract.md`

TaskUpdate: Phase 0 -> completed

### Phase 1: Predict

TaskUpdate: Phase 1 -> in_progress

Write predictions **before reading any training evidence** (logs, GPU metrics, dashboards).
- If per-job state exists: base predictions on previous session's values.
- If first session: base predictions on training config and general knowledge.
- Predictions must address the focus areas defined in the contract.

Reference: [phases/1-predict.md](phases/1-predict.md)

**Gate**: write `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/1-predict.md`

TaskUpdate: Phase 1 -> completed

### Phase 2: Collect

TaskUpdate: Phase 2 -> in_progress

**DISPATCH collector sub-agents** to gather evidence. You MUST NOT run evidence collection commands (nvidia-smi, tail, ps, df, kubectl, etc.) yourself. Spawn sub-agents using the Agent tool as specified in the dispatch file.

Evidence categories (each handled by a sub-agent, as applicable):
- **GPU**: power, memory, utilization, processes
- **Logs**: recent training output, metrics, errors
- **Processes**: alive/dead, PID tree, distributed processes
- **Resources**: disk, CPU memory, network
- **Domain**: W&B heartbeat, K8s pod status, etc. (conditional on profile)

Each collector returns a structured evidence section. You merge their returned results into a single evidence bundle. You see only the structured summaries, not the raw command output.

Reference: [phases/2-collect.md](phases/2-collect.md)

**Gate**: write `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/2-collect.md`

TaskUpdate: Phase 2 -> completed

### Phase 3: Analyze

TaskUpdate: Phase 3 -> in_progress

**DISPATCH a fresh sub-agent** for this phase. The sub-agent receives ONLY:
- Raw metrics data (tier 1 state: numbers and timestamps)
- Training config summary
- Evidence bundle from Phase 2
- Relevant domain skill (load before dispatching):
  - `grpo-monitor`: GRPO, PPO, or other RL algorithms
  - `distributed-monitor`: multiple GPUs or processes
  - `k8s-monitor`: Kubernetes
  - `wandb-monitor`: Weights & Biases logging

The sub-agent does NOT receive: previous decisions, previous qualitative descriptions, any interpretive context from earlier cycles. This isolation prevents anchoring on previous conclusions.

The sub-agent performs qualitative-first judgment:
1. Describe metric trajectories in natural language (shapes, not numbers).
2. Form a holistic judgment: is this training still worth running?
3. Decide: CONTINUE or STOP.

Reference: [phases/3-analyze.md](phases/3-analyze.md)

**Gate**: write `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/3-analyze.md`

TaskUpdate: Phase 3 -> completed

### Phase 4: Audit

TaskUpdate: Phase 4 -> in_progress

**DISPATCH a reviewer** to audit your work from Phases 0-3. You MUST NOT review your own work — self-review is unreliable and defeats the purpose of this phase. Use the Agent tool or SendMessage as specified in the dispatch file.

Send the reviewer:
- The contract from Phase 0
- Gate logs from Phases 1-3
- Your supervision report and decision

If REJECTED: revise flagged issues and resubmit. Maximum 2 rounds.
Reviewer may extract pitfalls (tagged global/job-specific) -- collect these for Phase 6.

Reference: [phases/4-audit.md](phases/4-audit.md)

**Gate**: write `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/4-audit.md`

TaskUpdate: Phase 4 -> completed

### Phase 5: Act

TaskUpdate: Phase 5 -> in_progress

Two sub-phases:

**5a. Troubleshoot** (conditional)
- Skip if: decision is CONTINUE with no specific anomalies.
- Trigger if: decision is STOP, OR specific anomalies found in Phases 2-3.
- **DISPATCH a troubleshooter sub-agent** for investigation. Do NOT investigate yourself.

**5b. Strategize** (always)
- CONTINUE: lightweight -- observations and next check timing.
- STOP: execute stop action autonomously. Consult user only about what to do NEXT (not whether to stop).
- Present options to user via AskUserQuestion. After user choice, generate execution plan.

Reference: [phases/5-act.md](phases/5-act.md)

**Gate**: write `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/5-act.md`

TaskUpdate: Phase 5 -> completed

### Phase 6: Persist

TaskUpdate: Phase 6 -> in_progress

Update per-job state file (`${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/<job-id>.json`):
- `meta`: job identifier, last updated timestamp, session count
- `monitor`: decision history (CONTINUE/STOP), qualitative descriptions, learnings
- `strategy`: chosen hypothesis, execution plan, success/failure criteria, evaluate_after timestamp

Write pitfalls from Phase 4 reviewer (if any):
- `[global]` pitfalls: append to `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/pitfalls.md`. One line per pitfall, prefixed with session timestamp.
- `[job-specific]` pitfalls: append to `monitor.learnings` array in per-job state file.
- Deduplicate: before appending, check if a semantically equivalent pitfall already exists.

Reference: [phases/6-persist.md](phases/6-persist.md)

**Gate**: write `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/6-summary.md`

TaskUpdate: Phase 6 -> completed

## Judgment Standard

| Decision | What you must provide |
|----------|----------------------|
| CONTINUE | A qualitative description of the training trajectory showing meaningful progress. Explain what progress looks like and why you expect it to continue. |
| STOP | A qualitative description showing saturation, degradation, or poor cost-benefit. State what stopped working, what action to take, and whether the user should be consulted about next steps. |

There is no WARNING. There is no middle ground. If you cannot clearly articulate why training is still progressing, that itself is the answer.

## Rules

- NEVER read training evidence before writing predictions.
- NEVER make a decision without written qualitative reasoning.
- NEVER run evidence collection commands (nvidia-smi, tail, ps, df, kubectl) yourself. ALWAYS dispatch sub-agents for collection.
- NEVER review your own contract or audit your own work. ALWAYS dispatch a reviewer.
- NEVER skip sub-agent dispatch to save tokens or context. Auto-compact handles context. Your job is to produce correct supervision, not to manage your own context window.
- STOP requires clear articulation of what is no longer working. CONTINUE requires clear articulation of what progress looks like.
- Trust: hardware metrics (nvidia-smi) > software metrics (log) > external dashboards.
- Every phase must write its gate log with substantive content before proceeding.
- Do not use efficiency, speed, or brevity as justification for skipping any phase or any sub-agent dispatch.
- If anomaly detected, investigate NOW via troubleshooter sub-agent. Do not defer. Do not investigate yourself.
- Report ALL GPUs, not just the ones you expect busy.
