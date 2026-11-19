# Next milestone - v0.3.27 full visible-state fidelity validation

Re-scan the Pardus source with fidelity schema v5, build and install the ISO, then compare the installed QEMU desktop against the source for:

- current wallpaper / slideshow initial image
- panel and widget layout
- pinned task-manager launchers and their icons
- Kickoff favorites and exact ordering
- user avatar
- icon, cursor, Plasma, GTK and window-decoration themes
- KWin rules, shortcuts, locale and power-management behavior
- optional installer applications: all selected by default, with opt-out checkboxes

After the installed QCOW2 matches the source visually, continue with functional launcher/package mapping for any Pardus-only favorites that do not have an Ubuntu/Kubuntu equivalent.
