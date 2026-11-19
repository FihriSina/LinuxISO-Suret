#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

PROFILE=${1:-$HOME/linux-iso-profile}
BUILD_DIR=${2:-$HOME/linux-iso-build}
RESULT_DIR=${3:-$HOME/linux-iso-build-result}

command -v uv >/dev/null 2>&1 || { echo 'uv is required' >&2; exit 2; }

printf '== Linux ISO - Suret v0.4.2 batch final acceptance ==\n'
printf 'Profile: %s\nBuild:   %s\nResult:  %s\n\n' "$PROFILE" "$BUILD_DIR" "$RESULT_DIR"

rm -rf "$PROFILE" "$BUILD_DIR" "$RESULT_DIR"

uv sync
printf '\n== Project regression suite ==\n'
uv run pytest -q

uv run linux-iso scan -o "$PROFILE"
uv run linux-iso verify "$PROFILE"
uv run linux-iso audit "$PROFILE"
uv run linux-iso portability "$PROFILE" --recipe ubuntu-26.04-kde

LINUX_ISO_RESULT_DIR="$RESULT_DIR" ./scripts/safe-first-iso.sh "$PROFILE" "$BUILD_DIR"

printf '\nStarting the final installer acceptance VM.\n'
printf 'Install normally. When Calamares says Done/Restart, do not close QEMU.\n'
printf 'The same VM will reboot from the installed disk automatically.\n'
printf 'If anything is still wrong after installed boot, run suret-diagnose once inside the VM and attach the generated archive.\n\n'

exec "$BUILD_DIR/test-qemu.sh" "$RESULT_DIR" install
