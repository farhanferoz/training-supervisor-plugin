# Phase 5: Act

Two sub-phases: troubleshoot (conditional) then execute/strategize.

---

## 5a. Troubleshoot (Conditional)

**Skip if**: decision is CONTINUE with no specific anomalies.
**Trigger if**: decision is STOP, OR specific anomalies or deviations were found in Phases 2-3.

Dispatch a troubleshooter sub-agent for systematic investigation.

### Procedure

#### 1. Observe
State exactly what is wrong, with specifics.
- Bad: "training seems slow"
- Good: "step time doubled compared to the rolling average"

#### 2. Reproduce
Is this consistent or intermittent? Re-run the failing check. Scan earlier logs for the same pattern.

#### 3. Isolate
Narrow down root cause category (check in order):
1. **Hardware**: GPU power, temperature, memory errors
2. **Data**: current batch corrupted, abnormally long, or all padding?
3. **Config**: did any hyperparameter change at this step?
4. **Software**: Python process state, OOM killer, disk full, CUDA errors
5. **Network**: if distributed, check inter-GPU communication

#### 4. Root Cause
Identify root cause(s). If multiple independent issues, report each separately.

#### 5. Recommended Action
Propose a specific action for each root cause. "Investigate further" is not acceptable.

#### 6. Risk Assessment
For each action: what could go wrong? Is it reversible?

### Escalation Protocol

If confidence remains low after investigation: record what was tried, why insufficient, and the one diagnostic step that would most narrow down the cause.

---

## 5b. Execute / Strategize

What happens next depends on the Phase 3 decision.

### If STOP (autonomous)

The monitor has authority to stop training. Execute:

1. **Save**: If a graceful stop mechanism exists (SIGTERM with checkpoint save), use it. Otherwise note the last saved checkpoint.
2. **Kill**: Stop the training process.
3. **Record**: Write the stop reason, the last good checkpoint, and the qualitative assessment to the gate log.
4. **Next steps**: If the Phase 3 sub-agent indicated uncertainty about what to do AFTER stopping (restart with different config? try different approach?), present options to the user via AskUserQuestion. The question is "what should we do next?" -- NOT "should we have stopped?"

**When `slurm-monitor` is active**, "Kill: stop the training process" means
calling `${CLAUDE_SKILL_ROOT}/scripts/scancel_safe.sh` with the configured
authority level. That script refuses to act under `paranoid` and restricts
the allowed `reason_class` set under `conservative`. The authority level
comes from the per-job state's `policy.authority` field; if absent, default
to `conservative`. The script logs every invocation (including refused ones)
into the Phase 5 gate log.

**After `scancel_safe.sh` succeeds AND slurm-monitor is active**, chain
`scripts/relaunch_with_fix.sh` with the same `--authority` and the failure
class from Phase 3. The script writes a `next_action.sh` proposal. Under
`aggressive` + a `safe`-risk fix, it auto-executes; under `balanced` or for
a `proposed` fix, the orchestrator surfaces the proposal via
AskUserQuestion. Under `paranoid` or for `escalate`-class fixes (loss_nan),
the registry returns nothing — surface a plain "STOPped; needs human
review" message.

### If CONTINUE

Lightweight response:

1. **Observations**: Note anything worth watching (resource trends, efficiency suggestions).
2. **Next check**: Set the next check interval based on how fast things are changing. Faster changes warrant sooner checks.
3. **No elaborate hypothesis structure needed** if training is clearly progressing.

### If CONTINUE but with concerns

If the training is progressing but something is suboptimal (inefficiency, resource waste, approaching a limit):

1. **Observations**: Describe the concern qualitatively.
2. **Suggestion**: Propose a specific adjustment if one is clear.
3. **Next check**: Consider a shorter interval to watch the concern.

### Hypotheses (only when needed)

Generate hypotheses only when the situation is genuinely ambiguous and you need the user's input to decide between approaches. When you do:

- Cover different angles (not variations of the same idea)
- For each: what to try, what outcome would confirm it, what outcome would refute it, rough cost
- Present via AskUserQuestion with clear options
- After user chooses, generate a concrete execution plan with success/failure criteria

---

## Gate Log Format

Record in `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/5-act.md`:

### Troubleshoot (if triggered)
- Observation, root cause, recommended action, risk, confidence

### Action Taken
- If STOP: what was stopped, how, last checkpoint, reason
- If CONTINUE: observations, next check timing, any suggestions

### Strategy (if hypotheses generated)
- Why hypotheses were needed
- Options presented
- User's choice
- Execution plan with success/failure criteria
