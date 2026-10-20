from typing import NoReturn

from fastapi import FastAPI, HTTPException

from agent_runtime.contract import AgentCard, AgentCards, Health, TaskRequest, TaskResult

AGENT_CARDS = AgentCards(
    agents=[
        AgentCard(
            id="room_lead",
            display="Room lead",
            description="Reads the task and decides which specialist agents to bring in.",
            capabilities=["plan a task", "bring in specialists", "hand proposals to the platform"],
        ),
        AgentCard(
            id="release_checker",
            display="Release checker",
            description="Reads a public GitHub repository's releases and finds the new ones.",
            capabilities=["read GitHub releases", "compare with the last known tag"],
        ),
    ]
)


def not_implemented() -> NoReturn:
    raise HTTPException(status_code=501, detail="Not implemented yet")


def create_app() -> FastAPI:
    app = FastAPI(title="Agent API", version="0.1.0")

    @app.post("/v1/tasks")
    def run_task(body: TaskRequest) -> TaskResult:
        not_implemented()

    @app.get("/v1/agents")
    def list_agents() -> AgentCards:
        return AGENT_CARDS

    @app.get("/healthz")
    def healthz() -> Health:
        return Health()

    return app
