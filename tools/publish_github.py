"""Publish blastr to GitHub without git installed.

Uses the GitHub REST API (Git Data API) to create the repository and push every
file as a single commit, then optionally cuts a release.

    # token from env, or from .github_token in the repo root
    python tools/publish_github.py --repo blastr --dry-run
    python tools/publish_github.py --repo blastr --public --release

Token scopes: classic PAT with `repo`. Fine-grained PAT needs
"Contents: read and write" plus permission to create repositories.
Revoke it when you are done.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = "https://api.github.com"

SKIP_DIRS = {".git", "__pycache__", ".demo", "_work", "dist", "build", ".venv", "venv"}
SKIP_SUFFIX = (".pyc", ".pyo")
SKIP_NAMES = {".github_token", "demo_out.txt", "demo_check.txt", "publish.log"}

DESCRIPTION = (
    "Blast radius for a diff — who calls what you just changed. "
    "Zero-dependency CLI + MCP tool for AI coding agents."
)
TOPICS = [
    "git", "diff", "code-review", "static-analysis", "impact-analysis",
    "ai-agents", "mcp", "cli", "python", "developer-tools",
]

RELEASE_NOTES = """\
`blastr` tells you what a diff will hit, not just what it changed.

- changed symbols with the kind of change (`sig`, `body`, `del`, `async`, …)
- every call site in the blast radius, including files the diff never touched
- tests that reference the symbols, and which assert exact values
- 13 rules (R001–R013), each with a file:line and the evidence line
- `--json` for tools, `--markdown` for PR comments, `--mcp` for agents

Zero dependencies. Python 3.9+. Works without git when you hand it a patch.
"""


class ApiError(Exception):
    def __init__(self, method, path, status, detail):
        super().__init__(f"GitHub API {method} {path} -> {status}: {detail}")
        self.status = status
        self.detail = detail


class GitHub:
    def __init__(self, token: str):
        self.token = token

    def call(self, method: str, path: str, payload=None):
        url = path if path.startswith("http") else API + path
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "blastr-publish")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", "replace")
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise ApiError(method, path, exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise SystemExit(
                f"cannot reach api.github.com ({exc.reason}). "
                "If this machine has no outbound network, use the git route in PUBLISH.md."
            ) from exc

    def get_or_none(self, path):
        try:
            return self.call("GET", path)
        except ApiError as exc:
            if exc.status == 404:
                return None
            raise


def looks_like_token(token: str) -> bool:
    """Cheap sanity check, so a placeholder fails here instead of with a 401."""
    if len(token) < 20:
        return False
    return token.startswith(("ghp_", "gho_", "ghu_", "ghs_", "github_pat_"))


def has_commits(gh, owner: str, repo: str) -> bool:
    """An empty repository answers 409 here, and rejects blob creation."""
    try:
        return bool(gh.call("GET", f"/repos/{owner}/{repo}/commits?per_page=1"))
    except ApiError as exc:
        if exc.status in (404, 409):
            return False
        raise


def collect() -> list:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        folders = rel.parts[:-1]
        if any(part in SKIP_DIRS for part in folders):
            continue
        # never ship tooling caches or local runtimes (.py39, .venv, ...)
        if any(part.startswith(".") and part != ".github" for part in folders):
            continue
        if path.name in SKIP_NAMES or path.name.startswith(".tmp_"):
            continue
        if path.suffix in SKIP_SUFFIX:
            continue
        files.append(rel)
    return files


def rewrite_owner(owner: str) -> None:
    """Replace the OWNER placeholder so badges and links point somewhere real."""
    for name in ("pyproject.toml", "README.md"):
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        if "OWNER" in text:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text.replace("OWNER", owner))
            print(f"  rewrote OWNER -> {owner} in {name}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="publish blastr to GitHub over the REST API")
    parser.add_argument("--repo", default="blastr")
    parser.add_argument("--owner", help="defaults to the token's own user")
    parser.add_argument("--public", action="store_true", help="create a public repo (default: private)")
    parser.add_argument("--release", action="store_true", help="tag v0.1.0 and create a release")
    parser.add_argument("--message", default="blastr 0.1.0 — blast radius for a diff")
    parser.add_argument("--token", help="token; defaults to $GITHUB_TOKEN or .github_token")
    parser.add_argument("--squash", action="store_true", help="replace history with a single root commit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    files = collect()
    total = sum((ROOT / rel).stat().st_size for rel in files)
    print(f"{len(files)} files, {total / 1024:.1f} KB")

    if args.dry_run:
        for rel in files:
            print(f"  {rel}")
        print(f"\nwould create {'public' if args.public else 'private'} repo {args.repo!r} with one commit")
        return 0

    token = (args.token or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        secret = ROOT / ".github_token"
        if secret.is_file():
            token = secret.read_text(encoding="utf-8-sig").strip()

    if token and not looks_like_token(token):
        print(
            f"that does not look like a GitHub token ({len(token)} chars, starts with {token[:4]!r}). "
            "A classic token starts with `ghp_` and is about 40 characters.",
            file=sys.stderr,
        )
        return 1
    if not token:
        print("no token: set GITHUB_TOKEN, pass --token, or write one to .github_token", file=sys.stderr)
        return 1

    gh = GitHub(token)
    owner = args.owner or gh.call("GET", "/user")["login"]
    print(f"authenticated as {owner}")
    rewrite_owner(owner)

    existing = gh.get_or_none(f"/repos/{owner}/{args.repo}")

    if existing is None:
        repo = gh.call(
            "POST",
            "/user/repos",
            {
                "name": args.repo,
                "description": DESCRIPTION,
                "private": not args.public,
                "has_issues": True,
                "has_wiki": False,
                "auto_init": False,
            },
        )
        print(f"created {repo['html_url']}")
    else:
        repo = existing
        print(f"repo already exists: {repo['html_url']}")

    branch = repo.get("default_branch") or "main"
    fresh = not has_commits(gh, owner, args.repo)
    if fresh:
        # the Git Database API refuses to create blobs in a repo with no commit,
        # so seed one throwaway commit and replace the branch afterwards
        gh.call(
            "PUT",
            f"/repos/{owner}/{args.repo}/contents/.bootstrap",
            {
                "message": "bootstrap",
                "content": base64.b64encode(b"blastr\n").decode(),
                "branch": branch,
            },
        )
        print("  seeded an empty repository")

    blobs = []
    for rel in files:
        content = base64.b64encode((ROOT / rel).read_bytes()).decode()
        blob = gh.call("POST", f"/repos/{owner}/{args.repo}/git/blobs", {"content": content, "encoding": "base64"})
        blobs.append({"path": rel.as_posix(), "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  uploaded {rel}")

    tree = None
    for attempt in range(4):
        try:
            tree = gh.call("POST", f"/repos/{owner}/{args.repo}/git/trees", {"tree": blobs})
            break
        except ApiError as exc:
            workflows = [b for b in blobs if b["path"].startswith(".github/workflows/")]
            if exc.status == 404 and workflows:
                # GitHub hides the real reason behind a 404: a PAT without the
                # `workflow` scope may not touch .github/workflows/*.
                print("  token lacks the `workflow` scope -> skipping .github/workflows/*")
                blobs = [b for b in blobs if not b["path"].startswith(".github/workflows/")]
                continue
            # a freshly seeded repo occasionally answers 404 while git catches up
            if exc.status == 404 and attempt < 3:
                time.sleep(2.0)
                continue
            raise

    parents = []
    if args.squash:
        fresh = True
    if not fresh:
        ref = gh.get_or_none(f"/repos/{owner}/{args.repo}/git/ref/heads/{branch}")
        if ref:
            parents = [ref["object"]["sha"]]

    commit = gh.call(
        "POST",
        f"/repos/{owner}/{args.repo}/git/commits",
        {"message": args.message, "tree": tree["sha"], "parents": parents},
    )

    gh.call(
        "PATCH",
        f"/repos/{owner}/{args.repo}/git/refs/heads/{branch}",
        {"sha": commit["sha"], "force": fresh},
    )

    gh.call("PATCH", f"/repos/{owner}/{args.repo}", {"description": DESCRIPTION})
    gh.call("PUT", f"/repos/{owner}/{args.repo}/topics", {"names": TOPICS})
    print(f"pushed {len(files)} files to https://github.com/{owner}/{args.repo}")

    if args.release:
        release = gh.call(
            "POST",
            f"/repos/{owner}/{args.repo}/releases",
            {"tag_name": "v0.1.0", "target_commitish": "main", "name": "v0.1.0", "body": RELEASE_NOTES, "draft": False},
        )
        print(f"released {release['html_url']}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.status == 401:
            print("the token was rejected - check that it is valid, not expired, and has the `repo` scope", file=sys.stderr)
        elif exc.status == 403:
            print("forbidden - a fine-grained token usually cannot create repositories; use a classic token with `repo`", file=sys.stderr)
        raise SystemExit(1)
