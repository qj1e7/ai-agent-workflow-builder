from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from platform_api.db import Database
from platform_api.orchestration.runs import Leg, sentence
from platform_api.shared import ApprovalId, N8nExecutionId, RunId, new_id


@dataclass(frozen=True)
class RetryPolicy:
    delays: tuple[timedelta, ...] = (
        timedelta(seconds=2),
        timedelta(seconds=5),
        timedelta(seconds=15),
        timedelta(seconds=30),
        timedelta(seconds=60),
    )
    operator_retry_delay: timedelta = timedelta(seconds=3)
    tick_interval: timedelta = timedelta(seconds=5)

    @property
    def tries(self) -> int:
        return len(self.delays) + 1

    @property
    def dispatch_budget(self) -> timedelta:
        return sum(self.delays, timedelta()) + self.tick_interval * self.tries


RETRY_POLICY = RetryPolicy()


class DispatchFailure(Exception): ...


class WorkflowEngine(Protocol):
    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId: ...


@dataclass(frozen=True)
class ApprovalNotice:
    run_id: RunId
    approval_id: ApprovalId
    use_case_name: str
    actions: tuple[str, ...]
    link: str
    summary: str = ""


class ApprovalChannel(Protocol):
    @property
    def name(self) -> str: ...

    async def announce(self, notice: ApprovalNotice) -> None: ...


@dataclass(frozen=True)
class TeamsMessage:
    id: str
    ts: datetime
    channel: str
    text: str
    link: str
    run_id: RunId
    approval_id: ApprovalId


class TeamsStub:
    def __init__(self, db: Database, channel: str) -> None:
        self._db = db
        self._channel = channel

    @property
    def name(self) -> str:
        return self._channel

    async def announce(self, notice: ApprovalNotice) -> None:
        said = f"{sentence(notice.summary)} " if notice.summary else ""
        text = (
            f"A run of {notice.use_case_name} needs an Approver. {said}"
            f"It would {' and '.join(notice.actions)}. "
            "Open the approval page to decide."
        )
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.teams_stub_messages "
                "(id, ts, channel, text, link, run_id, approval_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (approval_id) DO NOTHING",
                (
                    new_id("tm"),
                    uow.now,
                    self._channel,
                    text,
                    notice.link,
                    notice.run_id,
                    notice.approval_id,
                ),
            )

    async def messages(self) -> list[TeamsMessage]:
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    "SELECT id, ts, channel, text, link, run_id, approval_id "
                    "FROM orchestration.teams_stub_messages ORDER BY ts, id"
                )
            ).fetchall()
        return [
            TeamsMessage(
                id=row["id"],
                ts=row["ts"],
                channel=row["channel"],
                text=row["text"],
                link=row["link"],
                run_id=RunId(row["run_id"]),
                approval_id=ApprovalId(row["approval_id"]),
            )
            for row in rows
        ]


class N8nWebhooks:
    def __init__(
        self,
        base_url: str,
        path_for: Callable[[str, Leg], str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._path_for = path_for
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId:
        url = f"{self._base_url}/webhook/{self._path_for(workflow, leg)}"
        try:
            response = await self._client.post(url, json={"run_id": run_id})
        except httpx.HTTPError as error:
            raise DispatchFailure(f"n8n did not answer at {url}: {error!r}") from error
        if response.status_code != 202:
            raise DispatchFailure(f"n8n answered {response.status_code} at {url}")
        try:
            execution = str(response.json()["n8n_execution_id"])
        except (ValueError, KeyError, TypeError) as error:
            raise DispatchFailure(f"n8n's 202 carried no execution id: {error!r}") from error
        if not execution:
            raise DispatchFailure("n8n's 202 carried an empty execution id")
        return N8nExecutionId(execution)

    async def close(self) -> None:
        await self._client.aclose()
