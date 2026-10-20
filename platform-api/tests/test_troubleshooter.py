from typing import get_args

from platform_api.monitoring.troubleshooter import ADVICE
from platform_api.wire import FailureReason


def test_every_failure_reason_has_advice():
    assert set(ADVICE) == set(get_args(FailureReason.__value__))
