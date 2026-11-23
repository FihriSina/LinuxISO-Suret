from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from linux_iso import __version__
from linux_iso.builder import native


def _extract_function(script: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n(?P<body>.*?\n)\}}\n", script, flags=re.MULTILINE | re.DOTALL)
    assert match, f"missing shell function: {name}"
    return f"{name}() {{\n{match.group('body')}}}\n"


def test_v056_version_and_acceptance_banners_are_bumped():
    assert __version__ == "0.6.5"
    assert "v0.6.5 Native ISO acceptance" in Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")
    assert "v0.6.5 Native retry" in Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")


def test_v056_native_apt_uses_isolated_build_sources_not_live_media():
    text = native.NATIVE_INSTALL_SCRIPT
    assert "configure_native_build_apt()" in text
    assert "Dir::Etc::sourcelist=$APT_BUILD_SOURCES" in text
    assert "Dir::Etc::sourceparts=$sourceparts" in text
    assert "Dir::State::lists=$lists" in text
    assert "Acquire::Languages=none" in text
    assert "Contents-deb::DefaultEnabled=false" in text
    assert "deb http://depo.pardus.org.tr/pardus yirmibes " in text
    assert "deb http://depo.pardus.org.tr/pardus yirmibes-deb " in text
    assert "deb http://depo.pardus.org.tr/guvenlik yirmibes-deb " in text
    assert "ensure_native_network_sources" not in text
    assert 'APT_GET=(apt-get "${APT_CONFIG_OPTS[@]}"' in text
    assert 'APT_CACHE=(apt-cache "${APT_CONFIG_OPTS[@]}")' in text
    assert "apt-cache show" not in text


def test_v056_build_apt_configuration_is_ephemeral_and_excludes_file_media(tmp_path: Path):
    text = native.NATIVE_INSTALL_SCRIPT
    function = _extract_function(text, "configure_native_build_apt")
    runtime = tmp_path / "run-linux-iso"
    shell = "\n".join(
        [
            "set -euo pipefail",
            "DISTRO_ID=pardus",
            f"SURET_APT_RUNTIME_ROOT={shlex.quote(str(runtime))}",
            'APT_RUNTIME_ROOT="$SURET_APT_RUNTIME_ROOT"',
            'APT_BUILD_SOURCES=""',
            "APT_CONFIG_OPTS=()",
            "log() { :; }",
            function,
            "configure_native_build_apt",
            'cat "$APT_BUILD_SOURCES"',
            "printf '%s\\n' \"${APT_CONFIG_OPTS[@]}\"",
        ]
    )
    result = subprocess.run(["bash", "-c", shell], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "file:/run/live/medium" not in result.stdout
    assert "cdrom:" not in result.stdout
    assert "depo.pardus.org.tr/pardus yirmibes" in result.stdout
    assert f"Dir::Etc::sourcelist={runtime}/apt-build/sources.list" in result.stdout
    assert f"Dir::State::lists={runtime}/apt-build/lists" in result.stdout
    assert (runtime / "apt-build/sourceparts").is_dir()
    assert (runtime / "apt-build/lists/partial").is_dir()


def test_v056_live_apt_configuration_is_not_rewritten_by_native_install_template():
    text = native.NATIVE_INSTALL_SCRIPT
    assert "/etc/apt/sources.list.d/99-suret-pardus-native.list" not in text
    assert "rm -f /etc/apt/sources.list" not in text
    assert "rm -rf /etc/apt/sources.list.d" not in text
    assert "Preserving the live ISO's original local-media/package-source configuration" in text
