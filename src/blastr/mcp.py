"""Minimal MCP server over stdio.

One tool, `blast_radius`. Nothing else — an agent should be able to mount this
and use it without reading documentation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import __version__, diffparse, gitio
from .graph import analyze
from .report import render_markdown

TOOL = {
    "name": "blast_radius",
    "description": (
        "Report the blast radius of a code change before it is committed: which symbols changed, "
        "every call site that reaches them, tests that reference them, and high/medium risks "
        "(removed parameters, new serialized keys, weakened tests, schema changes). "
        "Call this after editing files and before claiming the work is done."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "diff": {"type": "string", "description": "unified diff text; omit to use the repo's git state"},
            "staged": {"type": "boolean", "description": "diff the index instead of the working tree"},
            "rev": {"type": "string", "description": "git revision to diff against, e.g. HEAD~1"},
            "depth": {"type": "integer", "description": "caller hops to walk (default 2)"},
            "root": {"type": "string", "description": "repository root; defaults to the current directory"},
        },
        "additionalProperties": False,
    },
}


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            continue
        response = _handle(request)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def _error(ident, code, message):
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def _handle(request):
    method = request.get("method")
    ident = request.get("id")
    params = request.get("params") or {}

    if ident is None and str(method).startswith("notifications/"):
        return None

    try:
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "blastr", "version": __version__},
            }
        elif method == "tools/list":
            result = {"tools": [TOOL]}
        elif method == "tools/call":
            return _call(ident, params)
        elif method == "ping":
            result = {}
        else:
            return _error(ident, -32601, f"unknown method: {method}")
    except Exception as exc:  # a tool crash must not kill the session
        return _error(ident, -32603, f"{type(exc).__name__}: {exc}")

    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _call(ident, params):
    if params.get("name") != "blast_radius":
        return _error(ident, -32602, f"unknown tool: {params.get('name')}")

    arguments = params.get("arguments") or {}
    root = Path(arguments.get("root") or os.getcwd()).resolve()

    text = arguments.get("diff")
    if text is None:
        text, error = gitio.load_diff(
            root, staged=bool(arguments.get("staged")), rev=arguments.get("rev")
        )
        if error:
            return _text(ident, f"blastr could not read a diff: {error}")

    diffs = diffparse.parse(text or "")
    if not diffs:
        return _text(ident, "blastr: the diff is empty, nothing to map")

    before = gitio.before_images(root, diffs, staged=bool(arguments.get("staged")), rev=arguments.get("rev"))
    try:
        depth = max(1, int(arguments.get("depth") or 2))
    except (TypeError, ValueError):
        depth = 2

    result = analyze(root, diffs, before, depth=depth)
    return _text(ident, render_markdown(result))


def _text(ident, content):
    return {
        "jsonrpc": "2.0",
        "id": ident,
        "result": {"content": [{"type": "text", "text": content}], "isError": False},
    }
