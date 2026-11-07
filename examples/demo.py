"""End-to-end demo: build a throwaway repo, change a signature, run blastr.

    python examples/demo.py

No git, no network, no fixture files — the diff is generated on the fly, which
also exercises blastr's "reconstruct the before-image from the patch" path.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BEFORE = {
    "core/user.py": '''\
class User:
    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email

    def to_dict(self) -> dict:
        return {"name": self.name, "email": self.email}

    @classmethod
    def from_dict(cls, payload: dict) -> "User":
        return cls(payload["name"], payload["email"])
''',
    "api/handlers.py": '''\
from core.user import User


def create_user(name: str, email: str) -> dict:
    user = User(name, email)
    return user.to_dict()
''',
    "api/admin.py": '''\
from api.handlers import create_user


def admin_create(user_name: str, user_email: str) -> dict:
    return create_user(user_name, user_email)
''',
    "scripts/seed.py": '''\
from core.user import User


def seed(rows):
    return [User.from_dict(row) for row in rows]
''',
    "tests/test_user.py": '''\
from core.user import User


def test_to_dict():
    user = User("ada", "ada@example.com")
    assert user.to_dict() == {"name": "ada", "email": "ada@example.com"}
''',
}

AFTER = dict(BEFORE)
AFTER["core/user.py"] = '''\
class User:
    def __init__(self, name: str, email: str, role: str = "member"):
        self.name = name
        self.email = email
        self.role = role

    def to_dict(self) -> dict:
        return {"name": self.name, "email": self.email, "role": self.role}

    @classmethod
    def from_dict(cls, payload: dict) -> "User":
        return cls(payload["name"], payload["email"], payload.get("role", "member"))
'''
AFTER["api/handlers.py"] = '''\
from core.user import User


def create_user(name: str, email: str, role: str) -> dict:
    user = User(name, email, role)
    return user.to_dict()
'''


def build_patch() -> str:
    chunks = []
    for path, old in BEFORE.items():
        new = AFTER[path]
        if old == new:
            continue
        chunks.append(
            "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    n=3,
                )
            )
        )
    return "".join(chunks)


def _workdir() -> Path:
    """Prefer a temp dir; some sandboxes only allow writes inside the repo."""
    try:
        candidate = Path(tempfile.mkdtemp(prefix="blastr-demo-"))
        (candidate / "core").mkdir()
        (candidate / "core").rmdir()
        return candidate
    except OSError:
        fallback = ROOT / ".demo"
        shutil.rmtree(fallback, ignore_errors=True)
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def write_text(path: Path, text: str) -> None:
    """Path.write_text(newline=...) only exists from Python 3.10."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main() -> int:
    work = _workdir()
    keep = work.parent == ROOT
    try:
        for path, text in BEFORE.items():
            target = work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text(target, text)

        patch = work / "change.patch"
        write_text(patch, build_patch())

        for path, text in AFTER.items():
            write_text(work / path, text)

        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NO_COLOR="1")
        proc = subprocess.run(
            [sys.executable, "-m", "blastr", "--root", str(work), "--diff", str(patch)],
            env=env,
            capture_output=True,
        )
        out = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        try:
            sys.stdout.write(out)
        except UnicodeEncodeError:  # legacy console codepage
            encoding = sys.stdout.encoding or "ascii"
            sys.stdout.write(out.encode(encoding, "replace").decode(encoding, "replace"))
        if proc.stderr:
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        return proc.returncode
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"\n[demo left in {work}]", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
