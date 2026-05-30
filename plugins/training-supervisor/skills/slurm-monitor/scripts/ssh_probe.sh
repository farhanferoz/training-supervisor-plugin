#!/usr/bin/env bash
# ssh_probe.sh — quick reachability check for the cluster login host.
# Used by the doctor + collect.py to surface "cert expired" / "host down" early.
set -euo pipefail
host="${1:?usage: ssh_probe.sh <host>}"
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    "$host" 'true' 2>&1
