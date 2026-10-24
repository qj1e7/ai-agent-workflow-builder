from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from platform_api.builder.models import (
    CreateUseCase,
    SuggestOut,
    UseCaseCreated,
    UseCaseList,
    UseCaseView,
)
from platform_api.builder.templates import (
    TEMPLATES,
    ParamErrors,
    TemplateNotOffered,
    UnknownTemplate,
    suggest_template,
    validate_params,
)
from platform_api.builder.views import template_view
from platform_api.builder.watchlist import Watchlist
from platform_api.db import Database, json
from platform_api.orchestration import ReleaseTask, RunSpec, RunStarted, RunStarter, Task
from platform_api.shared import Principal, UseCaseId, UserId, new_id

_CURRENT_VERSION = """
    SELECT u.use_case_id, u.owner, v.version, v.template, v.name, v.instruction, v.params,
           v.created_at
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
"""


def _view(row: Mapping[str, Any]) -> UseCaseView:
    return UseCaseView(
        use_case_id=row["use_case_id"],
        version=row["version"],
        template=row["template"],
        name=row["name"],
        instruction=row["instruction"],
        params=row["params"],
        owner=UserId(row["owner"]),
        created_at=row["created_at"],
    )


@dataclass(frozen=True)
class NothingToCheck:
    """The watchlist has no software, so a check would have nothing to do."""


class Builder:
    def __init__(
        self, db: Database, runs: RunStarter, watchlist: Watchlist, public_base_url: str
    ) -> None:
        self._db = db
        self._runs = runs
        self._watchlist = watchlist
        self.public_base_url = public_base_url

    async def create_use_case(
        self, principal: Principal, body: CreateUseCase
    ) -> UseCaseCreated | ParamErrors | UnknownTemplate | TemplateNotOffered:
        template = TEMPLATES.get(body.template)
        if template is None:
            return UnknownTemplate(body.template)
        if not template.offered:
            return TemplateNotOffered(template.key)
        checked = validate_params(template, body.params)
        if isinstance(checked, ParamErrors):
            return checked
        use_case_id = new_id("uc")
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version)"
                " VALUES (%s, %s, %s, 1)",
                (use_case_id, principal.user_id, uow.now),
            )
            await uow.conn.execute(
                "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
                " instruction, params, created_at) VALUES (%s, 1, %s, %s, %s, %s, %s)",
                (
                    use_case_id,
                    template.key,
                    body.name,
                    body.instruction,
                    json(dict(checked.values)),
                    uow.now,
                ),
            )
        return UseCaseCreated(use_case_id=use_case_id, version=1)

    async def list_use_cases(self) -> UseCaseList:
        """Team-wide by design: one team, two roles, and Approvers need the context.
        Per-team scoping comes with Entra ID, if more teams join."""
        async with self._db.connection("builder") as conn:
            cursor = await conn.execute(
                _CURRENT_VERSION + " ORDER BY u.created_at DESC, u.use_case_id DESC"
            )
            return UseCaseList(use_cases=[_view(row) for row in await cursor.fetchall()])

    async def get_use_case(self, use_case_id: str) -> UseCaseView | None:
        async with self._db.connection("builder") as conn:
            cursor = await conn.execute(
                _CURRENT_VERSION + " WHERE u.use_case_id = %s", (use_case_id,)
            )
            row = await cursor.fetchone()
        return None if row is None else _view(row)

    @staticmethod
    def suggest(text: str) -> SuggestOut:
        template, terms = suggest_template(text)
        return SuggestOut(
            template=None if template is None else template_view(template), matched_terms=terms
        )

    async def run_spec_for(self, use_case_id: UseCaseId) -> RunSpec | None | NothingToCheck:
        view = await self.get_use_case(use_case_id)
        if view is None:
            return None
        template = TEMPLATES[view.template]
        params = view.params
        task: Task
        if template.offered:
            carried = await self._runs.latest_carry_forward(use_case_id)
            task = ReleaseTask(
                repo=params["repo"],
                tag_pattern=params["tag_pattern"],
                last_known_tag=carried or params.get("last_seen_tag"),
            )
        else:
            listed = await self._watchlist.task_for(use_case_id, view.version)
            if listed is None:
                return NothingToCheck()
            task = listed
        return RunSpec(
            use_case_id=use_case_id,
            use_case_version=view.version,
            use_case_name=view.name,
            owner=view.owner,
            workflow=template.workflow,
            instruction=view.instruction,
            task=task,
            bindings=template.bindings_for(params),
            approval_policy=template.approval_policy,
        )

    async def check_spec(self, use_case_id: UseCaseId) -> RunSpec | None:
        """What the schedule tick asks for. None means nothing to check."""
        spec = await self.run_spec_for(use_case_id)
        return None if isinstance(spec, NothingToCheck) else spec

    async def start_run(
        self, use_case_id: UseCaseId, principal: Principal, idempotency_key: str
    ) -> RunStarted | None | NothingToCheck:
        spec = await self.run_spec_for(use_case_id)
        if spec is None or isinstance(spec, NothingToCheck):
            return spec
        return await self._runs.start_run(spec, principal, idempotency_key)
