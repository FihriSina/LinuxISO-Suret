from pathlib import Path


def test_safe_first_iso_uses_transient_screensaver_inhibitor():
    text = Path("scripts/safe-first-iso.sh").read_text(encoding="utf-8")
    assert "org.freedesktop.ScreenSaver.Inhibit" in text
    assert "org.freedesktop.ScreenSaver.UnInhibit" in text
    assert "trap cleanup EXIT INT TERM" in text
    assert "kwriteconfig" not in text
    assert "kscreenlockerrc" not in text


def test_safe_first_iso_does_not_start_qemu():
    text = Path("scripts/safe-first-iso.sh").read_text(encoding="utf-8")
    assert "test-qemu.sh" in text
    assert '"$BUILD_DIR/test-qemu.sh"' not in text


def test_diagnostics_include_kernel_graphics_events():
    text = Path("scripts/collect-display-crash-diagnostics.sh").read_text(encoding="utf-8")
    assert "journalctl -k -b 0" in text
    assert "journalctl -k -b -1" in text
    assert "amdgpu" in text
    assert "nvrm" in text
    assert "xid" in text
