#!/usr/bin/env bash
set -euo pipefail

# Bootstrap the host-side tools used by Native ISO Mode.
# This script is intentionally distro-conservative: it auto-installs only on
# apt-based hosts (Pardus/Debian/Ubuntu family). Other hosts get an exact list.

declare -A CMD_PKG=(
  [xorriso]=xorriso
  [unsquashfs]=squashfs-tools
  [mksquashfs]=squashfs-tools
  [rsync]=rsync
  [chroot]=coreutils
  [mount]=mount
  [umount]=mount
  [qemu-system-x86_64]=qemu-system-x86
  [qemu-img]=qemu-utils
)

missing_cmds=()
packages=()
for cmd in "${!CMD_PKG[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing_cmds+=("$cmd")
    packages+=("${CMD_PKG[$cmd]}")
  fi
done

need_ovmf=0
for f in \
  /usr/share/OVMF/OVMF_CODE_4M.fd \
  /usr/share/OVMF/OVMF_CODE.fd \
  /usr/share/ovmf/OVMF.fd
  do
  if [[ -f "$f" ]]; then
    need_ovmf=1
    break
  fi
done
if (( need_ovmf == 0 )); then
  packages+=(ovmf)
fi

# Deduplicate while keeping stable order.
unique_packages=()
declare -A seen=()
for pkg in "${packages[@]}"; do
  if [[ -z "${seen[$pkg]:-}" ]]; then
    unique_packages+=("$pkg")
    seen[$pkg]=1
  fi
done

if (( ${#unique_packages[@]} == 0 )); then
  echo "Native host dependencies: OK"
  exit 0
fi

echo "Native host dependencies are incomplete."
if (( ${#missing_cmds[@]} > 0 )); then
  printf 'Missing commands:'
  printf ' %s' "${missing_cmds[@]}"
  printf '\n'
fi
printf 'Packages to install:'
printf ' %s' "${unique_packages[@]}"
printf '\n'

if ! command -v apt-get >/dev/null 2>&1; then
  echo "Automatic dependency bootstrap currently supports apt-based hosts only." >&2
  echo "Install the packages above, then rerun native acceptance." >&2
  exit 2
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required to install missing Native ISO host dependencies." >&2
  exit 2
fi

echo "Installing missing Native ISO host dependencies..."
sudo -v
# Prefer the existing APT metadata for speed. Refresh only when the first
# install attempt cannot resolve/install the requested packages.
if ! sudo apt-get install -y --no-install-recommends "${unique_packages[@]}"; then
  echo "Initial install attempt failed; refreshing APT metadata and retrying..."
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends "${unique_packages[@]}"
fi

# Verify everything used by the full remaster + QEMU path, not just xorriso.
failed=()
for cmd in "${!CMD_PKG[@]}"; do
  command -v "$cmd" >/dev/null 2>&1 || failed+=("$cmd")
done
ovmf_ok=0
for f in \
  /usr/share/OVMF/OVMF_CODE_4M.fd \
  /usr/share/OVMF/OVMF_CODE.fd \
  /usr/share/ovmf/OVMF.fd
  do
  [[ -f "$f" ]] && ovmf_ok=1 && break
done
if (( ovmf_ok == 0 )); then
  failed+=("OVMF firmware")
fi

if (( ${#failed[@]} > 0 )); then
  printf 'Native dependency bootstrap incomplete; still missing:' >&2
  printf ' %s' "${failed[@]}" >&2
  printf '\n' >&2
  exit 2
fi

echo "Native host dependencies: installed and verified"
