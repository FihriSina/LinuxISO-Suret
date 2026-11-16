from __future__ import annotations

import argparse
import sys
from pathlib import Path

from linux_iso.branding import PRODUCT_NAME
from linux_iso.builder.kiwi import BuilderError, RECIPES, generate_kiwi_project
from linux_iso.capture import CaptureError, capture_profile
from linux_iso.diagnostics import doctor_report
from linux_iso.installer.catalog import write_catalog
from linux_iso.planner import audit, summarize
from linux_iso.restore import RestoreError, restore_profile
from linux_iso.verification import verify_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linux-iso",
        description=f"{PRODUCT_NAME}: capture, rebuild and install a personalized Linux desktop.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Capture the current KDE Plasma profile")
    scan.add_argument("-o", "--output", type=Path, default=Path("./linux-iso-profile"))
    scan.add_argument("--home", type=Path, default=None, help="Override source home (mainly for testing)")
    scan.add_argument(
        "--asset-mode",
        choices=("active", "all"),
        default="active",
        help="Capture only active appearance assets (default) or every installed user asset",
    )

    inspect = sub.add_parser("inspect", help="Show a captured profile summary")
    inspect.add_argument("profile", type=Path)

    audit_cmd = sub.add_parser("audit", help="Report captured assets, widgets and install dependencies")
    audit_cmd.add_argument("profile", type=Path)

    verify = sub.add_parser("verify", help="Verify payload checksums and restore dependencies")
    verify.add_argument("profile", type=Path)

    restore = sub.add_parser("restore", help="Restore profile files into a target home")
    restore.add_argument("profile", type=Path)
    restore.add_argument("--target-home", type=Path, required=True)
    restore.add_argument("--apply", action="store_true", help="Actually write files; otherwise dry-run")

    catalog = sub.add_parser("catalog", help="Generate the categorized installer application catalog")
    catalog.add_argument("profile", type=Path)
    catalog.add_argument("-o", "--output", type=Path, default=Path("./application-catalog.json"))

    kiwi = sub.add_parser("stage-iso", aliases=["stage-kiwi"], help="Generate the KIWI + Calamares ISO project")
    kiwi.add_argument("profile", type=Path)
    kiwi.add_argument("-o", "--output", type=Path, default=Path("./linux-iso-build"))
    kiwi.add_argument("--recipe", choices=sorted(RECIPES), default="ubuntu-26.04-kde")

    sub.add_parser("recipes", help="List available base ISO recipes")
    sub.add_parser("doctor", help="Diagnose the local Python/uv development environment")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scan":
            manifest = capture_profile(args.output, args.home, asset_mode=args.asset_mode)
            print(f"Profile created: {args.output.resolve()}")
            print(f"Configs: {len(manifest.desktop.configs)}")
            print(f"Assets: {len(manifest.desktop.custom_assets)}")
            print(f"Widgets: {len(manifest.desktop.widgets)}")
            print(f"Packages: {len(manifest.packages)}")
            print(f"Asset mode: {manifest.restore.get('asset_mode', 'unknown')}")
            return 0
        if args.command == "inspect":
            print(summarize(args.profile))
            return 0
        if args.command == "audit":
            print(audit(args.profile))
            return 0
        if args.command == "verify":
            result = verify_profile(args.profile)
            print(result.render())
            return 0 if result.ok else 3
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
        if args.command == "catalog":
            path = write_catalog(args.profile, args.output)
            print(f"Application catalog created: {path.resolve()}")
            return 0
        if args.command in {"stage-iso", "stage-kiwi"}:
            path = generate_kiwi_project(args.profile, args.output, recipe_id=args.recipe)
            print(f"ISO build project staged: {path.resolve()}")
            print(f"Build command: cd {path.resolve()} && ./build.sh")
            return 0
        if args.command == "recipes":
            for recipe_id in sorted(RECIPES):
                print(recipe_id)
            return 0
        if args.command == "doctor":
            print(doctor_report())
            return 0
    except (CaptureError, RestoreError, BuilderError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
