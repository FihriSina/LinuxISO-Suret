#!/bin/sh
set -eu

REPO_BASE='https://download.opensuse.org/repositories/Virtualization:/Appliances:/Builder/Debian_13'
KEYRING='/etc/apt/keyrings/kiwi-builder.gpg'
SOURCE='/etc/apt/sources.list.d/kiwi-builder.list'

echo '== Linux ISO - Suret build dependencies (Pardus 25) =='

sudo apt update
sudo apt install -y \
  ca-certificates curl gnupg \
  podman uidmap slirp4netns fuse-overlayfs \
  qemu-system-x86 qemu-system-gui qemu-utils ovmf

sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL "$REPO_BASE/Release.key" | gpg --dearmor | sudo tee "$KEYRING" >/dev/null
printf 'deb [signed-by=%s] %s/ /\n' "$KEYRING" "$REPO_BASE" | sudo tee "$SOURCE" >/dev/null
sudo apt update

# IMPORTANT: use the standalone Rust kiwi-boxbuild package only.
# It runs KIWI inside its runtime container and avoids host-side python3-kiwi
# dependency conflicts on Pardus/Debian derivatives.
sudo apt install -y kiwi-boxbuild

echo
echo 'Installed versions:'
podman --version || true
kiwi-boxbuild --version || true
qemu-system-x86_64 --version | head -n 1 || true

echo
echo 'Rootless Podman check:'
if podman info >/dev/null 2>&1; then
  echo 'podman: OK'
else
  echo 'podman: FAILED (rootless Podman is required for kiwi-boxbuild)' >&2
  exit 2
fi

echo
echo 'Build host check:'
uv run linux-iso build-doctor
