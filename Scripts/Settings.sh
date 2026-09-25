#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Keep upstream defaults separate from local configuration policy.
set -euo pipefail
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}"
cd "$GITHUB_WORKSPACE/wrt"

bash "$GITHUB_WORKSPACE/Scripts/upstream/Settings.sh"
python3 "$GITHUB_WORKSPACE/Scripts/wr30u-config.py" normalize \
  .config "$GITHUB_WORKSPACE/Config/PRIVATE.txt"
# Resolve dependencies BEFORE checking the actual selected target/packages.
make defconfig
python3 "$GITHUB_WORKSPACE/Scripts/wr30u-config.py" verify \
  .config "$GITHUB_WORKSPACE/Config/PRIVATE.txt"
# WRT-CORE's subsequent defconfig is intentionally idempotent.
