# Phase 3: Analyze

## Goal

Answer one question: **is this training still worth running?**

Think like an experienced ML practitioner who just opened the wandb dashboard and is deciding whether to keep paying for GPU time. You are not a rubric-checker. You are a person with judgment.

## CRITICAL: This phase is executed by a FRESH sub-agent

The orchestrator dispatches a fresh sub-agent for this phase. The sub-agent receives:
- Raw metrics data (tier 1 state: numbers and timestamps only)
- Training config summary
- Relevant domain skill (loaded by the orchestrator)
- Evidence bundle from Phase 2

The sub-agent does NOT receive previous decisions, previous qualitative descriptions, or any interpretive context from earlier cycles. This is intentional -- fresh eyes prevent anchoring on previous conclusions.

## Part 1: Qualitative Description

**Do this BEFORE forming any judgment.**

For each key metric in the evidence bundle, describe its trajectory in natural language:

- Use these words: **rising, falling, accelerating, decelerating, plateauing, oscillating, saturating, diverging, stabilizing, collapsing**
- Describe the **shape** of the trajectory, not the numbers
- Describe the **relationships** between metrics: are they moving together? Is one changing while another is flat? Are they diverging?
- Note any **inflection points**: where did the trajectory change character?

```
QUALITATIVE DESCRIPTION:
---
[Metric A]: [shape description -- e.g., "rose steadily, then plateaued"]
[Metric B]: [shape description]
[Metric C]: [shape description]

Relationships: [how metrics relate to each other -- e.g., "B is rising while A is flat, suggesting..."]
Inflection points: [where trajectories changed character]
---
```

**Rules:**
- Do NOT set or reference numerical thresholds
- Do NOT establish a "baseline" number to compare against
- Do NOT derive "criteria" from the training config
- The description should make sense to someone who cannot see the numbers -- only the shapes

## Part 2: Holistic Judgment

Based on your qualitative descriptions, answer these questions:

1. **Progress**: Is the training's key objective still improving? Is the rate of improvement itself changing?
2. **Coherence**: Are the metrics telling a consistent story, or are some improving while others degrade?
3. **Trajectory**: Extrapolating the current trend, where is this heading? More improvement, or diminishing returns?
4. **Cost-benefit**: Given the trajectory, would you invest more compute in this training? What's the realistic upside vs the cost of continuing?

Re-anchor on the training's actual objective (read from config): **what is this training trying to achieve, and is it still making meaningful progress toward that goal?**

## Part 3: Decision

Based on your holistic judgment, choose one:

**CONTINUE**: The training is still making meaningful progress toward its objective. State what progress looks like and why you expect it to continue.

**STOP**: The training has saturated, is degrading, or the remaining potential improvement is not worth the continued investment. State:
- What you observed that led to this conclusion
- What specific action to take (kill process, save checkpoint first, restart with changes, etc.)
- Whether the user should be consulted about next steps (restart? different hyperparameters? different approach?)

There is no middle ground. No "WARNING." No "let's watch for another cycle." If you are unsure, that itself is a signal -- a training that requires careful squinting to determine if it's still improving is probably not improving meaningfully.

## Domain Skills

If the training type matches a domain skill, the orchestrator will have loaded it before dispatching you. Use the domain skill to inform **how you think about the patterns** you observe -- it describes how experienced practitioners read the specific metrics for this training type.

Domain skills are thinking guides, not checklists. If the domain skill's guidance doesn't match what you're seeing, trust your own observation and explain why.

## Cross-Source Validation

When multiple data sources report on the same thing, they should agree. If they disagree, investigate:

| If | Then |
|----|------|
| Log says "training" but GPU is near idle | Process may be waiting, deadlocked, or doing non-GPU work |
| Process appears alive but log timestamp is stale | Possible silent stall or hang |
| Log step count differs from external tracker | Logging delay or sync issue |

When sources disagree, trust the lower-level source. Hardware measurements are more reliable than software reports, which are more reliable than external dashboards.

## General Observations

Regardless of the key metric trajectory, note if:
- Step time has changed noticeably compared to earlier steps
- Any single component is consuming a disproportionate share of step time
- Evaluation is taking a disproportionate amount of wall time relative to training

These are worth noting in your description even if the key metric looks fine.

## Gate Log Format

Record in `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/3-analyze.md`:

### Comparison
- Prediction vs actual (from Phase 1)
- Deviations noted

### Qualitative Description
- The full qualitative description from Part 1
- Metric trajectories in words
- Relationships and inflection points

### Judgment
- Decision: **CONTINUE** or **STOP**
- The reasoning from Part 2 (progress, coherence, trajectory, cost-benefit)
- If STOP: specific action and whether user consultation is needed
- General observations

### Contract Compliance
- Which contract focus areas were addressed
