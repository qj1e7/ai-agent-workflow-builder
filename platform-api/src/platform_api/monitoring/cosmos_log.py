import secrets
from contextlib import suppress
from typing import Any

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError
from azure.cosmos.http_constants import StatusCodes, SubStatusCodes

from platform_api.monitoring.events import ActivityEvent, activity_event_adapter
from platform_api.monitoring.log import Generation, LoggedEvent
from platform_api.settings import CosmosSettings
from platform_api.shared import RunId

DATABASE = "activity"
CONTAINER = "run_events"
PARTITION_KEY = "/runId"
_GENERATION_ID = "generation"
_GENERATION_PARTITION = "copier"

_READ_AFTER = "SELECT * FROM c WHERE c.seq > @after ORDER BY c.seq"


def cosmos_client(settings: CosmosSettings) -> CosmosClient:
    """Endpoint discovery is off: the emulator names an address that only it can reach."""
    return CosmosClient(settings.endpoint, credential=settings.key, enable_endpoint_discovery=False)


class CosmosEvents:
    def __init__(self, client: CosmosClient, *, database: str = DATABASE) -> None:
        self._client = client
        self._database = database
        self._container = client.get_database_client(database).get_container_client(CONTAINER)

    @classmethod
    def connect(cls, settings: CosmosSettings) -> CosmosEvents:
        return cls(cosmos_client(settings))

    async def close(self) -> None:
        await self._client.close()

    async def ensure(self) -> Generation:
        found = await self._generation()
        if found is not None:
            return found
        with suppress(CosmosResourceExistsError):
            await self._client.create_database_if_not_exists(self._database)
        with suppress(CosmosResourceExistsError):
            await self._client.get_database_client(self._database).create_container_if_not_exists(
                id=CONTAINER, partition_key=PartitionKey(path=PARTITION_KEY)
            )
        try:
            made = await self._container.create_item(
                {
                    "id": _GENERATION_ID,
                    "runId": _GENERATION_PARTITION,
                    "generation": secrets.token_hex(16),
                }
            )
        except CosmosResourceExistsError:
            return await self.ensure()
        return Generation(made["generation"])

    async def _generation(self) -> Generation | None:
        try:
            item = await self._container.read_item(
                _GENERATION_ID, partition_key=_GENERATION_PARTITION
            )
        except CosmosHttpResponseError as error:
            if _missing(error):
                return None
            raise
        return Generation(item["generation"])

    async def put(self, event: LoggedEvent) -> None:
        await self._container.upsert_item(
            {
                "id": str(event.seq),
                "runId": event.run_id,
                "seq": event.seq,
                "ts": event.ts.isoformat(),
                "actor": event.actor,
                "kind": event.kind,
                "summary": event.summary,
                "data": event.data,
                "dedupeKey": event.dedupe_key,
            }
        )

    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        events: list[ActivityEvent] = []
        items = self._container.query_items(
            _READ_AFTER, parameters=[{"name": "@after", "value": after}], partition_key=run_id
        )
        async for item in items:
            if item["seq"] != after + len(events) + 1:
                break
            events.append(_event(item))
        return events


def _missing(error: CosmosHttpResponseError) -> bool:
    sub_status: int | None = getattr(error, "sub_status", None)
    return (
        error.status_code == StatusCodes.NOT_FOUND
        or sub_status == SubStatusCodes.OWNER_RESOURCE_NOT_FOUND
    )


def _event(item: dict[str, Any]) -> ActivityEvent:
    return activity_event_adapter.validate_python(
        {
            "run_id": item["runId"],
            "seq": item["seq"],
            "ts": item["ts"],
            "actor": item["actor"],
            "kind": item["kind"],
            "summary": item["summary"],
            "data": item["data"],
        }
    )
