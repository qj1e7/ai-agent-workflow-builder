---
status: proposed
---

# Ship every service as a container image and run the stack locally with Docker Compose

Five people work on different laptops, CI builds and tests the code, and Azure Container Apps runs it. If each of those runs the services a different way, a bug can appear in one place and not the others. Every deployable unit ships as a Docker image with pinned versions, including n8n and PostgreSQL. A teammate runs the whole stack with Docker Compose. CI and Azure Container Apps run the same images, and so could AWS.

## Considered options

- **Run services directly on each machine,** for example n8n through `npx` and Python through `uv`. Startup is faster and needs no Docker, but versions drift between laptops, and the cloud would run something that nobody tested locally.
- **A local Kubernetes cluster.** It is closer to some production setups, but it is more to learn and run than a five-person part-time team needs. Container Apps does not need it.

## Consequences

- Each service has a `Dockerfile`, and the repo has one Compose file for local dev. The n8n image version is pinned to the version we tested.
- Docker Desktop is free for education and small companies. Larger companies need a paid subscription, so NCS needs a licence or a free runtime such as Colima, Podman or Rancher Desktop at handover. Our images follow the OCI standard, so they do not depend on Docker Desktop.
- Throwaway prototypes may skip Docker when it adds nothing.
