"""The team lead's rule of 25 Nov: "yes" is never a noun in anything a person sees. A person
approves, and a run waits for approval. Every string in the package can reach a person, through a
card, a report, a Teams message, an activity summary, an error or the API's own descriptions, so
this reads them all. Docstrings and comments are left out, and so are migrations, which are
history."""

import ast
import re
from pathlib import Path

import platform_api

YES_NOUN = re.compile(
    r"\b(?:a|an|your|the|their|no|one|any|second) yes\b|['’]s yes\b|\byeses\b", re.IGNORECASE
)
PACKAGE = Path(platform_api.__file__).parent


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        for statement in body if isinstance(body, list) else []:
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                found.add(id(statement.value))
    return found


def said(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstrings(tree)
    return [
        f"{path.relative_to(PACKAGE)}:{node.lineno}: {node.value}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docs
        and YES_NOUN.search(node.value)
    ]


def test_no_string_in_the_package_uses_yes_as_a_noun() -> None:
    modules = [p for p in PACKAGE.rglob("*.py") if "migrations" not in p.parts]
    assert len(modules) > 100
    assert [line for path in sorted(modules) for line in said(path)] == []


def test_the_rule_catches_the_shapes_it_names() -> None:
    for words in ("Waits for a yes", "Needs your yes", "after Bob's yes", "up to the yes."):
        assert YES_NOUN.search(words), words
    for words in ("Waits for approval", "Bob approved.", "Yes", "Approvers say yes or no"):
        assert not YES_NOUN.search(words), words
