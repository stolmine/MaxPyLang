"""Command-line interface for maxpylang."""
from __future__ import annotations

import argparse
import sys
from importlib.resources import files
from pathlib import Path


def setup_claude(args: argparse.Namespace) -> int:
    """Copy the CLAUDE.md template into the current working directory."""
    dest = Path.cwd() / "CLAUDE.md"

    if dest.exists() and not args.force:
        print(
            f"CLAUDE.md already exists at {dest}\n"
            "Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    try:
        template = files("maxpylang").joinpath("data", "CLAUDE_TEMPLATE.md").read_text(encoding="utf-8")
    except FileNotFoundError:
        print("Error: CLAUDE_TEMPLATE.md not found in package data. Reinstall maxpylang.", file=sys.stderr)
        return 1

    try:
        dest.write_text(template, encoding="utf-8")
    except OSError as exc:
        print(f"Error writing {dest}: {exc}", file=sys.stderr)
        return 1

    print(f"Created {dest}")
    return 0


def _read_device(func):
    """Run a device command, turning read errors into a message and exit code."""
    def run(args: argparse.Namespace) -> int:
        from .exceptions import DeviceReadError, EncryptedDeviceError
        try:
            return func(args)
        except EncryptedDeviceError:
            print(f"{args.device}: encrypted device — cannot be read", file=sys.stderr)
            return 2
        except (OSError, DeviceReadError, ValueError) as exc:
            print(f"{args.device}: {exc}", file=sys.stderr)
            return 1
    return run


@_read_device
def describe_cmd(args: argparse.Namespace) -> int:
    """Print a Markdown (or JSON) description of a device."""
    from .devinspect import describe
    d = describe(args.device, depth=args.depth, full_code=args.full_code)
    print(d.to_json() if args.json else d.to_markdown(), end="" if not args.json else "\n")
    return 0


@_read_device
def params_cmd(args: argparse.Namespace) -> int:
    """Print every Live parameter of a device."""
    import json
    from .devinspect import describe, format_param
    params = describe(args.device).params
    if args.json:
        print(json.dumps(params, indent=2, ensure_ascii=False))
        return 0
    for p in params:
        short = f" ({p['shortname']})" if p["shortname"] != p["longname"] else ""
        where = "" if p["path"] == "/" else f" in {p['path']}"
        view = "" if p["presentation"] else " [not in view]"
        feeds = f" -> {'; '.join(p['feeds'])}" if p.get("feeds") else ""
        print(f"{p['longname']}{short}: {p['object']}, {format_param(p)}{where}{view}{feeds}")
    return 0


@_read_device
def extract_cmd(args: argparse.Namespace) -> int:
    """Write a device's main patch and embedded files into a folder."""
    from .devinspect import extract
    written = extract(args.device, args.outdir)
    for path in written:
        print(path)
    print(f"Extracted {len(written)} files to {args.outdir}", file=sys.stderr)
    return 0


def survey_cmd(args: argparse.Namespace) -> int:
    """Print one line per .amxd under a folder."""
    from .devinspect import survey
    if not Path(args.folder).is_dir():
        print(f"Error: {args.folder} is not a folder", file=sys.stderr)
        return 1
    count = 0
    for row in survey(args.folder):
        size = f"{row['size'] / 1024:.0f}KB" if row["size"] is not None else "-"
        params = "-" if row["params"] is None else row["params"]
        print(f"{row['name'][:40]:<40}  {row['type'] or '-':<19}  {params!s:>4} params  "
              f"{row['status']:<10}  {size:>7}  {row['path']}")
        count += 1
    print(f"{count} devices", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="maxpylang",
        description="MaxPyLang command-line tools.",
    )
    subparsers = parser.add_subparsers(dest="command")

    sp = subparsers.add_parser(
        "setup-claude",
        help="Copy the CLAUDE.md template into the current directory.",
    )
    sp.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing CLAUDE.md if present.",
    )
    sp.set_defaults(func=setup_claude)

    sp = subparsers.add_parser(
        "describe",
        help="Describe an .amxd/.maxpat: parameters, device view, signal flow, code (read-only).",
    )
    sp.add_argument("device", help="Path to an .amxd or .maxpat file.")
    sp.add_argument("--json", action="store_true", help="Print full detail as JSON.")
    sp.add_argument("--depth", type=int, default=3,
                    help="Subpatcher levels shown in the structure section (default 3).")
    sp.add_argument("--full-code", action="store_true",
                    help="Include whole js/gen sources instead of the first lines.")
    sp.set_defaults(func=describe_cmd)

    sp = subparsers.add_parser("params", help="List every Live parameter of a device.")
    sp.add_argument("device", help="Path to an .amxd or .maxpat file.")
    sp.add_argument("--json", action="store_true", help="Print parameters as JSON.")
    sp.set_defaults(func=params_cmd)

    sp = subparsers.add_parser(
        "extract",
        help="Write a device's main patch (.maxpat) and embedded files into a folder.",
    )
    sp.add_argument("device", help="Path to an .amxd file.")
    sp.add_argument("outdir", help="Folder to write into (created if missing).")
    sp.set_defaults(func=extract_cmd)

    sp = subparsers.add_parser("survey", help="One line per .amxd found under a folder.")
    sp.add_argument("folder", help="Folder to search recursively.")
    sp.set_defaults(func=survey_cmd)

    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)

    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
