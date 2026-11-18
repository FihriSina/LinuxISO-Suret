from __future__ import annotations

from linux_iso.builder.kiwi import UBUNTU_2604_KDE


def test_v0318_rsync_is_explicit_in_image():
    assert "rsync" in UBUNTU_2604_KDE.image_packages
