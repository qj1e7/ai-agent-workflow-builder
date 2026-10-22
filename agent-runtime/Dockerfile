FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS base
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS test
RUN uv sync --locked --no-install-project
COPY src ./src
COPY evals ./evals
COPY tests ./tests
RUN uv sync --locked
USER nobody
CMD ["pytest", "-p", "no:cacheprovider"]

# The model bake-off. Provider packages live only in this stage, never in the runtime image.
FROM base AS evals
RUN uv sync --locked --no-dev --group evals --no-install-project
COPY src ./src
COPY evals ./evals
RUN uv sync --locked --no-dev --group evals
USER nobody
ENTRYPOINT ["python", "-m", "evals"]

FROM base AS build
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /opt/venv /opt/venv
USER app
EXPOSE 8100
CMD ["uvicorn", "agent_runtime.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]
