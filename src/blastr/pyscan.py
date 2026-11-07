"""Python analysis: symbols, signatures, imports and call sites.

Uses only `ast` from the standard library, so blastr has zero dependencies and
never needs to compile or import the project it is looking at.
"""

from __future__ import annotations

import ast
import hashlib
from typing import Optional

from .model import CallSite, ModuleScan, Symbol


def scan(path: str, source: str, hash_bodies: bool = True) -> ModuleScan:
    mod = ModuleScan(file=path, lang="python", hash_bodies=hash_bodies)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        mod.ok = False
        mod.error = f"syntax error at line {exc.lineno}: {exc.msg}"
        return mod
    except ValueError as exc:  # embedded null bytes and friends
        mod.ok = False
        mod.error = f"unparseable: {exc}"
        return mod

    lines = source.splitlines()
    mod.exports = _exports(tree)
    for stmt in tree.body:
        _visit(stmt, "", False, mod, lines)
    return mod


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _src(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return "?"


def _digest(node) -> str:
    """Hash the AST, not the text: reformatting or a comment is not a change."""
    try:
        dumped = ast.dump(node, annotate_fields=False, include_attributes=False)
    except TypeError:  # pragma: no cover - very old / very new signatures
        dumped = ast.dump(node)
    return hashlib.sha1(dumped.encode("utf-8", "replace")).hexdigest()[:12]


def _exports(tree: ast.Module) -> set:
    out = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except Exception:
            continue
        if isinstance(value, (list, tuple)):
            out |= {v for v in value if isinstance(v, str)}
    return out


def signature(node, name: str) -> str:
    """Normalised parameter list, without type annotations.

    Annotations are dropped on purpose: re-typing `x: int` to `x: str` is not
    what breaks callers, and flagging it would be noise.
    """
    args = node.args
    posonly = list(getattr(args, "posonlyargs", []))
    positional = posonly + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)

    rendered = []
    for arg, default in zip(positional, defaults):
        piece = arg.arg
        if default is not None:
            piece += "=" + _src(default)
        rendered.append(piece)
    if posonly:
        rendered = rendered[: len(posonly)] + ["/"] + rendered[len(posonly):]

    parts = list(rendered)
    if args.vararg:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults or []):
        piece = arg.arg
        if default is not None:
            piece += "=" + _src(default)
        parts.append(piece)
    if args.kwarg:
        parts.append("**" + args.kwarg.arg)
    return f"{name}({', '.join(parts)})"


def _callee(func) -> tuple:
    if isinstance(func, ast.Name):
        return func.id, "name"
    if isinstance(func, ast.Attribute):
        return func.attr, "attr"
    if isinstance(func, ast.Call):
        return _callee(func.func)
    return "", "name"


def _target_names(node) -> list:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    out = []
    for t in targets:
        if isinstance(t, ast.Name):
            out.append(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            out.extend(x.id for x in t.elts if isinstance(x, ast.Name))
    return out


# ---------------------------------------------------------------------------
# traversal
# ---------------------------------------------------------------------------


def _visit(node, qual: str, in_class: bool, mod: ModuleScan, lines: list) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name = node.name
        qname = f"{qual}{name}"
        mod.symbols[qname] = Symbol(
            file=mod.file,
            qualname=qname,
            kind="method" if in_class else "function",
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            signature=signature(node, name),
            body_hash=_digest(node) if mod.hash_bodies else "",
            decorators=tuple(_src(d) for d in node.decorator_list),
            is_public=(not name.startswith("_")) or name in mod.exports,
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )
        for dec in node.decorator_list:
            _visit(dec, qual, False, mod, lines)
        for default in list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]:
            _visit(default, qual, False, mod, lines)
        for stmt in node.body:
            _visit(stmt, qname + ".", False, mod, lines)
        return

    if isinstance(node, ast.ClassDef):
        qname = f"{qual}{node.name}"
        bases = ", ".join(_src(b) for b in node.bases)
        mod.symbols[qname] = Symbol(
            file=mod.file,
            qualname=qname,
            kind="class",
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            signature=f"{node.name}({bases})",
            body_hash=_digest(node) if mod.hash_bodies else "",
            decorators=tuple(_src(d) for d in node.decorator_list),
            is_public=(not node.name.startswith("_")) or node.name in mod.exports,
        )
        for base in node.bases:
            _visit(base, qual, False, mod, lines)
        for stmt in node.body:
            _visit(stmt, qname + ".", True, mod, lines)
        return

    if isinstance(node, (ast.Import, ast.ImportFrom)):
        _record_import(node, mod)
        return

    if isinstance(node, ast.Call):
        name, kind = _callee(node.func)
        if name:
            lineno = node.lineno
            text = lines[lineno - 1].strip()[:160] if 0 < lineno <= len(lines) else ""
            mod.calls.append(
                CallSite(
                    file=mod.file,
                    lineno=lineno,
                    callee=name,
                    caller=qual.rstrip(".") or "<module>",
                    text=text,
                    kind=kind,
                )
            )

    if isinstance(node, (ast.Assign, ast.AnnAssign)) and qual == "":
        for name in _target_names(node):
            if name == "__all__" or name in mod.symbols:
                continue
            mod.symbols[name] = Symbol(
                file=mod.file,
                qualname=name,
                kind="constant",
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", node.lineno) or node.lineno,
                signature=name,
                body_hash=_digest(node) if mod.hash_bodies else "",
                is_public=not name.startswith("_"),
            )

    for child in ast.iter_child_nodes(node):
        _visit(child, qual, in_class, mod, lines)


def _record_import(node, mod: ModuleScan) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            mod.imports[local] = (alias.name, alias.asname or alias.name.split(".")[-1])
        return
    module = node.module or ""
    prefix = "." * (node.level or 0)
    for alias in node.names:
        if alias.name == "*":
            continue
        mod.imports[alias.asname or alias.name] = (prefix + module, alias.name)
