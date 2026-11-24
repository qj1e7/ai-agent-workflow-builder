"""A fix's events leave the agent runtime only in the shape platform-api's activity log takes
(ADR 0055, section 8, #369). The JSON schema of each event's data matches
contracts/activity-event.schema.json exactly, and the checks the schema can't hold, a name the
log can show and the fields that go together, refuse what platform-api refuses."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from agent_runtime.fixing.events import (
    FixData,
    FixHandedBackData,
    FixHandoffData,
    FixProposedData,
    FixRoundData,
    FixStartedData,
    fix_kind,
)

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "activity-event.schema.json"
FIX = "fix_01FIRST"


def handoff(**fields: Any) -> FixHandoffData:
    return FixHandoffData.model_validate(
        {
            "fix_id": FIX,
            "handoff": 1,
            "to": "fix_drafter",
            "blocks": ["Read releases"],
            "found": "inside",
            **fields,
        }
    )


@pytest.mark.skipif(not CONTRACT.exists(), reason="contracts/ is not in the test image")
def test_each_event_s_data_has_the_schema_the_activity_log_publishes():
    published = json.loads(CONTRACT.read_text())["$defs"]
    ours = TypeAdapter(FixData).json_schema()["$defs"]
    assert set(ours) == {
        "FixStartedData",
        "FixHandoffData",
        "FixRoundData",
        "FixProposedData",
        "FixHandedBackData",
        "FixId",
        "ShownName",
        "FixHandedTo",
        "FixFound",
        "FixWidening",
        "FixHandBack",
    }
    for name, schema in ours.items():
        assert schema == published[name], name


def test_each_kind_is_the_activity_log_s():
    ends_by = datetime(2026, 11, 24, 6, 20, tzinfo=UTC)
    started = FixStartedData(fix_id=FIX, asked_by="alice", asked_by_name="Alice", ends_by=ends_by)
    kinds = [
        fix_kind(started),
        fix_kind(handoff()),
        fix_kind(FixRoundData(fix_id=FIX, round=1, passed=1, scenarios=2, progress=True)),
        fix_kind(FixProposedData(fix_id=FIX, version=2, digest="sha256:" + "ab" * 32)),
        fix_kind(FixHandedBackData(fix_id=FIX, why="no_progress")),
    ]
    assert kinds == ["fix_started", "fix_handoff", "fix_round", "fix_proposed", "fix_handed_back"]


@pytest.mark.parametrize(
    "name",
    [
        "Post “Done” to Teams",
        "Read​releases",
        "Read releases Approve it",
        "Read\x07releases",
        "́́",
        "R" * 81,
    ],
    ids=["curly quotes", "zero width", "line separator", "control", "nothing to see", "too long"],
)
def test_a_block_name_the_log_can_t_show_is_refused_here_too(name: str):
    with pytest.raises(ValidationError):
        handoff(blocks=[name])


def test_a_name_is_trimmed_before_its_length_counts():
    assert handoff(blocks=[f"  {'R' * 80}  "]).blocks == ["R" * 80]
    assert handoff(blocks=['Post "Done" to Teams']).blocks == ['Post "Done" to Teams']


@pytest.mark.parametrize(
    "fields",
    [
        {"to": "checker", "found": "inside", "blocks": []},
        {"to": "troubleshooter", "found": "not_in_version"},
        {"to": "troubleshooter", "found": "confirmed", "blocks": []},
        {"blocks": ["Read releases", "Read releases"]},
        {"found": "widened"},
        {"widened_by": "adds_a_block"},
        {"to": "simulation", "found": "ran", "blocks": [], "passed": 3, "scenarios": 2},
        {"to": "simulation", "found": "no_answer", "blocks": [], "passed": 0, "scenarios": 2},
    ],
    ids=[
        "found by another",
        "blocks for a block not in the version",
        "no blocks for a confirmed cause",
        "a block twice",
        "widened without how",
        "how without widened",
        "more passed than ran",
        "counts without a run",
    ],
)
def test_fields_that_don_t_go_together_are_refused(fields: dict[str, Any]):
    with pytest.raises(ValidationError):
        handoff(**fields)


def test_a_round_never_passes_more_than_apply():
    with pytest.raises(ValidationError):
        FixRoundData(fix_id=FIX, round=1, passed=3, scenarios=2, progress=True)
    with pytest.raises(ValidationError):
        FixRoundData(fix_id=FIX, round=4, passed=1, scenarios=2, progress=True)
