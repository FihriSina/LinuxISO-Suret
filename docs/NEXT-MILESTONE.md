# Next milestone - v0.3.30 source-native acceptance

1. Re-scan the source desktop and build a clean ISO.
2. Confirm the QEMU title says `Suret - LIVE ISO`.
3. Search Kickoff/KRunner for `install`: no Kubuntu/OEM installer entry may be visible; only the source-branded Suret installer should remain.
4. Confirm the live user is presented as the captured source distribution (`Pardus Live` for the current profile).
5. Confirm the visible `Bilgisayar` desktop launcher opens Dolphin's `computer:/` view without `pardus-mycomputer` errors.
6. Complete Calamares installation, then boot with `installed` mode and confirm the title changes to `Suret - INSTALLED SYSTEM`.
7. Continue full desktop fidelity comparison after these source-identity checks pass.
