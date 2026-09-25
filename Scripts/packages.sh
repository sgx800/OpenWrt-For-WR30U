#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Add only selected applications. No kernel/DTS/vendor driver modification.
set -euo pipefail
RECIPE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ROOT=$(cd -- "${1:?Usage: packages.sh OPENWRT_ROOT}" && pwd)
[[ -d "$ROOT/package" && -d "$ROOT/feeds/luci" && -d "$ROOT/feeds/packages" ]] || exit 1
STAGE=$(mktemp -d)
trap 'rm -rf -- "$STAGE"' EXIT
mkdir -p "$RECIPE/output"
LOG="$RECIPE/output/extra-package-sources.txt"
: > "$LOG"
python3 "$RECIPE/Scripts/sources.py" plan "$ROOT" > "$STAGE/plan.tsv"
for app in homeproxy autoreboot upnp; do
  [[ -f "$ROOT/feeds/luci/applications/luci-app-$app/Makefile" ]] || {
    echo "Required matching-feed package missing: luci-app-$app" >&2; exit 1;
  }
done
while IFS=$'\t' read -r name repo ref subdir; do
  dest="$STAGE/$name"
  git init -q "$dest"
  git -C "$dest" remote add origin "https://github.com/$repo.git"
  fetched=false
  for attempt in 1 2 3; do
    if git -C "$dest" fetch -q --depth=1 origin "$ref"; then fetched=true; break; fi
    sleep "$attempt"
  done
  "$fetched" || { echo "Cannot fetch $repo at $ref" >&2; exit 1; }
  git -C "$dest" checkout -q --detach FETCH_HEAD
  printf '%s %s %s %s\n' "$name" "$repo" "$ref" "$(git -C "$dest" rev-parse HEAD)" | tee -a "$LOG"
  [[ -f "$dest/$subdir/Makefile" ]] || { echo "Missing package Makefile: $name" >&2; exit 1; }
  # Stage first, then remove exact-name duplicates and stale feed links.
  # Never use substring matching, and never touch the vendor driver tree.
  find "$ROOT/package" "$ROOT/feeds/luci" -mindepth 1 \
    \( -type d -o -type l \) -name "$name" -prune -exec rm -rf -- {} +
  mkdir -p "$ROOT/package/$name"
  cp -a "$dest/$subdir/." "$ROOT/package/$name/"
  rm -rf -- "$ROOT/package/$name/.git"
done < "$STAGE/plan.tsv"
python3 "$RECIPE/Scripts/recipe.py" tailscale "$ROOT"
