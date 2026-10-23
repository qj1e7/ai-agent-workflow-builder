import asyncio, server, graph_bad
server.graph = graph_bad.app
async def m():
    async for e in server.events("f1", {}): print(e)
asyncio.run(m())
