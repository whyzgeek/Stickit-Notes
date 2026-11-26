#!/usr/bin/env bash
# Creates an empty stickit store for an eval run (used with --scaffold).
set -euo pipefail
export STICKIT_DIR="${STICKIT_DIR:-$PWD/.stickit-eval-store}"
timeout 30 python3 "${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}/bin/stickit" init --no-git
