"""The pin check of what the code of n8n's blocks reaches (ADR 0051, section 2), on small
packages laid out as the image holds them. scripts/pack-smoke.sh runs it on the image itself."""

import json
from pathlib import Path

import pytest

from platform_api.n8n_code_check import KNOWN, problems, scan

LISTED = ["fs", "tmp-promise", "vm", "v8"]
DEBUG_HELPER = """const v8_1 = require("v8");
const vm_1 = require("vm");
const runGarbageCollector = () => {
    (0, v8_1.setFlagsFromString)('--expose_gc');
    const gc = (0, vm_1.runInNewContext)('gc');
    gc();
};"""
"""What n8n 2.42.6's Debug Helper runs, from dist/nodes/DebugHelper/functions.js."""


def a_package(
    root: Path,
    package: str,
    blocks: dict[str, tuple[str, str]],
    shared: dict[str, str] | None = None,
) -> None:
    """Writes a package as the image holds it: its list of blocks, each block's code, and the
    helpers its blocks share."""
    known = {}
    for short, (folder, code) in blocks.items():
        source = f"dist/nodes/{folder}/{short}.node.js"
        known[short] = {"className": short, "sourcePath": source}
        (root / package / source).parent.mkdir(parents=True, exist_ok=True)
        (root / package / source).write_text(code)
    (root / package / "dist" / "known").mkdir(parents=True, exist_ok=True)
    (root / package / "dist" / "known" / "nodes.json").write_text(json.dumps(known))
    for path, code in (shared or {}).items():
        (root / package / "dist" / "utils" / path).parent.mkdir(parents=True, exist_ok=True)
        (root / package / "dist" / "utils" / path).write_text(code)


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    a_package(
        tmp_path,
        "n8n-nodes-base",
        {
            "webhook": ("Webhook", 'const fs_1 = require("fs"); require("tmp-promise");'),
            "mautic": ("Mautic", "displayName: 'Sandbox', isSandbox, enableSandbox"),
            "sort": ("Sort", 'require("../Code/JsTaskRunnerSandbox")'),
            "jira": ("Jira", "this.helpers.request(); await client.eval(script, keys);"),
            "debugHelper": ("DebugHelper", DEBUG_HELPER),
        },
        {"binary.js": 'require("n8n-workflow"); require("./utilities");'},
    )
    a_package(
        tmp_path,
        "@n8n/n8n-nodes-langchain",
        {
            "toolWorkflow": ("tools/ToolWorkflow", "await this.executeWorkflow(info, items)"),
            "code": ("code", "return `require('${newPath}')`; require('@n8n/ai-utilities');"),
        },
    )
    return tmp_path


def jira_also_runs(sources: Path, code: str) -> None:
    (sources / "n8n-nodes-base" / "dist" / "nodes" / "Jira" / "More.js").write_text(code)


def test_it_reads_what_each_block_s_code_reaches_and_what_it_reads_in(sources: Path):
    found = scan(sources)

    assert found.blocks == {
        "n8n-nodes-base.webhook": {"fs"},
        "n8n-nodes-base.mautic": set(),
        "n8n-nodes-base.sort": {"runs code"},
        "n8n-nodes-base.jira": set(),
        "n8n-nodes-base.debugHelper": {"runs code"},
        "@n8n/n8n-nodes-langchain.toolWorkflow": {"another workflow"},
        "@n8n/n8n-nodes-langchain.code": set(),
    }
    assert found.shared == {}
    assert found.imports == {"fs", "tmp-promise", "v8", "vm"}


def test_it_passes_what_section_2_names(sources: Path):
    assert problems(scan(sources), LISTED) == []


def test_debug_helper_would_fail_without_its_entry(sources: Path):
    (sources / "n8n-nodes-base" / "dist" / "nodes" / "Jira" / "Gc.js").write_text(DEBUG_HELPER)

    (problem,) = problems(scan(sources), LISTED)

    assert problem.startswith("n8n-nodes-base.jira reaches runs code, which ADR 0051")


@pytest.mark.parametrize(
    ("code", "reached"),
    [
        ('require("node:child_process").exec(command)', "child_process"),
        ("const url = process.env.JIRA_URL", "process.env"),
        ("await this.helpers.writeContentToFile(path, data)", "file helpers"),
        ('import { readFile } from "node:fs/promises"', "fs"),
        ('const vm = require("vm2")', "runs code"),
        ("new JavaScriptSandbox(context, code)", "runs code"),
        ('const vm = require("node:vm")', "runs code"),
        ("new vm.Script(code).runInContext(context)", "runs code"),
        ("(0, vm_1.runInThisContext)(code)", "runs code"),
        ("return eval(code)", "runs code"),
        ("(0, eval)(code)", "runs code"),
        ("const run = new Function('items', code)", "runs code"),
        ("await this.helpers.executeWorkflow(info)", "another workflow"),
    ],
)
def test_it_fails_on_a_block_reaching_what_section_2_does_not_name_for_it(
    sources: Path, code: str, reached: str
):
    jira_also_runs(sources, code)

    found = problems(scan(sources), [*LISTED, "child_process", "vm2"])

    assert found == [
        f"n8n-nodes-base.jira reaches {reached}, which ADR 0051 doesn't name for it. Read its "
        "code, then hold it off or add it to KNOWN in platform_api/n8n_code_check.py."
    ]


def test_a_known_block_reaching_something_new_fails_too(sources: Path):
    (sources / "n8n-nodes-base" / "dist" / "nodes" / "Webhook" / "Run.js").write_text(
        'require("child_process")'
    )

    (problem,) = problems(scan(sources), [*LISTED, "child_process"])

    assert problem.startswith("n8n-nodes-base.webhook reaches child_process, which")


def test_a_shared_helper_that_reaches_anything_fails(sources: Path):
    helper = sources / "n8n-nodes-base" / "dist" / "utils" / "sendAndWait" / "email.js"
    helper.parent.mkdir(parents=True)
    helper.write_text("const from = process.env.MAIL_FROM;")

    assert problems(scan(sources), LISTED) == [
        "The shared helper n8n-nodes-base/dist/utils/sendAndWait/email.js reaches process.env. "
        "Read it and the blocks that use it, then add it to KNOWN_SHARED in "
        "platform_api/n8n_code_check.py."
    ]


def test_a_package_nobody_has_looked_at_fails(sources: Path):
    jira_also_runs(sources, 'const git = require("simple-git/promise"); require("@scope/pkg/x");')

    assert problems(scan(sources), LISTED) == [
        "n8n's blocks now read in @scope/pkg, which platform_api/n8n_block_imports.json doesn't "
        "list. Look at what it can do, then add it.",
        "n8n's blocks now read in simple-git, which platform_api/n8n_block_imports.json doesn't "
        "list. Look at what it can do, then add it.",
    ]


def test_every_block_section_2_names_reaches_something():
    assert all(KNOWN.values())
