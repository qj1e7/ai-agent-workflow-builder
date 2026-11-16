"""Temporary: repeats the flaky stream test with the probe on. Removed before the fix lands."""

import os

import pytest
from fastapi import FastAPI

import tests.test_monitoring_http as http_tests
from tests.test_monitoring_http import app  # noqa: F401

pytestmark = pytest.mark.anyio

REPS = int(os.environ.get("STRESS_REPS", "40"))


@pytest.mark.parametrize("i", range(REPS))
async def test_stress_stream(app: FastAPI, i: int) -> None:  # noqa: F811
    await http_tests.test_the_stream_falls_back_to_after_when_last_event_id_is_not_a_number(app)
