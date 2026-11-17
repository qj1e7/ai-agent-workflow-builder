"""The pin check of the n8n defaults and the task runner's own config that spike P9's verdicts
rest on (ADR 0051, build step 12), on cut-down copies of what n8n 2.42.6 and n8nio/runners
2.42.6 hold. scripts/n8n-catalogue.sh runs it on the images themselves."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from platform_api.n8n_defaults_check import (
    CONFIGS,
    RUNNERS_CONFIG,
    config_problems,
    runner_problems,
    version_problems,
)

SECURITY = """let SecurityConfig = class SecurityConfig {
    constructor() {
        this.restrictFileAccessTo = '~/.n8n-files';
        this.blockFileAccessToN8nFiles = true;
        this.blockFilePatterns = '^(?:[^/]*/)*\\\\.git(?:/.*)?$';
    }
};
"""
NODES = """let NodesConfig = class NodesConfig {
    constructor() {
        this.include = [];
        this.blockDeprecated = true;
    }
};
"""
RUNNERS = """let TaskRunnersConfig = class TaskRunnersConfig {
    constructor() {
        this.mode = 'internal';
        this.insecureMode = false;
    }
};
"""
RUNNER_CONFIG: dict[str, Any] = {
    "task-runners": [
        {
            "runner-type": "javascript",
            "args": [
                "--disallow-code-generation-from-strings",
                "--disable-proto=delete",
                "/opt/runners/task-runner-javascript/dist/start.js",
            ],
            "env-overrides": {
                "NODE_FUNCTION_ALLOW_BUILTIN": "crypto",
                "NODE_FUNCTION_ALLOW_EXTERNAL": "moment",
                "N8N_RUNNERS_HEALTH_CHECK_SERVER_HOST": "0.0.0.0",
            },
        },
        {
            "runner-type": "python",
            "args": ["-I", "-B", "-X", "disable_remote_debug", "-m", "src.main"],
            "env-overrides": {"N8N_RUNNERS_STDLIB_ALLOW": "", "N8N_RUNNERS_EXTERNAL_ALLOW": ""},
        },
    ]
}
PINS = {
    "n8n": {"repository": "n8nio/n8n", "tag": "2.42.6", "digest": "sha256:a"},
    "n8n-runners": {"repository": "n8nio/runners", "tag": "2.42.6", "digest": "sha256:b"},
}


def sources(tmp_path: Path, **changed: str) -> Path:
    texts = {"security": SECURITY, "nodes": NODES, "runners": RUNNERS, **changed}
    for name, file in CONFIGS.items():
        path = tmp_path / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(texts[name])
    path = tmp_path / RUNNERS_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(RUNNER_CONFIG))
    return tmp_path


def test_the_pinned_defaults_and_runner_config_pass(tmp_path: Path) -> None:
    root = sources(tmp_path)
    assert config_problems(root) == []
    assert runner_problems(json.loads((root / RUNNERS_CONFIG).read_text())) == []
    assert version_problems(PINS) == []


@pytest.mark.parametrize(
    ("name", "text", "says"),
    [
        (
            "security",
            SECURITY.replace("'~/.n8n-files'", "''"),
            "N8N_RESTRICT_FILE_ACCESS_TO no longer defaults to ~/.n8n-files",
        ),
        (
            "security",
            SECURITY.replace(
                "blockFileAccessToN8nFiles = true", "blockFileAccessToN8nFiles = false"
            ),
            "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES no longer defaults to on",
        ),
        (
            "nodes",
            NODES.replace("blockDeprecated = true", "blockDeprecated = false"),
            "N8N_DEPRECATED_NODES_BLOCK no longer defaults to on",
        ),
        (
            "runners",
            RUNNERS.replace("insecureMode = false", "insecureMode = true"),
            "N8N_RUNNERS_INSECURE_MODE no longer defaults to off",
        ),
    ],
)
def test_a_default_spike_p9_rests_on_that_a_new_pin_changes_fails(
    tmp_path: Path, name: str, text: str, says: str
) -> None:
    problems = config_problems(sources(tmp_path, **{name: text}))
    assert len(problems) == 1 and says in problems[0], problems


def test_a_missing_config_file_fails(tmp_path: Path) -> None:
    root = sources(tmp_path)
    (root / CONFIGS["nodes"]).unlink()
    assert any("could not read" in p for p in config_problems(root))


def javascript(config: dict[str, Any]) -> dict[str, Any]:
    return config["task-runners"][0]


def python(config: dict[str, Any]) -> dict[str, Any]:
    return config["task-runners"][1]


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (
            lambda c: javascript(c)["env-overrides"].update(NODE_FUNCTION_ALLOW_BUILTIN="*"),
            "lets JavaScript load Node's own modules beyond crypto: *",
        ),
        (
            lambda c: javascript(c)["env-overrides"].update(NODE_FUNCTION_ALLOW_EXTERNAL="axios"),
            "lets JavaScript load packages beyond moment: axios",
        ),
        (
            lambda c: javascript(c)["args"].remove("--disallow-code-generation-from-strings"),
            "runs JavaScript without --disallow-code-generation-from-strings",
        ),
        (
            lambda c: python(c)["env-overrides"].update(N8N_RUNNERS_STDLIB_ALLOW="os"),
            "lets Python import from its standard library: os",
        ),
        (
            lambda c: python(c)["env-overrides"].update(N8N_RUNNERS_EXTERNAL_ALLOW="*"),
            "lets Python import packages: *",
        ),
        (lambda c: c["task-runners"].pop(1), "has no python runner"),
    ],
)
def test_a_runner_config_that_lets_code_reach_further_fails(change: Any, says: str) -> None:
    config = deepcopy(RUNNER_CONFIG)
    change(config)
    problems = runner_problems(config)
    assert len(problems) == 1 and says in problems[0], problems


def test_the_runner_image_must_be_the_n8n_pin_s_own_version() -> None:
    pins = deepcopy(PINS)
    pins["n8n-runners"]["tag"] = "2.43.0"
    assert version_problems(pins) == [
        "infra/public-images.json pins n8nio/runners 2.43.0, not n8n's own version 2.42.6. "
        "The runner must match n8n's version."
    ]
    del pins["n8n-runners"]
    assert version_problems(pins) == ["infra/public-images.json pins no n8n-runners image."]
