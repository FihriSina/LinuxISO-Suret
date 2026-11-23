#!/usr/bin/env bash
set -euo pipefail

# System administration tools such as chroot may live in /usr/sbin even when
# an interactive desktop session omits sbin directories from PATH.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

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
  [readlink]=coreutils
  [stat]=coreutils
  [df]=coreutils
  [du]=coreutils
  [tee]=coreutils
  [sort]=coreutils
  [md5sum]=coreutils
  [sha256sum]=coreutils
  [find]=findutils
  [xargs]=findutils
  [awk]=mawk
  [grep]=grep
)

missing_cmds=()
packages=()
for cmd in "${!CMD_PKG[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing_cmds+=("$cmd")
    packages+=("${CMD_PKG[$cmd]}")
  fi
done

have_ovmf_pair() {
  local pair code vars
  for pair in \
    "/usr/share/OVMF/OVMF_CODE_4M.fd|/usr/share/OVMF/OVMF_VARS_4M.fd" \
    "/usr/share/OVMF/OVMF_CODE.fd|/usr/share/OVMF/OVMF_VARS.fd" \
    "/usr/share/ovmf/OVMF.fd|/usr/share/ovmf/OVMF_VARS.fd"
  do
    code=${pair%%|*}
    vars=${pair#*|}
    [[ -f "$code" && -f "$vars" ]] && return 0
  done
  return 1
}

if ! have_ovmf_pair; then
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

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required by Native ISO remaster operations but is not available." >&2
  echo "Install the sudo package (or provide sudo on PATH), then rerun Native acceptance." >&2
  exit 2
fi

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
if ! have_ovmf_pair; then
  failed+=("OVMF CODE/VARS firmware pair")
fi

if (( ${#failed[@]} > 0 )); then
  printf 'Native dependency bootstrap incomplete; still missing:' >&2
  printf ' %s' "${failed[@]}" >&2
  printf '\n' >&2
  exit 2
fi

echo "Native host dependencies: installed and verified"
