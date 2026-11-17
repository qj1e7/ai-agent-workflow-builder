"""What bootstrap checks of n8n before the platform starts on it (ADR 0051, section 2, as spike
P9 and build step 12 settled it).

n8n loads every built-in block but two, so its own settings are what keep a workflow's code and
files away from n8n's secrets. Bootstrap fails the start unless all of these hold:

- n8n loads every type the class file names and all of our blocks, neither of the two left out,
  and no community or fetched block (`loaded_findings`);
- the settings the deploy gives n8n keep `$env` closed, run code in the external task runner,
  refuse the deprecated blocks, keep the file blocks out of n8n's own folders and `/proc`, and
  let code load no module of its own choosing (`deployed_findings`). The deploy gives bootstrap the
  same block of settings it gives n8n: `x-n8n-guards` in deploy/compose.yaml and
  `local.n8n_guards` in infra/envs/dev/main.tf;
- what n8n itself shows of those settings agrees (`shown_findings`), and n8n refuses a workflow
  with a deprecated block (`DEPRECATED`), which bootstrap tries.

Pure. The folder rules know where n8n's image keeps its own files (`N8NS_FOLDERS`).
"""

import posixpath
from collections.abc import Collection, Mapping, Sequence
from typing import Any, cast

from platform_api.orchestration.n8n_blocks import LEFT_OUT, OURS, SHIPPED, package
from platform_api.orchestration.node_classes import NODE_CLASSES
from platform_api.settings import N8N_GUARDED

SAFE: Mapping[str, str] = {
    "N8N_BLOCK_ENV_ACCESS_IN_NODE": "true",
    "N8N_RUNNERS_MODE": "external",
    "N8N_DEPRECATED_NODES_BLOCK": "true",
    "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES": "true",
    "N8N_RESTRICT_FILE_ACCESS_TO": "/home/node/.n8n-files",
}
"""The guards as the platform deploys them. bootstrap checks each by its own rule, so another
value that is as safe also passes."""
UNSET = ("NODE_FUNCTION_ALLOW_BUILTIN", "NODE_FUNCTION_ALLOW_EXTERNAL", "N8N_RUNNERS_INSECURE_MODE")
"""Settings n8n must not have at all: the first two let code load Node's modules and npm
packages, also in n8n's own process, and the third drops the runner's own guards."""
WATCHED = N8N_GUARDED
"""The names bootstrap reads from the block of n8n's settings the deploy gives it: each of SAFE
and UNSET."""
HOME = "/home/node"
"""n8n's user's home in its image, where `~` points."""
N8NS_FOLDERS = (
    f"{HOME}/.n8n",
    "/proc",
    "/sys",
    "/dev",
    "/opt/wab",
    "/usr/local/lib/node_modules",
)
"""Where n8n keeps something of its own: its settings, encryption key and the blocks it loads at
start, its environment (/proc), the kernel's views of it, our node pack, and n8n's own code."""
DEPRECATED = (
    "n8n-nodes-base.function",
    "n8n-nodes-base.functionItem",
    "@n8n/n8n-nodes-langchain.code",
)
"""The blocks that run code inside n8n's own process, which n8n refuses while
N8N_DEPRECATED_NODES_BLOCK is anything but false (spike P9)."""
SHOWN = 5


def loaded_findings(served: Collection[str]) -> list[str]:
    """n8n loads every type the class file names and every one of our blocks, neither type left
    out, and no type from a package that isn't n8n's own or ours. A type the file names that n8n
    doesn't load is also how an allow list left in NODES_INCLUDE shows."""
    loaded = set(served)
    findings: list[str] = []
    strangers = sorted(t for t in loaded if not t.startswith(OURS) and package(t) not in SHIPPED)
    if strangers:
        findings.append(
            f"n8n loads {len(strangers)} block(s) that are not n8n's own or ours, "
            f"{_named(strangers)}: community nodes and fetched blocks stay off"
        )
    if left_in := sorted(LEFT_OUT & loaded):
        findings.append(f"n8n loads {', '.join(left_in)}, which NODES_EXCLUDE must leave out")
    if missing := sorted(set(NODE_CLASSES.names()) - loaded):
        findings.append(
            f"n8n does not load {len(missing)} block(s) the class file names, {_named(missing)}: "
            "NODES_INCLUDE must be unset, so n8n loads every built-in block"
        )
    return findings


def deployed_findings(settings: Mapping[str, str]) -> list[str]:
    """Each guard the deploy's settings for n8n break."""
    findings: list[str] = []
    said = {name: value.strip() for name, value in settings.items()}
    if said.get("N8N_BLOCK_ENV_ACCESS_IN_NODE", "").lower() != "true":
        findings.append(
            "N8N_BLOCK_ENV_ACCESS_IN_NODE must be true, or n8n hands its whole environment to "
            "every expression and every block's code"
        )
    if said.get("N8N_RUNNERS_MODE") != "external":
        findings.append(
            "N8N_RUNNERS_MODE must be external, so code runs in the task runner's own container "
            "and never in n8n's"
        )
    for name, why in (
        ("N8N_DEPRECATED_NODES_BLOCK", "Function, Function Item and LangChain Code run in n8n"),
        ("N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES", "the file blocks could reach n8n's own folders"),
    ):
        if said.get(name, "").lower() == "false":
            findings.append(f"{name} must not be false: {why}")
    if "N8N_RESTRICT_FILE_ACCESS_TO" in said:
        findings += folder_findings(said["N8N_RESTRICT_FILE_ACCESS_TO"])
    findings += [
        f"{name} must be unset on n8n, and the deploy sets it" for name in UNSET if name in said
    ]
    return findings


def folder_findings(value: str) -> list[str]:
    """N8N_RESTRICT_FILE_ACCESS_TO names only absolute folders that hold nothing of n8n's, and
    is never empty, which n8n reads as no limit at all."""
    folders = [entry.strip() for entry in value.split(";") if entry.strip()]
    if not folders:
        return [
            "N8N_RESTRICT_FILE_ACCESS_TO is empty, which lets the file blocks reach every path, "
            "n8n's environment in /proc included. Leave it unset or name a folder"
        ]
    findings: list[str] = []
    for folder in folders:
        path = _resolved(folder)
        if path is None:
            findings.append(
                f"N8N_RESTRICT_FILE_ACCESS_TO names {folder}, which is not an absolute folder"
            )
        elif clash := [own for own in N8NS_FOLDERS if _overlaps(path, own)]:
            findings.append(
                f"N8N_RESTRICT_FILE_ACCESS_TO names {folder}, which holds or is part of "
                f"{', '.join(clash)}, where n8n keeps its own files"
            )
    return findings


def shown_findings(shown: Mapping[str, Any]) -> list[str]:
    """What n8n's own settings page (`/rest/settings`) shows of the guards it can show."""
    findings: list[str] = []
    modules = _mapping(shown.get("allowedModules"))
    for key, name in (
        ("builtIn", "NODE_FUNCTION_ALLOW_BUILTIN"),
        ("external", "NODE_FUNCTION_ALLOW_EXTERNAL"),
    ):
        if modules.get(key) is not None:
            findings.append(f"n8n runs with {name} set, so code may load modules it picks")
    if _mapping(shown.get("security")).get("blockFileAccessToN8nFiles") is not True:
        findings.append("n8n lets the file blocks reach its own folders")
    excluded = shown.get("excludeNodes")
    left_out = set(cast(Sequence[str], excluded)) if isinstance(excluded, list) else set[str]()
    if not left_out >= LEFT_OUT:
        findings.append(
            f"n8n's NODES_EXCLUDE leaves out {_named(sorted(left_out)) or 'nothing'}, not "
            f"{', '.join(sorted(LEFT_OUT))}"
        )
    if shown.get("communityNodesEnabled") is not False:
        findings.append("n8n lets people install community nodes")
    return findings


def deprecated_probe(node_type: str) -> dict[str, Any]:
    """A workflow with one deprecated block, which n8n must refuse to save."""
    return {
        "name": f"Platform check: n8n refuses {node_type}",
        "nodes": [
            {
                "id": "deprecated-probe",
                "name": "Deprecated",
                "type": node_type,
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {},
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }


def _named(names: Sequence[str]) -> str:
    return ", ".join(names[:SHOWN]) + (", …" if len(names) > SHOWN else "")


def _resolved(folder: str) -> str | None:
    if folder == "~" or folder.startswith("~/"):
        folder = HOME + folder[1:]
    if not folder.startswith("/"):
        return None
    return posixpath.normpath(folder)


def _overlaps(path: str, own: str) -> bool:
    """The same folder, one inside the other, or `/`, which holds everything."""
    return path == own or own.startswith(path.rstrip("/") + "/") or path.startswith(own + "/")


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}
