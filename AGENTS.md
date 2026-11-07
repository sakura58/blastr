# AGENTS.md

Instructions for AI agents working on **blastr** itself. If you are an agent
*using* blastr, skip to the last section.

## What this project is

A zero-dependency Python CLI that answers "what will this diff break?". It must
stay small, fast, and honest: every finding carries a file and a line, and
anything uncertain is labelled instead of guessed.

## Hard rules

- **stdlib only.** No runtime dependencies, ever. Tests use `unittest`, not pytest.
- **Python 3.9+.** No `match`, no `X | Y` at runtime, no `tomllib`.
- **Findings need evidence.** Every `Risk` carries `file` + `line` (and `evidence`
  when a source line exists). A rule that cannot point at a line is a rule that
  should not fire.
- **JSON is a contract.** `schema: blastr/v1` keys are append-only. Do not rename or
  remove a field; add one and bump the minor version.
- **Never invent certainty.** Name-only call resolution sets `weak=True`, which
  renders as `name-only`. Keep that distinction.

## Layout

| path | role |
|:--|:--|
| `src/blastr/diffparse.py` | unified diff parsing + before-image reconstruction |
| `src/blastr/pyscan.py` | Python symbols, signatures, imports, calls (stdlib `ast`) |
| `src/blastr/jsscan.py` | JS/TS heuristics (brace matching + regex) |
| `src/blastr/graph.py` | repo index, caller BFS, test correlation |
| `src/blastr/rules.py` | R001–R013, one function per rule |
| `src/blastr/report.py` | terminal / markdown / JSON rendering |
| `src/blastr/gitio.py` | git plumbing + the no-git fallback |
| `src/blastr/mcp.py` | MCP server on stdio, one tool |

## Adding a rule

1. Add `_my_rule(result, by_file)` in `rules.py`, append a `Risk` with a new id.
2. Pick the level deliberately: `high` = "will break at runtime", `medium` =
   "silently wrong or risky", `low` = "someone should read this".
3. Add a test in `tests/` that fails without the rule.
4. Add the row to the rules table in `README.md`.

## Before you say it is done

```bash
python -m unittest discover -s tests     # all green
python examples/demo.py                  # output still reads like the README
```

If you changed any flag, output section, or rule id, update `README.md` in the
same change. If you changed the JSON shape, update both the README sample and
`to_dict()`.

## Using blastr as an agent

Before claiming a task is complete:

```bash
blastr --staged --json
```

Read `risks` first. `R001`/`R002` mean you changed a signature that callers still
use — go fix those callers, do not edit the report. `R008` means a test was
weakened; restore the assertion instead of the green checkmark.
