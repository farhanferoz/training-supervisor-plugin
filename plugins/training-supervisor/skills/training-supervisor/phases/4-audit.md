# Phase 4: Audit

## Goal

An independent reviewer audits your supervision work for contract compliance, process compliance, and logical coherence. You cannot meaningfully review your own reasoning -- this phase exists because self-review is unreliable.

## What to Send the Reviewer

1. The **contract** from Phase 0 (the agreement on focus and acceptance criteria)
2. Your **gate logs** from Phases 1-3 (predictions, evidence, analysis)
3. Instruction to read `agents/quality-reviewer.md` for the full review checklist

The reviewer checks:
- **Contract compliance**: did you address the focus areas? meet the acceptance criteria?
- **Process compliance**: did you derive criteria from artifacts? state the key indicator and WHY? establish a baseline?
- **Logical coherence**: does your conclusion follow from your stated evidence?
- **Spot-check**: the reviewer independently verifies one claim

Dispatch determines the communication mechanism:
- Ralph mode: reviewer is an existing teammate (Team), multi-round negotiation possible
- Team mode: reviewer is a new sub-agent (Agent tool), single-round

## Handling Reviewer Feedback

If the reviewer sends **APPROVED**: proceed to Phase 5.

If the reviewer sends **REJECTED** with specific feedback:
1. Read the feedback carefully.
2. Re-run the specific checks the reviewer questioned (do not guess or restate old data).
3. Revise your assessment if new evidence warrants it.
4. Resubmit to the reviewer.

Maximum 2 rounds. After 2 rounds, record what remains unverified and proceed.

## Handling Pitfalls

The reviewer may include a `PITFALLS:` section in its response. Each pitfall is tagged `[global]` or `[job-specific]`.

Do NOT write pitfalls to disk in this phase. Collect them and pass to Phase 6 (Persist).

## Gate Log Format

Record in `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/4-audit.md`:
- Reviewer's verdict (APPROVED / REJECTED)
- Contract compliance check results
- What was spot-checked and the result
- If REJECTED: what was revised and why
- If unresolved after 2 rounds: what remains unverified
- Pitfalls extracted by reviewer (if any)
