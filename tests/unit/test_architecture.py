"""The rules in docs/ARCHITECTURE.md, as assertions.

They were prose, and prose does not fail a build. Two of them are cheap to check
and both describe things that go wrong silently: a package appearing that nobody
decided on, and a service reaching back into an adapter.
"""

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "old_news"
ARCHITECTURE = Path(__file__).resolve().parents[2] / "docs" / "ARCHITECTURE.md"

# Adapters, so they may import anything. Everything else is a service.
ADAPTERS = {"api", "tasks"}

# db/migrate.py applies procrastinate's schema as well as Alembic's, which is the
# one documented reason for a non-adapter to know the queue exists.
DIRECTION_EXEMPT = {"db/migrate.py", "__main__.py"}


def _documented_packages() -> set[str]:
    tree = re.search(r"```text\nsrc/old_news/\n(.*?)```", ARCHITECTURE.read_text(), re.DOTALL)
    assert tree, "the package tree is missing from ARCHITECTURE.md"
    return set(re.findall(r"^\s+(\w+)/", tree.group(1), re.MULTILINE))


def _actual_packages() -> set[str]:
    return {
        child.name
        for child in SRC.iterdir()
        if child.is_dir() and not child.name.startswith(("_", "."))
    }


def test_every_package_is_in_the_documented_tree():
    """A new top-level package is a decision. This is what makes it a visible one."""
    undocumented = _actual_packages() - _documented_packages()

    assert not undocumented, (
        f"{sorted(undocumented)} exist but are not in ARCHITECTURE.md's tree. "
        "Add them there, or put the code in a package that already exists."
    )


def test_the_documented_tree_has_no_ghosts():
    stale = _documented_packages() - _actual_packages()

    assert not stale, f"ARCHITECTURE.md lists {sorted(stale)}, which no longer exist"


def _modules() -> list[tuple[Path, ast.Module]]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        if "migrations" in path.parts:
            continue
        found.append((path, ast.parse(path.read_text())))
    return found


def _imported_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize("adapter", sorted(ADAPTERS))
def test_a_service_never_imports_an_adapter(adapter: str):
    """The only direction rule, and what keeps one service reachable from both a
    worker and an HTTP handler."""
    offenders = []
    for path, tree in _modules():
        relative = path.relative_to(SRC).as_posix()
        if relative.split("/")[0] in ADAPTERS or relative in DIRECTION_EXEMPT:
            continue
        if any(name.startswith(f"old_news.{adapter}") for name in _imported_names(tree)):
            offenders.append(relative)

    assert not offenders, f"{offenders} import old_news.{adapter}"
