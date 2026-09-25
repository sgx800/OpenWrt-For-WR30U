#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Only add the selected external applications; no driver/kernel/source hacks.
set -euo pipefail
RECIPE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ROOT=$(cd -- "${1:?Usage: packages.sh OPENWRT_ROOT}" && pwd)
cd "$ROOT"
[[ -d package && -d feeds/luci && -d feeds/packages ]] || exit 1
STAGE=$(mktemp -d)
trap 'rm -rf -- "$STAGE"' EXIT
mkdir -p "$RECIPE/output"
LOG="$RECIPE/output/extra-package-sources.txt"
: > "$LOG"
fetch_source() {
  local repo=$1 ref=$2 dest=$3 attempt
  git init -q "$dest"
  git -C "$dest" remote add origin "https://github.com/$repo.git"
  for attempt in 1 2 3; do
    if git -C "$dest" fetch -q --depth=1 origin "$ref"; then
      git -C "$dest" checkout -q --detach FETCH_HEAD
      printf '%s %s %s\n' "$repo" "$ref" "$(git -C "$dest" rev-parse HEAD)" | tee -a "$LOG"
      return 0
    fi
    sleep "$attempt"
  done
  echo "Cannot fetch $repo at $ref" >&2
  return 1
}
install_package() {
  local name=$1 src=$2
  [[ -f "$src/Makefile" ]] || { echo "Missing Makefile: $src" >&2; return 1; }
  find ./package ./feeds/luci -mindepth 1 \
    \( -type d -o -type l \) -name "$name" -prune -exec rm -rf -- {} +
  cp -a "$src" "./package/$name"
  rm -rf -- "./package/$name/.git"
}
# HomeProxy, sing-box, autoreboot and UPnP stay on the source's native feeds.
for name in homeproxy autoreboot upnp; do
  [[ -f "feeds/luci/applications/luci-app-$name/Makefile" ]] || {
    echo "Required native feed package missing: luci-app-$name" >&2; exit 1;
  }
done
fetch_source eamonxg/luci-theme-aurora master "$STAGE/aurora"
fetch_source eamonxg/luci-app-aurora-config master "$STAGE/aurora-config"
fetch_source asvow/luci-app-tailscale main "$STAGE/tailscale"
fetch_source tty228/luci-app-wechatpush master "$STAGE/wechatpush"
# Preserve WOLPlus, not its replacement WOLUltra.
fetch_source VIKINGYFY/packages e5b318ee58b0a81ce9c59158adabadf4b1f575dd "$STAGE/wolplus"
install_package luci-theme-aurora "$STAGE/aurora"
install_package luci-app-aurora-config "$STAGE/aurora-config"
install_package luci-app-tailscale "$STAGE/tailscale"
install_package luci-app-wechatpush "$STAGE/wechatpush"
install_package luci-app-wolplus "$STAGE/wolplus/luci-app-wolplus"
python3 "$RECIPE/Scripts/native.py" tailscale "$ROOT"
