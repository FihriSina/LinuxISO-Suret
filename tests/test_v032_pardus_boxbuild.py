from pathlib import Path
import types


def test_pardus_installer_uses_standalone_kiwi_boxbuild_only():
    text = Path('scripts/install-build-deps-pardus.sh').read_text(encoding='utf-8')
    assert 'kiwi-boxbuild' in text
    assert 'sudo apt install -y kiwi-boxbuild' in text
    install_lines = [line for line in text.splitlines() if line.lstrip().startswith('sudo apt install')]
    assert not any('python3-kiwi' in line for line in install_lines)
    assert 'kiwi-systemdeps-boxbuild' not in text
    assert 'podman info' in text


def test_first_iso_uses_v032_report_names():
    text = Path('scripts/first-iso.sh').read_text(encoding='utf-8')
    assert 'v032.txt' in text
    assert 'v031.txt' not in text


def test_build_doctor_standalone_boxbuild_does_not_require_host_kiwi(monkeypatch):
    import linux_iso.buildenv as env

    monkeypatch.setattr(env, 'parse_os_release', lambda: {'ID': 'pardus', 'PRETTY_NAME': 'Pardus 25'})
    monkeypatch.setattr(env.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(
        env,
        '_tool',
        lambda name: f'/usr/bin/{name}' if name in {'podman', 'kiwi-boxbuild'} else None,
    )
    monkeypatch.setattr(env, '_kvm_accessible', lambda: (True, '/dev/kvm is readable and writable'))
    monkeypatch.setattr(
        env.shutil,
        'disk_usage',
        lambda _: types.SimpleNamespace(total=50 * 1024**3, used=10 * 1024**3, free=40 * 1024**3),
    )

    report = env.build_host_report()
    assert report.ready is True
    assert report.recommended_backend == 'boxbuild'
    assert any('does not require host python3-kiwi' in item for item in report.checks)
    assert any('QEMU is not installed' in item for item in report.warnings)
