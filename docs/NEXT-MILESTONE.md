# Next milestone - v0.6.3 Native Pardus full visual acceptance

The next acceptance run validates the complete visual state now that the Native ISO boots, installs and reaches Plasma successfully.

A **fresh capture is required once** because v0.6.3 uses fidelity schema 12. It adds safe theme symlink closure and per-desktop slideshow runtime metadata that older profiles do not contain.

Run:

```bash
cd ~/Kodlama/LinuxISO-Suret

./scripts/native-acceptance.sh \
  "$HOME/İndirilenler/Pardus-25.2-XFCE-amd64.iso"
```

Before build, confirm the plan reports the actual source state, especially:

```text
- SDDM theme: <source KDE Store theme> (... external asset(s))
- Plasma slideshow: active (... collection path(s), ... desktop state(s))
- Active icon theme: Tela-manjaro-dark
- Active color scheme: <source dark scheme>
- Active Plasma theme: <source theme>
```

Acceptance criteria:

1. SDDM/password screen renders the customized source theme/background, not a white fallback.
2. System Settings opens with the captured dark color scheme when that is the source state.
3. Dolphin/System Settings use the real captured active icon theme rather than fallback grey icons.
4. User-installed theme variants visible on the source (for example Nordic/Tela variants) also appear in the target appearance library when they were user/manual installs.
5. Plasma remains `org.kde.slideshow`, the captured image collection exists, and slides rotate using the captured timing/order/random state.
6. Panels, favorites, desktop launchers, avatar and application fidelity remain intact.
7. ChatGPT and other Brave-bound web apps continue opening in Brave app-window mode.
8. No browser profile, cookies, passwords, tokens, credentials or unrelated personal documents are introduced.

After this passes in both Live and installed-system QEMU boots, further work should move to optional XFCE removal and additional Native distro adapters rather than more first-boot appearance repair.
