"""The team lead's rule of 25 Nov: "yes" is never a noun in anything a person sees. A person
approves, and a run waits for approval. The fixed replies are what people read, and the prompts
shape what the models say to them, so this reads every string in the package. Docstrings and
comments are left out. The allowed strings read people's own words, which may say "a yes"."""

import ast
import re
from pathlib import Path

import agent_runtime

YES_NOUN = re.compile(
    r"\b(?i:a|an|your|the|their|its|no|one|any|second) yes\b|['’]s yes\b|\byeses\b"
)
"""Lower-case yes only: Yes is the name of a button and of Ask for approval's exit."""
PACKAGE = Path(agent_runtime.__file__).parent
READS_PEOPLES_WORDS = (
    "|a yes|yes|",
    " can not no yes do ",
    " not no yes ok ",
)
"""A pattern that finds approval words in a request, and two lists of words too common to
explain anything."""


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
        and not any(allowed in node.value for allowed in READS_PEOPLES_WORDS)
    ]


def test_no_string_in_the_package_uses_yes_as_a_noun() -> None:
    modules = sorted(PACKAGE.rglob("*.py"))
    assert len(modules) > 40
    assert [line for path in modules for line in said(path)] == []


def test_the_rule_catches_the_shapes_it_names() -> None:
    for words in (
        "Waits for a yes",
        "Needs your yes",
        "after Bob's yes",
        "up to the yes.",
        "expired before its yes.",
    ):
        assert YES_NOUN.search(words), words
    for words in (
        "Waits for approval",
        "Bob approved.",
        "Yes",
        "Wire the Yes exit",
        "Approvers say yes or no",
    ):
        assert not YES_NOUN.search(words), words
