"""JavaScript / TypeScript analysis.

Deliberately heuristic: no parser bundled, no `node_modules` traversal, no type
checker. It is good enough to answer "who imports and calls this export", which
is the question that matters for a blast radius. Python is the precise path;
treat JS/TS numbers as a strong hint rather than ground truth.
"""

from __future__ import annotations

import hashlib
import re

from .model import CallSite, ModuleScan, Symbol

FUNC = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
)
ARROW = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*=>"
)
CLASS = re.compile(r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)([^{]*)\{")
METHOD = re.compile(
    r"^\s+(?:(?:public|private|protected|static|async|readonly|override)\s+)*"
    r"([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::[^{]+)?\{"
)
IMPORT_NAMED = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
IMPORT_DEFAULT = re.compile(r"import\s+([A-Za-z_$][\w$]*)\s*(?:,\s*\{[^}]*\})?\s*from\s*['\"]([^'\"]+)['\"]")
REQUIRE = re.compile(r"(?:const|let|var)\s+(?:\{([^}]*)\}|([A-Za-z_$][\w$]*))\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)")
CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")

KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "function", "typeof",
    "await", "new", "delete", "void", "in", "of", "do", "else", "try",
    "finally", "class", "const", "let", "var", "import", "export", "default",
    "case", "break", "continue", "throw", "yield", "super", "this", "async",
    "static", "require",
}


def scan(path: str, source: str, hash_bodies: bool = True) -> ModuleScan:
    mod = ModuleScan(file=path, lang="js", hash_bodies=hash_bodies)
    lines = source.splitlines()
    offsets = _line_offsets(source)

    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith(("//", "/*", "*")):
            continue
        indent = len(line) - len(stripped)
        if indent != 0:
            continue

        match = FUNC.match(stripped)
        if match:
            _add_function(mod, path, source, lines, offsets, idx, match.group(1), match.group(2), line)
            continue
        match = ARROW.match(stripped)
        if match:
            name = match.group(1)
            params = match.group(2) if match.group(2) is not None else match.group(3)
            _add_function(mod, path, source, lines, offsets, idx, name, params, line)
            continue
        match = CLASS.match(stripped)
        if match:
            _add_class(mod, path, source, lines, offsets, idx, match.group(1), match.group(2), line)
            continue

    # second pass: call sites and imports, skipping the definition lines themselves
    definitions = {(symbol.lineno, symbol.short) for symbol in mod.symbols.values()}
    for idx, line in enumerate(lines):
        _collect_calls(mod, line, idx + 1, definitions)
        _collect_imports(mod, line)

    mod.exports = {s.short for s in mod.symbols.values() if s.is_public}
    return mod


# ---------------------------------------------------------------------------


def _line_offsets(text: str) -> list:
    offsets = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def _block_end(text: str, start: int) -> int:
    """Index of the brace that closes the block opening at/after `start`."""
    depth = 0
    quote = None
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text) - 1


def _body_end(text: str, start: int, line_no: int) -> int:
    brace = text.find("{", start)
    newline = text.find("\n", start)
    if brace == -1 or (newline != -1 and newline < brace):
        return line_no
    close = _block_end(text, brace)
    return text.count("\n", 0, close) + 1


def _normalise_params(raw: str) -> str:
    params = re.sub(r"\s+", " ", raw or "").strip()
    return params


def _add_function(mod, path, source, lines, offsets, idx, name, params, line) -> None:
    qual = name
    if qual in mod.symbols:
        return
    start = offsets[idx]
    end_line = _body_end(source, start + len(line) - len(line.lstrip()), idx + 1)
    body = source[start:offsets[min(end_line, len(offsets) - 1)]]
    indent = len(line) - len(line.lstrip())
    mod.symbols[qual] = Symbol(
        file=path,
        qualname=qual,
        kind="function",
        lineno=idx + 1,
        end_lineno=end_line,
        signature=f"{name}({_normalise_params(params)})",
        body_hash=hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:12] if mod.hash_bodies else "",
        is_public="export" in line or indent == 0,
    )


def _add_class(mod, path, source, lines, offsets, idx, name, heritage, line) -> None:
    qual = name
    start = offsets[idx]
    end_line = _body_end(source, start + len(line) - len(line.lstrip()), idx + 1)
    body = source[start:offsets[min(end_line, len(offsets) - 1)]]
    mod.symbols[qual] = Symbol(
        file=path,
        qualname=qual,
        kind="class",
        lineno=idx + 1,
        end_lineno=end_line,
        signature=f"{name}{heritage.strip()}",
        body_hash=hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:12] if mod.hash_bodies else "",
        is_public="export" in line,
    )
    for offset in range(idx + 1, min(end_line, len(lines))):
        match = METHOD.match(lines[offset])
        if not match:
            continue
        method = match.group(1)
        if method in KEYWORDS or method == "constructor":
            continue
        mqual = f"{qual}.{method}"
        if mqual in mod.symbols:
            continue
        mod.symbols[mqual] = Symbol(
            file=path,
            qualname=mqual,
            kind="method",
            lineno=offset + 1,
            end_lineno=_body_end(source, offsets[offset], offset + 1),
            signature=f"{method}({_normalise_params(match.group(2))})",
            body_hash=hashlib.sha1(lines[offset].encode("utf-8", "replace")).hexdigest()[:12] if mod.hash_bodies else "",
            is_public=not method.startswith("_"),
        )


def _collect_calls(mod, line: str, lineno: int, definitions=frozenset()) -> None:
    if "(" not in line:
        return
    seen = set()
    for match in CALL.finditer(line):
        name = match.group(1)
        if name in KEYWORDS or name in seen:
            continue
        if (lineno, name) in definitions:
            continue
        seen.add(name)
        mod.calls.append(
            CallSite(
                file=mod.file,
                lineno=lineno,
                callee=name,
                caller="<module>",
                text=line.strip()[:160],
                kind="name",
            )
        )


def _collect_imports(mod, line: str) -> None:
    for match in IMPORT_NAMED.finditer(line):
        module = match.group(2)
        for part in match.group(1).split(","):
            piece = part.strip()
            if not piece:
                continue
            bits = piece.split(" as ")
            original = bits[0].strip()
            local = bits[-1].strip()
            mod.imports[local] = (module, original)
    for match in IMPORT_DEFAULT.finditer(line):
        mod.imports.setdefault(match.group(1), (match.group(2), "default"))
    for match in REQUIRE.finditer(line):
        module = match.group(3)
        named, single = match.group(1), match.group(2)
        if named:
            for part in named.split(","):
                piece = part.strip()
                if piece:
                    mod.imports[piece.split(":")[0].strip()] = (module, piece.split(":")[0].strip())
        elif single:
            mod.imports[single] = (module, "default")
