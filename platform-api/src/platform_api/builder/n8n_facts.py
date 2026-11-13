"""What our node pack's calls need from the use case builder (ENGINE-PLAN 2.2 and 2.3): which use
case an n8n workflow carries, how each of its versions graded and who published it, the agents
a block may run, and the places a Read block may read.

Orchestration may not import the builder, so it asks through its WorkflowFacts and SourceReads
ports, and wiring hands it this.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from platform_api.builder.card_store import CardLibrary
from platform_api.builder.cards import VERSION_CHECKER_ID, card_spec
from platform_api.builder.layout import REPO_INPUT
from platform_api.builder.templates import TAG_PATTERN
from platform_api.db import Database
from platform_api.orchestration import (
    GITHUB_RELEASES,
    AgentRejected,
    AgentToRun,
    AgentUnavailable,
    CannotRun,
    CardInput,
    CardRun,
    KnownOptions,
    NodeOption,
    OwnWorkflow,
    Publisher,
    RanVersion,
    ReadFailed,
    ReadItems,
    ReadReleasesRequest,
    ReadReleasesResult,
    ReleasesNotRead,
    RunSpec,
    WriteEntry,
    card_bindings,
    known_options,
)
from platform_api.shared import UseCaseId, UserId

_PLACES = """
    SELECT s.source_ref AS repo, s.name FROM builder.use_cases u
    JOIN builder.watched_software s
      ON s.use_case_id = u.use_case_id AND s.version = u.current_version
    WHERE u.deleted_at IS NULL
    UNION
    SELECT c."values" ->> %(input)s, c."values" ->> %(input)s FROM builder.use_cases u
    JOIN builder.use_case_cards c
      ON c.use_case_id = u.use_case_id AND c.version = u.current_version
    WHERE u.deleted_at IS NULL AND c.card_id = %(card)s AND c."values" ? %(input)s
"""


class Specs(Protocol):
    async def run_spec_for(self, use_case_id: UseCaseId) -> object: ...


class ReleaseReader(Protocol):
    async def read_releases(
        self, request: ReadReleasesRequest
    ) -> ReadReleasesResult | AgentUnavailable | AgentRejected: ...


def missing_target(card_name: str, inputs: Sequence[CardInput], values: Mapping[str, str]) -> str:
    gaps = [i.name for i in inputs if i.kind == "jira_project" and i.name not in values]
    named = f'"{gaps[0]}"' if gaps else "where it writes"
    return f'"{card_name}" needs {named}, so our platform knows where its change goes.'


class BuilderWorkflowFacts:
    def __init__(
        self,
        db: Database,
        specs: Specs,
        releases: ReleaseReader | None,
        writes: Sequence[WriteEntry],
    ) -> None:
        self._db = db
        self._specs = specs
        self._releases = releases
        self._writes = writes
        self._cards = CardLibrary(db)

    async def known(self, adding: Mapping[str, Iterable[str]]) -> KnownOptions:
        """What the editor's lists hold now, and the places a use case about to be saved adds,
        since saving it lists them."""
        cards = await self._cards.list()
        listed = [option.id for option in await self.places(GITHUB_RELEASES)]
        places = {GITHUB_RELEASES: [*listed, *adding.get(GITHUB_RELEASES, ())]}
        agents = {card.card_id: card_spec(card).inputs for card in cards}
        return known_options(agents, places, self._writes)

    async def workflow(self, n8n_workflow_id: str) -> OwnWorkflow | None:
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT use_case_id, held_by FROM builder.use_cases WHERE n8n_workflow_id = %s"
                    " AND engine = 'own' AND deleted_at IS NULL",
                    (n8n_workflow_id,),
                )
            ).fetchone()
        if row is None:
            return None
        spec = await self._specs.run_spec_for(UseCaseId(row["use_case_id"]))
        if not isinstance(spec, RunSpec):
            return None
        holder = None if row["held_by"] is None else UserId(row["held_by"])
        return OwnWorkflow(spec, holder)

    async def version(self, n8n_workflow_id: str, version_id: str) -> RanVersion | None:
        """The grade stored when the version was saved. A version nobody published has no
        publisher, and one published in n8n by someone we cannot match has Publisher(None)."""
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT v.grade, v.published_by, v.published_in"
                    " FROM builder.use_case_versions v JOIN builder.use_cases u"
                    " ON u.use_case_id = v.use_case_id"
                    " WHERE u.n8n_workflow_id = %s AND v.n8n_version_id = %s"
                    " ORDER BY v.version DESC LIMIT 1",
                    (n8n_workflow_id, version_id),
                )
            ).fetchone()
        if row is None:
            return None
        publisher = None
        if row["published_in"] is not None:
            by = row["published_by"]
            publisher = Publisher(None if by is None else UserId(by))
        return RanVersion(row["grade"], publisher)

    async def agents(self) -> Sequence[NodeOption]:
        return [NodeOption(card.card_id, card.name) for card in await self._cards.list()]

    async def agent_inputs(self, agent_id: str) -> Sequence[CardInput]:
        card = await self._cards.get(agent_id)
        return [] if card is None else card_spec(card).inputs

    async def agent_run(
        self, agent_id: str, values: Mapping[str, str]
    ) -> AgentToRun | CannotRun | None:
        """None for an agent nobody saved. A write whose target the block left out is refused in
        words, never sent to a default place."""
        card = await self._cards.get(agent_id)
        if card is None:
            return None
        spec = card_spec(card)
        try:
            bindings = card_bindings(spec, values)
        except ValueError:
            return CannotRun(missing_target(card.name, spec.inputs, values))
        release_of = values.get(REPO_INPUT) if agent_id == VERSION_CHECKER_ID else None
        return AgentToRun(CardRun(spec, dict(values), bindings), release_of)

    async def places(self, source: str) -> Sequence[NodeOption]:
        """GitHub releases: the watched software and the repositories the Version checker
        watches. Nothing else is set up to be read yet."""
        if source != GITHUB_RELEASES:
            return []
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(_PLACES, {"input": REPO_INPUT, "card": VERSION_CHECKER_ID})
            ).fetchall()
        named = {str(row["repo"]): str(row["name"]) for row in rows}
        return [NodeOption(repo, name) for repo, name in sorted(named.items())]

    async def read(self, source: str, place: str, query: str | None) -> ReadItems | ReadFailed:
        """A repository's counted releases, newest first, through the agent runtime, which holds
        GitHub's key."""
        if source != GITHUB_RELEASES or self._releases is None:
            return ReadFailed("Our platform does not read this source yet.")
        answer = await self._releases.read_releases(
            ReadReleasesRequest(repo=place, tag_pattern=TAG_PATTERN)
        )
        match answer:
            case AgentUnavailable(detail) | AgentRejected(detail):
                return ReadFailed(detail)
            case ReleasesNotRead(message=message):
                return ReadFailed(message)
            case _:
                return [
                    {
                        "kind": "release",
                        "id": release.tag,
                        "name": release.name,
                        "published_at": release.published_at,
                    }
                    for release in answer.releases
                ]
