# Linux ISO - Suret v0.5.5 - Acceptance Guard Fix

v0.5.5 fixes a shell `errexit` regression introduced by the v0.5.4 destructive-path hardening.

## Root cause

`guard_native_layout()` used `path_within ... && { reject; }` checks while the acceptance scripts run with `set -e`. A valid non-overlapping layout makes `path_within` return status 1. Because the final guard expression also became the function's return status, Bash treated the expected false result as a fatal command failure and exited silently immediately after printing the Native `Result:` path.

## Fixes

- Rewrites all Native layout guard checks as explicit `if ...; then ...; fi` blocks.
- Makes successful layout validation return 0 explicitly.
- Applies the fix to both full Native acceptance and profile-preserving Native retry.
- Adds phase markers before host bootstrap, Python sync, profile/probe/staging, build, and QEMU validation so a future stop identifies the exact pipeline stage.
- Adds executable regression coverage proving a valid layout survives `set -e` and an unsafe overlapping layout is still rejected with exit code 2.

All v0.5.4 Native deep-hardening behavior remains in place.

## Validation

- 196/196 regression tests pass.
- Python compile and shell syntax checks pass.
