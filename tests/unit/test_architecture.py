"""The rules in CLAUDE.md and docs/ARCHITECTURE.md, as assertions.

Each describes something that otherwise goes wrong silently: an undecided package, a
service reaching back into an adapter, and prose growing back over the code.
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


# Ratchets. Both may only go down: a docstring past one line, or a comment past one, is
# a claim that the code cannot be read as it stands. Raising either is the argument.
MULTI_LINE_DOCSTRING_BUDGET = 10
MAX_DOCSTRING_LINES = 4
MAX_COMMENT_RUN = 4


def _docstring_lengths() -> list[tuple[str, str, int]]:
    found = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                continue
            text = ast.get_docstring(node, clean=False)
            if text:
                name = getattr(node, "name", "<module>")
                found.append(
                    (path.relative_to(SRC).as_posix(), name, len(text.strip().split("\n")))
                )
    return found


def test_no_docstring_runs_past_a_paragraph():
    too_long = [
        f"{where}::{name} ({length} lines)"
        for where, name, length in _docstring_lengths()
        if length > MAX_DOCSTRING_LINES
    ]

    assert not too_long, f"{too_long} — say it in one line, or put it in docs/"


def test_multi_line_docstrings_stay_within_budget():
    multi = [entry for entry in _docstring_lengths() if entry[2] > 1]

    assert len(multi) <= MULTI_LINE_DOCSTRING_BUDGET, (
        f"{len(multi)} multi-line docstrings against a budget of "
        f"{MULTI_LINE_DOCSTRING_BUDGET}. Collapse one, or lower the budget deliberately."
    )


def test_no_comment_block_runs_past_a_few_lines():
    offenders = []
    for path, _ in _modules():
        run = 0
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            run = run + 1 if line.strip().startswith("#") else 0
            if run == MAX_COMMENT_RUN + 1:
                offenders.append(f"{path.relative_to(SRC).as_posix()}:{number}")

    assert not offenders, f"{offenders} — a comment that long belongs in docs/"
