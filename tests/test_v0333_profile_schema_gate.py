from pathlib import Path
import os
import shutil
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAFE_FIRST = PROJECT_ROOT / "scripts/safe-first-iso.sh"


def _sandbox(tmp_path: Path, schema: str | None) -> tuple[Path, Path]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(SAFE_FIRST, scripts / "safe-first-iso.sh")
    first = scripts / "first-iso.sh"
    first.write_text("#!/usr/bin/env bash\nset -e\nmkdir -p \"$2\"\ntouch \"$2/build-was-called\"\n", encoding="utf-8")
    first.chmod(0o755)

    profile = tmp_path / "profile"
    profile.mkdir()
    if schema is not None:
        (profile / "manifest.yaml").write_text(
            "schema_version: 1\nrestore:\n  fidelity_schema: " + schema + "\n",
            encoding="utf-8",
        )
    return profile, tmp_path / "build"


def _run(tmp_path: Path, schema: str | None) -> subprocess.CompletedProcess[str]:
    profile, build = _sandbox(tmp_path, schema)
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    return subprocess.run(
        ["bash", "scripts/safe-first-iso.sh", str(profile), str(build)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_v0333_safe_build_accepts_current_schema_8(tmp_path: Path):
    result = _run(tmp_path, "8")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "build/build-was-called").exists()


def test_v0333_safe_build_accepts_future_schema(tmp_path: Path):
    result = _run(tmp_path, "9")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "build/build-was-called").exists()


def test_v0333_safe_build_rejects_schema_7(tmp_path: Path):
    result = _run(tmp_path, "7")
    assert result.returncode == 6
    assert "system-visible fidelity capture v8" in result.stderr
    assert "Detected fidelity_schema: 7" in result.stderr
    assert not (tmp_path / "build/build-was-called").exists()


def test_v0333_safe_build_rejects_missing_manifest(tmp_path: Path):
    result = _run(tmp_path, None)
    assert result.returncode == 6
    assert "Profile manifest is missing" in result.stderr
