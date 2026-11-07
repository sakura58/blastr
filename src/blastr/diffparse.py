"""Parse unified diffs, with no dependency on git being installed.

`git diff` output and plain `difflib.unified_diff` output are both accepted.
The before-image of a file can be reconstructed from the diff itself when the
repository has no usable history (see `reverse_apply`), which is what makes
`blastr --diff patch.diff` work inside a CI container that only has the patch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list = field(default_factory=list)  # (tag, text) where tag in " +-\\"


@dataclass
class FileDiff:
    path: str
    old_path: str = ""
    hunks: list = field(default_factory=list)
    added: list = field(default_factory=list)  # (new_lineno, text)
    removed: list = field(default_factory=list)  # (old_lineno, text)
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False
    is_rename: bool = False

    @property
    def additions(self) -> int:
        return len(self.added)

    @property
    def deletions(self) -> int:
        return len(self.removed)

    def new_ranges(self) -> list:
        """Contiguous ranges of added line numbers in the new file."""
        nums = sorted({n for n, _ in self.added})
        if not nums:
            return []
        spans = []
        start = prev = nums[0]
        for n in nums[1:]:
            if n == prev + 1:
                prev = n
                continue
            spans.append((start, prev))
            start = prev = n
        spans.append((start, prev))
        return spans

    def added_lines(self, pattern: re.Pattern) -> list:
        return [(n, t) for n, t in self.added if pattern.search(t)]

    def removed_lines(self, pattern: re.Pattern) -> list:
        return [(n, t) for n, t in self.removed if pattern.search(t)]


def _clean_path(raw: str) -> str:
    p = raw.strip()
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    return p


def parse(text: str) -> list:
    """Parse a unified diff into FileDiff objects (drops empty sections)."""
    diffs: list = []
    cur = None
    hunk = None
    n_old = n_new = 0

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            m = re.match(r"^diff --git a/(.*?) b/(.*)$", raw)
            cur = FileDiff(path=_clean_path(m.group(2)) if m else "", old_path=_clean_path(m.group(1)) if m else "")
            diffs.append(cur)
            hunk = None
            continue

        if cur is None:
            if raw.startswith("--- "):
                cur = FileDiff(path="", old_path=_clean_path(raw[4:]))
                diffs.append(cur)
            else:
                continue
        elif raw.startswith("--- ") and cur.hunks:
            # second file of a plain (non-git) unified diff
            cur = FileDiff(path="", old_path=_clean_path(raw[4:]))
            diffs.append(cur)
            hunk = None
            continue

        if raw.startswith("new file mode"):
            cur.is_new = True
            continue
        if raw.startswith("deleted file mode"):
            cur.is_deleted = True
            continue
        if raw.startswith("old mode") or raw.startswith("new mode"):
            continue
        if raw.startswith("similarity index"):
            cur.is_rename = True
            continue
        if raw.startswith("rename from "):
            cur.old_path = raw[len("rename from "):].strip()
            cur.is_rename = True
            continue
        if raw.startswith("rename to "):
            cur.path = raw[len("rename to "):].strip()
            cur.is_rename = True
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            cur.is_binary = True
            continue
        if raw.startswith("--- "):
            cur.old_path = _clean_path(raw[4:])
            if cur.old_path == "/dev/null":
                cur.is_new = True
            continue
        if raw.startswith("+++ "):
            p = _clean_path(raw[4:])
            if p == "/dev/null":
                cur.is_deleted = True
            else:
                cur.path = p
            continue

        m = HUNK_RE.match(raw)
        if m:
            hunk = Hunk(
                old_start=int(m.group(1)),
                old_len=int(m.group(2) or 1),
                new_start=int(m.group(3)),
                new_len=int(m.group(4) or 1),
            )
            cur.hunks.append(hunk)
            n_old, n_new = hunk.old_start, hunk.new_start
            continue

        if hunk is None:
            continue

        tag = raw[:1]
        if tag == "+":
            hunk.lines.append(("+", raw[1:]))
            cur.added.append((n_new, raw[1:]))
            n_new += 1
        elif tag == "-":
            hunk.lines.append(("-", raw[1:]))
            cur.removed.append((n_old, raw[1:]))
            n_old += 1
        elif tag == " ":
            hunk.lines.append((" ", raw[1:]))
            n_old += 1
            n_new += 1
        elif raw.startswith("\\"):
            hunk.lines.append(("\\", raw[1:]))

    return [d for d in diffs if d.path or d.hunks]


def reverse_apply(new_text: str, fd: FileDiff) -> str | None:
    """Reconstruct the pre-change file by undoing the diff on the new text.

    Returns None when the diff does not line up with the file (stale patch,
    binary content, or hunks out of order).
    """
    if fd.is_binary or not fd.hunks:
        return None
    lines = new_text.splitlines()
    out: list = []
    idx = 0
    for h in fd.hunks:
        target = max(h.new_start - 1, 0)
        if target < idx or target > len(lines):
            return None
        out.extend(lines[idx:target])
        idx = target
        for tag, text in h.lines:
            if tag == " ":
                if idx >= len(lines):
                    return None
                out.append(lines[idx])
                idx += 1
            elif tag == "+":
                if idx >= len(lines):
                    return None
                idx += 1
            elif tag == "-":
                out.append(text)
    out.extend(lines[idx:])
    body = "\n".join(out)
    if new_text.endswith("\n"):
        body += "\n"
    return body


def files_touched(text: str) -> list:
    return [d.path for d in parse(text) if d.path]
