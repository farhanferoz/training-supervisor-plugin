#!/usr/bin/env bash
# relaunch_with_fix.sh — propose or autonomously execute a job relaunch
# after a STOP, consulting the fix registry.
#
# Reads the failed job's config from W&B (via rendered.py's _read_run_config),
# looks up applicable fixes for the given failure_class, and writes a
# next_action.sh file with the proposed relaunch command. Under aggressive +
# safe-risk, also EXECUTES next_action.sh. Otherwise the file is left for the
# orchestrator to surface to the user.
#
# Note: anti-loop counter (per fingerprint) is NOT YET IMPLEMENTED — see SKILL.md.
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --wandb-run RUN --failure-class CLASS --authority LEVEL \\
          --ssh-host HOST --relaunch-template TEMPLATE \\
          [--registry PATH] [--state-dir DIR]

Required:
  --wandb-run         W&B run id (fully-qualified entity/project/id, or just
                      id if WANDB_ENTITY + WANDB_PROJECT are exported).
  --failure-class     oom|nccl_timeout|crashed|loss_nan|stagnant
  --authority         paranoid|conservative|balanced|aggressive
  --ssh-host          Cluster login host for the relaunch.
  --relaunch-template Bash command template. Use {HOST} and {OVERRIDES} as
                      placeholders. NO default — every project's relaunch
                      command differs; set this explicitly or via env var
                      \$JOB_MONITOR_RELAUNCH_TEMPLATE. Example for autocast:
                        'ssh {HOST} autocast epd --mode slurm {OVERRIDES}'

Optional:
  --registry          Fix registry path. Default: \$JOB_MONITOR_FIX_REGISTRY,
                      else \$CLAUDE_SKILL_ROOT/fixes/registry.yaml.
  --state-dir         State dir. Default: \$TRAINING_SUPERVISOR_STATE_DIR or
                      ~/.claude-job-monitor.
EOF
}

WANDB_RUN="" FAILURE_CLASS="" AUTHORITY="" SSH_HOST=""
REGISTRY="" STATE_DIR=""
RELAUNCH_TEMPLATE="${JOB_MONITOR_RELAUNCH_TEMPLATE:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --wandb-run) WANDB_RUN="$2"; shift 2 ;;
        --failure-class) FAILURE_CLASS="$2"; shift 2 ;;
        --authority) AUTHORITY="$2"; shift 2 ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        --registry) REGISTRY="$2"; shift 2 ;;
        --state-dir) STATE_DIR="$2"; shift 2 ;;
        --relaunch-template) RELAUNCH_TEMPLATE="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
for v in WANDB_RUN FAILURE_CLASS AUTHORITY SSH_HOST; do
    [[ -n "${!v}" ]] || { echo "missing --${v,,}" >&2; usage >&2; exit 2; }
done
if [[ -z "$RELAUNCH_TEMPLATE" ]]; then
    echo "missing --relaunch-template (no default; set explicitly or via" \
         "\$JOB_MONITOR_RELAUNCH_TEMPLATE — every project's relaunch CLI is" \
         "different)" >&2
    usage >&2
    exit 2
fi

REGISTRY="${REGISTRY:-${JOB_MONITOR_FIX_REGISTRY:-$(dirname "$0")/../fixes/registry.yaml}}"
STATE_DIR="${STATE_DIR:-${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}}"

HERE="$(cd "$(dirname "$0")" && pwd)"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
log_dir="$STATE_DIR/sessions/$ts"
mkdir -p "$log_dir"
next_action="$log_dir/next_action.sh"

# Call the Python helper to select and render the fix.
python "$HERE/rendered.py" \
    --registry "$REGISTRY" \
    --wandb-run "$WANDB_RUN" \
    --failure-class "$FAILURE_CLASS" \
    --authority "$AUTHORITY" \
    --ssh-host "$SSH_HOST" \
    --relaunch-template "$RELAUNCH_TEMPLATE" \
    --next-action "$next_action" \
    --log-dir "$log_dir"
rc=$?

# Under aggressive + a safe fix, rendered.py writes a .autonomous marker
# file; we then execute next_action.sh. Otherwise the file is left for the
# orchestrator to surface via AskUserQuestion.
if [[ -f "$log_dir/.autonomous" && "$rc" -eq 0 ]]; then
    "$next_action" 2>&1 | tee -a "$log_dir/relaunch_output.log"
fi
exit "$rc"
