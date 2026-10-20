FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS base
WORKDIR /app
COPY server.py ./

FROM base AS test
COPY test_server.py ./
USER nobody
CMD ["python", "-m", "unittest", "-v", "test_server"]

FROM base AS runtime
ENV PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home app
USER app
EXPOSE 8200
HEALTHCHECK --interval=2s --timeout=3s --retries=15 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8200/healthz', timeout=2)"]
CMD ["python", "server.py"]
