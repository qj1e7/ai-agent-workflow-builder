"""The pin check of what the code of n8n's blocks reaches (ADR 0051, section 2).

It reads, in each package in `SHIPPED` as the image holds it:
- each block's own folder, and fails on a block that reaches n8n's environment, its disk, code it
  runs, or another workflow, when `KNOWN` doesn't name that block for it;
- the package's shared helpers in `dist/utils`, file by file, against `KNOWN_SHARED`;
- every package either reads in with `require` or `import`, and fails on one that isn't in
  `n8n_block_imports.json`, so that a new dependency gets a person's look before a pin moves.

platform_api.n8n_catalogue runs it on the code scripts/n8n-catalogue.sh copies out of the image.
"""

import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from platform_api.orchestration.n8n_blocks import SHIPPED

SHARED = "dist/utils"
"""Where each package keeps the helpers its blocks share."""
CODE_SUFFIXES = frozenset({".js", ".cjs", ".mjs"})

type Reach = Literal[
    "child_process", "process.env", "fs", "file helpers", "runs code", "another workflow"
]

_MODULE = r"""(?:\brequire\(\s*|\bimport\(\s*|\bfrom\s*)["']"""
REACHES: Mapping[Reach, re.Pattern[str]] = {
    "child_process": re.compile(r"\bchild_process\b"),
    "process.env": re.compile(r"""\bprocess\.env\b|\bprocess\[\s*["']env["']\s*\]"""),
    "fs": re.compile(_MODULE + r"""(?:node:)?fs(?:/promises)?["']"""),
    "file helpers": re.compile(r"\b(?:createReadStream|writeContentToFile|resolvePath)\b"),
    "runs code": re.compile(
        "|".join(
            (
                # n8n's code sandboxes and its task runners
                r"\b[A-Z]\w*Sandbox\b",
                r"\bstartJob\b",
                _MODULE + r"""[^"']*(?:[Ss]andbox|vm2|isolated-vm|alasql)[^"']*["']""",
                # Node's own vm
                _MODULE + r"""(?:node:)?vm["']""",
                r"\b(?:runInNewContext|runInThisContext|runInContext|compileFunction)\b",
                r"\bvm(?:_\d+)?\.Script\b",
                # JavaScript's own
                r"(?<![.\w$])eval\s*\(",
                r"\(\s*0\s*,\s*eval\s*\)",
                r"\bnew\s+Function\s*\(",
            )
        )
    ),
    "another workflow": re.compile(r"\bhelpers\.executeWorkflow\b|\.executeWorkflow\("),
}
"""What the check searches code for: shell commands, n8n's environment, Node's file system,
n8n's file helpers, anything that runs code it is given, and running another workflow."""

KNOWN: Mapping[str, frozenset[Reach]] = {
    # Execute Command, which n8n never loads.
    "n8n-nodes-base.executeCommand": frozenset({"child_process"}),
    # The blocks that run code a workflow gives them. Code, the Code Tool, AI Transform, Sort and
    # Item Lists run it in n8n's external task runner, and Merge's SQL mode in an isolate, so
    # they load (spike P9). Function, Function Item and LangChain Code run it in n8n's own
    # process and stay held (orchestration/n8n_blocks.py). Code and LangChain Code also read
    # process.env. Merge reads AlaSQL's own bundle from n8n's packages with fs.
    "n8n-nodes-base.code": frozenset({"runs code", "process.env"}),
    "@n8n/n8n-nodes-langchain.code": frozenset({"runs code", "process.env"}),
    "@n8n/n8n-nodes-langchain.toolCode": frozenset({"runs code"}),
    "n8n-nodes-base.function": frozenset({"runs code"}),
    "n8n-nodes-base.functionItem": frozenset({"runs code"}),
    "n8n-nodes-base.aiTransform": frozenset({"runs code"}),
    "n8n-nodes-base.sort": frozenset({"runs code"}),
    "n8n-nodes-base.itemLists": frozenset({"runs code"}),
    "n8n-nodes-base.merge": frozenset({"runs code", "fs"}),
    # The blocks that read or write a path on n8n's disk. n8n keeps them in ~/.n8n-files, so they
    # load (spike P9), except Git, which stays held until a probe with a real repository.
    "n8n-nodes-base.readWriteFile": frozenset({"fs", "file helpers"}),
    "n8n-nodes-base.readBinaryFile": frozenset({"file helpers"}),
    "n8n-nodes-base.readBinaryFiles": frozenset({"file helpers"}),
    "n8n-nodes-base.writeBinaryFile": frozenset({"fs", "file helpers"}),
    "n8n-nodes-base.git": frozenset({"fs", "file helpers"}),
    # The sub-workflow blocks, held for an amendment. Execute Sub-workflow also loads a workflow
    # from a file on n8n's disk.
    "n8n-nodes-base.executeWorkflow": frozenset({"another workflow", "fs", "file helpers"}),
    "@n8n/n8n-nodes-langchain.toolWorkflow": frozenset({"another workflow"}),
    "@n8n/n8n-nodes-langchain.retrieverWorkflow": frozenset({"another workflow"}),
    # Each reads only settings of its own from n8n's environment: Airtop its addresses and
    # N8N_VERSION, Microsoft Agent 365 Trigger ENABLE_OBSERVABILITY and
    # ENABLE_A365_OBSERVABILITY_EXPORTER. Airtop also reads n8n's own package.json for n8n's
    # version.
    "n8n-nodes-base.airtop": frozenset({"process.env", "fs"}),
    "@n8n/n8n-nodes-langchain.microsoftAgent365Trigger": frozenset({"process.env"}),
    # Each uses fs only for files of its own in n8n's temporary folder. Edit Image, FTP, SSH and
    # Webhook write to a file tmp-promise makes for them. Form, n8n Form Trigger and Webhook
    # delete the files a person uploaded. AI Agent's SQL agent writes a sqlite file it was given
    # to a temporary path, and AI Agent Tool shares AI Agent's folder.
    "n8n-nodes-base.editImage": frozenset({"fs"}),
    "n8n-nodes-base.form": frozenset({"fs"}),
    "n8n-nodes-base.formTrigger": frozenset({"fs"}),
    "n8n-nodes-base.ftp": frozenset({"fs"}),
    "n8n-nodes-base.ssh": frozenset({"fs"}),
    "n8n-nodes-base.webhook": frozenset({"fs"}),
    "@n8n/n8n-nodes-langchain.agent": frozenset({"fs"}),
    "@n8n/n8n-nodes-langchain.agentTool": frozenset({"fs"}),
    # Debug Helper runs the fixed text "gc" in Node's vm to free memory before its Out Of Memory
    # choice fills n8n's memory on purpose. A workflow can't give it code.
    "n8n-nodes-base.debugHelper": frozenset({"runs code"}),
}
"""What each block's own folder reaches in n8n 2.42.6, and why each is held or safe. ADR 0051's
section 2 lists the same blocks."""

KNOWN_SHARED: Mapping[str, frozenset[Reach]] = {}
"""What each shared helper reaches, by its path in the image, and why it is safe."""

IMPORTS = Path(__file__).with_name("n8n_block_imports.json")
"""Every package n8n's blocks and their shared helpers read in, as n8n 2.42.6 has them. Node's
own modules are in it too."""
N8NS_OWN = ("n8n-workflow", "n8n-core", "n8n-nodes-base", "@n8n/")
"""n8n's own packages, which are n8n's code as much as the blocks are."""
_IMPORTED = re.compile(
    r"""(?:\brequire(?:\.resolve)?\(\s*|\bimport\(\s*)["']([^"']+)["']"""
    r"""|^\s*(?:import|export)\b[^;\n]*?\bfrom\s*["']([^"']+)["']""",
    re.MULTILINE,
)
_PACKAGE_NAME = re.compile(r"(?:@[a-z0-9][\w.~-]*/)?[a-z0-9][\w.~-]*")


@dataclass(frozen=True)
class Scan:
    blocks: Mapping[str, frozenset[Reach]]
    """For each block of each package, what the code in its own folder reaches."""
    shared: Mapping[str, frozenset[Reach]]
    """For each shared helper that reaches anything, what it reaches."""
    imports: frozenset[str]
    """Every package the blocks and the shared helpers read in, other than n8n's own."""


def scan(sources: Path) -> Scan:
    """Reads the code of each package in `SHIPPED`, as `sources/<package>/dist` holds it."""
    by_folder: dict[Path, tuple[frozenset[Reach], frozenset[str]]] = {}
    blocks: dict[str, frozenset[Reach]] = {}
    shared: dict[str, frozenset[Reach]] = {}
    imports: set[str] = set()
    for package in SHIPPED:
        root = sources / package
        known = cast(
            Mapping[str, Mapping[str, str]],
            json.loads((root / "dist" / "known" / "nodes.json").read_text()),
        )
        for short, entry in known.items():
            folder = (root / entry["sourcePath"]).parent
            if folder not in by_folder:
                by_folder[folder] = _read(_code(folder))
            reached, read_in = by_folder[folder]
            blocks[f"{package}.{short}"] = reached
            imports |= read_in
        for path in _code(root / SHARED):
            reached, read_in = _read([path])
            if reached:
                shared[f"{package}/{path.relative_to(root).as_posix()}"] = reached
            imports |= read_in
    return Scan(blocks, shared, frozenset(imports))


def problems(found: Scan, listed: Collection[str] | None = None) -> list[str]:
    """Each block or shared helper that reaches what `KNOWN` or `KNOWN_SHARED` doesn't name for
    it, and each package read in that `n8n_block_imports.json` doesn't list."""
    imports = listed if listed is not None else listed_imports()
    said = [
        f"{name} reaches {', '.join(sorted(new))}, which ADR 0051 doesn't name for it. Read "
        "its code, then hold it off or add it to KNOWN in platform_api/n8n_code_check.py."
        for name, reached in sorted(found.blocks.items())
        if (new := reached - KNOWN.get(name, frozenset()))
    ]
    said += [
        f"The shared helper {path} reaches {', '.join(sorted(new))}. Read it and the blocks "
        "that use it, then add it to KNOWN_SHARED in platform_api/n8n_code_check.py."
        for path, reached in sorted(found.shared.items())
        if (new := reached - KNOWN_SHARED.get(path, frozenset()))
    ]
    said += [
        f"n8n's blocks now read in {name}, which platform_api/n8n_block_imports.json doesn't "
        "list. Look at what it can do, then add it."
        for name in sorted(found.imports - set(imports))
    ]
    return said


def listed_imports() -> list[str]:
    return cast(list[str], json.loads(IMPORTS.read_text()))


def _code(folder: Path) -> list[Path]:
    return [p for p in sorted(folder.rglob("*")) if p.suffix in CODE_SUFFIXES and p.is_file()]


def _read(paths: list[Path]) -> tuple[frozenset[Reach], frozenset[str]]:
    reached: set[Reach] = set()
    read_in: set[str] = set()
    for path in paths:
        text = path.read_text(errors="replace")
        reached.update(reach for reach, pattern in REACHES.items() if pattern.search(text))
        read_in.update(
            name
            for match in _IMPORTED.finditer(text)
            if (name := _package(match[1] or match[2])) is not None
        )
    return frozenset(reached), frozenset(read_in)


def _package(specifier: str) -> str | None:
    """The package a `require` names, or None for a file of the block's own, n8n's own code, or
    text that only looks like a `require`, such as code a block writes for a person."""
    specifier = specifier.removeprefix("node:")
    parts = specifier.split("/")
    name = "/".join(parts[:2]) if specifier.startswith("@") else parts[0]
    if not _PACKAGE_NAME.fullmatch(name) or name.startswith(N8NS_OWN):
        return None
    return name
