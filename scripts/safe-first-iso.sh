#!/usr/bin/env bash
set -Eeuo pipefail

PROFILE=${1:-$HOME/linux-iso-profile}
BUILD_DIR=${2:-$HOME/linux-iso-build}
LOCK_COOKIE=""
LOCK_INHIBITED=0

cleanup() {
  if [ "$LOCK_INHIBITED" -eq 1 ] && [ -n "$LOCK_COOKIE" ] && command -v gdbus >/dev/null 2>&1; then
    gdbus call --session \
      --dest org.freedesktop.ScreenSaver \
      --object-path /ScreenSaver \
      --method org.freedesktop.ScreenSaver.UnInhibit \
      "$LOCK_COOKIE" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

if [ -f "$PROFILE/manifest.yaml" ]; then
  FIDELITY_SCHEMA=$(awk '/^[[:space:]]*fidelity_schema:[[:space:]]*/ { print $2; exit }' "$PROFILE/manifest.yaml")
  if ! [[ "$FIDELITY_SCHEMA" =~ ^[0-9]+$ ]] || [ "$FIDELITY_SCHEMA" -lt 11 ]; then
    echo "Profile predates SDDM/slideshow fidelity capture v11: $PROFILE" >&2
    echo "Detected fidelity_schema: ${FIDELITY_SCHEMA:-missing}" >&2
    echo "Re-capture it with: uv run linux-iso scan -o $PROFILE" >&2
    exit 6
  fi
else
  echo "Profile manifest is missing: $PROFILE/manifest.yaml" >&2
  echo "Create it with: uv run linux-iso scan -o $PROFILE" >&2
  exit 6
fi

if command -v gdbus >/dev/null 2>&1; then
  RAW=$(gdbus call --session \
    --dest org.freedesktop.ScreenSaver \
    --object-path /ScreenSaver \
    --method org.freedesktop.ScreenSaver.Inhibit \
    'Linux ISO - Suret' 'ISO build in progress' 2>/dev/null || true)
  LOCK_COOKIE=$(printf '%s\n' "$RAW" | sed -n 's/.*uint32 \([0-9][0-9]*\).*/\1/p')
  if [ -n "$LOCK_COOKIE" ]; then
    LOCK_INHIBITED=1
    echo "Temporary KDE screen-lock inhibitor enabled (cookie $LOCK_COOKIE)."
  else
    echo "Warning: KDE screen-lock inhibitor could not be enabled; continuing without changing persistent settings." >&2
  fi
else
  echo "Warning: gdbus is unavailable; continuing without a KDE screen-lock inhibitor." >&2
fi

export LINUX_ISO_BUILD_BACKEND=${LINUX_ISO_BUILD_BACKEND:-container}
export LINUX_ISO_KEEP_AWAKE=${LINUX_ISO_KEEP_AWAKE:-1}
export LINUX_ISO_MONITOR_RESOURCES=${LINUX_ISO_MONITOR_RESOURCES:-1}

./scripts/first-iso.sh "$PROFILE" "$BUILD_DIR"

echo
printf 'Build finished. QEMU was not started automatically.\n'
RESULT_DIR=${LINUX_ISO_RESULT_DIR:-${BUILD_DIR}-result}
printf 'Final installer test: %s/test-qemu.sh %s install\n' "$BUILD_DIR" "$RESULT_DIR"
