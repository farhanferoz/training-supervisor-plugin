# Phase 1: Predict

Write predictions for the job based on previous checks and training config. This MUST happen before any evidence collection (tool calls that read training data).

## Prediction Template

```
PREDICTIONS (written before reading any data):
---
[Job Name]
- Running since: [timestamp or duration]
- Expected current step: [N / total] (based on elapsed time and observed step rate)
- Expected step time: [X min] (based on previous steps)
- Expected GPU power: [X W out of Y W TDP] (primary utilization metric)
- Expected GPU memory: [X GB per GPU]
- Expected phase: [init / forward / backward / optimizer / checkpoint / eval / idle]
- Expected key metrics: [loss/reward range based on trend from previous steps]
- Risk factors: [what could go wrong given current state]
- Judgment prediction: [do you expect this training to still be progressing? what trajectory do you expect?]
- Contract focus: [what the contract says to watch for this pass]
---
```

The last two lines are important: predict not just metrics but your judgment -- will you expect to see progress or saturation? This creates a prediction you can compare against your actual holistic assessment in Phase 3.

## GPU Power as Primary Utilization Indicator

nvidia-smi "utilization %" is misleading. It only measures whether any kernel is running, not how hard the GPU is working. A GPU doing token-by-token inference shows 99% utilization but only 80W power (20% of TDP).

**Always use power draw as the primary utilization indicator.**

### Power as a Rough Guide

GPU power draw varies by model and variant. Use the GPU's rated TDP as a reference point:
- **Near TDP**: GPU is doing heavy compute (training backward pass). This is the useful work.
- **Well below TDP**: GPU is doing lighter work (inference/generation) or partially idle. Normal during rollout phases in RL training.
- **Near idle**: No useful work happening.

The ratio of actual power to TDP gives a rough sense of how hard the GPU is working. Look up the specific GPU's TDP if needed.

## Gate Log Format

Record in `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/1-predict.md`:
- All predictions
- Basis for each prediction (previous data, config, or first-session reasoning)
- Contract focus areas addressed
