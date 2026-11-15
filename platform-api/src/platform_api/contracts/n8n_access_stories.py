"""n8n access per person and the In n8n data (ENGINE-PLAN E7): Carol, an Operator with n8n access,
her own n8n account before and after she sets her password, the workflow she holds as n8n holds
it, and a run of it waiting at the yes and then ended, each block's state read."""

from dataclasses import replace
from datetime import timedelta

from platform_api.builder.n8n_draft import Checked
from platform_api.builder.n8n_http import HoldOut
from platform_api.builder.n8n_view import N8nHolderView, RunN8nView, UseCaseN8nView, graph
from platform_api.contracts.cards_stories import USE_CASE as AGENT_USE_CASE
from platform_api.contracts.lifecycle_stories import LAID_OUT, SET_UP_IN_N8N
from platform_api.contracts.people_stories import ADDED, CAROL
from platform_api.orchestration.n8n_staff import SET_PASSWORD
from platform_api.orchestration.people import N8nAccount, PeopleRefusal
from platform_api.orchestration.people_http import MyN8nOut, PeopleRefusalOut, person_out
from platform_api.orchestration.people_store import PersonRow
from platform_api.shared import RunId
from platform_api.wire import WireModel

EDITOR = "https://n8n.example"
assert SET_UP_IN_N8N.n8n_workflow_id is not None and isinstance(LAID_OUT, Checked)
WORKFLOW: str = SET_UP_IN_N8N.n8n_workflow_id
OPENED = ADDED + timedelta(days=1, hours=2)
CAROL_IN_N8N = replace(CAROL, n8n_access=True, n8n_account=N8nAccount("n8n-user-carol", False))
NODES, EDGES = graph(LAID_OUT.document)
IN_N8N = UseCaseN8nView(
    use_case_id=AGENT_USE_CASE.use_case_id,
    workflow_id=WORKFLOW,
    version=1,
    n8n_version_id="2f6d4c1e-1d52-4a8e-9b1c-6f1f0f6b2c11",
    published_by=CAROL.id,
    published_by_name=CAROL.display,
    published_in="portal",
    nodes=NODES,
    edges=EDGES,
    holder=None,
    can_open=True,
    why_not=None,
    editor_url=None,
)
HELD = IN_N8N.model_copy(
    update={
        "holder": N8nHolderView(id=CAROL.id, name=CAROL.display, since=OPENED),
        "editor_url": f"{EDITOR}/workflow/{WORKFLOW}",
    }
)
RUN = RunN8nView(
    run_id=RunId("run_01JN8N"),
    use_case_id=AGENT_USE_CASE.use_case_id,
    workflow_id=WORKFLOW,
    execution_id="482",
    n8n_version_id=IN_N8N.n8n_version_id,
    nodes=NODES,
    edges=EDGES,
    states={"Read release": "done", "Compare": "done", "Ask for a yes": "waiting"},
    from_n8n=False,
)
RUN_ENDED = RUN.model_copy(
    update={
        "states": {
            "Start from the Portal": "done",
            "Read release": "done",
            "Compare": "done",
            "Newer?": "done",
            "Ask for a yes": "done",
            "Create ticket": "failed",
        },
        "from_n8n": True,
    }
)


def n8n_access_fixtures() -> dict[str, WireModel | list[WireModel]]:
    return {
        "people/person.n8n-access.json": person_out(PersonRow(CAROL_IN_N8N, None)),
        "people/refusal.n8n_operators_only.json": PeopleRefusalOut(
            refusal=PeopleRefusal.N8N_OPERATORS_ONLY,
            message="Only Operators can have n8n access, and Approvers never can.",
        ),
        "people/me-n8n.invited.json": MyN8nOut(
            access=True,
            account="invited",
            set_password_url="https://n8n.example/signup?token=example-not-a-real-token",
            can_open=False,
            why_not=SET_PASSWORD,
            editor_url=None,
        ),
        "people/me-n8n.ready.json": MyN8nOut(
            access=True,
            account="ready",
            set_password_url=None,
            can_open=True,
            why_not=None,
            editor_url=EDITOR,
        ),
        "builder/use-case.n8n.json": IN_N8N,
        "builder/use-case.n8n.held.json": HELD,
        "builder/opened-in-n8n.json": HoldOut(
            use_case_id=IN_N8N.use_case_id,
            workflow_id=WORKFLOW,
            held_by=CAROL.id,
            held_since=OPENED,
            editor_url=f"{EDITOR}/workflow/{WORKFLOW}",
        ),
        "builder/run.n8n.waiting.json": RUN,
        "builder/run.n8n.ended.json": RUN_ENDED,
    }
