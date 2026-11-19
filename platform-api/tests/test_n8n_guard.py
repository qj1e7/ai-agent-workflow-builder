"""What bootstrap checks of n8n before the platform starts on it (ADR 0051, spike P9, build step
12). Each guard broken alone is named, and the settings as deployed pass."""

import json
from typing import Any

import pytest

from platform_api.n8n_guard import (
    SAFE,
    UNSET,
    WATCHED,
    deployed_findings,
    folder_findings,
    loaded_findings,
    shown_findings,
)
from platform_api.orchestration.n8n_blocks import LEFT_OUT
from platform_api.orchestration.node_classes import NODE_CLASSES

LOADED = [*NODE_CLASSES.names(), "n8n-nodes-base.airtable", "@n8n/n8n-nodes-langchain.agent"]
"""What the platform's n8n loads, cut down: every type the class file names and others."""

SHOWN: dict[str, Any] = {
    "allowedModules": {},
    "security": {"blockFileAccessToN8nFiles": True},
    "excludeNodes": sorted(LEFT_OUT),
    "communityNodesEnabled": False,
}
"""What n8n's /rest/settings shows with the platform's settings."""


def test_n8n_as_the_platform_runs_it_passes() -> None:
    assert loaded_findings(LOADED) == []
    assert deployed_findings(SAFE) == []
    assert shown_findings(SHOWN) == []


@pytest.mark.parametrize(
    ("loads", "says"),
    [
        (
            [*LOADED, "n8n-nodes-base.executeCommand"],
            "n8n loads n8n-nodes-base.executeCommand, which NODES_EXCLUDE must leave out",
        ),
        (
            [*LOADED, "n8n-nodes-community.anything", "@n8n/mcp-registry.airtable"],
            "n8n loads 2 block(s) that are not n8n's own or ours, @n8n/mcp-registry.airtable, "
            "n8n-nodes-community.anything: community nodes and fetched blocks stay off",
        ),
        (
            [t for t in LOADED if t not in ("n8n-nodes-base.httpRequest", "n8n-nodes-base.code")],
            "n8n does not load 2 block(s) the class file names, n8n-nodes-base.code, "
            "n8n-nodes-base.httpRequest: NODES_INCLUDE must be unset",
        ),
        (
            [t for t in LOADED if t != "CUSTOM.wabAskForYes"],
            "n8n does not load 1 block(s) the class file names, CUSTOM.wabAskForYes",
        ),
    ],
    ids=["left-out", "community", "allow-list", "ours"],
)
def test_each_block_n8n_loads_that_it_must_not_or_misses_is_named(
    loads: list[str], says: str
) -> None:
    assert any(says in finding for finding in loaded_findings(loads)), loaded_findings(loads)


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"N8N_BLOCK_ENV_ACCESS_IN_NODE": "false"}, "N8N_BLOCK_ENV_ACCESS_IN_NODE must be true"),
        ({"N8N_BLOCK_ENV_ACCESS_IN_NODE": None}, "N8N_BLOCK_ENV_ACCESS_IN_NODE must be true"),
        ({"N8N_RUNNERS_MODE": "internal"}, "N8N_RUNNERS_MODE must be external"),
        ({"N8N_RUNNERS_MODE": None}, "N8N_RUNNERS_MODE must be external"),
        ({"N8N_DEPRECATED_NODES_BLOCK": "False"}, "N8N_DEPRECATED_NODES_BLOCK must not be false"),
        ({"N8N_DEPRECATED_NODES_BLOCK": "0"}, "N8N_DEPRECATED_NODES_BLOCK must not be false"),
        ({"N8N_DEPRECATED_NODES_BLOCK": " 0 "}, "N8N_DEPRECATED_NODES_BLOCK must not be false"),
        (
            {"N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES": "0"},
            "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES must not be false",
        ),
        (
            {"N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES": "false"},
            "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES must not be false",
        ),
        ({"N8N_RESTRICT_FILE_ACCESS_TO": ""}, "N8N_RESTRICT_FILE_ACCESS_TO is empty"),
        ({"NODE_FUNCTION_ALLOW_BUILTIN": "*"}, "NODE_FUNCTION_ALLOW_BUILTIN must be unset"),
        ({"NODE_FUNCTION_ALLOW_EXTERNAL": "lodash"}, "NODE_FUNCTION_ALLOW_EXTERNAL must be unset"),
        ({"N8N_RUNNERS_INSECURE_MODE": "false"}, "N8N_RUNNERS_INSECURE_MODE must be unset"),
        ({"NODES_EXCLUDE": None}, "NODES_EXCLUDE must leave out"),
        (
            {"NODES_EXCLUDE": json.dumps(["n8n-nodes-base.executeCommand"])},
            "NODES_EXCLUDE must leave out @n8n/n8n-nodes-langchain.code, n8n-nodes-base.function",
        ),
        ({"NODES_EXCLUDE": "executeCommand"}, "NODES_EXCLUDE must leave out"),
    ],
)
def test_each_deployed_setting_that_breaks_a_guard_is_named(
    change: dict[str, str | None], says: str
) -> None:
    settings = {**SAFE, **change}
    found = deployed_findings({k: v for k, v in settings.items() if v is not None})
    assert len(found) == 1 and says in found[0], found


@pytest.mark.parametrize(
    "unset", ["N8N_DEPRECATED_NODES_BLOCK", "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES"]
)
def test_a_guard_whose_default_is_on_may_be_left_unset(unset: str) -> None:
    assert deployed_findings({k: v for k, v in SAFE.items() if k != unset}) == []


def test_the_file_folder_may_be_left_unset_as_n8n_defaults_it_to_its_own_files_folder() -> None:
    """Pin check: n8n 2.42.6 defaults it to ~/.n8n-files (n8n_defaults_check)."""
    assert (
        deployed_findings({k: v for k, v in SAFE.items() if k != "N8N_RESTRICT_FILE_ACCESS_TO"})
        == []
    )


@pytest.mark.parametrize(
    "folders",
    ["/home/node/.n8n-files", "~/.n8n-files", "/data/files;/srv/shared", " /data ; "],
)
def test_folders_that_hold_nothing_of_n8n_s_pass(folders: str) -> None:
    assert folder_findings(folders) == []


@pytest.mark.parametrize(
    ("folders", "says"),
    [
        (";", "is empty"),
        ("   ", "is empty"),
        ("/", "holds or is part of /home/node/.n8n"),
        ("/home/node", "holds or is part of /home/node/.n8n"),
        ("~/.n8n", "holds or is part of /home/node/.n8n"),
        ("/home/node/.n8n/custom", "holds or is part of /home/node/.n8n"),
        ("/home/node/.n8n-files/../.n8n", "holds or is part of /home/node/.n8n"),
        ("/proc", "/proc"),
        ("/data;/proc/self", "/proc"),
        ("/opt/wab/n8n-nodes-wab", "/opt/wab"),
        ("/usr/local/lib", "/usr/local/lib/node_modules"),
        ("files", "is not an absolute folder"),
        ("//proc", "/proc"),
        ("///proc/self", "/proc"),
        ("//home/node/.n8n", "holds or is part of /home/node/.n8n"),
        ("/tmp", "a system folder"),
        ("/tmp/uploads", "a system folder"),
        ("/etc", "a system folder"),
        ("//etc/n8n", "a system folder"),
        ("/root", "a system folder"),
        ("/dev/shm", "/dev"),
    ],
)
def test_a_folder_that_holds_something_of_n8n_s_or_none_at_all_is_named(
    folders: str, says: str
) -> None:
    found = folder_findings(folders)
    assert len(found) == 1 and says in found[0], found


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"allowedModules": {"builtIn": ["*"]}}, "NODE_FUNCTION_ALLOW_BUILTIN set"),
        ({"allowedModules": {"external": ["lodash"]}}, "NODE_FUNCTION_ALLOW_EXTERNAL set"),
        ({"security": {"blockFileAccessToN8nFiles": False}}, "reach its own folders"),
        ({"security": {}}, "reach its own folders"),
        ({"excludeNodes": []}, "NODES_EXCLUDE leaves in @n8n/n8n-nodes-langchain.code"),
        (
            {"excludeNodes": ["n8n-nodes-base.executeCommand"]},
            "leaves in @n8n/n8n-nodes-langchain.code",
        ),
        (
            {"excludeNodes": sorted(LEFT_OUT - {"n8n-nodes-base.git"})},
            "leaves in n8n-nodes-base.git",
        ),
        ({"communityNodesEnabled": True}, "install community nodes"),
        ({"communityNodesEnabled": None}, "install community nodes"),
    ],
)
def test_each_guard_n8n_shows_broken_is_named(change: dict[str, Any], says: str) -> None:
    found = shown_findings({**SHOWN, **change})
    assert len(found) == 1 and says in found[0], found


def test_n8n_never_loads_a_block_that_reaches_its_own_secrets_or_disk() -> None:
    """Spike P9, and the security review of step 12: a load-time exclusion doesn't rest on n8n
    still calling a block deprecated, or on a probe nobody has run."""
    assert {
        "n8n-nodes-base.executeCommand",
        "n8n-nodes-base.localFileTrigger",
        "n8n-nodes-base.function",
        "n8n-nodes-base.functionItem",
        "@n8n/n8n-nodes-langchain.code",
        "n8n-nodes-base.git",
        "n8n-nodes-base.gitTool",
    } <= LEFT_OUT


def test_bootstrap_reads_every_guard_it_checks_from_the_deploy_s_settings() -> None:
    assert sorted(WATCHED) == sorted([*SAFE, *UNSET])
