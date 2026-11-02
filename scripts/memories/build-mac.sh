#!/bin/bash
# Build user-facing Mac artifacts only from a freshly fetched, clean origin/main.
set -euo pipefail
cd "$(dirname "$0")/../.."
git fetch origin main
[[ $(git rev-parse HEAD) == "$(git rev-parse origin/main)" ]] || {
  echo "error: check out origin/main before building an installable Mac app" >&2; exit 1;
}
[[ -z $(git status --porcelain) ]] || { echo "error: source tree is not clean" >&2; exit 1; }
destination=${1:?usage: build-mac.sh ABSOLUTE_OUTPUT_DIRECTORY}
[[ $destination == /* ]] || { echo "error: output directory must be absolute" >&2; exit 1; }
umask 077
app="$destination/TV Memories.app"
mkdir -p "$app/Contents/MacOS"
target="$(uname -m)-apple-macos12.0"
/usr/bin/swiftc -O -target "$target" scripts/memories/owner.swift -o "$app/Contents/MacOS/TVMemories"
/usr/bin/swiftc -O -target "$target" scripts/memories/image.swift -o "$destination/memory-image"
cp scripts/memories/Info.plist "$app/Contents/Info.plist"
cp scripts/memories/sync.py "$destination/sync.py"
/usr/bin/plutil -lint "$app/Contents/Info.plist"
/usr/bin/codesign --force --sign - --identifier tv.dumbtv.memories-sync "$app"
/usr/bin/codesign --verify --strict "$app"
git rev-parse HEAD > "$destination/source-commit.txt"
echo "Built fresh main-branch TV Memories artifacts."
