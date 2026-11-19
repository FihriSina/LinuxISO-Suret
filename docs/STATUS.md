## v0.3.30 implemented

- Source distribution identity now reaches the live user's visible name (`Pardus Live` for the current source profile).
- Kubuntu and OEM installer desktop entries are masked through higher-priority XDG application overrides before the live Plasma session starts.
- The live environment exposes one source-branded Suret installer desktop/application entry.
- The installed target removes the Suret installer entry while retaining the foreign-installer masks.
- QEMU test windows clearly distinguish LIVE ISO from INSTALLED SYSTEM mode.
- Known source-only desktop convenience launchers can be translated to portable KDE equivalents; `pardus-mycomputer` now opens `dolphin computer:/`.
- v0.3.29 fidelity fixes remain in place.
- Regression suite: 116 tests.
