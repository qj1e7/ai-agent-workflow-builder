from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema


def run_migrations() -> None:
    url: str = context.config.attributes["url"]
    schema: str = context.config.attributes["schema"]
    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.connect() as connection:
        connection.execute(CreateSchema(schema, if_not_exists=True))
        connection.commit()
        context.configure(
            connection=connection,
            version_table="alembic_version",
            version_table_schema=schema,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
