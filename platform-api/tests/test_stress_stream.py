"""Temporary: repeats every stream test with the probe on. Removed before the fix lands."""

import os

import pytest
from fastapi import FastAPI

import tests.test_monitoring_http as http_tests
from tests.test_monitoring_http import app  # noqa: F401

pytestmark = pytest.mark.anyio

REPS = int(os.environ.get("STRESS_REPS", "40"))
STREAM_TESTS = [
    "test_the_stream_resumes_after_last_event_id_then_follows_and_keeps_alive",
    "test_the_stream_falls_back_to_after_when_last_event_id_is_not_a_number",
    "test_the_stream_closes_once_the_person_leaves_the_list",
    "test_a_disconnected_stream_stops_the_handler",
]


@pytest.mark.parametrize("i", range(REPS))
@pytest.mark.parametrize("name", STREAM_TESTS)
async def test_stress_stream(app: FastAPI, name: str, i: int) -> None:  # noqa: F811
    await getattr(http_tests, name)(app)
