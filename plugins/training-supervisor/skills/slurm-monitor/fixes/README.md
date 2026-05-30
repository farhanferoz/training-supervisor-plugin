# Known-Fixes Registry

Data file describing safe, well-known fixes the supervisor can apply when a
job fails with a specific `failure_class`. Driven by `relaunch_with_fix.sh`.

## Schema

```yaml
version: 1
fixes:
  <failure_class>:
    - id: <unique_fix_id>            # used in the anti-loop fingerprint
      description: <one-line text>   # shown to the user if proposed
      risk: safe | proposed | escalate
      requires: [<jinja-style condition>, ...]   # optional; ALL must hold to apply
      hydra_overrides:                            # passed verbatim to relaunch
        - "<hydra_override_with_{{ template }}>"
        - ...
```

## Risk levels

- **safe** — apply autonomously under `aggressive` authority. Propose (via
  AskUserQuestion) under `balanced`. Refuse under `paranoid` /
  `conservative`.
- **proposed** — never autonomous. Surface via AskUserQuestion under
  `balanced` / `aggressive`. Refuse under `paranoid` / `conservative`.
- **escalate** — no auto-fix. Always surface to the user with the
  description as the prompt.

## Template substitution

The `hydra_overrides` field supports `{{ ... }}` substitutions filled in by
`relaunch_with_fix.sh`. Variables are pulled from the previous run's
config (via `wandb.Api().run().config`):

- `batch_size`    — `datamodule.batch_size` (or `batch_size`, `data.batch_size`)
- `accumulate`    — `trainer.accumulate_grad_batches` (default 1)
- `lr`            — `optimizer.lr` (default unset)
- `current_min_lr_ratio` — `optimizer.min_lr_ratio` (default 0)

Substitutions are evaluated as Python expressions inside the braces. Keep
them simple — arithmetic only, no function calls or imports.

## Overriding the default registry

Point `JOB_MONITOR_FIX_REGISTRY` at your own copy:

```bash
export JOB_MONITOR_FIX_REGISTRY=/path/to/my-project-fixes.yaml
```

Or set it in supervisor-doctor's profile under `.claude/`.

## Anti-loop interaction

> **NOT YET IMPLEMENTED.** See `slurm-monitor/SKILL.md` → Anti-Loop Protocol (deferred).
