#!/usr/bin/env bash
set -euo pipefail

BASE_ISO=${1:-}
if [[ -z "$BASE_ISO" ]]; then
  echo "Usage: $0 /path/to/base.iso" >&2
  exit 2
fi
BASE_ISO=$(readlink -f "$BASE_ISO")
[[ -f "$BASE_ISO" ]] || { echo "Base ISO not found: $BASE_ISO" >&2; exit 2; }

PROFILE=${LINUX_ISO_PROFILE:-"$HOME/linux-iso-profile"}
BUILD=${LINUX_ISO_NATIVE_BUILD:-"$HOME/linux-iso-native-build"}
RESULT=${LINUX_ISO_NATIVE_RESULT:-"$HOME/linux-iso-native-result"}
HERE=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$HERE"

echo "== Linux ISO - Suret v0.5.1 Native retry =="
echo "Base ISO: $BASE_ISO"
echo "Profile:  $PROFILE"
echo "Build:    $BUILD"
echo "Result:   $RESULT"

"$HERE/scripts/bootstrap-native-host.sh"
uv sync

[[ -f "$PROFILE/manifest.yaml" ]] || {
  echo "Existing profile not found: $PROFILE" >&2
  echo "Run native-acceptance.sh once to create it." >&2
  exit 2
}
uv run linux-iso verify "$PROFILE"

rm -rf "$BUILD" "$RESULT"
uv run linux-iso probe-iso "$BASE_ISO"
uv run linux-iso stage-native "$PROFILE" "$BASE_ISO" -o "$BUILD" --result "$RESULT"
"$BUILD/build-native.sh"
"$BUILD/test-native-qemu.sh" "$RESULT"
