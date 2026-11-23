# Linux ISO - Suret v0.6.1

## Brave-bound web app fidelity

v0.6.1 fixes a Native-mode fidelity regression where captured desktop web apps
such as ChatGPT and WhatsApp were normalized to `xdg-open URL`. On a restored
system that meant the target's default browser (for example Zen) opened even
when the source launcher had been installed by Brave.

### What changed

- Native staging now consumes the reversible `X-Suret-Original-Exec-B64`
  metadata already present in older profiles and recovers the browser identity.
- Native Brave PWAs are rewritten to profile-independent app mode:
  `/usr/bin/brave-browser --app=<URL>`.
- Browser profile state, cookies, authentication, history, `--profile-directory`
  and source `--app-id` data are not copied into the ISO.
- Obsolete `StartupWMClass=crx_<app-id>` values are removed when the profile app
  ID is intentionally discarded.
- A source Flatpak Brave launcher stays bound to `com.brave.Browser`; it is not
  silently converted to another browser.
- A native Brave dependency is installed from Brave Software's official Debian
  repository via a code-owned allow-list. The official binary keyring and
  `.sources` descriptor are retained in the installed image for normal updates.
- `brave-browser` is no longer converted to the Flathub fallback when it was an
  APT-managed source application.
- Acceptance output reports how many browser-bound web-app launchers were
  rewritten, so fidelity is visible before the expensive ISO build begins.

### Compatibility

Existing v0.6.0 and earlier profiles do not need to be recaptured. The browser
identity is recovered from Suret's reversible launcher metadata during Native
staging.

### Security boundary

The implementation accepts only HTTP(S) URLs without embedded credentials and
only code-owned browser identities. Arbitrary profile commands are never
re-emitted. Brave profile directories remain excluded by the existing sensitive
path policy.
