#!/bin/sh
set -eu

OUT=${1:-$HOME/linux-iso-display-diagnostics.txt}
{
  echo 'Linux ISO - Suret display/build diagnostics'
  echo '=========================================== '
  date -Is || true
  echo
  echo '== current memory =='
  free -h 2>/dev/null || true
  echo
  echo '== current swap =='
  swapon --show 2>/dev/null || true
  echo
  echo '== display adapters/drivers =='
  lspci -k 2>/dev/null | grep -A4 -Ei 'VGA|3D|Display' || true
  echo
  echo '== DRM devices =='
  ls -l /dev/dri 2>/dev/null || true
  echo
  echo '== NVIDIA =='
  nvidia-smi 2>/dev/null || true
  echo
  echo '== current boot: kernel graphics events =='
  journalctl -k -b 0 --no-pager 2>/dev/null | grep -Ei 'amdgpu|nvidia|nvrm|xid|drm|gpu|ring|reset|fault|timeout' | tail -n 600 || true
  echo
  echo '== previous boot: kernel graphics events =='
  journalctl -k -b -1 --no-pager 2>/dev/null | grep -Ei 'amdgpu|nvidia|nvrm|xid|drm|gpu|ring|reset|fault|timeout' | tail -n 800 || true
  echo
  echo '== previous boot: OOM / graphics / Plasma / session events =='
  journalctl -b -1 --no-pager 2>/dev/null | grep -Ei 'oom|out of memory|killed process|kwin|plasmashell|kscreenlocker|sddm|nvidia|xid|drm|gpu|hang|segfault|wayland|display' | tail -n 800 || true
  echo
  echo '== previous boot: warnings and errors =='
  journalctl -b -1 -p warning..alert --no-pager 2>/dev/null | tail -n 500 || true
  echo
  echo '== recent boots/shutdowns =='
  last -x 2>/dev/null | head -n 40 || true
} > "$OUT"

echo "Diagnostics saved: $OUT"
