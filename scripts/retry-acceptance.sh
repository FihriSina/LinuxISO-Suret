#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

PROFILE=${1:-$HOME/linux-iso-profile}
BUILD_DIR=${2:-$HOME/linux-iso-build}
RESULT_DIR=${3:-$HOME/linux-iso-build-result}

command -v uv >/dev/null 2>&1 || { echo 'uv is required' >&2; exit 2; }

echo '== Linux ISO - Suret v0.4.3 fast acceptance retry =='
echo "Reusing validated profile: $PROFILE"

test -f "$PROFILE/manifest.yaml" || { echo "Profile missing: $PROFILE/manifest.yaml" >&2; exit 6; }
uv sync
uv run linux-iso verify "$PROFILE"

rm -rf "$BUILD_DIR" "$RESULT_DIR"
LINUX_ISO_RESULT_DIR="$RESULT_DIR" ./scripts/safe-first-iso.sh "$PROFILE" "$BUILD_DIR"

exec "$BUILD_DIR/test-qemu.sh" "$RESULT_DIR" install
