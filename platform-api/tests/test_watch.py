from dataclasses import replace
from datetime import timedelta

import pytest

from platform_api.orchestration.agents import Finding, ProposedIntentIn
from platform_api.orchestration.spec import WatchlistTask
from platform_api.orchestration.watch import (
    ATTENTION_ORDER,
    Checked,
    CouldNotCheck,
    CouldNotRead,
    FromFirstCheck,
    FromTicketDone,
    Given,
    OpenTicket,
    PendingTicket,
    ReadNewest,
    Reviewed,
    SoftwareFacts,
    Standing,
    Status,
    TicketToPropose,
    Unusable,
    newer,
    review,
    standing,
    status_of,
)
from platform_api.shared import ApprovalId, ProposalId, RunId, SoftwareId
from tests.support import FASTAPI, LANGGRAPH, NOW, POSTGRES, REDIS, WATCHLIST_TASK, watched

RUN = RunId("run_1")
LATER = NOW + timedelta(minutes=5)
GIVEN = Given("1.2.14", NOW)
NEWEST = Checked(RUN, LATER, "1.2.16")
SAME = Checked(RUN, LATER, "1.2.14")
PENDING = PendingTicket(ProposalId("prp_1"), 0, "1.2.16", ApprovalId("apr_1"))
OPEN = OpenTicket("MOCK-7", "1.2.16")
NOTHING = SoftwareFacts(None, None, None, None)

TASK = WATCHLIST_TASK


@pytest.mark.parametrize(
    ("candidate", "than", "expected"),
    [
        ("1.2.16", "1.2.14", True),
        ("1.2.14", "1.2.16", False),
        ("1.2.14", "1.2.14", False),
        ("1.10.0", "1.9.9", True),
        ("2.0.0", "1.99.99", True),
        ("8.2.1", "8.2", True),
        ("v2", "v1", True),
        ("v1", "v1", False),
    ],
)
def test_newer_compares_version_numbers_part_by_part(candidate: str, than: str, expected: bool):
    assert newer(candidate, than) is expected


@pytest.mark.parametrize(
    ("facts", "status"),
    [
        (NOTHING, "not_checked"),
        (replace(NOTHING, our_version=GIVEN), "not_checked"),
        (SoftwareFacts(GIVEN, NEWEST, None, None), "behind"),
        (SoftwareFacts(GIVEN, SAME, None, None), "up_to_date"),
        (SoftwareFacts(FromFirstCheck("1.2.16", LATER), NEWEST, None, None), "up_to_date"),
        (
            SoftwareFacts(FromTicketDone("1.2.16", LATER, "MOCK-7"), NEWEST, None, None),
            "up_to_date",
        ),
        (SoftwareFacts(None, NEWEST, None, None), "up_to_date"),
        (SoftwareFacts(GIVEN, NEWEST, PENDING, None), "awaiting_approval"),
        (
            SoftwareFacts(GIVEN, NEWEST, replace(PENDING, approval_id=None), None),
            "awaiting_approval",
        ),
        (SoftwareFacts(GIVEN, NEWEST, None, OPEN), "ticket_open"),
        (SoftwareFacts(GIVEN, NEWEST, PENDING, OPEN), "awaiting_approval"),
        (
            SoftwareFacts(GIVEN, CouldNotCheck(RUN, LATER, "GitHub answered 404"), None, None),
            "cant_check",
        ),
        (SoftwareFacts(GIVEN, CouldNotCheck(RUN, LATER, "no answer"), PENDING, OPEN), "cant_check"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_the_status_rules_apply_in_order(facts: SoftwareFacts, status: Status):
    assert status_of(facts) == status


def test_every_status_has_a_place_in_the_attention_order():
    assert set(ATTENTION_ORDER) == set(Status.__value__.__args__)
    assert ATTENTION_ORDER[0] == "cant_check" and ATTENTION_ORDER[-1] == "up_to_date"


def test_a_learned_version_outranks_the_one_the_operator_typed():
    learned = FromTicketDone("1.2.16", LATER, "MOCK-7")
    assert standing(GIVEN, learned, NEWEST, None, None) == Standing(
        SoftwareFacts(learned, NEWEST, None, None), "up_to_date"
    )
    assert standing(GIVEN, None, NEWEST, None, None).facts.our_version == GIVEN
    assert standing(None, None, None, None, None) == Standing(NOTHING, "not_checked")


def finding(software_id: SoftwareId, state: str, newest: str | None, detail: str = "") -> Finding:
    return Finding.model_validate(
        {
            "software_id": software_id,
            "state": state,
            "newest": newest,
            "new_versions": [newest] if state == "behind" and newest else [],
            "detail": detail,
        }
    )


def ticket(subject: str | None, name: str = "LangGraph") -> ProposedIntentIn:
    return ProposedIntentIn(
        kind="create_ticket",
        fields={"title": f"Upgrade {name}", "body": "..."},
        reason=f"{name} is behind",
        subject=subject,
    )


FINDINGS = [
    finding(LANGGRAPH, "behind", "1.2.16"),
    finding(REDIS, "starting_point", "8.2.1"),
    finding(FASTAPI, "cant_check", None, "GitHub answered 404 Not Found."),
    finding(POSTGRES, "up_to_date", "17.2"),
]


def test_a_sound_answer_is_kept_as_what_was_learned_and_which_tickets_to_make():
    assert review(TASK, FINDINGS, [ticket(LANGGRAPH)]) == Reviewed(
        (
            ReadNewest(LANGGRAPH, "1.2.16", False),
            ReadNewest(REDIS, "8.2.1", True),
            CouldNotRead(FASTAPI, "GitHub answered 404 Not Found."),
            ReadNewest(POSTGRES, "17.2", False),
        ),
        (TicketToPropose(0, LANGGRAPH, "1.2.16"),),
    )


def test_findings_may_leave_software_out_and_tickets_may_be_absent():
    assert review(TASK, FINDINGS[:1], []) == Reviewed((ReadNewest(LANGGRAPH, "1.2.16", False),), ())
    assert review(TASK, [], []) == Reviewed((), ())


HELD = replace(
    TASK,
    software=(
        watched(LANGGRAPH, "LangGraph", "langchain-ai/langgraph", "1.2.14", open_ticket="MOCK-3"),
        watched(REDIS, "Redis", "redis/redis", "8.2.0", awaiting_approval=True),
    ),
)


@pytest.mark.parametrize(
    ("task", "findings", "proposed", "words"),
    [
        (TASK, [finding(SoftwareId("sw_ghost"), "behind", "1.0.0")], [], "not on the list"),
        (TASK, [FINDINGS[0], FINDINGS[0]], [], "twice on LangGraph"),
        (TASK, [finding(LANGGRAPH, "behind", None)], [], "no newest version for LangGraph"),
        (TASK, FINDINGS, [ticket(None)], "without naming its software"),
        (TASK, FINDINGS, [ticket("sw_ghost", "Ghost")], "sw_ghost, which is not on the list"),
        (TASK, FINDINGS, [ticket(LANGGRAPH), ticket(LANGGRAPH)], "two tickets for LangGraph"),
        (TASK, FINDINGS, [ticket(FASTAPI, "FastAPI")], "FastAPI without reading its newest"),
        (TASK, FINDINGS[1:], [ticket(LANGGRAPH)], "LangGraph without reading its newest"),
        (HELD, [finding(LANGGRAPH, "behind", "1.2.16")], [ticket(LANGGRAPH)], "has one already"),
        (
            HELD,
            [finding(REDIS, "behind", "8.2.1")],
            [ticket(REDIS, "Redis")],
            "Redis, which has one",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_an_answer_that_does_not_fit_the_list_is_unusable(
    task: WatchlistTask, findings: list[Finding], proposed: list[ProposedIntentIn], words: str
):
    result = review(task, findings, proposed)
    assert isinstance(result, Unusable)
    assert words in result.detail
