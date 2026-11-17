#!/bin/sh
set -eu

echo '== Linux ISO - Suret build dependencies (Pardus 25) =='

sudo apt update
sudo apt install -y \
  podman uidmap slirp4netns fuse-overlayfs \
  qemu-system-x86 qemu-system-gui qemu-utils ovmf

echo
echo 'Installed versions:'
uv --version || true
podman --version || true
qemu-system-x86_64 --version | head -n 1 || true
if command -v kiwi-boxbuild >/dev/null 2>&1; then
  echo "optional VM fallback: $(kiwi-boxbuild --version 2>/dev/null || echo installed)"
fi

echo
echo 'Rootless Podman check:'
if podman info >/dev/null 2>&1; then
  echo 'podman: OK'
else
  echo 'podman: FAILED (rootless Podman is required)' >&2
  exit 2
fi

echo
echo 'Build host check:'
uv run linux-iso build-doctor
