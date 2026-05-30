# Phase 2: Collect Evidence

## Goal

Gather all evidence needed for analysis. This phase is delegated to collector sub-agents (dispatch determines how many and whether parallel). The main agent does NOT run evidence collection commands directly.

## Evidence Categories

Each collector is responsible for one category and returns a structured markdown section.

### GPU Collector

```bash
nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,power.draw,power.limit --format=csv,noheader
nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader
```

Return format:
```
## GPU Evidence
| GPU | Util% | Memory Used/Total | Power Draw/Limit | Real Util |
|-----|-------|-------------------|------------------|-----------|
| 0   | ...   | ...               | ...              | ...       |

Processes: [PID, GPU, memory for each]
Anomalies: [any GPU at idle power, memory >95%, unexpected processes]
```

### Log Collector

```bash
tail <log_file>    # recent output -- adjust line count as needed for context
```

Also extract: latest step number, latest metric values, any error/warning messages, timestamps.

Return format:
```
## Log Evidence
Latest step: [N]
Latest metrics: [key=value pairs]
Last log timestamp: [when]
Errors/warnings: [any, or "none"]
Raw tail (last 5 lines):
  [lines]
```

### Process Collector

```bash
ps -p <PID> -o pid,etime,state --no-headers 2>/dev/null || echo "DEAD"
```

For distributed training, also check for torchrun/deepspeed parent processes.

Return format:
```
## Process Evidence
Main process: [PID, state, elapsed time]
Child processes: [list if distributed]
Status: [ALIVE / DEAD / ZOMBIE]
```

### Resource Collector

```bash
df -h <checkpoint_dir>
free -h
```

Return format:
```
## Resource Evidence
Disk: [used/total, % for checkpoint dir]
CPU Memory: [used/total]
Disk projection: [enough room for remaining checkpoints? estimate: current_ckpt_size * remaining_saves]
Memory trend: [growing / stable / N/A if first check]
```

### Domain Collector (conditional)

Only dispatched when the job profile includes domain-specific tools. Load the corresponding skill for collection commands:
- `wandb-monitor`: W&B heartbeat, run status, metric keys
- `k8s-monitor`: pod status, events, scheduling
- `distributed-monitor`: NCCL status, process hierarchy, stragglers

Return format: domain-skill-specific.

## Evidence Bundle

The main agent merges all collector outputs into a single evidence bundle. This is what Phase 3 (Analyze) works with -- not raw command output.

## Notes

- For distributed training, load the `distributed-monitor` skill for multi-process PID management.
- For K8s jobs, load the `k8s-monitor` skill for kubectl-based collection.
- For W&B integration, the `wandb-primary` skill from `wandb/skills` is required. Use `supervisor-doctor` to verify.

## Gate Log Format

Record in `${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}/sessions/<timestamp>/2-collect.md`:
- The merged evidence bundle (all collector outputs)
- Which collectors ran and their status (success/failure)
- Any collection failures (command errors, timeouts)
