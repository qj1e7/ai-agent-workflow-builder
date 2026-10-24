from pathlib import Path

from alembic import command
from alembic.config import Config

from platform_api.settings import Context

MIGRATION_ORDER: tuple[Context, ...] = ("monitoring", "orchestration", "builder")


def _config(context: Context, owner_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / context))
    config.attributes["url"] = owner_url
    config.attributes["schema"] = context
    return config


def upgrade(context: Context, owner_url: str) -> None:
    command.upgrade(_config(context, owner_url), "head")


def downgrade(context: Context, owner_url: str, revision: str) -> None:
    command.downgrade(_config(context, owner_url), revision)


def upgrade_all(owner_url: str) -> None:
    for context in MIGRATION_ORDER:
        upgrade(context, owner_url)
