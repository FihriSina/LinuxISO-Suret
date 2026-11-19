# Linux ISO - Suret v0.4.3

## Batch build reliability fix

The v0.4.2 acceptance run reached KIWI bootstrap and then failed before package installation because KIWI tried to download the Ubuntu archive signing key from `https://archive.ubuntu.com/ubuntu/project/ubuntu-archive-keyring.gpg` and received HTTP 403.

### Fixed

- Ubuntu 26.04 repository trust no longer depends on a build-time key download.
- The Ubuntu Archive Automatic Signing Key (2018) is bundled with Suret and staged into every generated KIWI project.
- Repository `<signing>` entries now use `this://keys/ubuntu-archive-key-2018.asc`.
- The bundled key is pinned by SHA-256 and generated `build.sh` checks its integrity before KIWI starts.
- `ubuntu-keyring` is installed during bootstrap so the resulting system has Ubuntu's normal archive key package.
- A regression test asserts that no generated KIWI config contains the former remote key URL.
- Adds `scripts/retry-acceptance.sh` so this exact build-only failure can be retried without recapturing the already-valid profile.

### Security

This does **not** disable APT signature verification and does not use `trusted=yes` or `AllowUnauthenticated`. The same Ubuntu archive signing key is supplied locally as the trust anchor, avoiding only the fragile key-download step.

### Validation

- 141/141 project tests pass.
- The staged key parses as fingerprint `F6ECB3762474EDA9D21B7022871920D1991BC93C`.
- Generated repository entries all reference the local `this://` key.
- Generated shell scripts pass `bash -n`.
- Generated project contains no reference to the old remote key URL.
