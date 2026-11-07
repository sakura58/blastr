"""Render a Result as terminal text, PR markdown, or stable JSON."""

from __future__ import annotations

import json
import os
import shutil
import sys

from . import __version__

KIND_LABEL = {
    "signature": "sig",
    "removed": "del",
    "added": "new",
    "body": "body",
    "decorator": "dec",
    "async": "async",
    "touched": "touch",
    "caller": "call",
}

LEVEL_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


class Paint:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text):
        return self("1", text)

    def dim(self, text):
        return self("2", text)

    def red(self, text):
        return self("31", text)

    def green(self, text):
        return self("32", text)

    def yellow(self, text):
        return self("33", text)

    def cyan(self, text):
        return self("36", text)

    def level(self, level, text):
        return {"high": self.red, "medium": self.yellow, "low": self.cyan}.get(level, self.dim)(text)


def _cut(text: str, width: int, ell: str = "…") -> str:
    if len(text) <= width:
        return text
    return text[: width - len(ell)] + ell


def _terminal_width(default=100):
    try:
        return max(70, min(shutil.get_terminal_size().columns, 140))
    except Exception:  # pragma: no cover
        return default


def color_enabled(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_dict(result) -> dict:
    return {
        "schema": "blastr/v1",
        "version": __version__,
        "root": result.root,
        "stats": result.stats,
        "verdict": {
            "level": result.level,
            "likely_breaks": result.breaks,
            "silent_risks": result.silent,
            "checks": len(result.risks),
        },
        "direct": [
            {
                "file": change.file,
                "symbol": change.symbol.qualname,
                "kind": change.kind,
                "signature": change.symbol.signature,
                "previous_signature": change.before.signature if change.before else None,
                "line": change.symbol.lineno,
            }
            for change in result.changes
        ],
        "blast": [
            {
                "file": occ.file,
                "line": occ.lineno,
                "caller": occ.caller,
                "callee": occ.callee,
                "hop": occ.hop,
                "name_only_match": occ.weak,
                "code": occ.text,
            }
            for occ in result.occurrences
        ],
        "tests": [
            {"file": ref.file, "line": ref.lineno, "symbol": ref.symbol, "exact_assertion": ref.exact}
            for ref in result.tests
        ],
        "uncovered": result.uncovered,
        "risks": [
            {
                "id": risk.id,
                "level": risk.level,
                "title": risk.title,
                "detail": risk.detail,
                "file": risk.file,
                "line": risk.line,
                "symbol": risk.symbol,
                "evidence": risk.evidence,
            }
            for risk in result.risks
        ],
        "notes": result.notes,
    }


def render_json(result) -> str:
    return json.dumps(to_dict(result), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# terminal
# ---------------------------------------------------------------------------


def render_text(result, color: bool = True, ascii_only: bool = False) -> str:
    paint = Paint(color)
    width = _terminal_width()
    ell = "..." if ascii_only else "…"
    minus = "-" if ascii_only else "−"
    arrow = "->" if ascii_only else "→"
    dot = "|" if ascii_only else "·"

    def cut(text, span):
        return _cut(text, span, ell)

    out = []

    stats = result.stats
    head = " ".join(
        filter(
            None,
            [
                paint.bold(f"blastr {__version__}"),
                paint.dim(dot),
                f"{stats.get('files', 0)} files",
                paint.dim(dot),
                paint.green(f"+{stats.get('additions', 0)}") + " " + paint.red(f"{minus}{stats.get('deletions', 0)}"),
                paint.dim(dot),
                f"{stats.get('symbols', 0)} symbols",
                paint.dim(dot),
                f"{stats.get('call_sites', 0)} call sites",
                paint.dim(dot),
                f"{stats.get('hops', 0)} hops",
            ],
        )
    )
    out.append(head)

    if not result.changes:
        out.append("")
        out.append(paint.yellow("no analyzable changes") + paint.dim(" — nothing to map (see notes below)"))
        return _finish(out, result, paint)

    out.append("")
    out.append(paint.bold("changed") + paint.dim(f"  ({len(result.changes)})"))
    for change in result.changes:
        kind = KIND_LABEL.get(change.kind, change.kind)
        tone = paint.red if change.kind in ("signature", "removed", "async") else paint.dim
        suffix = ""
        if change.kind == "signature" and change.before is not None:
            suffix = paint.dim(arrow + " ") + cut(change.symbol.signature, 48)
        elif change.kind == "removed" and change.before is not None:
            suffix = paint.dim("was ") + cut(change.before.signature or change.symbol.qualname, 40)
        out.append(
            "  "
            + tone(f"{kind:<5}")
            + cut(change.file, 26).ljust(27)
            + cut(change.symbol.qualname, 24).ljust(25)
            + suffix
        )

    if result.occurrences:
        out.append("")
        out.append(
            paint.bold("blast radius")
            + paint.dim(f"  ({len(result.occurrences)} call sites, {result.stats.get('hops', 0)} hops)")
        )
        budget = 40
        for occ in result.occurrences[:budget]:
            marker = paint.dim(f"h{occ.hop}")
            weak = paint.dim(" name-only") if occ.weak else ""
            where = f"{occ.file}:{occ.lineno}"
            out.append(
                "  "
                + marker.ljust(4)
                + cut(where, 30).ljust(31)
                + cut(occ.caller, 20).ljust(21)
                + cut(occ.text, max(20, width - 62))
                + weak
            )
        if len(result.occurrences) > budget:
            out.append(paint.dim(f"  {ell} {len(result.occurrences) - budget} more (see --json)"))

    if result.tests or result.uncovered:
        out.append("")
        out.append(paint.bold("tests") + paint.dim(f"  ({len(result.tests)} referencing, {len(result.uncovered)} uncovered)"))
        for ref in result.tests[:20]:
            tag = paint.red("exact") if ref.exact else paint.cyan("hit  ")
            out.append(
                "  "
                + tag
                + "  "
                + cut(f"{ref.file}:{ref.lineno}", 32).ljust(33)
                + cut(ref.symbol, 26)
                + (paint.dim("  exact-value assertion") if ref.exact else "")
            )
        for name in result.uncovered[:10]:
            out.append("  " + paint.dim("none ") + "  " + paint.dim(cut(name, 60)))

    if result.risks:
        out.append("")
        out.append(paint.bold("risks") + paint.dim(f"  ({len(result.risks)})"))
        for risk in result.risks:
            out.append(
                "  "
                + paint.level(risk.level, risk.level.upper().ljust(6))
                + " "
                + paint.dim(f"{risk.id}  ")
                + risk.title
            )
            evidence = risk.evidence.strip()
            if evidence:
                where = f"{risk.file}:{risk.line}" if risk.file else ""
                out.append("        " + paint.dim(f"{arrow} {where}  {cut(evidence, max(30, width - 20))}"))

    return _finish(out, result, paint, arrow=arrow)


def _finish(out, result, paint, arrow="→"):
    if result.notes:
        for note in result.notes:
            out.append(paint.dim(f"note: {note}"))
    out.append("")
    verdict = result.level.upper() if result.level != "none" else "clear"
    label = {"HIGH": "REVIEW", "MEDIUM": "REVIEW", "LOW": "skim", "CLEAR": "clear"}.get(verdict, verdict)
    out.append(
        paint.bold("verdict")
        + "  "
        + f"{result.breaks} likely break(s) · {result.silent} silent risk(s) · {len(result.risks)} finding(s)"
        + paint.dim(f"  {arrow}  ")
        + paint.level(result.level, label)
    )
    return "\n".join(line.rstrip() for line in out)


# ---------------------------------------------------------------------------
# markdown (PR comment)
# ---------------------------------------------------------------------------


def render_markdown(result) -> str:
    stats = result.stats
    out = []
    headline = {"high": "⚠️ review before merge", "medium": "🟠 worth a look", "low": "🟡 minor", "none": "clear"}[result.level]
    out.append(f"## blastr · {headline}")
    out.append("")
    out.append(
        f"`{stats.get('files', 0)} files` · `+{stats.get('additions', 0)} −{stats.get('deletions', 0)}` · "
        f"`{stats.get('symbols', 0)} symbols` · `{stats.get('call_sites', 0)} call sites` · "
        f"`{stats.get('hops', 0)} hops`"
    )

    if result.risks:
        out.append("")
        out.append("### Risks")
        out.append("")
        out.append("| | rule | finding | where |")
        out.append("|:--:|:--:|---|---|")
        for risk in result.risks:
            where = f"`{risk.file}:{risk.line}`" if risk.file else "—"
            out.append(
                f"| {LEVEL_ICON.get(risk.level, '•')} | {risk.id} | {risk.title} | {where} |"
            )

    if result.changes:
        out.append("")
        out.append(f"<details><summary>Changed symbols ({len(result.changes)})</summary>")
        out.append("")
        for change in result.changes:
            signature = f" — `{change.symbol.signature}`" if change.kind == "signature" else ""
            out.append(f"- **{KIND_LABEL.get(change.kind, change.kind)}** `{change.symbol.qualname}` `{change.file}`{signature}")
        out.append("")
        out.append("</details>")

    if result.occurrences:
        out.append("")
        out.append(f"<details><summary>Blast radius ({len(result.occurrences)} call sites)</summary>")
        out.append("")
        for occ in result.occurrences[:100]:
            weak = " _name-only match_" if occ.weak else ""
            out.append(f"- `{occ.file}:{occ.lineno}` **{occ.caller}** → `{occ.callee}` (hop {occ.hop}){weak}")
        if len(result.occurrences) > 100:
            out.append(f"- … {len(result.occurrences) - 100} more")
        out.append("")
        out.append("</details>")

    if result.uncovered:
        out.append("")
        out.append(f"**No test references:** {', '.join('`' + name + '`' for name in result.uncovered[:15])}")

    if result.notes:
        out.append("")
        out.append("<sub>" + " · ".join(result.notes) + "</sub>")

    out.append("")
    out.append("<sub>generated by <b>blastr</b> — blast radius for AI-made diffs</sub>")
    return "\n".join(out)
