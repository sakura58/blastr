"""Shared data model.

Everything downstream (graph building, rules, report, cli, mcp) speaks these
objects, so the analyzers only need to produce `ModuleScan`s and the rules
only need to read a `Result`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# file classification
# ---------------------------------------------------------------------------

TEST_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec)/"
    r"|(^|/)test_[^/]*\.py$"
    r"|_test\.(py|go)$"
    r"|\.(test|spec)\.[cm]?[jt]sx?$",
    re.IGNORECASE,
)

CODE_EXT = {
    ".py": "python",
    ".pyi": "python",
    ".js": "js",
    ".jsx": "js",
    ".ts": "js",
    ".tsx": "js",
    ".mjs": "js",
    ".cjs": "js",
}

# Directories that are never interesting, and reading them makes blastr slow.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "target",
    "vendor",
    "coverage",
    "htmlcov",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
    ".idea",
    ".vscode",
    ".tox",
    "site-packages",
}


def is_test_path(path: str) -> bool:
    return bool(TEST_RE.search(path))


def lang_of(path: str) -> Optional[str]:
    for ext, lang in CODE_EXT.items():
        if path.endswith(ext):
            return lang
    return None


# ---------------------------------------------------------------------------
# static analysis primitives
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    """A definition we might have broken."""

    file: str
    qualname: str
    kind: str  # function | method | class | constant
    lineno: int
    end_lineno: int
    signature: str = ""
    body_hash: str = ""
    decorators: tuple = ()
    is_public: bool = True
    is_async: bool = False

    @property
    def short(self) -> str:
        return self.qualname.rsplit(".", 1)[-1]

    @property
    def key(self) -> str:
        return f"{self.file}::{self.qualname}"


@dataclass
class CallSite:
    """Somewhere a function or method is called."""

    file: str
    lineno: int
    callee: str
    caller: str = "<module>"
    text: str = ""
    kind: str = "name"  # name | attr
    resolved: list = field(default_factory=list)
    weak: bool = False


@dataclass
class ModuleScan:
    """Everything one file tells us."""

    file: str
    lang: str
    symbols: dict = field(default_factory=dict)  # qualname -> Symbol
    imports: dict = field(default_factory=dict)  # local -> (module, original)
    calls: list = field(default_factory=list)
    exports: set = field(default_factory=set)
    ok: bool = True
    error: str = ""
    hash_bodies: bool = True


# ---------------------------------------------------------------------------
# analysis result
# ---------------------------------------------------------------------------


@dataclass
class Change:
    """A symbol that the diff changed, and how."""

    file: str
    symbol: Symbol
    kind: str  # added | removed | signature | body | decorator | async | touched
    before: Optional[Symbol] = None

    @property
    def key(self) -> str:
        return self.symbol.key


@dataclass
class Occurrence:
    """A call site that lands inside the blast radius."""

    file: str
    lineno: int
    caller: str
    callee: str
    hop: int
    text: str = ""
    weak: bool = False
    via: str = ""


@dataclass
class TestRef:
    """A test that mentions a changed symbol."""

    file: str
    lineno: int
    symbol: str
    exact: bool = False
    note: str = ""


@dataclass
class Risk:
    """Something a human should look at before merging."""

    id: str
    level: str  # high | medium | low
    title: str
    detail: str = ""
    file: str = ""
    line: int = 0
    symbol: str = ""
    evidence: str = ""


@dataclass
class Result:
    root: str
    diffs: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    occurrences: list = field(default_factory=list)
    tests: list = field(default_factory=list)
    uncovered: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    @property
    def breaks(self) -> int:
        return sum(1 for r in self.risks if r.level == "high")

    @property
    def silent(self) -> int:
        return sum(1 for r in self.risks if r.level == "medium")

    @property
    def level(self) -> str:
        if any(r.level == "high" for r in self.risks):
            return "high"
        if any(r.level == "medium" for r in self.risks):
            return "medium"
        if self.risks:
            return "low"
        return "none"
