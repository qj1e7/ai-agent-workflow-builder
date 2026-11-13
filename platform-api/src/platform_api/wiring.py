import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import httpx
from fastapi import FastAPI

from platform_api.auth import DEV_PEOPLE, DevAuth, OidcAuth
from platform_api.builder import Builder, Home, PlannerFront, TeamRequests, Watchlist
from platform_api.builder.planner_facts import PlannerFactsReader
from platform_api.db import Database
from platform_api.monitoring import ActivityLog, Copier, CosmosEvents, callback_for
from platform_api.orchestration.agents import CardInput, HttpAgentRuntime
from platform_api.orchestration.confluence_rest import (
    ConfluencePages,
    confluence_identity,
    confluence_pages,
)
from platform_api.orchestration.connections import (
    TEAMS_NOT_CHECKED,
    Checked,
    ConfluenceChecker,
    Connections,
    Entry,
    GitHubChecker,
    JiraChecker,
    ModelView,
    Observed,
    ReadFresh,
    Unset,
    WatchedChannel,
    confluence_probe,
    github_probe,
    jira_probe,
    model_probe,
    practice_teams,
)
from platform_api.orchestration.dispatch import (
    PRACTICE,
    ApprovalChannel,
    Identity,
    N8nWaker,
    N8nWebhooks,
    identity_of,
)
from platform_api.orchestration.jira import JiraWriteConnector, jira_site
from platform_api.orchestration.jira_rest import JiraAuth, JiraRestAdapter
from platform_api.orchestration.model_settings import KeyBox, ModelSettings
from platform_api.orchestration.n8n_call_service import NodeCalls
from platform_api.orchestration.n8n_calls import (
    ExecutionFacts,
    FailedExecution,
    NodeCatalog,
    NodeOption,
    OwnWorkflow,
    RanVersion,
    ReadFailed,
    ReadItems,
    WriteEntry,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.planning import (
    CapabilityRegistry,
    CardPlanning,
    PlannerAnswers,
    ProjectFinding,
)
from platform_api.orchestration.runs import Leg
from platform_api.orchestration.schedule_store import ScheduleBook, ScheduleTicker
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.spec import CardRun
from platform_api.orchestration.team_request_card import TeamsRequestChannel
from platform_api.orchestration.teams import TeamsStub, TeamsWorkflowsWebhook
from platform_api.orchestration.tell import TellFlow, TellOutlet, TellPractice
from platform_api.orchestration.watch_store import WatchFacts
from platform_api.orchestration.workflows import load_all
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.practice_jira import PRACTICE_EMAIL, PracticeJira, practice_token
from platform_api.settings import Settings
from platform_api.shared import N8nExecutionId, RunId, TaskId


@dataclass(frozen=True)
class Services:
    settings: Settings
    db: Database
    activity_log: ActivityLog
    orchestrator: Orchestrator
    node_calls: NodeCalls
    builder: Builder
    planner_front: PlannerFront
    home: Home
    watchlist: Watchlist
    team_requests: TeamRequests
    request_channel: TeamsRequestChannel
    schedule_ticker: ScheduleTicker
    teams_stub: TeamsStub
    jira: JiraRestAdapter
    jira_client: httpx.AsyncClient
    model_settings: ModelSettings
    connections: Connections
    people: People
    confluence: ConfluencePages
    copier: Copier | None = None
    cosmos: CosmosEvents | None = None
    teams_webhook: TeamsWorkflowsWebhook | None = None
    waker: N8nWaker | None = None
    practice_jira: PracticeJira | None = None
    tell_flow: TellFlow | None = None


JIRA_TIMEOUT_SECONDS = 10.0
KEY_HINT_MIN_LENGTH = 8
"""A token shorter than this shows no last two characters, as they would give too much away."""


def key_hint(token: str | None) -> str | None:
    return token[-2:] if token and len(token) >= KEY_HINT_MIN_LENGTH else None


def jira_for(
    settings: Settings, db: Database, client: httpx.AsyncClient
) -> tuple[JiraRestAdapter, PracticeJira | None]:
    """The one Jira adapter (ADR 0035). With no JIRA_BASE_URL it calls the practice Jira that
    platform-api serves itself, over HTTP at its own internal address, as it would call a real
    Jira. The practice Jira's token comes from the callback signing key."""
    jira = settings.jira
    if jira.base_url is None:
        token = practice_token(settings.callback_signing_key)
        practice = PracticeJira(db, token, settings.public_base_url)
        base_url = f"{settings.platform_internal_url}/practice-jira"
        auth = JiraAuth.of(jira.flavor, token, PRACTICE_EMAIL)
    else:
        practice = None
        base_url = jira.base_url
        auth = JiraAuth.of(jira.flavor, jira.token or "", jira.email)
    adapter = JiraRestAdapter(
        base_url, jira.flavor, auth, client, issue_type=jira.issue_type, browse_url=jira.browse_url
    )
    return adapter, practice


def install(app: FastAPI, services: Services) -> None:
    app.state.settings = services.settings
    app.state.step_key = services.settings.step_key
    app.state.db = services.db
    app.state.activity_log = services.activity_log
    app.state.copier = services.copier
    app.state.orchestrator = services.orchestrator
    app.state.node_calls = services.node_calls
    app.state.builder = services.builder
    app.state.planner_front = services.planner_front
    app.state.home = services.home
    app.state.watchlist = services.watchlist
    app.state.team_requests = services.team_requests
    app.state.schedule_ticker = services.schedule_ticker
    app.state.teams_stub = services.teams_stub
    app.state.teams_webhook = services.teams_webhook
    app.state.jira = services.jira
    app.state.practice_jira = services.practice_jira
    app.state.model_settings = services.model_settings
    app.state.connections = services.connections
    app.state.people = services.people
    app.state.confluence = services.confluence


class NoOwnWorkflowsYet:
    """Until the Planner lays use cases out as n8n workflows of their own (E4), no n8n workflow
    is ours, so every node call is refused, and no agent or place can be named."""

    async def workflow(self, n8n_workflow_id: str) -> OwnWorkflow | None:
        return None

    async def version(self, n8n_workflow_id: str, version_id: str) -> RanVersion | None:
        return None

    async def agents(self) -> Sequence[NodeOption]:
        return []

    async def agent_inputs(self, agent_id: str) -> Sequence[CardInput]:
        return []

    async def agent_run(self, agent_id: str, values: Mapping[str, str]) -> CardRun | None:
        return None

    async def execution(self, execution_id: N8nExecutionId) -> ExecutionFacts | None:
        """n8n's records are not read yet (E4), so every execution is of no workflow of ours."""
        return ExecutionFacts("", "", None, None, None)

    async def error_workflow_id(self) -> str | None:
        """Not known until n8n's records are read (E3, E4), so every failure report is refused."""
        return None

    async def failed_executions(self, workflow_id: str) -> Sequence[N8nExecutionId]:
        return []

    async def failure(self, execution_id: N8nExecutionId) -> FailedExecution | None:
        return None

    async def places(self, source: str) -> Sequence[NodeOption]:
        return []

    async def read(self, source: str, place: str, query: str | None) -> ReadItems | ReadFailed:
        return ReadFailed("No Read source is set up yet.")


def node_writes(settings: Settings) -> list[WriteEntry]:
    """The writes a Propose a change block may name: the registry's one ready write, in the
    Jira project the platform writes to."""
    project = NodeOption(settings.watchlist_jira_project, settings.watchlist_jira_project)
    return [
        WriteEntry(
            "jira.create_ticket",
            "Create a Jira ticket",
            "jira",
            "create_ticket",
            "project",
            (project,),
        )
    ]


def request_channel_for(settings: Settings) -> TeamsRequestChannel:
    """Where new team requests are announced (ADR 0038): TEAMS_REQUESTS_WEBHOOK_URL, else the
    approvals channel's webhook, else nowhere. The request is kept either way."""
    return TeamsRequestChannel(settings.teams_requests_webhook_url or settings.teams_webhook_url)


def approval_channel(
    settings: Settings, practice: TeamsStub, client: httpx.AsyncClient | None = None
) -> tuple[ApprovalChannel, TeamsWorkflowsWebhook | None]:
    """Where approval cards go (ADR 0036): the practice copy, or real Teams when
    TEAMS_WEBHOOK_URL is set. Returns the channel, and the webhook adapter to close on shutdown."""
    if settings.teams_webhook_url is None:
        return practice, None
    webhook = TeamsWorkflowsWebhook(settings.teams_webhook_url, settings.teams_channel, client)
    return webhook, webhook


def tell_outlet(settings: Settings, db: Database) -> tuple[TellOutlet, TellFlow | None]:
    """Where a Tell goes: the practice copy, or the team's Tell flow when TEAMS_TELL_WEBHOOK_URL
    is set. E13 sets it, with the registry's "Posts in Teams and emails" made ready. Returns the
    outlet, and the flow to close on shutdown."""
    if settings.teams_tell_webhook_url is None:
        return TellPractice(db, settings.teams_channel), None
    flow = TellFlow(settings.teams_tell_webhook_url, settings.teams_channel)
    return flow, flow


CONFLUENCE_UNSET = "Confluence is not connected."


def confluence_entry(settings: Settings, confluence: ConfluenceChecker | None) -> Entry:
    """Confluence is optional: the platform runs without it, and only the reads that need it say
    so."""
    if settings.confluence.base_url is None or confluence is None:
        return Entry("confluence", "Confluence", Identity("confluence"), Unset(CONFLUENCE_UNSET))
    key = key_hint(settings.confluence.token)
    return Entry(
        "confluence",
        "Confluence",
        confluence_identity(settings.confluence),
        Checked(confluence_probe(confluence, key)),
    )


def connections_for(
    settings: Settings,
    db: Database,
    jira: JiraChecker,
    channel: ApprovalChannel,
    agents: GitHubChecker,
    models: ModelView,
    confluence: ConfluenceChecker | None = None,
) -> tuple[Connections, ApprovalChannel]:
    jira_settings = settings.jira
    jira_identity = (
        PRACTICE
        if jira_settings.base_url is None
        else identity_of(
            "jira",
            jira_settings.base_url,
            jira_settings.flavor,
            jira_settings.email or "",
            jira_settings.token or "",
        )
    )
    teams = (
        Entry("teams", "Teams", PRACTICE, Checked(practice_teams))
        if settings.teams_webhook_url is None
        else Entry("teams", "Teams", channel.identity, Observed(TEAMS_NOT_CHECKED))
    )
    connections = Connections(
        db,
        [
            Entry(
                "jira",
                "Jira",
                jira_identity,
                Checked(jira_probe(jira, "Jira", key_hint(jira_settings.token))),
            ),
            # GitHub's address and key are the agent runtime's settings, which platform-api cannot
            # see, so a change there is found by the next check, not here.
            Entry("github", "GitHub", Identity("github"), Checked(github_probe(agents))),
            teams,
            confluence_entry(settings, confluence),
            Entry("model", "AI model", Identity("model"), ReadFresh(model_probe(models))),
        ],
    )
    if teams.practice:
        return connections, channel
    return connections, WatchedChannel(channel, connections)


async def build(settings: Settings) -> Services:
    db = Database(settings.database)
    await db.open()
    cosmos = None if settings.cosmos is None else CosmosEvents.connect(settings.cosmos)
    copier = None if cosmos is None else Copier(db, cosmos)
    if settings.activity_reader == "cosmos" and cosmos is not None:
        activity = ActivityLog(db, copy=cosmos, status=copier)
    else:
        activity = ActivityLog(db)
    await activity.start()
    if copier is not None:
        await copier.start()
    people = People(db)
    match settings.auth:
        case DevAuth():
            await people.seed_dev(DEV_PEOPLE)
        case OidcAuth():
            await people.seed_first(settings.first_people)
    jira_client = httpx.AsyncClient(timeout=JIRA_TIMEOUT_SECONDS, follow_redirects=False)
    jira, practice_jira = jira_for(settings, db, jira_client)
    site = jira_site(settings.jira.base_url)
    teams = TeamsStub(db, settings.teams_channel)
    channel, webhook = approval_channel(settings, teams)

    def mint(run_id: RunId, task_id: TaskId, expires_at: datetime) -> tuple[str, str]:
        callback = callback_for(
            settings.callback_signing_key,
            settings.platform_internal_url,
            run_id,
            task_id,
            expires_at,
        )
        return callback.url, callback.token

    definitions = {d.name: d for d in load_all()}

    def path_for(workflow: str, leg: Leg) -> str:
        return definitions[workflow].webhook_path(leg)

    agents = HttpAgentRuntime(settings.agent_runtime_url, settings.agent_api_key)
    secret = settings.settings_encryption_key
    box = KeyBox(secret) if secret else None
    model_settings = ModelSettings(db, agents, box, people=people)
    waker = None
    if settings.node_key is not None and box is not None:
        waker = N8nWaker(settings.n8n_base_url, settings.node_key, box)
    confluence = confluence_pages(settings.confluence)
    connections, channel = connections_for(
        settings, db, jira, channel, agents, model_settings, confluence
    )
    gateway = WriteGateway(db, [JiraWriteConnector(jira, db, site)])
    orchestrator = Orchestrator(
        db,
        activity,
        N8nWebhooks(settings.n8n_base_url, path_for),
        channel,
        agents,
        gateway,
        mint,
        models=model_settings,
        people=people,
        public_base_url=settings.public_base_url,
        time_zone=settings.team_time_zone,
        waker=waker,
    )
    not_yet = NoOwnWorkflowsYet()
    tells, tell_flow = tell_outlet(settings, db)
    node_calls = NodeCalls(
        db,
        activity,
        agents,
        mint,
        NodeCatalog(not_yet, not_yet, node_writes(settings)),
        not_yet,
        not_yet,
        not_yet,
        gateway.sites,
        model_settings,
        start_secret=settings.start_secret,
        box=box,
        time_zone=settings.team_time_zone,
        gateway=gateway,
        tells=tells,
        failures=not_yet,
    )
    schedules = ScheduleBook(db)
    watchlist = Watchlist(
        db,
        WatchFacts(db, jira, site.identity),
        schedules,
        settings.watchlist_jira_project,
        ProjectFinding(agents),
    )
    await watchlist.adopt_ticket_project()
    builder = Builder(
        db,
        orchestrator,
        watchlist,
        settings.public_base_url,
        CardPlanning(db, model_settings, agents),
        schedules,
        orchestrator,
    )
    request_channel = request_channel_for(settings)
    team_requests = TeamRequests(
        db, request_channel, orchestrator, activity, settings.public_base_url
    )
    home = Home(builder, orchestrator, people, team_requests, connections, watchlist)
    return Services(
        settings=settings,
        db=db,
        activity_log=activity,
        orchestrator=orchestrator,
        node_calls=node_calls,
        builder=builder,
        planner_front=PlannerFront(
            PlannerAnswers(db, model_settings, agents),
            builder,
            watchlist,
            CapabilityRegistry(agents),
            connections,
            PlannerFactsReader(watchlist, builder, home),
        ),
        home=home,
        watchlist=watchlist,
        team_requests=team_requests,
        request_channel=request_channel,
        schedule_ticker=ScheduleTicker(db, schedules, builder, orchestrator),
        teams_stub=teams,
        jira=jira,
        jira_client=jira_client,
        practice_jira=practice_jira,
        model_settings=model_settings,
        connections=connections,
        people=people,
        confluence=confluence,
        copier=copier,
        cosmos=cosmos,
        teams_webhook=webhook,
        waker=waker,
        tell_flow=tell_flow,
    )


class Runner:
    def __init__(self, services: Services) -> None:
        self._services = services
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._services.orchestrator.run_forever(self._stop)),
            asyncio.create_task(self._services.node_calls.sweep_forever(self._stop)),
        ]

    async def stop(self) -> None:
        self._stop.set()
        self._services.orchestrator.nudge()
        for task in self._tasks:
            await task
        if self._services.tell_flow is not None:
            await self._services.tell_flow.close()
        if self._services.teams_webhook is not None:
            await self._services.teams_webhook.close()
        if self._services.waker is not None:
            await self._services.waker.close()
        await self._services.request_channel.close()
        if self._services.copier is not None:
            await self._services.copier.stop()
        await self._services.activity_log.stop()
        await self._services.jira_client.aclose()
        await self._services.confluence.close()
        if self._services.cosmos is not None:
            await self._services.cosmos.close()
        await self._services.db.close()
