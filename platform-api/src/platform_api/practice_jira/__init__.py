"""The practice Jira: a stand-in that speaks Jira's own REST API (ADR 0035).

It belongs to no bounded context. It imports none of them and none of them import it, as an
outside system would be, and only the app and the wiring mount it. Its tickets live in
orchestration.mock_jira_tickets, so it needs no database role of its own.
"""

from platform_api.practice_jira.http import router
from platform_api.practice_jira.store import (
    PRACTICE_EMAIL,
    PracticeJira,
    PracticeTicket,
    practice_token,
)

__all__ = ["PRACTICE_EMAIL", "PracticeJira", "PracticeTicket", "practice_token", "router"]
