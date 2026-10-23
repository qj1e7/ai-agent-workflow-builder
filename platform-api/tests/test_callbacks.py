from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest

from platform_api.monitoring import callback_for, verify_callback
from platform_api.shared import RunId, TaskId

KEY = "test-signing-key"
BASE = "http://platform-api:8000"
RUN = RunId("run_01JB8")
TASK = TaskId("run_01JB8/work/1/1")
MINTED = datetime(2026, 11, 3, 2, 14, 0, tzinfo=UTC)
EXPIRES = MINTED + timedelta(hours=2)


def test_the_callback_names_the_run_and_task_and_verifies_within_its_life():
    callback = callback_for(KEY, BASE, RUN, TASK, EXPIRES)
    task = quote(TASK, safe="")
    assert callback.url == f"{BASE}/internal/v1/runs/{RUN}/agent-events?task={task}"
    assert verify_callback(KEY, RUN, TASK, callback.token, MINTED)
    assert verify_callback(KEY, RUN, TASK, callback.token, EXPIRES - timedelta(seconds=1))


def test_the_same_inputs_mint_the_same_token():
    minted = callback_for(KEY, BASE, RUN, TASK, EXPIRES)
    assert minted == callback_for(KEY, BASE, RUN, TASK, EXPIRES)
    assert (
        callback_for(KEY, BASE, RUN, TASK, EXPIRES).token
        != callback_for(KEY, BASE, RUN, TASK, EXPIRES + timedelta(seconds=1)).token
    )


GOOD = callback_for(KEY, BASE, RUN, TASK, EXPIRES).token
EXPIRY, SIGNATURE = GOOD.split(".")
LATER = str(int(EXPIRY) + 60)


@pytest.mark.parametrize(
    ("label", "key", "run_id", "task_id", "token", "now"),
    [
        ("expired", KEY, RUN, TASK, GOOD, EXPIRES),
        ("another run", KEY, RunId("run_01JB9"), TASK, GOOD, MINTED),
        ("another task", KEY, RUN, TaskId("run_01JB8/work/2/1"), GOOD, MINTED),
        ("another key", "other-key", RUN, TASK, GOOD, MINTED),
        ("empty", KEY, RUN, TASK, "", MINTED),
        ("no dot", KEY, RUN, TASK, GOOD.replace(".", ""), MINTED),
        ("expiry not a number", KEY, RUN, TASK, "soon." + SIGNATURE, MINTED),
        ("expiry moved", KEY, RUN, TASK, LATER + "." + SIGNATURE, MINTED),
        ("signature changed", KEY, RUN, TASK, GOOD[:-1] + "0", MINTED),
        ("signature truncated", KEY, RUN, TASK, GOOD[:-2], MINTED),
    ],
)
def test_verify_refuses(
    label: str, key: str, run_id: RunId, task_id: TaskId, token: str, now: datetime
):
    assert not verify_callback(key, run_id, task_id, token, now), label
