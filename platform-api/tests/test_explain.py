import json
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest

from platform_api.builder import Builder
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.explain import NOTHING_TO_EXPLAIN, Explainer
from platform_api.builder.models import CreateAgentUseCase, UseCaseCreated
from platform_api.orchestration import ExplainWordings
from platform_api.orchestration.agents import HttpAgentRuntime, ModelAccess
from tests.support import ALICE
from tests.test_builder_lifecycle import ModelConnected
from tests.test_made_in_n8n import laid_out, made_in_n8n, named, set_up, space_of
from tests.test_n8n_access import Staffed, lab, s
from tests.test_n8n_builder import WRITES, Drafts
from tests.test_n8n_lifecycle import Workflows, made

pytestmark = pytest.mark.anyio

__all__ = ["lab", "s"]

EXPLAIN = "/api/v1/use-cases/{use_case_id}/explain"
KEY = "sk-example-key-not-real-x7"
ACCESS = ModelAccess(
    style="anthropic", base_url="https://llm-gateway.aisg.sg", model="claude-haiku-5-5", api_key=KEY
)
SMOOTH = (
    "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. It can create "
    "Jira tickets in “MOCK”, each after a yes, and changes nothing else."
)
IN_SHORT = (
    "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
    "It can create Jira tickets in “MOCK”, each after a yes. It changes nothing else."
)
FASTAPI = {
    "name": "FastAPI release check",
    "instruction": "Check FastAPI for new releases.",
    "agents": [
        {
            "card_id": VERSION_CHECKER_ID,
            "values": {"GitHub repository": "fastapi/fastapi", "Jira project": "MOCK"},
        }
    ],
    "schedule": {"day": "every_day", "at": "08:00"},
    "on": True,
}
STEPS = [
    ("Daily 8:00", False, "Starts it"),
    ("Start from the Portal", True, "Starts it"),
    ("Read release", True, "Reads GitHub"),
    ("Compare", True, "Runs an agent"),
    ("Newer?", False, "Shapes the data"),
    ("Ask for a yes", True, "Waits for a yes"),
    ("Create ticket", True, "Writes after a yes"),
    ("Nothing to change", False, "Ends the run"),
]


@dataclass
class Runtime:
    status: int = 200
    answer: object = field(default_factory=lambda: {"kind": "reworded", "text": SMOOTH})
    times_out: bool = False
    asked: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, Any]])

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append((request.url.path, json.loads(request.content)))
        if self.times_out:
            raise httpx.ReadTimeout("no answer", request=request)
        return httpx.Response(self.status, json=self.answer)


class Connected:
    def __init__(self, model: ModelAccess | None) -> None:
        self._model = model

    async def access(self, uow: object) -> ModelAccess | None:
        return self._model


def explainer(s: Staffed, runtime: Runtime, model: ModelAccess | None = ACCESS) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(runtime.handle))
    agents = HttpAgentRuntime("http://agent-runtime:8100", "agent-key-not-real", client=client)
    wordings = ExplainWordings(s.lab.h.db, Connected(model), agents)
    s.lab.app.state.explainer = Explainer(s.lab.h.db, s.lab.builder, wordings)


@pytest.fixture
async def runtime(s: Staffed) -> Runtime:
    answering = Runtime()
    explainer(s, answering)
    return answering


async def fastapi(s: Staffed, **changes: object) -> str:
    use_case_id, _ = await made(s.own, **{**FASTAPI, **changes})
    return use_case_id


async def explain(s: Staffed, user: str, use_case_id: str, **query: object) -> httpx.Response:
    asked = f"?{urlencode(query)}" if query else ""
    path = f"/api/v1/use-cases/{use_case_id}/explain{asked}"
    return await s.lab.call(user, "GET", path, template=EXPLAIN)


async def explained(s: Staffed, user: str, use_case_id: str, **query: object) -> dict[str, Any]:
    answer = await explain(s, user, use_case_id, **query)
    assert answer.status_code == 200, answer.text
    body: dict[str, Any] = answer.json()
    return body


def text(segments: list[dict[str, Any]] | None) -> str:
    return "".join(f"“{p['text']}”" if p["quoted"] else p["text"] for p in segments or [])


async def test_the_fastapi_release_check_explains_in_plain_steps_without_n8n_access(
    s: Staffed, runtime: Runtime
):
    use_case_id = await fastapi(s)
    body = await explained(s, "alice", use_case_id)
    assert (body["use_case_id"], body["name"], body["version"]) == (
        use_case_id,
        "FastAPI release check",
        1,
    )
    assert (body["grade"], body["then"], body["reworded"]) == ("safe", None, None)
    assert text(body["in_short"]) == IN_SHORT
    assert [(st["name"], st["ours"], st["tag"]) for st in body["steps"]] == STEPS
    assert {st["block_type"] for st in body["steps"]} == {None}, "no n8n access, no block types"
    assert [(t["action"], t["system"], t["place"], t["block"]) for t in body["touches"]] == [
        ("reads", "GitHub", "fastapi/fastapi", "Read release"),
        ("reads", "GitHub", "fastapi/fastapi", "Compare"),
        ("reads", "Jira", "MOCK", "Compare"),
        ("writes", "Jira", "MOCK", "Create ticket"),
    ]
    assert [(a["block"], a["decides"], a["approvers"]) for a in body["approves"]] == [
        ("Create ticket", "each_run", 1)
    ]
    assert (body["flags"], body["needs_an_answer"]) == ([], 0)
    assert "no_yes_before_write" in {c["rule"] for c in body["fixed"]}
    assert body["approval"].startswith("None needed. The Planner laid it out")
    assert ("Run time", "every day at 8:00", "set") in [
        (text(x["label"]), text(x["value"]), x["mark"]) for x in body["settings"]
    ]
    assert runtime.asked == [], "only the chat card asks for the reworded one"


async def test_someone_with_n8n_access_sees_each_block_s_type_and_an_approver_sees_the_steps(
    s: Staffed, runtime: Runtime
):
    use_case_id, workflow_id = await made(s.own, **FASTAPI)
    await s.member("carol")
    types = {n["name"]: n["type"] for n in s.n8n.workflows[workflow_id]["nodes"]}
    seen = await explained(s, "carol", use_case_id)
    assert {st["name"]: st["block_type"] for st in seen["steps"]} == {
        name: types[name] for name, _, _ in STEPS
    }
    plain = await explained(s, "bob", use_case_id)
    assert [(st["name"], st["block_type"]) for st in plain["steps"]] == [
        (name, None) for name, _, _ in STEPS
    ]
    assert {**plain, "steps": []} == {**seen, "steps": []}, "the same report otherwise"


async def test_a_deleted_workflow_and_a_version_it_never_had_answer_404(
    s: Staffed, runtime: Runtime
):
    use_case_id = await fastapi(s)
    missing = await explain(s, "alice", use_case_id, version=7)
    assert (missing.status_code, missing.json()["detail"]) == (404, "No such version")
    assert (await s.lab.move("alice", "delete", use_case_id)).status_code == 200
    gone = await explain(s, "alice", use_case_id)
    assert (gone.status_code, gone.json()["detail"]) == (404, "No such workflow")
    assert (await explain(s, "alice", "uc_never")).status_code == 404


async def test_an_older_version_carries_its_number_and_its_grade_then_graded_under_today_s_rules(
    s: Staffed, runtime: Runtime
):
    use_case_id = await fastapi(s)
    path = f"/api/v1/use-cases/{use_case_id}/schedule"
    monday = {"day": "monday", "at": "09:00", "expected_version": 1}
    assert (await s.lab.call("alice", "PUT", path, monday)).status_code == 200
    in_use = await explained(s, "alice", use_case_id, version=2)
    assert (in_use["version"], in_use["then"]) == (2, None)
    assert text(in_use["in_short"]).startswith("Every Monday at 9:00")

    s.lab.builder = Builder(
        s.lab.h.db,
        s.lab.h.orchestrator,
        s.lab.app.state.watchlist,
        "https://portal.example",
        ModelConnected(),
        n8n=Drafts(s.n8n, s.lab.h.db, "wfNewErrorReporter"),
        writes=WRITES,
    )
    explainer(s, runtime)
    older = await explained(s, "alice", use_case_id, version=1)
    assert (older["version"], older["then"]) == (1, {"number": 1, "grade": "safe"})
    assert text(older["in_short"]).startswith("Every day at 8:00")
    assert older["grade"] == "needs_a_fix", "n8n's error workflow changed since"
    assert "no_error_workflow" in {f["rule"] for f in older["flags"]}


async def test_a_draft_explains_with_no_version_and_has_no_versions_to_ask_for(
    s: Staffed, runtime: Runtime
):
    use_case_id = await fastapi(s, on=False)
    draft = await explained(s, "alice", use_case_id)
    assert (draft["version"], draft["then"], draft["grade"]) == (None, None, "safe")
    assert text(draft["in_short"]) == IN_SHORT
    asked = await explain(s, "alice", use_case_id, version=1)
    assert (asked.status_code, asked.json()["detail"]) == (404, "No such version")


async def test_a_workflow_on_the_shared_n8n_workflow_has_nothing_to_explain(
    s: Staffed, runtime: Runtime
):
    shared = Builder(
        s.lab.h.db,
        s.lab.h.orchestrator,
        s.lab.app.state.watchlist,
        "https://portal.example",
        ModelConnected(),
    )
    created = await shared.create_agent_use_case(ALICE, CreateAgentUseCase.model_validate(FASTAPI))
    assert isinstance(created, UseCaseCreated), created
    refused = await explain(s, "alice", created.use_case_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, NOTHING_TO_EXPLAIN)


async def test_a_workflow_set_up_from_n8n_says_its_values_were_set_in_n8n(
    s: Staffed, runtime: Runtime
):
    made_in_n8n(s, s.staff, Workflows(s.n8n, s.lab.h.db))
    carol_n8n, carol_space = await space_of(s, "carol")
    workflow_id = s.n8n.make_in(carol_space, named(await laid_out(s), "Morning check"), carol_n8n)
    created = await set_up(s, "carol", workflow_id)
    assert created.status_code == 201, created.text
    body = await explained(s, "alice", created.json()["use_case_id"])
    assert body["approval"] == "None needed. An Operator with n8n access set it up."
    assert {x["said"] for x in body["settings"]} == {"Set in n8n"}
    assert body["fixed"] == [], "code laid none of it out"


@pytest.mark.parametrize(
    ("status", "answer", "times_out", "reworded"),
    [
        pytest.param(200, {"kind": "reworded", "text": SMOOTH}, False, SMOOTH, id="reworded"),
        pytest.param(200, {"kind": "kept", "why": "negation"}, False, None, id="kept"),
        pytest.param(
            200,
            {"status": "problem", "reason": "too_slow", "message": "The model took too long."},
            False,
            None,
            id="model-problem",
        ),
        pytest.param(500, {"detail": "boom"}, False, None, id="http-500"),
        pytest.param(200, {}, True, None, id="timeout"),
        pytest.param(200, {"kind": "reworded"}, False, None, id="bad-answer"),
    ],
)
async def test_the_chat_card_gets_the_smoothed_in_short_only_when_the_runtime_reworded_it(
    s: Staffed,
    runtime: Runtime,
    status: int,
    answer: object,
    times_out: bool,
    reworded: str | None,
):
    use_case_id = await fastapi(s)
    runtime.status, runtime.answer, runtime.times_out = status, answer, times_out
    body = await explained(s, "bob", use_case_id, reworded="true")
    assert body["reworded"] == reworded
    assert text(body["in_short"]) == IN_SHORT, "code's own wording is always there"
    [(path, sent)] = runtime.asked
    assert path == "/v1/workflows/explain"
    assert sent["model"] == ACCESS.model_dump(mode="json")
    assert sent["wording"] == IN_SHORT
    assert sent["facts"][0] == {"kind": "runs", "together": ["day", "8:00"], "negated": False}


async def test_the_log_names_only_the_status_or_the_error_never_the_words_or_the_key(
    s: Staffed, runtime: Runtime, caplog: pytest.LogCaptureFixture
):
    use_case_id = await fastapi(s)
    runtime.status, runtime.answer = 500, {"detail": IN_SHORT}
    with caplog.at_level(logging.WARNING, logger="platform_api"):
        await explained(s, "alice", use_case_id, reworded="true")
        runtime.status, runtime.times_out = 200, True
        await explained(s, "alice", use_case_id, reworded="true")
    logged = " ".join(caplog.messages)
    assert "500" in logged and "ReadTimeout" in logged
    assert KEY not in logged and "fastapi/fastapi" not in logged


async def test_without_reworded_or_without_a_model_the_runtime_is_never_asked(
    s: Staffed, runtime: Runtime
):
    use_case_id = await fastapi(s)
    assert (await explained(s, "alice", use_case_id, reworded="false"))["reworded"] is None
    explainer(s, runtime, model=None)
    assert (await explained(s, "alice", use_case_id, reworded="true"))["reworded"] is None
    assert runtime.asked == []
