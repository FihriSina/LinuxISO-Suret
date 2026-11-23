#!/usr/bin/env bash
set -euo pipefail

# System administration tools such as chroot may live in /usr/sbin even when
# an interactive desktop session omits sbin directories from PATH.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

command -v readlink >/dev/null 2>&1 || { echo "readlink is required to normalize Suret paths." >&2; exit 2; }

BASE_ISO=${1:-}
if [[ -z "$BASE_ISO" ]]; then
  echo "Usage: $0 /path/to/base.iso" >&2
  exit 2
fi
BASE_ISO=$(readlink -f "$BASE_ISO")
[[ -f "$BASE_ISO" ]] || { echo "Base ISO not found: $BASE_ISO" >&2; exit 2; }

DEFAULT_PROFILE=$(readlink -m -- "$HOME/linux-iso-profile")
DEFAULT_BUILD=$(readlink -m -- "$HOME/linux-iso-native-build")
DEFAULT_RESULT=$(readlink -m -- "$HOME/linux-iso-native-result")
PROFILE=${LINUX_ISO_PROFILE:-"$DEFAULT_PROFILE"}
BUILD=${LINUX_ISO_NATIVE_BUILD:-"$DEFAULT_BUILD"}
RESULT=${LINUX_ISO_NATIVE_RESULT:-"$DEFAULT_RESULT"}
PROFILE=$(readlink -m -- "$PROFILE")
BUILD=$(readlink -m -- "$BUILD")
RESULT=$(readlink -m -- "$RESULT")

guard_reset_dir() {
  local target=$1
  case "$target" in
    ""|/|/home|/root|/usr|/var|/etc|/opt|/srv|/tmp|/mnt|/media|"${HOME:-/__no_home__}")
      echo "Refusing destructive acceptance path: $target" >&2
      exit 2
      ;;
  esac
}

cleanup_stale_native_mounts() {
  local build=$1
  local rootfs="$build/work/rootfs"
  [[ -d "$rootfs" && ! -L "$rootfs" ]] || return 0

  # A killed/failed chroot can leave rbind/pseudo-filesystems mounted below
  # the old rootfs. Never recursively remove a Native build tree before these
  # known mountpoints have been detached, or sudo rm could cross into host /dev.
  # Also never hand a symlinked pseudo-filesystem path to privileged umount.
  for path in run sys proc dev; do
    [[ -L "$rootfs/$path" ]] && continue
    sudo umount -R -l "$rootfs/$path" >/dev/null 2>&1 || true
  done
  # v0.6.0 makes the chroot root a self bind-mount for Flatpak/bubblewrap.
  sudo umount -l "$rootfs" >/dev/null 2>&1 || true
}

trusted_native_project_marker() {
  local target=$1
  local marker="$target/.suret-native-project"
  [[ -f "$marker" && ! -L "$marker" ]] || return 1
  [[ "$(cat -- "$marker" 2>/dev/null || true)" == "linux-iso-suret-native-project-v1" ]] || return 1
  [[ "$(stat -Lc '%u' -- "$marker" 2>/dev/null || echo -1)" == "$(id -u)" ]]
}

reset_native_dir() {
  local target=$1 role=$2
  local trusted_before=0
  guard_reset_dir "$target"
  [[ -e "$target" || -L "$target" ]] || return 0

  if [[ "$role" == "build" ]]; then
    trusted_native_project_marker "$target" && trusted_before=1 || true
    cleanup_stale_native_mounts "$target"
  fi

  # User-owned acceptance output should normally disappear without sudo.
  # Suppress the expected permission flood from root-owned unsquashfs/chroot
  # files and escalate only for Suret's default build path or a marked staged
  # Native project. Record marker trust before the first rm because that user
  # removal may partially delete the project shell while leaving rootfs behind.
  if rm -rf --one-file-system -- "$target" 2>/dev/null; then
    return 0
  fi

  if [[ "$role" != "build" ]]; then
    echo "Could not reset Native $role path without elevated privileges: $target" >&2
    echo "Refusing privileged removal of a non-build directory." >&2
    exit 2
  fi
  if [[ "$target" != "$DEFAULT_BUILD" && "$trusted_before" != "1" ]]; then
    echo "Refusing privileged removal of custom Native build path without a Suret marker: $target" >&2
    exit 2
  fi

  echo "Removing root-owned stale Native build tree: $target"
  cleanup_stale_native_mounts "$target"
  sudo rm -rf --one-file-system -- "$target"
  [[ ! -e "$target" && ! -L "$target" ]] || {
    echo "Native build path still exists after cleanup; a stale mount may remain: $target" >&2
    exit 2
  }
}

path_within() {
  local child=$1 parent=$2
  [[ "$child" == "$parent" || "$child" == "$parent/"* ]]
}

guard_native_layout() {
  if path_within "$PROFILE" "$BUILD"; then
    echo "Profile must not be inside disposable Native build path: $BUILD" >&2
    exit 2
  fi
  if path_within "$PROFILE" "$RESULT"; then
    echo "Profile must not be inside disposable Native result path: $RESULT" >&2
    exit 2
  fi
  if path_within "$RESULT" "$BUILD"; then
    echo "Native result path must not be inside disposable build path: $BUILD" >&2
    exit 2
  fi
  if path_within "$BUILD" "$RESULT"; then
    echo "Native build path must not be inside disposable result path: $RESULT" >&2
    exit 2
  fi
  return 0
}

phase() {
  printf '\n==> %s\n' "$*"
}

HERE=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$HERE"

echo "== Linux ISO - Suret v0.6.2 Native retry =="
echo "Base ISO: $BASE_ISO"
echo "Profile:  $PROFILE"
echo "Build:    $BUILD"
echo "Result:   $RESULT"

guard_native_layout

command -v uv >/dev/null 2>&1 || { echo "uv is required to run Suret acceptance." >&2; exit 2; }

phase "Checking Native host dependencies"
"$HERE/scripts/bootstrap-native-host.sh"
phase "Synchronizing Python environment"
uv sync --frozen

[[ -f "$PROFILE/manifest.yaml" ]] || {
  echo "Existing profile not found: $PROFILE" >&2
  echo "Run native-acceptance.sh once to create it." >&2
  exit 2
}
phase "Verifying existing profile"
uv run linux-iso verify "$PROFILE"

uv run python - "$PROFILE/manifest.yaml" <<'PYFIDELITY'
import sys
from pathlib import Path
import yaml

data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
restore = data.get("restore") or {}
version = str(restore.get("profile_version") or "").strip()
try:
    fidelity = int(restore.get("fidelity_schema") or 0)
except (TypeError, ValueError):
    fidelity = 0
if version and fidelity < 11:
    raise SystemExit(
        "Existing profile predates SDDM/slideshow fidelity schema 11.\n"
        "Run ./scripts/native-acceptance.sh BASE_ISO once to recapture the source appearance, "
        "then use retry-native-acceptance.sh for later retries."
    )
PYFIDELITY

phase "Resetting previous Native build state"
reset_native_dir "$BUILD" build
reset_native_dir "$RESULT" result
phase "Probing base ISO"
uv run linux-iso probe-iso "$BASE_ISO"
phase "Staging Native remaster"
uv run linux-iso stage-native "$PROFILE" "$BASE_ISO" -o "$BUILD" --result "$RESULT"
phase "Native application plan"
uv run python - "$BUILD/native.json" <<'PYPLAN'
import json
import sys
from pathlib import Path

meta = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for label, key in (("Distro packages", "native_apps"), ("Vendor APT", "vendor_apt_apps"), ("Vendor archive", "vendor_archive_apps"), ("Flatpak", "flatpaks")):
    values = meta.get(key) or []
    print(f"- {label}: {', '.join(values) if values else '(none)'}")
web = meta.get("webapp_bindings") or {}
if web.get("rewritten"):
    browsers = web.get("browsers") or {}
    detail = ", ".join(f"{name}={count}" for name, count in sorted(browsers.items()))
    print(f"- Browser-bound web apps: {web.get('rewritten')} rewritten ({detail or 'browser affinity preserved'})")
visual = meta.get("visual_fidelity") or {}
sddm = visual.get("sddm") or {}
if sddm.get("theme_captured"):
    print(f"- SDDM theme: {sddm.get('source_theme') or 'captured'} ({len(sddm.get('external_assets') or [])} external asset(s))")
slideshow = visual.get("slideshow") or {}
print(f"- Plasma slideshow: {'active' if slideshow.get('active') else 'inactive'} ({len(slideshow.get('paths') or [])} collection path(s))")
PYPLAN
phase "Building Native ISO"
"$BUILD/build-native.sh"
phase "Validating Native ISO in QEMU"
"$BUILD/test-native-qemu.sh" "$RESULT"
phase "Native retry completed successfully"
