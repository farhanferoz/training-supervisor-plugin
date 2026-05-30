# Progress-Check Collector Contract

A **collector** is a CLI program that takes job-identity arguments and emits
a structured markdown bundle describing the job's current state, progress,
and heartbeat. The slurm-monitor skill ships `scripts/collect.py` as the
default (wraps `~/bin/wbcheck` + `~/bin/sjob` + `heartbeat_baseline.py`),
but any program matching this contract can replace it.

**Use case:** Drop in a TensorBoard scraper, MLflow client, or custom JSON
log reader without modifying the skill.

## How to plug in a custom collector

Set the `JOB_MONITOR_COLLECTOR` environment variable to the absolute path of
your script (in `~/.claude/settings.json` env block, your shell rc, or
supervisor-doctor's profile yaml):

```bash
export JOB_MONITOR_COLLECTOR=/home/me/bin/my-collector.sh
```

The skill's dispatch then invokes `$JOB_MONITOR_COLLECTOR` with the standard
args (below). If unset, the default `collect.py` is used.

## Input arguments (all required unless noted)

```
--job-id <STR>             Scheduler-specific job identifier (e.g. SLURM jobid).
--run-id <STR>             Metric-tracker run identifier (e.g. W&B run id).
--ref-run <STR|empty>      Reference run for matched-epoch comparison; "" if none.
--ssh-host <STR|empty>     Cluster login host for remote scheduler queries; "" if local.
--epochs <CSV>             Comma-separated epoch ladder (e.g. 0,5,10,20,40).
--aggressiveness <PROFILE> One of paranoid|conservative|balanced|aggressive.
                           Used by the collector's heartbeat-verdict subcall.
--since <ISO|empty>        Wall-clock cutoff for incremental signal; "" if first cycle.
```

## Required output sections (markdown to stdout)

Every collector MUST emit these four top-level sections in this order. Extra
sections are allowed at the end. All field values are markdown — code blocks
welcome for tabular content. The header MUST include a contract-version
marker so the supervisor can detect collectors written against an older
contract after a future bump.

```markdown
# collector evidence — <job_id> / <run_id>
> contract: v1

> If reachability failed (cluster unreachable, run not found, etc.), prefix
> the body with: `> **PARTIAL** — <one-line reason>`

## job state
- state: RUNNING|PENDING|FAILED|COMPLETED|UNKNOWN
- elapsed: <duration string, e.g. "13h47m">
- timelimit: <duration string or "unknown">
- reachable: true|false

## progress
- last_step: <int or "unknown">
- trajectory:
```
<matched-epoch markdown table, columns = epochs, rows = run-and-metric,
 grouped by family with subheaders [loss], [accuracy], [calibration],
 [health], [other]. wbcheck's output format is the reference shape.>
```

## heartbeat
- verdict: OK|STALE|WARMUP|INSUFFICIENT_HISTORY|TERMINAL
- baseline_s: <float>
- threshold_s: <float>
- gap_now_s: <float>

Verdict glossary:
- **OK** — heartbeat gap is within the adaptive threshold; run appears healthy.
- **STALE** — gap exceeds K × baseline; run may be hung or crashed.
- **WARMUP** — run is within the 5-minute warm-up window; check is suspended.
- **INSUFFICIENT_HISTORY** — fewer than ~5 history rows; no reliable baseline.
- **TERMINAL** — the run has reached a final state (finished/crashed/failed/
  completed). Treat as CONTINUE — no STOP action is needed since the run is
  no longer active.

## run state
- run: running|finished|crashed|failed
```

## Exit codes

- `0` — collector ran successfully (regardless of job health).
- non-zero — collector itself errored (e.g., dependencies missing, network
  failure for the collector's own infrastructure). The orchestrator treats
  this as a Phase 2 partial failure and proceeds with a degraded bundle.

## Validation

Run `scripts/validate_collector.sh <your-collector>` to check your CLI emits
all required sections. (Future ticket — for now, eyeball against the example
output of the default `collect.py`.)
