# Linux ISO - Suret v0.6.3

## Complete KDE appearance convergence

v0.6.3 closes the visual gap observed after the first successful Pardus Native
installation: the target could boot and install correctly while the SDDM greeter
fell back to white, Plasma slideshow state did not resume, and a selected
third-party icon theme rendered fallback icons or an incomplete theme library.

### Exact appearance bundles

- Active KDE appearance packages are copied with safe symlink dependency
  closure. Relative/sibling links used by icon/theme packs such as Tela are
  dereferenced into inert regular files in the profile.
- Links that escape trusted appearance roots are rejected, so a theme cannot
  pull arbitrary personal files into the ISO.
- Active-only mode now also preserves the visible user-installed appearance
  library from KDE Store/XDG locations. Manual unpackaged theme-family entries
  under system roots are retained; distro-owned defaults remain supplied by the
  native Pardus base.
- The active icon theme, color scheme and Plasma theme are re-applied after the
  first Plasma session starts. Global LookAndFeel is deliberately not re-applied
  because it can reset panels/widgets/favorites.

### SDDM first-frame convergence

- Captured SDDM themes may safely dereference sibling assets inside trusted SDDM
  theme roots.
- The Native restore mirrors KDE's SDDM Plasma-settings synchronization by
  copying the captured `kdeglobals`, `plasmarc`, `kcminputrc`, output/font state
  into the dedicated `sddm` account and clearing its stale cache.
- Captured active icon/cursor/Plasma/color assets are promoted to system-readable
  locations needed by the greeter.
- System visual restore runs once during image construction and once again on
  the first real boot before the display manager. The Live marker is volatile
  under `/run`, so it cannot suppress installed-system convergence if the
  installer rewrites SDDM configuration.

### Plasma slideshow convergence

- Fidelity schema 12 stores per-desktop slideshow state: screen mapping,
  `SlidePaths`, current `Image`, interval/order/random settings and other safe
  wallpaper configuration values.
- First-login convergence uses Plasma's DBus scripting API to restore
  `org.kde.slideshow` after the target session exists, so installer/live-session
  containment rewrites cannot silently leave a static wallpaper.
- Captured collection paths remain portable `{{HOME}}` references and are
  validated to contain actual image payloads.

### Profile compatibility

Because older profiles were captured before safe appearance-symlink closure and
per-desktop slideshow runtime metadata, v0.6.3 raises the fidelity schema to 12.
A single fresh `native-acceptance.sh` capture is required. Later failed builds
can continue to use `retry-native-acceptance.sh` without recapturing.

### QA

- 255 regression tests pass before artifact packaging.
- Python compile, shell syntax and offline lock validation pass.
- Generated Native staging renders schema-3 runtime restore metadata containing
  the active icon/color/Plasma themes and slideshow desktop states.
- Generated first-login, pre-login, system-visual and vendor-archive helpers
  compile as standalone Python files.
