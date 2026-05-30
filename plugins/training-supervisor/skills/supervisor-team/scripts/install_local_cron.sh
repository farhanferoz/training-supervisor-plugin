#!/usr/bin/env bash
# install_local_cron.sh — install a local cron entry (or systemd-user timer)
# that runs the supervisor-team dispatch every <frequency>.
# Usage: install_local_cron.sh --frequency <Nm|Nh> --prompt-file <path>
set -euo pipefail

FREQUENCY=""
PROMPT_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --frequency) FREQUENCY="$2"; shift 2 ;;
        --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
        -h|--help) sed -n '2,5p' "$0" >&2; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
[[ -n "$FREQUENCY" && -n "$PROMPT_FILE" ]] || { sed -n '2,5p' "$0" >&2; exit 2; }
[[ -f "$PROMPT_FILE" ]] || { echo "prompt file not found: $PROMPT_FILE" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
DISPATCH="$HERE/cron_dispatch.sh"
chmod +x "$DISPATCH"

# Translate user-friendly frequency to cron syntax.
case "$FREQUENCY" in
    *m) mins="${FREQUENCY%m}";    spec="*/$mins * * * *" ;;
    *h) hours="${FREQUENCY%h}";   spec="0 */$hours * * *" ;;
    *)  echo "unsupported frequency '$FREQUENCY' (use Nm or Nh)" >&2; exit 2 ;;
esac

LINE="$spec $DISPATCH $PROMPT_FILE  # training-supervisor-team"

# Prefer systemd --user timer if available; fall back to crontab.
if command -v systemctl >/dev/null 2>&1 && systemctl --user --version >/dev/null 2>&1; then
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    cat >"$UNIT_DIR/training-supervisor-team.service" <<EOF
[Unit]
Description=training-supervisor-team one-shot dispatch
After=network-online.target
[Service]
Type=oneshot
ExecStart=$DISPATCH $PROMPT_FILE
EOF
    cat >"$UNIT_DIR/training-supervisor-team.timer" <<EOF
[Unit]
Description=training-supervisor-team periodic dispatch
[Timer]
OnBootSec=2min
OnUnitActiveSec=$FREQUENCY
Persistent=false
[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now training-supervisor-team.timer
    echo "Installed systemd-user timer: training-supervisor-team.timer ($FREQUENCY)"
    systemctl --user list-timers training-supervisor-team.timer || true
    exit 0
fi

# Crontab fallback.
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
crontab -l 2>/dev/null | grep -v 'training-supervisor-team' > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab "$TMP"
echo "Installed crontab entry: $LINE"
crontab -l | grep training-supervisor-team
