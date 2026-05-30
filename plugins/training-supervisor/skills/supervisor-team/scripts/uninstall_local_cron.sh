#!/usr/bin/env bash
# uninstall_local_cron.sh — remove the local cron/timer entries installed
# by install_local_cron.sh for the supervisor-team monitoring loop.
set -euo pipefail

if command -v systemctl >/dev/null 2>&1 && \
   systemctl --user list-timers training-supervisor-team.timer >/dev/null 2>&1; then
    systemctl --user disable --now training-supervisor-team.timer 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/training-supervisor-team.service"
    rm -f "$HOME/.config/systemd/user/training-supervisor-team.timer"
    systemctl --user daemon-reload
    echo "Removed systemd-user timer."
fi

TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
if crontab -l 2>/dev/null | grep -q 'training-supervisor-team'; then
    crontab -l | grep -v 'training-supervisor-team' > "$TMP"
    crontab "$TMP"
    echo "Removed crontab entry."
fi
echo "Done."
