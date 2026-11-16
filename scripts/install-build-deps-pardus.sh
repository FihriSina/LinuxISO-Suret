#!/bin/sh
set -eu

REPO_BASE='https://download.opensuse.org/repositories/Virtualization:/Appliances:/Builder/Debian_13'
KEYRING='/etc/apt/keyrings/kiwi-builder.gpg'
SOURCE='/etc/apt/sources.list.d/kiwi-builder.list'

echo '== Linux ISO - Suret build dependencies (Pardus 25) =='
sudo apt update
sudo apt install -y ca-certificates curl gnupg podman qemu-system-x86 qemu-system-gui qemu-utils ovmf uidmap slirp4netns fuse-overlayfs
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL "$REPO_BASE/Release.key" | gpg --dearmor | sudo tee "$KEYRING" >/dev/null
printf 'deb [signed-by=%s] %s/ /\n' "$KEYRING" "$REPO_BASE" | sudo tee "$SOURCE" >/dev/null
sudo apt update
sudo apt install -y python3-kiwi kiwi-systemdeps-boxbuild

echo
echo 'Installed versions:'
podman --version || true
kiwi-ng --version || true
qemu-system-x86_64 --version | head -n 1 || true

echo
echo 'Build host check:'
uv run linux-iso build-doctor
