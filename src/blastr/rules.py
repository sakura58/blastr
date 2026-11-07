"""Rules that turn a blast radius into something a reviewer can act on.

Each rule is cheap, explainable and evidence-backed: no LLM, no scoring model.
A rule either fires with a concrete line or it stays quiet.
"""

from __future__ import annotations

import re

from .model import Risk, is_test_path

ORDER = {"high": 0, "medium": 1, "low": 2}

SERIAL_NAME = re.compile(r"(to_|as_|_dict|serial|dump|encode|payload|schema|json)", re.IGNORECASE)
DICT_KEY = re.compile(r"""(["'])([A-Za-z_][\w-]*)\1\s*:""")
CONFIG_FILE = re.compile(r"(settings|config|conf|constants|defaults|env)\.(py|ts|js|json|toml|ya?ml)$", re.IGNORECASE)
CONFIG_LINE = re.compile(r"^\s*[A-Z][A-Z0-9_]{2,}\s*=")
ENV_LINE = re.compile(r"os\.environ|os\.getenv|process\.env")
MIGRATION_PATH = re.compile(r"(^|/)migrations?/|alembic/versions/|(^|/)schema[^/]*\.sql$", re.IGNORECASE)
DDL = re.compile(r"\b(ADD|DROP|ALTER|RENAME)\s+(COLUMN|TABLE|INDEX|CONSTRAINT)\b", re.IGNORECASE)
DEPS = {
    "pyproject.toml", "package.json", "requirements.txt", "requirements-dev.txt",
    "poetry.lock", "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "Cargo.toml", "go.mod",
}
WEAKEN = re.compile(r"\b(skip|xfail|xit|xdescribe|\.only\b|@unittest\.skip|@pytest\.mark\.skip)", re.IGNORECASE)
ASSERT = re.compile(r"\bassert\b|assertEqual|assert_eq|assertRaises")
EXCEPT = re.compile(r"^\s*except\b[^:]*:\s*(.*)$")
ENDPOINT = re.compile(
    r"@(app|router|bp|blueprint)\.(get|post|put|patch|delete)\(|@(Get|Post|Put|Patch|Delete)Mapping"
)


def apply(result) -> None:
    by_file = {fd.path: fd for fd in result.diffs}
    _removed(result)
    _signature(result)
    _public_api(result)
    _serialization(result, by_file)
    _config(result, by_file)
    _migrations(result, by_file)
    _swallowed(result, by_file)
    _test_weakening(result, by_file)
    _exact_assertions(result)
    _manifests(result, by_file)
    _async(result)
    _endpoints(result, by_file)
    result.risks.sort(key=lambda risk: (ORDER[risk.level], risk.id))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _callers(result, name):
    return [occ for occ in result.occurrences if occ.callee == name]


def _param_map(signature):
    """{'name': has_default} for a rendered signature."""
    inner = signature[signature.find("(") + 1: signature.rfind(")")] if "(" in signature else ""
    params = {}
    for piece in inner.split(","):
        piece = piece.strip()
        if not piece or piece in ("*", "/"):
            continue
        name = piece.split("=")[0].split(":")[0].strip().lstrip("*").strip()
        if not name:
            continue
        params[name] = "=" in piece
    return params


def _in_symbol(lineno, symbol):
    return symbol.lineno <= lineno <= max(symbol.end_lineno, symbol.lineno)


def _add(result, **kwargs):
    result.risks.append(Risk(**kwargs))


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


def _removed(result):
    for change in result.changes:
        if change.kind != "removed":
            continue
        symbol = change.symbol
        callers = _callers(result, symbol.short)
        if callers:
            first = callers[0]
            _add(
                result,
                id="R001",
                level="high",
                title=f"`{symbol.qualname}` was deleted and still has {len(callers)} call site(s)",
                detail="These calls raise NameError / ImportError at runtime.",
                file=first.file,
                line=first.lineno,
                symbol=symbol.qualname,
                evidence=first.text,
            )
        elif symbol.is_public:
            _add(
                result,
                id="R001",
                level="medium",
                title=f"public symbol `{symbol.qualname}` was deleted",
                detail="Nothing in this repo calls it. External users may.",
                file=change.file,
                line=symbol.lineno,
                symbol=symbol.qualname,
            )


def _signature(result):
    for change in result.changes:
        if change.kind != "signature" or change.before is None:
            continue
        symbol = change.symbol
        before = change.before
        old_params = _param_map(before.signature)
        new_params = _param_map(symbol.signature)
        callers = _callers(result, symbol.short)

        removed = [name for name in old_params if name not in new_params]
        required = [
            name for name, has_default in new_params.items()
            if not has_default and name not in old_params
        ]
        added_optional = [name for name in new_params if name not in old_params and name not in required]

        if removed:
            first = callers[0] if callers else None
            _add(
                result,
                id="R002",
                level="high" if callers else "medium",
                title=f"`{symbol.qualname}` lost parameter(s): {', '.join(removed)}",
                detail=f"signature was `{before.signature}`, now `{symbol.signature}`.",
                file=first.file if first else change.file,
                line=first.lineno if first else symbol.lineno,
                symbol=symbol.qualname,
                evidence=first.text if first else "",
            )
        elif required and callers:
            first = callers[0]
            _add(
                result,
                id="R002",
                level="high",
                title=f"`{symbol.qualname}` gained required parameter(s): {', '.join(required)}",
                detail=f"{len(callers)} call site(s) do not pass it. signature is `{symbol.signature}`.",
                file=first.file,
                line=first.lineno,
                symbol=symbol.qualname,
                evidence=first.text,
            )
        elif required or added_optional:
            what = ", ".join(required + added_optional)
            _add(
                result,
                id="R002",
                level="medium",
                title=f"`{symbol.qualname}` gained parameter(s): {what}",
                detail=f"`{before.signature}` -> `{symbol.signature}`",
                file=change.file,
                line=symbol.lineno,
                symbol=symbol.qualname,
            )


def _public_api(result):
    for change in result.changes:
        symbol = change.symbol
        if change.kind not in ("signature", "removed") or not symbol.is_public:
            continue
        if change.kind in ("signature", "removed") and not is_test_path(change.file):
            _add(
                result,
                id="R003",
                level="low",
                title=f"public API `{symbol.qualname}` changed",
                detail="Bump the version and mention it in the changelog, or it ships as a surprise.",
                file=change.file,
                line=symbol.lineno,
                symbol=symbol.qualname,
            )


def _serialization(result, by_file):
    for change in result.changes:
        symbol = change.symbol
        if not SERIAL_NAME.search(symbol.qualname):
            continue
        fd = by_file.get(change.file)
        if fd is None:
            continue

        previous = change.before or symbol
        before_keys = []
        for lineno, text in fd.removed:
            if _in_symbol(lineno, previous):
                before_keys.extend(match.group(2) for match in DICT_KEY.finditer(text))

        fresh = []
        for lineno, text in fd.added:
            if not _in_symbol(lineno, symbol):
                continue
            for match in DICT_KEY.finditer(text):
                if match.group(2) not in before_keys:
                    fresh.append((match.group(2), text))

        seen = set()
        for key, text in fresh:
            if key in seen:
                continue
            seen.add(key)
            _add(
                result,
                id="R004",
                level="medium",
                title=f"`{symbol.qualname}` now emits key `{key}`",
                detail=(
                    "Cached rows, stored JSON and older clients will not have it. "
                    "Readers that assume every key exists will break."
                ),
                file=change.file,
                line=symbol.lineno,
                symbol=symbol.qualname,
                evidence=text.strip(),
            )


def _config(result, by_file):
    for path, fd in by_file.items():
        if not CONFIG_FILE.search(path):
            continue
        for lineno, text in fd.added:
            if CONFIG_LINE.match(text) or ENV_LINE.search(text):
                _add(
                    result,
                    id="R005",
                    level="medium",
                    title="new configuration surface",
                    detail="Defaults must land everywhere before code reads them, or the rollout is half-broken.",
                    file=path,
                    line=lineno,
                    evidence=text.strip(),
                )


def _migrations(result, by_file):
    for path, fd in by_file.items():
        is_migration = bool(MIGRATION_PATH.search(path))
        for lineno, text in fd.added:
            if DDL.search(text):
                is_migration = True
        if not is_migration:
            continue
        evidence = next((t.strip() for _, t in fd.added if DDL.search(t)), "")
        _add(
            result,
            id="R006",
            level="high",
            title="schema change",
            detail="Old code may read the new shape during a rolling deploy. Check ordering and reversible steps.",
            file=path,
            line=fd.added[0][0] if fd.added else 0,
            evidence=evidence,
        )


def _swallowed(result, by_file):
    for path, fd in by_file.items():
        for position, (lineno, text) in enumerate(fd.added):
            match = EXCEPT.match(text)
            if not match:
                continue
            tail = match.group(1).strip()
            following = fd.added[position + 1][1].strip() if position + 1 < len(fd.added) else ""
            body = tail or following
            if body in ("pass", "...", "continue", "return"):
                _add(
                    result,
                    id="R007",
                    level="medium",
                    title="exception swallowed",
                    detail="A failure here becomes a silent no-op: green tests, wrong data.",
                    file=path,
                    line=lineno,
                    evidence=text.strip(),
                )


def _test_weakening(result, by_file):
    for path, fd in by_file.items():
        if not is_test_path(path):
            continue
        for lineno, text in fd.removed:
            if ASSERT.search(text):
                _add(
                    result,
                    id="R008",
                    level="high",
                    title="assertion removed from a test",
                    detail="The diff makes the suite pass by deleting the check. This is the classic agent move.",
                    file=path,
                    line=lineno,
                    evidence="- " + text.strip(),
                )
        for lineno, text in fd.added:
            if WEAKEN.search(text):
                _add(
                    result,
                    id="R008",
                    level="high",
                    title="test disabled or narrowed",
                    detail="skip / xfail / .only turns a failing test into a passing suite.",
                    file=path,
                    line=lineno,
                    evidence="+ " + text.strip(),
                )


def _exact_assertions(result):
    for ref in result.tests:
        if not ref.exact:
            continue
        _add(
            result,
            id="R009",
            level="high",
            title=f"test asserts an exact value of `{ref.symbol}`",
            detail="Any field or shape change fails this test, even when the behaviour is intended.",
            file=ref.file,
            line=ref.lineno,
            symbol=ref.symbol,
        )


def _manifests(result, by_file):
    for path in by_file:
        name = path.rsplit("/", 1)[-1]
        if name in DEPS:
            _add(
                result,
                id="R010",
                level="medium",
                title="dependency manifest changed",
                detail="Lockfile drift breaks other machines before it breaks this one.",
                file=path,
            )
        elif path.startswith(".github/workflows/"):
            _add(
                result,
                id="R011",
                level="low",
                title="CI configuration changed",
                detail="Widening a workflow is how a bypass gets merged quietly.",
                file=path,
            )


def _async(result):
    for change in result.changes:
        if change.kind != "async":
            continue
        callers = _callers(result, change.symbol.short)
        _add(
            result,
            id="R012",
            level="high" if callers else "medium",
            title=f"`{change.symbol.qualname}` changed between sync and async",
            detail=f"{len(callers)} caller(s) will keep a coroutine instead of a value.",
            file=callers[0].file if callers else change.file,
            line=callers[0].lineno if callers else change.symbol.lineno,
            symbol=change.symbol.qualname,
            evidence=callers[0].text if callers else "",
        )


def _endpoints(result, by_file):
    for path, fd in by_file.items():
        for lineno, text in fd.added:
            if ENDPOINT.search(text):
                _add(
                    result,
                    id="R013",
                    level="low",
                    title="new HTTP endpoint",
                    detail="Worth an explicit auth and rate-limit review before it is reachable.",
                    file=path,
                    line=lineno,
                    evidence=text.strip(),
                )
