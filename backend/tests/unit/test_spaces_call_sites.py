"""Guard (T-J2): content-access call sites must go through the Space resolver and be reviewed.

A file that calls ``question_contexts(`` or ``require_member_access(``, or that builds a ``select(...)`` over
``WorkspaceFolder`` outside the owning packages, must be listed in ``specs/espacos/call-sites.md``. A new file
there means a new way to reach content: add it to the list *after* confirming it uses the resolver.
The second guard forbids ``access=None`` (system view) in member-facing code."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
LIST = ROOT.parent / "specs" / "espacos" / "call-sites.md"
OWNERS = ("app/spaces/", "app/workspaces/", "app/library/service.py", "app/ingestion/", "app/integrations/")
CALLS = {"question_contexts", "require_member_access"}


def _name(node: ast.AST) -> str | None:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _mentions(node: ast.AST, name: str) -> bool:
    return any(isinstance(child, ast.Name) and child.id == name or isinstance(child, ast.Attribute) and child.attr == name
               for child in ast.walk(node))


def call_sites() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(OWNERS[:2] + OWNERS[3:]) or rel == OWNERS[2]:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = _name(node.func)
            if callee in CALLS:
                found.setdefault(rel, set()).add(callee)
            elif callee == "select" and any(_mentions(arg, "WorkspaceFolder") for arg in node.args):
                found.setdefault(rel, set()).add("select(WorkspaceFolder)")
    return found


def listed() -> set[str]:
    return set(re.findall(r"^- `(app/[^`]+\.py)`", LIST.read_text(), flags=re.MULTILINE))


def test_no_content_access_call_site_without_review():
    unreviewed = sorted(set(call_sites()) - listed())
    assert not unreviewed, (
        "new content-access call sites; confirm they use SpaceAccessResolver and list them in "
        f"specs/espacos/call-sites.md: {unreviewed}")


def test_every_listed_call_site_still_exists():
    missing = sorted(path for path in listed() if not (ROOT / path).exists())
    assert not missing, f"call-sites.md lists files that no longer exist: {missing}"


def test_no_member_facing_code_passes_the_system_view():
    offenders = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.keyword) and node.arg == "access" and isinstance(node.value, ast.Constant) \
                    and node.value.value is None:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.value.lineno}")
    assert not offenders, f"access=None means the system view and must not be passed by app code: {offenders}"
