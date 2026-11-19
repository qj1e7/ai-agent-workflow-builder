"""The pin check of what spike P9's verdicts rest on beyond the blocks' own code (ADR 0051, build
step 12): n8n's defaults for the settings bootstrap checks, and the task runner image's own
config, which decides what code in the runner may load.

On each new pin it reads, as the images hold them:
- `@n8n/config`'s security, nodes and runners configs in the n8n image, which must still default
  the file blocks to `~/.n8n-files`, block n8n's own folders, refuse the deprecated blocks, and
  keep the runner's insecure mode off;
- `/etc/n8n-task-runners.json` in the runner image, which must still let JavaScript load only
  `crypto` and `moment`, keep its flags against code made from strings, and let Python import
  nothing;
- infra/public-images.json, whose runner image must be n8n's own version.

The deploy sets most of these settings anyway (deploy/compose.yaml's x-n8n-guards), so a change
here is a change to what an unset setting means, which a person must read before the pin moves.
platform_api.n8n_catalogue runs it on the files scripts/n8n-catalogue.sh copies out of the images.
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

CONFIGS: Mapping[str, str] = {
    "security": "config/configs/security.config.js",
    "nodes": "config/configs/nodes.config.js",
    "runners": "config/configs/runners.config.js",
}
"""Where each of `@n8n/config`'s compiled configs sits under the sources folder."""
RUNNERS_CONFIG = "runners/n8n-task-runners.json"
"""The runner image's /etc/n8n-task-runners.json, under the sources folder."""

DEFAULTS: tuple[tuple[str, str, str], ...] = (
    (
        "security",
        "this.restrictFileAccessTo = '~/.n8n-files';",
        "N8N_RESTRICT_FILE_ACCESS_TO no longer defaults to ~/.n8n-files",
    ),
    (
        "security",
        "this.blockFileAccessToN8nFiles = true;",
        "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES no longer defaults to on",
    ),
    (
        "nodes",
        "this.blockDeprecated = true;",
        "N8N_DEPRECATED_NODES_BLOCK no longer defaults to on",
    ),
    (
        "runners",
        "this.insecureMode = false;",
        "N8N_RUNNERS_INSECURE_MODE no longer defaults to off",
    ),
)
"""For each config, a default written as n8n 2.42.6 compiles it, and what it means when it goes."""

JS_BUILTIN = frozenset({"crypto"})
JS_EXTERNAL = frozenset({"moment"})
JS_FLAGS = ("--disallow-code-generation-from-strings", "--disable-proto=delete")
READ_IT = "Read it, then change the guard or this check in the same change."


def config_problems(sources: Path) -> list[str]:
    """Each default bootstrap's checks rest on that the pinned image no longer has."""
    problems: list[str] = []
    for name, file in CONFIGS.items():
        try:
            text = (sources / file).read_text()
        except OSError:
            problems.append(f"The pin check could not read {file} from the image.")
            continue
        compact = re.sub(r"\s+", " ", text)
        problems += [
            f"{said} in @n8n/config's {name} config. {READ_IT}"
            for config, line, said in DEFAULTS
            if config == name and line not in compact
        ]
    return problems


def runner_problems(config: Mapping[str, Any]) -> list[str]:
    """Each way the runner image's own config lets code reach further than spike P9 saw."""
    runners = {
        str(r.get("runner-type")): r
        for r in cast(list[Mapping[str, Any]], config.get("task-runners") or [])
        if isinstance(r, dict)
    }
    problems: list[str] = []
    javascript, python = runners.get("javascript"), runners.get("python")
    if javascript is None:
        problems.append("The runner image has no javascript runner.")
    else:
        overrides = _overrides(javascript)
        if extra := _listed(overrides.get("NODE_FUNCTION_ALLOW_BUILTIN")) - JS_BUILTIN:
            problems.append(
                "The runner image lets JavaScript load Node's own modules beyond crypto: "
                f"{', '.join(sorted(extra))}."
            )
        if extra := _listed(overrides.get("NODE_FUNCTION_ALLOW_EXTERNAL")) - JS_EXTERNAL:
            problems.append(
                f"The runner image lets JavaScript load packages beyond moment: "
                f"{', '.join(sorted(extra))}."
            )
        args = cast(list[object], javascript.get("args") or [])
        problems += [
            f"The runner image runs JavaScript without {flag}."
            for flag in JS_FLAGS
            if flag not in args
        ]
    if python is None:
        problems.append("The runner image has no python runner.")
    else:
        overrides = _overrides(python)
        if stdlib := _listed(overrides.get("N8N_RUNNERS_STDLIB_ALLOW")):
            problems.append(
                "The runner image lets Python import from its standard library: "
                f"{', '.join(sorted(stdlib))}."
            )
        if external := _listed(overrides.get("N8N_RUNNERS_EXTERNAL_ALLOW")):
            problems.append(
                f"The runner image lets Python import packages: {', '.join(sorted(external))}."
            )
    return problems


def version_problems(pins: Mapping[str, Mapping[str, str]]) -> list[str]:
    """The runner image is n8n's own version, as n8n's broker expects."""
    runner, n8n = pins.get("n8n-runners"), pins.get("n8n")
    if runner is None:
        return ["infra/public-images.json pins no n8n-runners image."]
    if n8n is None or runner.get("tag") != n8n.get("tag"):
        version = None if n8n is None else n8n.get("tag")
        return [
            f"infra/public-images.json pins {runner.get('repository')} {runner.get('tag')}, not "
            f"n8n's own version {version}. The runner must match n8n's version."
        ]
    return []


def _overrides(runner: Mapping[str, Any]) -> Mapping[str, Any]:
    overrides = runner.get("env-overrides")
    return cast(Mapping[str, Any], overrides) if isinstance(overrides, dict) else {}


def _listed(value: object) -> frozenset[str]:
    if not isinstance(value, str):
        return frozenset()
    return frozenset(part.strip() for part in value.split(",") if part.strip())
