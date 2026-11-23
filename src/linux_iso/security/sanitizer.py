from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


SENSITIVE_PATH_PARTS = {
    ".ssh",
    ".gnupg",
    ".pki",
    ".aws",
    ".azure",
    ".kube",
    ".docker",
    ".password-store",
    ".mozilla",
    "google-chrome",
    "chromium",
    "bravesoftware",
    "microsoft-edge",
    "keyrings",
    "wallet",
    "kwalletd",
    "networkmanager",
    "credentials",
}

SECRET_ASSIGNMENT = re.compile(
    r"(?i)^\s*(?:export\s+)?([A-Z0-9_]*(?:TOKEN|PASSWORD|PASSWD|SECRET|API_KEY|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*)\s*=\s*(.+)$"
)

DESKTOP_SECRET_ARG = re.compile(
    r"(?i)(?P<prefix>(?:^|\s)--(?:access[-_]?token|refresh[-_]?token|auth[-_]?token|api[-_]?key|password|passwd|secret)(?:=|\s+))(?P<value>\"[^\"]*\"|'[^']*'|[^\s]+)"
)
DESKTOP_SECRET_ENV = re.compile(
    r"(?i)(?P<prefix>(?:^|\s)(?:ACCESS_TOKEN|REFRESH_TOKEN|AUTH_TOKEN|API_KEY|PASSWORD|PASSWD|SECRET)=)(?P<value>\"[^\"]*\"|'[^']*'|[^\s]+)"
)
URL_SECRET_QUERY = re.compile(
    r"(?i)(?P<prefix>[?&](?:access_token|refresh_token|auth_token|api_key|password|passwd|secret)=)(?P<value>[^&#\s]+)"
)


@dataclass
class SanitizeResult:
    text: str
    redacted_lines: int = 0
    notes: list[str] = field(default_factory=list)


def path_is_sensitive(path: Path) -> bool:
    return any(part.casefold() in SENSITIVE_PATH_PARTS for part in path.parts)


def sanitize_shell_text(text: str) -> SanitizeResult:
    out: list[str] = []
    redacted = 0
    for line in text.splitlines(keepends=True):
        match = SECRET_ASSIGNMENT.match(line.rstrip("\r\n"))
        if match:
            newline = "\n" if line.endswith("\n") else ""
            out.append(f"# linux-iso: redacted possible secret: {match.group(1)}{newline}")
            redacted += 1
        else:
            out.append(line)
    return SanitizeResult("".join(out), redacted, ["Possible shell secrets are redacted."] if redacted else [])


def sanitize_desktop_text(text: str) -> SanitizeResult:
    """Redact credential-like values embedded in Desktop Entry Exec lines.

    Launchers are user-visible state and are intentionally captured, but a
    hand-written launcher can embed an API token, password or authenticated URL.
    Keep the launcher structure while replacing only the secret value.
    """
    out: list[str] = []
    redacted = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if not stripped.startswith("Exec="):
            out.append(line)
            continue
        updated = line
        for pattern in (DESKTOP_SECRET_ARG, DESKTOP_SECRET_ENV, URL_SECRET_QUERY):
            updated, count = pattern.subn(lambda match: match.group("prefix") + "<redacted>", updated)
            redacted += count
        out.append(updated)
    notes = ["Credential-like values in desktop launcher commands are redacted."] if redacted else []
    return SanitizeResult("".join(out), redacted, notes)
