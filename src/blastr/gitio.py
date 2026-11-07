"""git plumbing, kept in one place so the CLI and the MCP server agree.

git is optional: the fallback path reconstructs the pre-change file from the
diff itself, so blastr still works on a machine with no git installed.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from . import diffparse


def _run(root, *args):
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


@lru_cache(maxsize=16)
def available(root: str) -> bool:
    if shutil.which("git") is None:
        return False
    out = _run(root, "rev-parse", "--is-inside-work-tree")
    return bool(out and out.strip() == "true")


def git(root, *args):
    return _run(root, *args)


def load_diff(root, diff=None, staged=False, rev=None):
    """Returns (diff_text, error)."""
    if diff == "-":
        import sys

        return sys.stdin.read(), None
    if diff:
        path = Path(diff)
        if not path.is_file():
            return None, f"{diff}: no such file"
        return path.read_text(encoding="utf-8", errors="replace"), None

    if not available(str(root)):
        return None, "git not found and --diff was not given; pass a patch with --diff"

    args = ["diff", "--no-color", "-U3", "--find-renames"]
    if staged:
        args.append("--cached")
    elif rev:
        args.append(rev)
    text = _run(root, *args)
    if text is None:
        return None, "git diff failed (bad revision?)"
    return text, None


def before_images(root, diffs, staged=False, rev=None):
    """Old content per file: from git when possible, else rebuilt from the diff."""
    root = Path(root)
    usable = available(str(root))
    if staged:
        ref = ":"
    elif rev:
        ref = rev
    else:
        ref = "HEAD"

    before = {}
    for fd in diffs:
        if fd.is_new:
            before[fd.path] = None
            continue
        text = None
        if usable:
            text = _run(root, "show", f"{ref}:{fd.old_path or fd.path}")
        if text is None and not fd.is_deleted:
            try:
                current = (root / fd.path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                current = None
            if current is not None:
                text = diffparse.reverse_apply(current, fd)
        before[fd.path] = text
    return before
