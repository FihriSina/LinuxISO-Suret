from __future__ import annotations

import re
import subprocess
from pathlib import Path

from linux_iso import __version__


def _extract_function(script: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n(?P<body>.*?\n)\}}\n", script, flags=re.MULTILINE | re.DOTALL)
    assert match, f"missing shell function: {name}"
    return f"{name}() {{\n{match.group('body')}}}\n"


def _run_guard(script_path: str, *, profile: str, build: str, result: str) -> subprocess.CompletedProcess[str]:
    text = Path(script_path).read_text(encoding="utf-8")
    shell = "\n".join(
        [
            "set -euo pipefail",
            f"PROFILE={profile!r}",
            f"BUILD={build!r}",
            f"RESULT={result!r}",
            _extract_function(text, "path_within"),
            _extract_function(text, "guard_native_layout"),
            "guard_native_layout",
            "printf 'GUARD_OK\\n'",
        ]
    )
    return subprocess.run(["bash", "-c", shell], text=True, capture_output=True, check=False)


def test_v055_version_and_acceptance_banners_are_bumped():
    assert __version__ == "0.6.5"
    assert "v0.6.5 Native ISO acceptance" in Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")
    assert "v0.6.5 Native retry" in Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")


def test_v055_valid_native_layout_survives_errexit_guard():
    for script in ("scripts/native-acceptance.sh", "scripts/retry-native-acceptance.sh"):
        result = _run_guard(
            script,
            profile="/home/test/linux-iso-profile",
            build="/home/test/linux-iso-native-build",
            result="/home/test/linux-iso-native-result",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "GUARD_OK\n"


def test_v055_invalid_native_layout_is_still_rejected():
    for script in ("scripts/native-acceptance.sh", "scripts/retry-native-acceptance.sh"):
        result = _run_guard(
            script,
            profile="/home/test/linux-iso-native-build/profile",
            build="/home/test/linux-iso-native-build",
            result="/home/test/linux-iso-native-result",
        )
        assert result.returncode == 2
        assert "Profile must not be inside disposable Native build path" in result.stderr
        assert "GUARD_OK" not in result.stdout


def test_v055_acceptance_scripts_emit_phase_markers_before_long_steps():
    retry = Path("scripts/retry-native-acceptance.sh").read_text(encoding="utf-8")
    full = Path("scripts/native-acceptance.sh").read_text(encoding="utf-8")
    for text in (retry, full):
        assert 'phase "Checking Native host dependencies"' in text
        assert 'phase "Synchronizing Python environment"' in text
        assert 'phase "Probing base ISO"' in text
        assert 'phase "Staging Native remaster"' in text
        assert 'phase "Building Native ISO"' in text
        assert 'phase "Validating Native ISO in QEMU"' in text
