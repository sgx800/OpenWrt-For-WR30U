#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Runs from the OpenWrt source root, matching CloseWRT-CI 5398107.
set -euo pipefail
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}"
cd "$GITHUB_WORKSPACE/wrt"
[[ -d package && -d feeds/luci && -d feeds/packages ]] || {
  echo 'Missing source tree or feeds' >&2; exit 1;
}
STAGE=$(mktemp -d)
trap 'rm -rf -- "$STAGE"' EXIT
SOURCE_LOG="$GITHUB_WORKSPACE/wr30u-package-sources.txt"
: > "$SOURCE_LOG"

fetch_source() {
  local repo=$1 ref=$2 dest=$3 attempt
  git init -q "$dest"
  git -C "$dest" remote add origin "https://github.com/$repo.git"
  for attempt in 1 2 3; do
    if git -C "$dest" fetch -q --depth=1 origin "$ref"; then
      git -C "$dest" checkout -q --detach FETCH_HEAD
      printf '%s %s %s\n' "$repo" "$ref" "$(git -C "$dest" rev-parse HEAD)" | tee -a "$SOURCE_LOG"
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
  # Exact names only: do not remove unrelated packages by substring.
  # Remove stale feed symlinks as well as their source directories.
  find ./package ./feeds -mindepth 1 \
    \( -type d -o -type l \) -name "$name" -prune -exec rm -rf -- {} +
  cp -a "$src" "./package/$name"
  rm -rf -- "./package/$name/.git"
}

# HomeProxy and sing-box come from the matching 24.10 feeds.
# The former VIKINGYFY/homeproxy repository is no longer available.
[[ -f feeds/luci/applications/luci-app-homeproxy/Makefile ]] || {
  echo 'HomeProxy is missing from the selected LuCI feed' >&2; exit 1;
}

fetch_source eamonxg/luci-theme-aurora master "$STAGE/aurora"
fetch_source eamonxg/luci-app-aurora-config master "$STAGE/aurora-config"
fetch_source asvow/luci-app-tailscale main "$STAGE/tailscale"
fetch_source tty228/luci-app-wechatpush master "$STAGE/wechatpush"
# Last tree before wolplus was removed/replaced upstream. Do not silently
# substitute wolultra: the user's selected plugin is wolplus.
fetch_source VIKINGYFY/packages e5b318ee58b0a81ce9c59158adabadf4b1f575dd "$STAGE/wolplus"

install_package luci-theme-aurora "$STAGE/aurora"
install_package luci-app-aurora-config "$STAGE/aurora-config"
install_package luci-app-tailscale "$STAGE/tailscale"
install_package luci-app-wechatpush "$STAGE/wechatpush"
install_package luci-app-wolplus "$STAGE/wolplus/luci-app-wolplus"

# asvow supplies these two files. Preserve the daemon and CLI from the feed,
# but avoid duplicate ownership of /etc/init.d/tailscale and its UCI config.
python3 - <<'PY'
from pathlib import Path
import re
p = Path('feeds/packages/net/tailscale/Makefile')
text = p.read_text()
lines = text.splitlines(keepends=True)
conflicts = [line for line in lines if
             re.search(r'\$\(INSTALL_(?:BIN|DATA)\)', line)
             and './files/' in line
             and ('/etc/init.d/tailscale' in line or '/etc/config/tailscale' in line)]
if len(conflicts) != 2:
    raise SystemExit('Tailscale install layout changed: review duplicate-file handling')
for relative in ('etc/init.d/tailscale', 'etc/config/tailscale'):
    if not (Path('package/luci-app-tailscale/root') / relative).is_file():
        raise SystemExit('Custom Tailscale package does not provide ' + relative)
p.write_text(''.join(line for line in lines if line not in conflicts))
print('Tailscale duplicate-file ownership resolved; daemon/CLI retained.')
PY
