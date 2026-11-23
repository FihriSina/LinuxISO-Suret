# Linux ISO - Suret v0.5.7 - Root-owned Native retry cleanup

v0.5.7 fixes retry failures after an interrupted/failed Native remaster leaves root-owned SquashFS/chroot files under the disposable build tree.

## Fixes

- `retry-native-acceptance.sh` and `native-acceptance.sh` no longer attempt a plain user `rm -rf` across a root-owned Native work tree.
- Before any privileged recursive build cleanup, Suret detaches the known chroot pseudo-filesystems under `work/rootfs/{run,sys,proc,dev}` with recursive lazy unmounts.
- Privileged build removal uses `rm --one-file-system` so a stale mount cannot be traversed into another filesystem.
- Custom Native build directories require a user-owned Suret staging marker before cleanup may escalate to `sudo`; the default `~/linux-iso-native-build` path remains directly recoverable for existing v0.5.6 work trees that predate the marker.
- Staged Native projects now contain `.suret-native-project` with a fixed marker value used only as a cleanup trust signal.
- Direct reruns of generated `build-native.sh` also detach stale mounts before resetting the disposable work directory and use one-filesystem cleanup on successful completion.
- Pseudo-filesystem cleanup ignores symlinked `run/sys/proc/dev` paths instead of passing them to privileged `umount`.
- Default profile/build/result paths are canonicalized before safety comparisons.

## Validation

- 206 regression tests pass.
- Python compile checks pass.
- All repository shell scripts pass `bash -n`.
- Generated Native staging scripts pass shell/Python syntax validation.
- The root-owned retry path is exercised with a fake `sudo`/failed unprivileged `rm` regression, including mount-detach ordering.
