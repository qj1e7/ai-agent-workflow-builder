from typing import cast

import pytest

from platform_api.builder.models import AddSoftware, WatchlistView
from platform_api.orchestration import RemoveSoftwareAnswer
from platform_api.shared import Principal, Role, UserId
from tests.test_builder_http import Front, answered, ask_as_bob, front, say

__all__ = ["front"]

pytestmark = pytest.mark.anyio

ALICE = Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice")


async def watch(front: Front, name: str, repo: str) -> str:
    view = await front.watchlist.add(ALICE, AddSoftware(name=name, repo=repo))
    assert isinstance(view, WatchlistView), view
    return next(s.id for s in view.software if s.name == name)


async def removal(front: Front, software: str, *watched_as: str) -> dict[str, object]:
    asked = RemoveSoftwareAnswer(software=software, watched_as=list(watched_as))
    front.answers.result = answered(asked)
    reply = await say(front, f"remove {software} from the watchlist")
    assert reply["answer"] == "remove_software", reply
    return reply


def names(reply: dict[str, object]) -> list[str]:
    return [m["name"] for m in cast(list[dict[str, str]], reply["matches"])]


async def test_the_runtimes_match_is_the_software_to_remove(front: Front):
    node = await watch(front, "node js", "nodejs/node")
    await watch(front, "LangGraph", "langchain-ai/langgraph")
    reply = await removal(front, "Node.js", "node js")
    assert reply["software"] == "Node.js"
    assert reply["matches"] == [{"software_id": node, "name": "node js", "source": "nodejs/node"}]
    assert reply["watched"] == ["LangGraph", "node js"]


async def test_several_matches_are_each_offered(front: Front):
    await watch(front, "node js", "nodejs/node")
    await watch(front, "Node.js", "nodejs/nodejs.org")
    assert sorted(names(await removal(front, "nodejs", "node js", "Node.js"))) == [
        "Node.js",
        "node js",
    ]


async def test_a_name_the_watchlist_doesnt_hold_names_what_it_holds(front: Front):
    await watch(front, "LangGraph", "langchain-ai/langgraph")
    reply = await removal(front, "Kubernetes")
    assert (reply["matches"], reply["watched"]) == ([], ["LangGraph"])


async def test_software_removed_since_the_facts_were_read_is_no_match(front: Front):
    await watch(front, "LangGraph", "langchain-ai/langgraph")
    assert names(await removal(front, "node js", "node js")) == []


async def test_an_approver_asking_to_remove_gets_operators(front: Front):
    await watch(front, "node js", "nodejs/node")
    front.answers.result = answered(
        RemoveSoftwareAnswer(software="node js", watched_as=["node js"])
    )
    reply = await ask_as_bob(front, "remove node js from the watchlist")
    assert reply["answer"] == "operators"
