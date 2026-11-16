from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mydistro.builder.kiwi import generate_kiwi_overlay
from mydistro.capture import CaptureError, capture_profile
from mydistro.planner import summarize
from mydistro.restore import RestoreError, restore_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mydistro",
        description="Capture and restore a personalized KDE Plasma Linux profile.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Capture the current KDE Plasma profile")
    scan.add_argument("-o", "--output", type=Path, default=Path("./mydistro-profile"))
    scan.add_argument("--home", type=Path, default=None, help="Override source home (mainly for testing)")

    inspect = sub.add_parser("inspect", help="Show a captured profile summary")
    inspect.add_argument("profile", type=Path)

    restore = sub.add_parser("restore", help="Restore profile files into a target home")
    restore.add_argument("profile", type=Path)
    restore.add_argument("--target-home", type=Path, required=True)
    restore.add_argument("--apply", action="store_true", help="Actually write files; otherwise dry-run")

    kiwi = sub.add_parser("stage-kiwi", help="Stage profile overlay for the future KIWI ISO builder")
    kiwi.add_argument("profile", type=Path)
    kiwi.add_argument("-o", "--output", type=Path, default=Path("./kiwi-stage"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scan":
            manifest = capture_profile(args.output, args.home)
            print(f"Profile created: {args.output.resolve()}")
            print(f"Configs: {len(manifest.desktop.configs)}")
            print(f"Assets: {len(manifest.desktop.custom_assets)}")
            print(f"Widgets: {len(manifest.desktop.widgets)}")
            print(f"Packages: {len(manifest.packages)}")
            return 0
        if args.command == "inspect":
            print(summarize(args.profile))
            return 0
        if args.command == "restore":
            ops = restore_profile(args.profile, args.target_home, apply=args.apply)
            action = "Restored" if args.apply else "Would restore"
            print(f"{action} {len(ops)} files into {args.target_home}")
            if not args.apply:
                for _, dst in ops[:20]:
                    print(f"  {dst}")
                if len(ops) > 20:
                    print(f"  ... {len(ops) - 20} more")
            return 0
        if args.command == "stage-kiwi":
            path = generate_kiwi_overlay(args.profile, args.output)
            print(f"KIWI overlay staged: {path.resolve()}")
            return 0
    except (CaptureError, RestoreError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
