#!/usr/bin/env bash
# cron_dispatch.sh — one-shot dispatch entrypoint for the local-cron path.
# Invoked by cron or by the systemd-user timer; runs `claude --print` with
# the supervisor-team teammate prompt and logs output to the state dir.
set -euo pipefail

PROMPT_FILE="${1:?usage: cron_dispatch.sh <prompt_file>}"
STATE_DIR="${TRAINING_SUPERVISOR_STATE_DIR:-$HOME/.claude-job-monitor}"

# Skip if the system just woke up (uptime < 60 s) — missed cycles are not
# retroactively fired. /proc/uptime is Linux-only; on other OSes (macOS etc.)
# the wake-skip is disabled (uptime check returns 999999 → never skipped).
if [[ -r /proc/uptime ]]; then
    uptime_s="$(awk '{ print int($1) }' /proc/uptime)"
else
    uptime_s=999999
fi
if [[ "$uptime_s" -lt 60 ]]; then
    echo "cron_dispatch: uptime ${uptime_s}s < 60s; skipping post-wake cycle"
    exit 0
fi

ts="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="$STATE_DIR/sessions/$ts"
mkdir -p "$out_dir"

# CCAGE_DISABLE bypasses the ccage per-project wrapper; the cron entrypoint
# always wants the default global config dir.
rc=0
CCAGE_DISABLE=1 claude --print --output-format=text < "$PROMPT_FILE" \
    >"$out_dir/cron_output.log" 2>&1 || rc=$?

if [[ $rc -ne 0 ]]; then
    echo "cron_dispatch: claude --print exited rc=${rc}; log -> $out_dir/cron_output.log"
else
    echo "cron_dispatch: log -> $out_dir/cron_output.log (rc=0)"
fi
exit "${rc}"
