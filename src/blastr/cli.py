"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, diffparse, gitio
from .graph import analyze
from .report import color_enabled, render_json, render_markdown, render_text

LEVELS = {"high": 0, "medium": 1, "low": 2}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blastr",
        description="Blast radius for a diff: who calls what you just changed.",
        epilog="examples:  blastr  |  blastr --staged  |  blastr --rev HEAD~1  |  blastr --diff fix.patch",
    )
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument("--diff", metavar="FILE", help="read a unified diff from FILE ('-' for stdin)")
    parser.add_argument("--staged", action="store_true", help="analyze staged changes only")
    parser.add_argument("--rev", metavar="REV", help="diff against a revision, e.g. HEAD~1 or main")
    parser.add_argument("--depth", type=int, default=2, metavar="N", help="caller hops to walk (default 2)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--markdown", action="store_true", help="PR-comment markdown")
    parser.add_argument("--no-color", action="store_true", help="never colourise")
    parser.add_argument(
        "--fail-on",
        choices=["high", "medium", "low"],
        help="exit 2 when a finding at this level or above is present (for CI)",
    )
    parser.add_argument("--mcp", action="store_true", help="serve blast_radius over MCP on stdio")
    parser.add_argument("--version", action="version", version=f"blastr {__version__}")
    return parser


def _encodable(text: str) -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _emit(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:  # GBK console, redirected pipe on Windows
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(text.encode(encoding, "replace").decode(encoding, "replace") + "\n")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.mcp:
        from .mcp import serve

        return serve()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"blastr: {root} is not a directory", file=sys.stderr)
        return 1

    text, error = gitio.load_diff(root, diff=args.diff, staged=args.staged, rev=args.rev)
    if error:
        print(f"blastr: {error}", file=sys.stderr)
        return 1

    diffs = diffparse.parse(text or "")
    if not diffs:
        print("blastr: the diff is empty — nothing to map", file=sys.stderr)
        return 1

    before = gitio.before_images(root, diffs, staged=args.staged, rev=args.rev)
    result = analyze(root, diffs, before, depth=max(1, args.depth))

    if args.json:
        _emit(render_json(result))
    elif args.markdown:
        _emit(render_markdown(result))
    else:
        ascii_only = not _encodable("…−→")
        _emit(render_text(result, color=not args.no_color and color_enabled(), ascii_only=ascii_only))

    if args.fail_on:
        threshold = LEVELS[args.fail_on]
        if any(LEVELS[risk.level] <= threshold for risk in result.risks):
            return 2
    return 0
