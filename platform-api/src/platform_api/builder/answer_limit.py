"""A cap on how often one person asks the Planner in words (ADR 0047). One typed answer can make
four model calls, and a choice can be tapped as fast as a finger moves, so a loop of choices or
a stuck key could spend the model's budget. Each platform-api process keeps its own count."""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from platform_api.shared import ANSWERS_PER_MINUTE

TOO_MANY: Final = (
    "You've asked the Planner a lot in the last minute. Wait a moment, then ask again."
)


@dataclass
class AnswerLimit:
    per_minute: int = ANSWERS_PER_MINUTE
    clock: Callable[[], float] = time.monotonic
    _asked: dict[str, deque[float]] = field(default_factory=dict[str, deque[float]])

    def allow(self, who: str) -> bool:
        """Whether this person may ask now, counting the ask when they may."""
        now = self.clock()
        asked = self._asked.setdefault(who, deque())
        while asked and now - asked[0] >= 60:
            asked.popleft()
        if len(asked) >= self.per_minute:
            return False
        asked.append(now)
        return True
