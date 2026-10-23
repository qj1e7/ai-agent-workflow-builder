FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83
RUN useradd --system --uid 10001 --no-create-home app
COPY server.py /app/server.py
USER app
EXPOSE 8100
CMD ["python", "-u", "/app/server.py"]
