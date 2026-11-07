"""Build the blast radius: changed symbols -> call sites -> tests -> risks."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import jsscan, pyscan
from .model import (SKIP_DIRS, Change, ModuleScan, Occurrence, Result, Symbol,
                    TestRef, is_test_path, lang_of)
from .rules import apply as apply_rules

MAX_FILES = 4000
MAX_BYTES = 400_000

_SEVERITY = {
    "touched": 0,
    "body": 1,
    "added": 2,
    "decorator": 2,
    "async": 3,
    "signature": 4,
    "removed": 5,
}


class Index:
    """Lazy, cached view of every source file under the repo root."""

    def __init__(self, root):
        self.root = Path(root)
        self._text = {}
        self._scan = {}
        self._files = None
        self.by_name = {}
        self.module_files = {}
        self.body_files = set()

    def files(self):
        if self._files is None:
            found = []
            for base, dirnames, filenames in os.walk(self.root):
                dirnames[:] = sorted(
                    d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
                )
                for fname in filenames:
                    rel = Path(base, fname).relative_to(self.root).as_posix()
                    if lang_of(rel):
                        found.append(rel)
            found.sort()
            self._files = found[:MAX_FILES]
        return self._files

    def text(self, rel):
        if rel in self._text:
            return self._text[rel]
        path = self.root / rel
        try:
            if path.stat().st_size > MAX_BYTES:
                self._text[rel] = None
                return None
            data = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._text[rel] = None
            return None
        self._text[rel] = data
        return data

    def scan(self, rel):
        if rel in self._scan:
            return self._scan[rel]
        text = self.text(rel)
        lang = lang_of(rel)
        result = None
        if text is not None and lang:
            hashing = rel in self.body_files
            result = (
                pyscan.scan(rel, text, hash_bodies=hashing)
                if lang == "python"
                else jsscan.scan(rel, text, hash_bodies=hashing)
            )
        self._scan[rel] = result
        if result is not None:
            self._register(result)
        return result

    def _register(self, mod):
        self.module_files.setdefault(self.module_name(mod.file), mod.file)
        for symbol in mod.symbols.values():
            bucket = self.by_name.setdefault(symbol.short, [])
            if all(existing.key != symbol.key for existing in bucket):
                bucket.append(symbol)

    @staticmethod
    def module_name(rel):
        stem = rel[:-3] if rel.endswith(".py") else rel
        parts = stem.replace("\\", "/").split("/")
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    def find(self, name):
        pattern = re.compile(r"\b" + re.escape(name) + r"\b")
        hits = []
        for rel in self.files():
            text = self.text(rel)
            if text and pattern.search(text):
                hits.append(rel)
        return hits


# ---------------------------------------------------------------------------


def _scan_text(path, text):
    if not text:
        return None
    lang = lang_of(path)
    if lang == "python":
        return pyscan.scan(path, text)
    if lang == "js":
        return jsscan.scan(path, text)
    return None


def _overlaps(symbol, ranges):
    return any(start <= symbol.lineno <= end for start, end in ranges)


def _diff_kind(old, new):
    if old.signature != new.signature:
        return "signature"
    if tuple(old.decorators) != tuple(new.decorators):
        return "decorator"
    if old.is_async != new.is_async:
        return "async"
    if old.body_hash and new.body_hash and old.body_hash != new.body_hash:
        # a class "body" is every method in it; flagging that would drown the real changes
        return "" if old.kind == "class" else "body"
    if old.kind != new.kind:
        return "body"
    return ""


def _import_path(index, from_file, module):
    if module.startswith("."):
        level = len(module) - len(module.lstrip("."))
        rest = module.lstrip(".")
        base = from_file.split("/")[:-1]
        if level > 1:
            base = base[: max(len(base) - (level - 1), 0)]
        parts = [p for p in base if p]
        if rest:
            parts.extend(rest.split("."))
        key = ".".join(parts)
    else:
        key = module

    found = index.module_files.get(key)
    if found:
        return found

    suffix = key.replace(".", "/")
    for rel in index.files():
        if rel in (suffix + ".py", suffix + "/__init__.py", suffix + ".ts", suffix + ".tsx", suffix + ".js"):
            return rel
    return None


def _resolve(index, scan, call):
    """Where does this call actually land? Returns (symbols, weak)."""
    name = call.callee
    if not name:
        return [], False

    imported = scan.imports.get(name)
    if imported:
        module, original = imported
        path = _import_path(index, scan.file, module)
        if path:
            target = index.scan(path)
            if target is not None:
                symbol = target.symbols.get(original) or target.symbols.get(name)
                if symbol is not None:
                    return [symbol], False

    if name in scan.symbols:
        return [scan.symbols[name]], False

    candidates = index.by_name.get(name, [])
    if len(candidates) == 1:
        return candidates, False
    if candidates:
        return candidates, True
    return [], False


IMPORT_LINE = re.compile(r"^\s*(from\s+\S+\s+import|import\s+\S+)")


def _first_mention(lines, name, limit=4000, skip_imports=True):
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    fallback = 0
    for number, line in enumerate(lines[:limit], start=1):
        if not pattern.search(line):
            continue
        if skip_imports and IMPORT_LINE.match(line):
            fallback = fallback or number
            continue
        return number
    return fallback


def _exact_assertion_near(lines, lineno, name, radius=8):
    """True when a test asserts an exact value *of this symbol*.

    Both conditions are required: the name must be on the assertion line, and
    the assertion must compare whole values. Otherwise every test file that
    mentions a helper looks like it will fail.
    """
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    window = lines[max(lineno - 1 - radius, 0): lineno + radius]
    for line in window:
        if not pattern.search(line):
            continue
        lowered = line.lower()
        if "assert" not in lowered and "expect(" not in lowered:
            continue
        if "== " in line or "==" in line or "assertEqual" in line or "toEqual" in line or "toStrictEqual" in line:
            return True
        if ".tobe(" in lowered:
            return True
    return False


def analyze(root, diffs, before, depth=2):
    root = Path(root)
    index = Index(root)
    result = Result(root=str(root), diffs=diffs)
    changes = []

    for fd in diffs:
        if fd.is_binary:
            result.notes.append(f"{fd.path}: binary, skipped")
            continue

        index.body_files.add(fd.path)

        if fd.is_deleted:
            old_text = before.get(fd.path)
            old_scan = _scan_text(fd.path, old_text)
            if old_scan is not None:
                for symbol in old_scan.symbols.values():
                    changes.append(Change(fd.path, symbol, "removed"))
            continue

        new_text = index.text(fd.path)
        if new_text is None:
            result.notes.append(f"{fd.path}: missing from the working tree, skipped")
            continue

        new_scan = index.scan(fd.path)
        if new_scan is None or not new_scan.ok:
            reason = new_scan.error if new_scan is not None else "unreadable"
            result.notes.append(f"{fd.path}: {reason}")
            continue

        old_text = before.get(fd.path)
        old_scan = _scan_text(fd.path, old_text) if old_text is not None else None
        if old_scan is not None and not old_scan.ok:
            result.notes.append(
                f"{fd.path}: before-image unparseable ({old_scan.error}); reporting touched symbols only"
            )
            old_scan = None

        touched = fd.new_ranges()
        for qname, symbol in new_scan.symbols.items():
            previous = old_scan.symbols.get(qname) if old_scan is not None else None
            if previous is None:
                if old_scan is None:
                    if not touched or _overlaps(symbol, touched):
                        changes.append(Change(fd.path, symbol, "touched"))
                else:
                    changes.append(Change(fd.path, symbol, "added"))
                continue
            kind = _diff_kind(previous, symbol)
            if kind:
                changes.append(Change(fd.path, symbol, kind, previous))

        if old_scan is not None:
            for qname, previous in old_scan.symbols.items():
                if qname not in new_scan.symbols:
                    changes.append(Change(fd.path, previous, "removed"))

    # one row per symbol, keeping the most severe kind
    picked = {}
    for change in changes:
        existing = picked.get(change.key)
        if existing is None or _SEVERITY.get(change.kind, 0) > _SEVERITY.get(existing.kind, 0):
            picked[change.key] = change
    changes = list(picked.values())

    # BFS over callers
    occurrences = []
    seen_calls = set()
    frontier = {change.key: change for change in changes}
    visited = set(frontier)

    for hop in range(1, depth + 1):
        nxt = {}
        for change in frontier.values():
            name = change.symbol.short
            for path in index.find(name):
                scan = index.scan(path)
                if scan is None:
                    continue
                for call in scan.calls:
                    if call.callee != name:
                        continue
                    targets, weak = _resolve(index, scan, call)
                    if not any(t.key == change.symbol.key for t in targets):
                        continue
                    token = (call.file, call.lineno, call.caller)
                    if token in seen_calls:
                        continue
                    seen_calls.add(token)
                    occurrences.append(
                        Occurrence(
                            file=call.file,
                            lineno=call.lineno,
                            caller=call.caller,
                            callee=name,
                            hop=hop,
                            text=call.text,
                            weak=weak,
                        )
                    )
                    caller = scan.symbols.get(call.caller)
                    if caller is not None and caller.key not in visited:
                        nxt[caller.key] = Change(call.file, caller, "caller")
        frontier = nxt
        visited |= set(frontier)

    # tests that mention the changed symbols
    tests = []
    uncovered = []
    for change in changes:
        symbol = change.symbol
        # constructor calls look like `User(...)`, not `__init__(...)`
        search = symbol.qualname.split(".")[0] if symbol.short == "__init__" else symbol.short
        hit_files = [p for p in index.find(search) if is_test_path(p)]
        if not hit_files:
            if symbol.kind in ("function", "method", "class"):
                uncovered.append(symbol.qualname)
            continue
        for path in hit_files:
            text = index.text(path)
            if not text:
                continue
            lines = text.splitlines()
            lineno = _first_mention(lines, search)
            if not lineno:
                continue
            tests.append(
                TestRef(
                    file=path,
                    lineno=lineno,
                    symbol=symbol.qualname,
                    exact=_exact_assertion_near(lines, lineno, search),
                )
            )

    result.changes = changes
    result.occurrences = occurrences
    result.tests = tests
    result.uncovered = sorted(set(uncovered))
    result.stats = {
        "files": sum(1 for d in diffs if not d.is_binary),
        "additions": sum(d.additions for d in diffs),
        "deletions": sum(d.deletions for d in diffs),
        "symbols": len(changes),
        "call_sites": len(occurrences),
        "hops": depth,
        "scanned": len(index.files()),
    }
    apply_rules(result)
    return result
