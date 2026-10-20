"""The n8n workflow files, read once into a model shared by the lint, bootstrap and the fake engine.

A file is a plain n8n export with `${PLACEHOLDER}` strings that bootstrap fills in. The lint
checks the design's seven rules on the files in CI and again on what n8n hands back.
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from platform_api.orchestration.dispatch import RETRY_POLICY
from platform_api.orchestration.runs import (
    DEADLINES,
    LEG_STEPS,
    STEP_LEG,
    Acting,
    ActiveState,
    Leg,
    Pending,
    Proposed,
    StepName,
    Working,
)
from platform_api.orchestration.write_actions import CONNECTOR_TIMEOUT

WORKFLOWS_DIR = Path(__file__).parent / "workflows"
PLATFORM_INTERNAL_URL = "${PLATFORM_INTERNAL_URL}"
ERROR_WORKFLOW_ID = "${ERROR_WORKFLOW_ID}"
STEP_KEY_CREDENTIAL_ID = "${STEP_KEY_CREDENTIAL_ID}"
INTERNAL_PREFIX = "/internal/v1/"
MIN_RETRY_WAIT = timedelta(milliseconds=2000)

_PLACEHOLDER = re.compile(r"\$\{([A-Z_]+)\}")
_STEP_URL = re.compile(
    r"^(?P<base>.+)/internal/v1/runs/"
    r"\{\{ \$\('(?P<webhook>[^']+)'\)\.first\(\)\.json\.body\.run_id \}\}"
    r"/steps/(?P<step>[a-z_]+)$"
)


class NodeType(Enum):
    WEBHOOK = "n8n-nodes-base.webhook"
    RESPOND = "n8n-nodes-base.respondToWebhook"
    HTTP_REQUEST = "n8n-nodes-base.httpRequest"
    IF = "n8n-nodes-base.if"
    ERROR_TRIGGER = "n8n-nodes-base.errorTrigger"


ALLOWED_NODE_TYPES = frozenset(t.value for t in NodeType)

# The run state each step runs in, and the state each leg's dispatch lands in. Rule 5 sums
# the budgets per state and compares them with the deadline of that state.
STEP_STATE: Mapping[StepName, type[ActiveState]] = {
    StepName.RUN_AGENTS: Working,
    StepName.ASK_APPROVAL: Proposed,
    StepName.WRITE_ACTION: Acting,
}
DISPATCH_STATE: Mapping[Leg, type[ActiveState]] = {Leg.WORK: Pending, Leg.ACT: Acting}


@dataclass(frozen=True)
class StepNode:
    step: StepName
    node_name: str
    tries: int
    wait: timedelta
    timeout: timedelta

    @property
    def budget(self) -> timedelta:
        return self.tries * self.timeout + (self.tries - 1) * self.wait


@dataclass(frozen=True)
class HttpNode:
    name: str
    url: str
    tries: int
    wait: timedelta
    timeout: timedelta


@dataclass(frozen=True)
class WebhookNode:
    name: str
    path: str


@dataclass(frozen=True)
class StepUrl:
    base: str
    webhook: str
    step: str


def parse_step_url(url: str) -> StepUrl | None:
    match = _STEP_URL.match(url)
    if match is None:
        return None
    return StepUrl(match["base"], match["webhook"], match["step"])


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    document: Mapping[str, Any]
    node_types: Mapping[str, str]
    webhooks: tuple[WebhookNode, ...]
    http_nodes: Mapping[str, HttpNode]
    chains: Mapping[str, tuple[str, ...]]
    error_workflow: str | None
    is_error_workflow: bool

    def webhook_path(self, leg: Leg) -> str:
        return f"{self.name.replace('_', '-')}/{leg.value}"

    def webhook(self, leg: Leg) -> WebhookNode | None:
        path = self.webhook_path(leg)
        return next((w for w in self.webhooks if w.path == path), None)

    def leg_http_nodes(self, leg: Leg) -> tuple[HttpNode, ...]:
        webhook = self.webhook(leg)
        if webhook is None:
            return ()
        chain = self.chains.get(webhook.name, ())
        return tuple(self.http_nodes[name] for name in chain if name in self.http_nodes)

    def steps(self, leg: Leg) -> tuple[StepNode, ...]:
        webhook = self.webhook(leg)
        if webhook is None:
            return ()
        found: list[StepNode] = []
        for node in self.leg_http_nodes(leg):
            parsed = parse_step_url(node.url)
            if parsed is None or parsed.webhook != webhook.name:
                continue
            try:
                step = StepName(parsed.step)
            except ValueError:
                continue
            found.append(StepNode(step, node.name, node.tries, node.wait, node.timeout))
        return tuple(found)


def parse(document: Mapping[str, Any]) -> WorkflowDefinition:
    """Read an n8n workflow document. Only name, nodes, connections and settings matter."""
    nodes: list[Mapping[str, Any]] = list(document.get("nodes", []))
    node_types = {str(n["name"]): str(n["type"]) for n in nodes}
    webhooks = tuple(
        WebhookNode(str(n["name"]), str(n.get("parameters", {}).get("path", "")))
        for n in nodes
        if n["type"] == NodeType.WEBHOOK.value
    )
    http_nodes = {
        str(n["name"]): _http_node(n) for n in nodes if n["type"] == NodeType.HTTP_REQUEST.value
    }
    connections: Mapping[str, Any] = document.get("connections", {})
    chains = {w.name: _chain(connections, w.name) for w in webhooks}
    settings: Mapping[str, Any] = document.get("settings", {})
    error_workflow = settings.get("errorWorkflow")
    return WorkflowDefinition(
        name=str(document["name"]),
        document=document,
        node_types=node_types,
        webhooks=webhooks,
        http_nodes=http_nodes,
        chains=chains,
        error_workflow=str(error_workflow) if error_workflow is not None else None,
        is_error_workflow=NodeType.ERROR_TRIGGER.value in node_types.values(),
    )


def _http_node(node: Mapping[str, Any]) -> HttpNode:
    parameters: Mapping[str, Any] = node.get("parameters", {})
    url = str(parameters.get("url", "")).removeprefix("=")
    retries = bool(node.get("retryOnFail", False))
    tries = int(node.get("maxTries", 3)) if retries else 1
    wait = (
        timedelta(milliseconds=int(node.get("waitBetweenTries", 1000))) if retries else timedelta()
    )
    timeout = timedelta(milliseconds=int(parameters.get("options", {}).get("timeout", 0)))
    return HttpNode(str(node["name"]), url, tries, wait, timeout)


def _chain(connections: Mapping[str, Any], start: str) -> tuple[str, ...]:
    """Every node downstream of `start`, in connection order, each once."""
    order: list[str] = []
    stack = [start]
    while stack:
        name = stack.pop()
        if name in order:
            continue
        order.append(name)
        outputs: list[list[Mapping[str, Any]]] = connections.get(name, {}).get("main", [])
        successors = [str(link["node"]) for output in outputs for link in output]
        stack.extend(reversed(successors))
    return tuple(order)


def load_all(directory: Path = WORKFLOWS_DIR) -> tuple[WorkflowDefinition, ...]:
    return tuple(
        parse(json.loads(path.read_text())) for path in sorted(directory.glob("*.n8n.json"))
    )


def placeholders(definition: WorkflowDefinition) -> frozenset[str]:
    return frozenset(_PLACEHOLDER.findall(json.dumps(definition.document)))


def render(definition: WorkflowDefinition, values: Mapping[str, str]) -> dict[str, Any]:
    """The body for n8n's workflow API, with every placeholder filled in."""
    missing = placeholders(definition) - values.keys()
    if missing:
        raise ValueError(f"{definition.name}: no value for {', '.join(sorted(missing))}")
    text = json.dumps(
        {key: definition.document[key] for key in ("name", "nodes", "connections", "settings")}
    )
    rendered = _PLACEHOLDER.sub(lambda m: json.dumps(values[m[1]])[1:-1], text)
    return json.loads(rendered)


class Rule(Enum):
    WEBHOOK_PATHS = 1
    INTERNAL_URLS = 2
    STEP_ORDER = 3
    RETRY_WAIT = 4
    DEADLINES = 5
    ERROR_WORKFLOW = 6
    NODE_TYPES = 7


@dataclass(frozen=True)
class Finding:
    rule: Rule
    workflow: str
    message: str

    def __str__(self) -> str:
        return f"rule {self.rule.value} ({self.rule.name.lower()}), {self.workflow}: {self.message}"


@dataclass(frozen=True)
class LiveWorkflow:
    id: str
    active: bool


@dataclass(frozen=True)
class LiveState:
    """What n8n reports after bootstrap loads the workflows, keyed by workflow name."""

    platform_internal_url: str
    workflows: Mapping[str, LiveWorkflow]


def lint(
    definitions: Iterable[WorkflowDefinition], *, live: LiveState | None = None
) -> list[Finding]:
    definitions = tuple(definitions)
    findings: list[Finding] = []
    error_workflows = [d for d in definitions if d.is_error_workflow]
    base = PLATFORM_INTERNAL_URL if live is None else live.platform_internal_url
    for d in definitions:
        findings += _node_types(d)
        findings += _internal_urls(d, base)
        findings += _retry_waits(d)
        if not d.is_error_workflow:
            findings += _webhook_paths(d)
            findings += _step_order(d)
            findings += _deadlines(d)
            findings += _error_workflow_setting(d, error_workflows, live)
    if len(error_workflows) != 1:
        names = ", ".join(d.name for d in error_workflows) or "none"
        findings.append(
            Finding(Rule.ERROR_WORKFLOW, "*", f"expected one error workflow, found {names}")
        )
    return findings


def _webhook_paths(d: WorkflowDefinition) -> list[Finding]:
    expected = {d.webhook_path(leg): leg for leg in Leg}
    findings = [
        Finding(Rule.WEBHOOK_PATHS, d.name, f"webhook '{w.name}' has path '{w.path}'")
        for w in d.webhooks
        if w.path not in expected
    ]
    for path in expected:
        count = sum(1 for w in d.webhooks if w.path == path)
        if count != 1:
            findings.append(
                Finding(Rule.WEBHOOK_PATHS, d.name, f"{count} webhooks have path '{path}'")
            )
    return findings


def _internal_urls(d: WorkflowDefinition, base: str) -> list[Finding]:
    prefix = base + INTERNAL_PREFIX
    return [
        Finding(Rule.INTERNAL_URLS, d.name, f"'{n.name}' calls {n.url}, not {prefix}")
        for n in d.http_nodes.values()
        if not n.url.startswith(prefix)
    ]


def _step_order(d: WorkflowDefinition) -> list[Finding]:
    findings: list[Finding] = []
    for leg in Leg:
        webhook = d.webhook(leg)
        if webhook is None:
            continue
        for node in d.leg_http_nodes(leg):
            parsed = parse_step_url(node.url)
            if parsed is None:
                findings.append(
                    Finding(
                        Rule.STEP_ORDER,
                        d.name,
                        f"'{node.name}' must call .../runs/{{{{ $('{webhook.name}')"
                        f".first().json.body.run_id }}}}/steps/<step>",
                    )
                )
            elif parsed.webhook != webhook.name:
                findings.append(
                    Finding(
                        Rule.STEP_ORDER,
                        d.name,
                        f"'{node.name}' reads run_id from '{parsed.webhook}', "
                        f"not from '{webhook.name}'",
                    )
                )
            elif parsed.step not in {s.value for s in StepName}:
                findings.append(
                    Finding(Rule.STEP_ORDER, d.name, f"'{node.name}' names no step: {parsed.step}")
                )
            elif STEP_LEG[StepName(parsed.step)] is not leg:
                findings.append(
                    Finding(
                        Rule.STEP_ORDER,
                        d.name,
                        f"'{node.name}' calls {parsed.step}, which belongs to the "
                        f"{STEP_LEG[StepName(parsed.step)].value} leg",
                    )
                )
        found = tuple(s.step for s in d.steps(leg))
        if found != LEG_STEPS[leg]:
            findings.append(
                Finding(
                    Rule.STEP_ORDER,
                    d.name,
                    f"the {leg.value} leg calls {[s.value for s in found]}, "
                    f"expected {[s.value for s in LEG_STEPS[leg]]}",
                )
            )
    return findings


def _retry_waits(d: WorkflowDefinition) -> list[Finding]:
    findings: list[Finding] = []
    for n in d.http_nodes.values():
        if n.tries < 2:
            findings.append(Finding(Rule.RETRY_WAIT, d.name, f"'{n.name}' does not retry"))
        elif n.wait < MIN_RETRY_WAIT:
            findings.append(
                Finding(
                    Rule.RETRY_WAIT,
                    d.name,
                    f"'{n.name}' waits {_ms(n.wait)} ms between tries, "
                    f"less than {_ms(MIN_RETRY_WAIT)} ms",
                )
            )
    return findings


def _deadlines(d: WorkflowDefinition) -> list[Finding]:
    findings: list[Finding] = []
    budgets: dict[type[ActiveState], timedelta] = {
        DISPATCH_STATE[leg]: RETRY_POLICY.dispatch_budget for leg in Leg
    }
    for leg in Leg:
        for node in d.steps(leg):
            if node.timeout <= timedelta():
                findings.append(
                    Finding(Rule.DEADLINES, d.name, f"'{node.node_name}' sets no timeout")
                )
                continue
            if node.step is StepName.WRITE_ACTION and node.timeout <= CONNECTOR_TIMEOUT:
                findings.append(
                    Finding(
                        Rule.DEADLINES,
                        d.name,
                        f"'{node.node_name}' times out after {node.timeout.total_seconds():g} s, "
                        f"not longer than the connector timeout of "
                        f"{CONNECTOR_TIMEOUT.total_seconds():g} s",
                    )
                )
            state = STEP_STATE[node.step]
            budgets[state] = budgets.get(state, timedelta()) + node.budget
    for state, budget in budgets.items():
        if budget > DEADLINES[state]:
            findings.append(
                Finding(
                    Rule.DEADLINES,
                    d.name,
                    f"{state.__name__} needs {budget.total_seconds():g} s but its deadline is "
                    f"{DEADLINES[state].total_seconds():g} s",
                )
            )
    return findings


def _error_workflow_setting(
    d: WorkflowDefinition, error_workflows: list[WorkflowDefinition], live: LiveState | None
) -> list[Finding]:
    if live is None:
        if d.error_workflow != ERROR_WORKFLOW_ID:
            return [
                Finding(
                    Rule.ERROR_WORKFLOW,
                    d.name,
                    f"settings.errorWorkflow is {d.error_workflow!r}, not {ERROR_WORKFLOW_ID}",
                )
            ]
        return []
    if len(error_workflows) != 1:
        return []
    reporter = live.workflows.get(error_workflows[0].name)
    if reporter is None:
        return [Finding(Rule.ERROR_WORKFLOW, d.name, "the error workflow is not loaded in n8n")]
    findings: list[Finding] = []
    if d.error_workflow != reporter.id:
        findings.append(
            Finding(
                Rule.ERROR_WORKFLOW,
                d.name,
                f"settings.errorWorkflow is {d.error_workflow!r}, "
                f"not the error workflow's id {reporter.id}",
            )
        )
    if not reporter.active:
        findings.append(
            Finding(
                Rule.ERROR_WORKFLOW,
                d.name,
                f"the error workflow {reporter.id} is inactive, so n8n would skip it",
            )
        )
    return findings


def _node_types(d: WorkflowDefinition) -> list[Finding]:
    return [
        Finding(Rule.NODE_TYPES, d.name, f"'{name}' is a {node_type}")
        for name, node_type in d.node_types.items()
        if node_type not in ALLOWED_NODE_TYPES
    ]


def _ms(value: timedelta) -> int:
    return int(value.total_seconds() * 1000)
