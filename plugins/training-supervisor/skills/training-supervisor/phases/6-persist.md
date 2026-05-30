# Phase 6: Persist

## Goal

Write all session results to persistent storage. This is the final phase -- after this, the supervision pass is complete.

## Per-Job State (Tiered)

Update `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/jobs/<job-id>.json` using the tiered structure:

```json
{
  "meta": {
    "job_id": "<config_path + model_path>",
    "last_updated": "<ISO timestamp>",
    "session_count": "<N>"
  },
  "tier1_facts": {
    "metrics_history": [
      {
        "timestamp": "<ISO>",
        "step": "<step number>",
        "metrics": {
          "<metric_name>": "<value>",
          "...": "..."
        }
      }
    ],
    "config_summary": "<training type, model, key hyperparameters>",
    "training_type": "<SFT/GRPO/etc.>",
    "job_targets": {
      "pid": "<pid>",
      "gpus": "<list>",
      "config_path": "<path>",
      "log_path": "<path>",
      "checkpoint_dir": "<path>"
    }
  },
  "tier2_interpretations": {
    "previous_decisions": [
      {
        "timestamp": "<ISO>",
        "decision": "<CONTINUE or STOP>",
        "qualitative_description": "<the natural language trajectory description>",
        "reasoning": "<why this decision was made>"
      }
    ],
    "learnings": [
      "<job-specific pitfall 1>",
      "<job-specific pitfall 2>"
    ]
  },
  "strategy": {
    "chosen_action": "<description or null>",
    "execution_plan": "<plan or null>",
    "success_criterion": "<criterion>",
    "failure_criterion": "<criterion>",
    "evaluate_after": "<ISO timestamp>",
    "history": [
      {"timestamp": "...", "action": "...", "outcome": "..."}
    ]
  }
}
```

### Tier Access Rules

| Who | Reads | Writes |
|-----|-------|--------|
| Orchestrator (Phase 0, 5, 6) | All tiers | All tiers |
| Fresh sub-agent (Phase 3) | `meta` + `tier1_facts` ONLY | Nothing (returns judgment to orchestrator) |
| Collector sub-agents (Phase 2) | `tier1_facts.job_targets` | Nothing (returns evidence to orchestrator) |

**CRITICAL**: When dispatching the Phase 3 sub-agent, the orchestrator reads `tier1_facts` and passes it as input. It does NOT pass `tier2_interpretations`. The sub-agent never sees previous decisions.

If the orchestrator needs to provide historical context to the sub-agent (because the sub-agent flagged confusion), it presents `tier2_interpretations` in **third-person framing**:

> "A previous supervision session noted: [qualitative_description]. That session concluded: [decision] because [reasoning]. Does this context change your assessment?"

### What goes where

**tier1_facts** (raw data, no interpretation):
- Append new metrics to `metrics_history` from Phase 2 evidence
- Update `job_targets` if PIDs or paths changed
- Update `config_summary` if config changed

**tier2_interpretations** (judgments, can anchor future agents):
- Append the Phase 3 sub-agent's decision, qualitative description, and reasoning
- Append any job-specific pitfalls from the Phase 4 reviewer

**strategy** (forward-looking plans):
- Record what action was taken or planned
- Set `evaluate_after` for time-based follow-up
- Record outcome of previous strategy if applicable

### What does NOT go in state

- Derived criteria or thresholds (these should never exist)
- Status labels (HEALTHY/WARNING/CRITICAL -- these are gone)
- Numerical baselines or expected values

## Pitfalls

Write pitfalls collected from the Phase 4 reviewer:

### Global pitfalls

Append to `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/pitfalls.md` (create if doesn't exist). One line per pitfall, prefixed with session timestamp. Before appending, check for semantic duplicates.

### Job-specific pitfalls

Append to `tier2_interpretations.learnings` in per-job state.

## Summary Gate Log

Record in `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/6-summary.md`:

```
MONITORING SUMMARY: [job name] -- [timestamp]
---
Decision: [CONTINUE / STOP]
Key observation: [one-sentence qualitative summary]
Contract compliance: [all focus areas addressed? Y/N]

Phases completed: [list]
Reviewer verdict: [APPROVED / REJECTED (resolved) / REJECTED (unresolved)]
Anomalies: [list or "none"]
Action taken: [what was done, or "continue supervision"]

New pitfalls recorded: [count or "none"]
Next evaluation: [evaluate_after timestamp or "N/A"]
---
```
