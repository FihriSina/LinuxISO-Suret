# Linux ISO - Suret v0.6.0

## Android Studio vendor archive resolution

This release closes the next real Pardus 25 Native blocker observed after v0.5.9: `com.google.AndroidStudio` was a genuine Flatpak capture, but its proprietary `extra-data/apply_extra` phase failed in the Pardus 25 remaster chroot with `bwrap: Can't find source path /proc/self/fd/N`.

### Changes

- Adds a strict `google-android-studio` vendor-archive resolver for `com.google.AndroidStudio`.
- Resolves the current official Linux archive through Android Developers metadata; only exact Google-owned download hosts are accepted.
- Pairs the Linux filename with its adjacent published SHA-256 and verifies the downloaded bytes before extraction.
- Rejects absolute/traversal tar paths, escaping symbolic/hard links, device/FIFO entries, and setuid/setgid archive members.
- Installs to `/opt/android-studio`, creates `com.google.AndroidStudio.desktop`, exports an icon when available, and verifies the real executable before success.
- Rewrites only the matching captured Android Studio launcher; unrelated Flatpak desktop entries are not modified.
- Uses `/var/tmp/linux-iso-vendor` for the large temporary archive so the isolated `/run` tmpfs is not consumed; successful installation removes the temporary vendor data.
- Keeps v0.5.9 Code/Signal vendor-APT resolution and all v0.5.8 Flatpak safety gates for any true Flatpaks that remain.
- Adds `Vendor archive` to the acceptance application-plan report.

### Validation

- 228 regression tests pass.
- Python compilation passes.
- Repository and generated Native shell scripts pass `bash -n`.
- Offline `uv lock --check` passes.
- Synthetic Pardus staging verifies Android Studio moves from `flatpaks` to `vendor_archive_apps`, renders no unresolved template tokens, and produces an executable/tested vendor helper.
