from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


SENSITIVE_PATH_PARTS = {
    ".ssh",
    ".gnupg",
    ".pki",
    "keyrings",
    "wallet",
    "kwalletd",
    "NetworkManager",
}

SECRET_ASSIGNMENT = re.compile(
    r"(?i)^\s*(?:export\s+)?([A-Z0-9_]*(?:TOKEN|PASSWORD|PASSWD|SECRET|API_KEY|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*)\s*=\s*(.+)$"
)


@dataclass
class SanitizeResult:
    text: str
    redacted_lines: int = 0
    notes: list[str] = field(default_factory=list)


def path_is_sensitive(path: Path) -> bool:
    return any(part in SENSITIVE_PATH_PARTS for part in path.parts)


def sanitize_shell_text(text: str) -> SanitizeResult:
    out: list[str] = []
    redacted = 0
    for line in text.splitlines(keepends=True):
        match = SECRET_ASSIGNMENT.match(line.rstrip("\r\n"))
        if match:
            newline = "\n" if line.endswith("\n") else ""
            out.append(f"# mydistro: redacted possible secret: {match.group(1)}{newline}")
            redacted += 1
        else:
            out.append(line)
    return SanitizeResult("".join(out), redacted, ["Possible shell secrets are redacted."] if redacted else [])
