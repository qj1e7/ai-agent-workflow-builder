from typing import Any

from agent_runtime.contract import (
    AgentEvent,
    AgentFailedEvent,
    TaskFailed,
    TaskFinished,
    TaskRequest,
    TaskResult,
    WatchlistInputs,
)
from agent_runtime.contracts import failed_task, finished_task, task_request
from agent_runtime.events import EventLog
from agent_runtime.planner import FixedPlanner, run_task
from agent_runtime.summary import TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from tests.fakes import FakeClock, FakeSource, langgraph_tags


class Room:
    def __init__(self, source: FakeSource) -> None:
        self.clock = FakeClock()
        self.delivered: list[AgentEvent] = []
        self.log = EventLog(self.clock, self.delivered.append)
        self.checker = VersionChecker(source, TemplateSummarizer(), sleep=self.clock.sleep)

    def run(self, request: TaskRequest) -> TaskResult:
        return run_task(request, FixedPlanner(), self.checker, self.log)


def without_timestamps(result: TaskResult) -> dict[str, Any]:
    dumped = result.model_dump(mode="json")
    for event in dumped["events"]:
        del event["ts"]
    return dumped


def up_to_date(request: TaskRequest) -> TaskRequest:
    assert isinstance(request.inputs, WatchlistInputs)
    software = request.inputs.software[0].model_copy(update={"our_version": "1.2.16"})
    inputs = request.inputs.model_copy(update={"software": [software]})
    return request.model_copy(update={"inputs": inputs})


def test_a_check_of_one_software_tells_the_story_the_contract_fixture_records():
    result = Room(FakeSource(langgraph_tags())).run(task_request("run_01JB8"))
    assert isinstance(result, TaskFinished)
    assert without_timestamps(result) == without_timestamps(finished_task())


def test_a_dead_upstream_tells_the_failure_story_the_contract_fixture_records():
    source = FakeSource(langgraph_tags(), failures=[503] * 9)
    result = Room(source).run(task_request("run_01JB9"))
    assert isinstance(result, TaskFailed)
    assert without_timestamps(result) == without_timestamps(failed_task())


def test_every_event_is_delivered_to_the_sink_in_order_as_it_is_logged():
    room = Room(FakeSource(langgraph_tags()))
    result = room.run(task_request("run_01JB8"))
    assert room.delivered == result.events
    assert [e.agent_seq for e in result.events] == list(range(1, len(result.events) + 1))
    stamps = [e.ts for e in result.events]
    assert stamps == sorted(stamps)


def test_nothing_behind_ends_with_the_planner_saying_there_is_nothing_to_propose():
    result = Room(FakeSource(langgraph_tags())).run(up_to_date(task_request("run_01JB8")))
    assert isinstance(result, TaskFinished)
    assert result.output.proposed == []
    assert [e.kind for e in result.events][-2:] == ["agent_message", "agent_message"]
    assert result.events[-1].agent.id == "planner"
    assert result.events[-1].summary == "Planner noted that there is nothing to propose."


def test_an_unexpected_error_still_returns_a_failed_result_with_a_failure_event():
    source = FakeSource(langgraph_tags())

    def explode(repo: str):
        raise RuntimeError("boom")

    source.fetch = explode
    result = Room(source).run(task_request("run_01JB8"))
    assert isinstance(result, TaskFailed)
    assert (result.error.type, result.error.retryable) == ("AgentError", False)
    assert "boom" not in result.error.message
    last = result.events[-1]
    assert isinstance(last, AgentFailedEvent)
    assert last.data.error_type == "AgentError"
