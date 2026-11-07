<div align="center">

# blastr

**A diff says what changed. blastr says what that change hits.**

[![python](https://img.shields.io/badge/python-3.9%2B-3776ab)](https://www.python.org)
[![dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](#how-it-works)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![tests](https://github.com/sakura58/blastr/actions/workflows/ci.yml/badge.svg)](https://github.com/sakura58/blastr/actions/workflows/ci.yml)

</div>

---

You turned `create_user(name, email)` into `create_user(name, email, role)`.
Tests pass. The diff is four lines. Eleven call sites are about to raise
`TypeError`, and nine of them live in files you never opened.

That gap is where AI-written code goes wrong. An agent can produce a change in
seconds; nobody can hold the whole call graph in their head while reviewing it.
`blastr` closes the gap: give it a diff, get back the symbols you changed, every
call site that reaches them, the tests that touch them, and the handful of things
that are about to break.

```console
$ blastr
blastr 0.1.0 · 2 files · +6 −5 · 4 symbols · 4 call sites · 2 hops

changed  (4)
  sig  core/user.py               User.__init__            → __init__(self, name, email, role='member')
  body core/user.py               User.to_dict
  body core/user.py               User.from_dict
  sig  api/handlers.py            create_user              → create_user(name, email, role)

blast radius  (4 call sites, 2 hops)
  h1  api/handlers.py:6              create_user          return user.to_dict…
  h1  tests/test_user.py:6           test_to_dict         assert user.to_dict…
  h1  scripts/seed.py:5              seed                 return [User.from_d…
  h1  api/admin.py:5                 admin_create         return create_user(…

tests  (2 referencing, 2 uncovered)
  hit    tests/test_user.py:5             User.__init__
  exact  tests/test_user.py:6             User.to_dict  exact-value assertion
  none   User.from_dict
  none   create_user

risks  (5)
  HIGH   R002  `create_user` gained required parameter(s): role
        → api/admin.py:5  return create_user(user_name, user_email)
  HIGH   R009  test asserts an exact value of `User.to_dict`
  MEDIUM R002  `User.__init__` gained parameter(s): role
  MEDIUM R004  `User.to_dict` now emits key `role`
        → core/user.py:7  return {"name": self.name, "email": self.email, "role": sel…
  LOW    R003  public API `create_user` changed

verdict  2 likely break(s) · 2 silent risk(s) · 5 finding(s)  →  REVIEW
```

No LLM. No index. No daemon. One process, a fraction of a second, and a diff you
can actually review.

## Install

```bash
pipx install blastr        # isolated, recommended for a CLI
uvx blastr --staged        # or run it without installing
pip install blastr         # or into the current environment
```

Python 3.9+. Zero dependencies — not even a parser library.

## Usage

```bash
blastr                     # working tree vs HEAD
blastr --staged            # what this commit would do
blastr --rev main          # what this branch would do
blastr --diff fix.patch    # any patch, from CI or from an agent
blastr --json              # stable schema for tools
blastr --markdown          # a ready-to-post PR comment
blastr --fail-on high      # exit 2 when something is likely broken
blastr --depth 3           # walk one more caller hop
blastr --mcp               # expose it to agents over MCP
```

`--diff` accepts `-` for stdin, so it slots into any pipeline:

```bash
git diff | blastr --diff - --json
```

## What it reports

**Direct changes** — every symbol the diff touched, and *how*: `sig` (signature),
`body`, `dec` (decorator), `async`, `new`, `del`, `touch`. Comments and
reformatting are not changes: Python bodies are compared as parsed ASTs.

**Blast radius** — call sites that reach the changed symbols, up to N hops, including
files the diff never touched. Resolution is import-aware; when a call can only be
matched by name it is labelled `name-only` instead of pretending to be certain.

**Tests** — which tests mention the symbol, which of them assert an *exact* value
(those will fail even when the change is intended), and which changed symbols no
test refers to at all.

**Risks** — thirteen rules, each with a file, a line, and the evidence line:

| rule | fires on | level |
|:--|:--|:--|
| `R001` | symbol deleted, call sites remain | high |
| `R002` | parameter removed, or a new required one, with callers | high |
| `R003` | public API signature/removal | low |
| `R004` | serializer starts emitting a new key | medium |
| `R005` | new config constant or env var | medium |
| `R006` | schema / migration change | high |
| `R007` | exception swallowed (`except: pass`) | medium |
| `R008` | test assertion deleted, or test skipped/narrowed | high |
| `R009` | test asserts an exact value of a changed symbol | high |
| `R010` | dependency manifest changed | medium |
| `R011` | CI workflow changed | low |
| `R012` | a function flipped between sync and async | high |
| `R013` | new HTTP endpoint | low |

Machine-readable output is versioned and stable:

```json
{
  "schema": "blastr/v1",
  "verdict": { "level": "high", "likely_breaks": 2, "silent_risks": 2, "checks": 5 },
  "direct": [{ "file": "api/handlers.py", "symbol": "create_user", "kind": "signature" }],
  "blast": [{ "file": "api/admin.py", "line": 5, "callee": "create_user", "hop": 1, "name_only_match": false }],
  "risks": [{ "id": "R002", "level": "high", "title": "`create_user` gained required parameter(s): role", "file": "api/admin.py", "line": 5 }]
}
```

## Use it from an agent

This is the intended use. Register `blastr` as an MCP server and the agent gets a
`blast_radius` tool — usually the difference between "I'm done" and "I'm done
correctly".

```json
{
  "mcpServers": {
    "blastr": {
      "command": "blastr",
      "args": ["--mcp"]
    }
  }
}
```

The tool takes the diff (or reads the repo's git state), returns markdown, and
tells the agent which call sites it just orphaned. Add one line to `AGENTS.md`
and it becomes policy:

```markdown
Before saying a task is done, run `blastr --staged`. If R001 or R002 fires, you
changed a signature something still calls — go update the callers.
```

## In CI

```yaml
# .github/workflows/blastr.yml
- run: pipx install blastr
- run: blastr --rev origin/main --markdown >> "$GITHUB_STEP_SUMMARY"
- run: blastr --rev origin/main --fail-on high
```

The `--markdown` output is a self-contained PR comment: a risk table, then
collapsible sections for changed symbols and the full call-site list.

## How it works

- **Python** — parsed with the stdlib `ast`. Symbols, parameter lists, imports and
  call sites are exact; body changes are hashed from the AST, so reformatting and
  comments never show up as changes.
- **JavaScript / TypeScript** — token heuristics, no bundled parser. Good enough for
  "who imports and calls this", honest about being a hint.
- **Before-image** — `git show` when git is around, and when it is not, the diff is
  reverse-applied to the files on disk. That is why `--diff patch.diff` works inside
  a container that only has the patch.
- **Scope** — the whole repo is read once for names, but only plausible files are
  parsed. Parsing CPython's 688-module stdlib takes ~2.5s; a normal diff touches a
  handful of files, so runs are effectively instant.

## Honest limits

- Resolution is name-based, not a type checker. Dynamic dispatch, `getattr`,
  dependency injection and decorators that rename things can under- or over-report.
  Weak matches are labelled rather than hidden.
- JS/TS is heuristic. Treat it as a strong hint, not ground truth.
- "No test references it" is not the same as "untested" — there is no coverage data
  yet (see roadmap).
- Renames across files rely on `git diff -M`. If git is not available, a rename looks
  like a delete plus an add.
- Very large monorepos hit a 4,000-file read cap so it stays fast.

## Roadmap

- [ ] ingest `coverage.py` / `lcov` to report genuinely unexecuted lines
- [ ] Go and Ruby analyzers
- [ ] `--baseline`: report only what is new relative to `main`
- [ ] a thin GitHub Action that posts the comment itself
- [ ] `--explain R002` to show the full evidence chain for one finding

## 中文说明

`blastr` 回答一个具体问题：**这次改动会打到谁？**

给它一个 diff（或让它读 git 状态），它会输出四件事：改了哪些符号、这些符号还有哪些调用点（包含你没打开过的文件）、哪些测试引用了它们（尤其是断言了精确值、一改必挂的那种）、以及 13 条规则筛出的风险（删了参数、新增了序列化字段、测试被削弱、schema 变更……）。

设计上的取舍：不调用大模型、不建索引、零依赖，纯静态分析；参数变更、调用点、序列化字段这些都带行号证据，可以直接贴进 PR。Python 走标准库 AST，JS/TS 是启发式，匹配不确定会明确标注 `name-only`。

最适合的用法是接成 MCP 工具，让 agent 在说"做完了"之前先跑一遍。

## License

MIT
