from pathlib import Path


def test_pardus_build_dependency_installer_exists():
    script = Path('scripts/install-build-deps-pardus.sh')
    assert script.is_file()
    text = script.read_text(encoding='utf-8')
    assert 'Virtualization:/Appliances:/Builder/Debian_13' in text
    assert 'podman' in text
    assert 'qemu-system-x86' in text
    assert 'python3-kiwi' in text
    assert 'kiwi-systemdeps-boxbuild' in text


def test_first_iso_points_to_pardus_installer():
    text = Path('scripts/first-iso.sh').read_text(encoding='utf-8')
    assert 'install-build-deps-pardus.sh' in text
    assert 'v031' in text
