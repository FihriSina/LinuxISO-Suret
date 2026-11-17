from pathlib import Path


def test_display_diagnostic_script_collects_previous_boot_signals():
    script = Path("scripts/collect-display-crash-diagnostics.sh")
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "journalctl -b -1" in text
    assert "out of memory" in text
    assert "kwin" in text
    assert "nvidia" in text


def test_first_iso_does_not_auto_launch_qemu():
    text = Path("scripts/first-iso.sh").read_text(encoding="utf-8")
    assert "test-qemu.sh" in text
    assert '"$BUILD_DIR/test-qemu.sh"' not in text
