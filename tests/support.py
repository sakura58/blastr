"""Shared fixtures for the test suite (stdlib unittest only, no pytest)."""

from __future__ import annotations

import atexit
import difflib
import shutil
import tempfile
from pathlib import Path

LOCAL_BASE = Path(__file__).resolve().parent / "_work"
_counter = 0


def _root() -> Path:
    global _counter
    try:
        root = Path(tempfile.mkdtemp(prefix="blastr-test-"))
        probe = root / "probe"
        probe.mkdir()
        probe.rmdir()
        return root
    except OSError:
        _counter += 1
        root = LOCAL_BASE / f"case{_counter}"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        atexit.register(shutil.rmtree, LOCAL_BASE, True)
        return root


def write_text(path: Path, text: str) -> None:
    """Path.write_text(newline=...) only exists from Python 3.10."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def make_repo(files: dict) -> Path:
    root = _root()
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text(target, text)
    return root


def make_patch(before: dict, after: dict) -> str:
    chunks = []
    for path, old in before.items():
        new = after.get(path, old)
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


BEFORE = {
    "core/user.py": '''\
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email

    def to_dict(self):
        return {"name": self.name, "email": self.email}
''',
    "api/handlers.py": '''\
from core.user import User


def create_user(name, email):
    return User(name, email).to_dict()
''',
    "api/admin.py": '''\
from api.handlers import create_user


def admin_create(user_name, user_email):
    return create_user(user_name, user_email)
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
    def __init__(self, name, email, role="member"):
        self.name = name
        self.email = email
        self.role = role

    def to_dict(self):
        return {"name": self.name, "email": self.email, "role": self.role}
'''
AFTER["api/handlers.py"] = '''\
from core.user import User


def create_user(name, email, role):
    return User(name, email, role).to_dict()
'''
