from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from agent_runtime.contract import GitHubCheckResult, GitHubProblem, GitHubWorking
from agent_runtime.release_source import Fetched, Release, SourceRejected, SourceUnavailable

PAGE_SIZE = 30
NOTES_LENGTH = 400
TIMEOUT_SECONDS = 10.0
RETRY_STATUSES = {429}
EXPIRY_HEADER = "github-authentication-token-expiration"
EXPIRY_FORMATS = ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S %z")
TOKEN_REFUSED = "GitHub does not accept the token. Ask whoever set it up for a new one."
UNREACHABLE = "GitHub could not be reached just now."
UNEXPECTED = "GitHub answered in a way the platform did not expect."


class _GitHubRelease(BaseModel):
    tag_name: str
    prerelease: bool = False
    draft: bool = False
    name: str | None = None
    published_at: str | None = None
    body: str | None = None


class _GitHubRepo(BaseModel):
    full_name: str


_RELEASES = TypeAdapter(list[_GitHubRelease])
_REPO = TypeAdapter(_GitHubRepo)


def _headers_for(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-workflow-builder-version-checker",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _expiry_of(response: httpx.Response) -> datetime | None:
    raw = response.headers.get(EXPIRY_HEADER)
    if raw is None:
        return None
    text = raw.strip()
    for shape in EXPIRY_FORMATS:
        try:
            parsed = datetime.strptime(text, shape)
        except ValueError:
            continue
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


class GitHubConnection:
    """Asks GitHub's rate limit endpoint, which does not count against the limit."""

    def __init__(
        self, base_url: str, token: str | None = None, client: httpx.Client | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token or None
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)

    def check(self) -> GitHubCheckResult:
        try:
            response = self._client.get(
                f"{self._base_url}/rate_limit", headers=_headers_for(self._token)
            )
        except httpx.TransportError:
            return GitHubProblem(reason="unreachable", message=UNREACHABLE)
        status = response.status_code
        if status == 200:
            expires_at = _expiry_of(response) if self._token else None
            return GitHubWorking(using_token=self._token is not None, expires_at=expires_at)
        if status in (401, 403) and self._token:
            return GitHubProblem(reason="token_refused", message=TOKEN_REFUSED)
        if status >= 500 or status in RETRY_STATUSES:
            return GitHubProblem(reason="unreachable", message=UNREACHABLE)
        return GitHubProblem(reason="unexpected_answer", message=UNEXPECTED)


class GitHubReleaseSource:
    def __init__(
        self, base_url: str, token: str | None = None, client: httpx.Client | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)
        self._headers = _headers_for(token)

    def current_name(self, repo: str) -> str:
        return self._get(repo, "", _REPO)[0].full_name

    def fetch(self, repo: str) -> list[Release]:
        return self.fetch_noting_move(repo).releases

    def fetch_noting_move(self, repo: str) -> Fetched:
        parsed, redirected = self._get(repo, "/releases", _RELEASES, {"per_page": PAGE_SIZE})
        releases = [
            Release(
                r.tag_name,
                prerelease=r.prerelease,
                draft=r.draft,
                name=r.name,
                published_at=r.published_at,
                notes=(r.body or "")[:NOTES_LENGTH] or None,
            )
            for r in parsed
        ]
        return Fetched(releases, redirected)

    def _get[T](
        self,
        repo: str,
        tail: str,
        shape: TypeAdapter[T],
        params: dict[str, int] | None = None,
    ) -> tuple[T, bool]:
        parts = repo.split("/", 1)
        if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts):
            raise SourceRejected(400)
        owner, name = (quote(part, safe="") for part in parts)
        try:
            response = self._client.get(
                f"{self._base_url}/repos/{owner}/{name}{tail}",
                params=params,
                headers=self._headers,
            )
        except httpx.TransportError as error:
            raise SourceUnavailable(None) from error
        status = response.status_code
        if status >= 500 or status in RETRY_STATUSES:
            raise SourceUnavailable(status)
        if status >= 300:
            raise SourceRejected(status, limited=_rate_limited(response))
        try:
            return shape.validate_json(response.content), bool(response.history)
        except ValidationError as error:
            raise SourceUnavailable(None) from error


def _rate_limited(response: httpx.Response) -> bool:
    headers = response.headers
    if headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers:
        return True
    return "rate limit" in response.text.lower()
