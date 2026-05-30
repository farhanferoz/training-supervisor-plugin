#!/usr/bin/env bash
# scancel_safe.sh — Phase 5 STOP path for slurm-monitor.
#
# Gated by authority level. Records every action to the gate log. Refuses to
# act under paranoid; restricts under conservative. Used by the supervisor's
# Phase 5 only when Phase 3 has returned STOP.
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --job-id N --ssh-host HOST --reason "TEXT" --authority LEVEL [--reason-class CLASS]

Required:
  --job-id N         SLURM job id to cancel.
  --ssh-host HOST    Cluster login host.
  --reason "TEXT"    One-line stop reason for the audit log.
  --authority LEVEL  paranoid | conservative | balanced | aggressive

Optional:
  --reason-class C   One of: loss_nan, nccl_hang, crashed, stagnant, other.
                     Required when LEVEL=conservative. Defaults to "other".
  --state-dir DIR    Defaults to \$TRAINING_SUPERVISOR_STATE_DIR or ~/.claude-job-monitor.
  --dry-run          Print the command that would run; do not execute.
EOF
}

JOB_ID="" SSH_HOST="" REASON="" AUTHORITY="" REASON_CLASS="other"
STATE_DIR="${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}"
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --job-id) JOB_ID="$2"; shift 2 ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        --reason) REASON="$2"; shift 2 ;;
        --authority) AUTHORITY="$2"; shift 2 ;;
        --reason-class) REASON_CLASS="$2"; shift 2 ;;
        --state-dir) STATE_DIR="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
    esac
done

for v in JOB_ID SSH_HOST REASON AUTHORITY; do
    [[ -n "${!v}" ]] || { echo "missing --${v,,}" >&2; exit 2; }
done

case "$AUTHORITY" in
    paranoid)
        echo "scancel_safe: REFUSED (authority=paranoid) job=$JOB_ID reason=$REASON" >&2
        exit 3 ;;
    conservative)
        case "$REASON_CLASS" in
            loss_nan|nccl_hang|crashed) ;;
            *)
                echo "scancel_safe: REFUSED (authority=conservative, reason_class=$REASON_CLASS not in allowed set) job=$JOB_ID" >&2
                exit 3 ;;
        esac ;;
    balanced|aggressive) ;;
    *) echo "scancel_safe: unknown authority '$AUTHORITY'" >&2; exit 2 ;;
esac

ts="$(date -u +%Y%m%dT%H%M%SZ)"
log_dir="$STATE_DIR/sessions/$ts"
mkdir -p "$log_dir"
log_path="$log_dir/5-act.md"

cmd=(ssh "$SSH_HOST" scancel "$JOB_ID")
if [[ "$DRY_RUN" -eq 1 ]]; then
    rc=0
    out="(dry-run — would have executed: ${cmd[*]})"
else
    out="$("${cmd[@]}" 2>&1 || true)"
    rc=$?
fi

cat >>"$log_path" <<EOF
## scancel_safe.sh — $(date -u +%Y-%m-%dT%H:%M:%SZ)

- job_id: $JOB_ID
- ssh_host: $SSH_HOST
- reason_class: $REASON_CLASS
- authority: $AUTHORITY
- reason: $REASON
- command: ${cmd[*]}
- exit_status: $rc
- stdout/stderr:
\`\`\`
$out
\`\`\`
EOF

echo "scancel_safe: logged to $log_path (rc=$rc)"
exit "$rc"
