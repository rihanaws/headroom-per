#!/usr/bin/env bash
# Phase 4: Codex session-resume wrapper.
# Builds a capsule from the knowledge base (or Headroom fallback) and injects
# it as the initial prompt to headroom wrap codex.
# Usage: ./resume-codex.sh [extra codex args...]

set -euo pipefail

CAPSULE_SCRIPT="/Users/rihan/Downloads/rihan-personal-ai/build-capsule.py"
HEADROOM="~/.local/bin/headroom"

capsule=$(python3 "$CAPSULE_SCRIPT" 2>/dev/null) || {
  echo "Warning: build-capsule.py failed (KB may be unreachable and headroom fallback unavailable). Starting Codex without capsule." >&2
  capsule=""
}

if [[ -n "$capsule" ]]; then
  eval "$HEADROOM" wrap codex -- "$capsule" "$@"
else
  eval "$HEADROOM" wrap codex "$@"
fi
