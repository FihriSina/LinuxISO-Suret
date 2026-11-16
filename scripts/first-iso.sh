#!/bin/sh
set -eu

PROFILE=${1:-$HOME/linux-iso-profile}
BUILD_DIR=${2:-$HOME/linux-iso-build}
RECIPE=${LINUX_ISO_RECIPE:-ubuntu-26.04-kde}

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 2
fi

printf '\n== 1/6 project tests ==\n'
uv sync --dev
./scripts/test.sh

printf '\n== 2/6 profile verification ==\n'
uv run linux-iso verify "$PROFILE"

printf '\n== 3/6 portability ==\n'
uv run linux-iso portability "$PROFILE" --recipe "$RECIPE" -o "$HOME/linux-iso-portability-v032.txt"

printf '\n== 4/6 build host ==\n'
if uv run linux-iso build-doctor | tee "$HOME/linux-iso-build-doctor-v032.txt"; then
  HOST_READY=1
else
  HOST_READY=0
fi

printf '\n== 5/6 ISO project staging ==\n'
uv run linux-iso stage-iso "$PROFILE" -o "$BUILD_DIR" --recipe "$RECIPE"

if [ "$HOST_READY" -eq 1 ]; then
  printf '\n== 6/6 ISO build ==\n'
  "$BUILD_DIR/build.sh"
  printf '\nISO build finished. To boot it, run: %s/test-qemu.sh\n' "$BUILD_DIR"
else
  printf '\n== 6/6 ISO build deferred ==\n'
  echo "Build project is ready at: $BUILD_DIR"
  echo "The build host is missing a KIWI/Podman/QEMU requirement."
  echo "On Pardus 25 run: ./scripts/install-build-deps-pardus.sh"
  echo "Then rerun: ./scripts/first-iso.sh \"$PROFILE\" \"$BUILD_DIR\""
fi
