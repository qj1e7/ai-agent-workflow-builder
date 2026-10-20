from alembic import context
from sqlalchemy import create_engine, text


def run_migrations() -> None:
    url: str = context.config.attributes["url"]
    schema: str = context.config.attributes["schema"]
    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        connection.commit()
        context.configure(
            connection=connection,
            version_table="alembic_version",
            version_table_schema=schema,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
