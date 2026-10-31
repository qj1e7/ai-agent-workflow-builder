"""Prints the activity database, its container's partition key, and a few items, from inside platform-api."""
import asyncio
import json
import os

from azure.cosmos.aio import CosmosClient


async def main() -> None:
    async with CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=os.environ["COSMOS_KEY"], enable_endpoint_discovery=False) as client:
        print("databases:", [d["id"] async for d in client.list_databases()])
        db = client.get_database_client("activity")
        print("containers:", [c["id"] async for c in db.list_containers()])
        container = db.get_container_client("run_events")
        props = await container.read()
        print("partition key:", json.dumps(props["partitionKey"]))
        print("indexing:", json.dumps(props.get("indexingPolicy", {}).get("indexingMode")))
        items = [i async for i in container.query_items("SELECT c.runId, COUNT(1) AS n FROM c GROUP BY c.runId")]
        print("items per partition:", json.dumps(items))
        clean = lambda i: {k: v for k, v in i.items() if not k.startswith("_")}
        gen = await container.read_item("generation", partition_key="copier")
        print("generation item:", json.dumps(clean(gen)))
        runs = [i["runId"] for i in items if i["runId"] != "copier"]
        sample = [i async for i in container.query_items("SELECT * FROM c WHERE c.kind = 'approval_requested'", partition_key=runs[0])]
        print("example item:", json.dumps(clean(sample[0]), indent=2))


asyncio.run(main())
