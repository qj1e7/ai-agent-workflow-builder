from pathlib import Path

from alembic import command
from alembic.config import Config

from platform_api.settings import Context

MIGRATION_ORDER: tuple[Context, ...] = ("monitoring", "orchestration", "builder")


def upgrade(context: Context, owner_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / context))
    config.attributes["url"] = owner_url
    config.attributes["schema"] = context
    command.upgrade(config, "head")


def upgrade_all(owner_url: str) -> None:
    for context in MIGRATION_ORDER:
        upgrade(context, owner_url)
