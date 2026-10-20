import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from agent_runtime.release_checker import Release, SourceRejected, SourceUnavailable

PAGE_SIZE = 30
TIMEOUT_SECONDS = 10.0
RETRY_STATUSES = {429}


class _GitHubRelease(BaseModel):
    tag_name: str
    prerelease: bool = False
    draft: bool = False


_RELEASES = TypeAdapter(list[_GitHubRelease])


class GitHubReleaseSource:
    def __init__(
        self, base_url: str, token: str | None = None, client: httpx.Client | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-workflow-builder-release-checker",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def fetch(self, repo: str) -> list[Release]:
        try:
            response = self._client.get(
                f"{self._base_url}/repos/{repo}/releases",
                params={"per_page": PAGE_SIZE},
                headers=self._headers,
            )
        except httpx.TransportError as error:
            raise SourceUnavailable(None) from error
        status = response.status_code
        if status >= 500 or status in RETRY_STATUSES:
            raise SourceUnavailable(status)
        if status >= 300:
            raise SourceRejected(status)
        try:
            parsed = _RELEASES.validate_json(response.content)
        except ValidationError as error:
            raise SourceUnavailable(None) from error
        return [Release(r.tag_name, prerelease=r.prerelease, draft=r.draft) for r in parsed]
