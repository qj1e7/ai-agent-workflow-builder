import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from platform_api.auth import AuthConfig, ConfigError, auth_config
from platform_api.shared import ANSWERS_PER_MINUTE, JIRA_PROJECT_PATTERN, TEAM_TIME_ZONE

type Context = Literal["builder", "orchestration", "monitoring"]
type ActivityReader = Literal["postgres", "cosmos"]
type JiraFlavor = Literal["datacenter", "cloud"]

CONTEXTS: tuple[Context, ...] = ("builder", "orchestration", "monitoring")


@dataclass(frozen=True)
class DatabaseUrls:
    builder: str = field(repr=False)
    orchestration: str = field(repr=False)
    monitoring: str = field(repr=False)

    def for_context(self, context: Context) -> str:
        match context:
            case "builder":
                return self.builder
            case "orchestration":
                return self.orchestration
            case "monitoring":
                return self.monitoring


@dataclass(frozen=True)
class CosmosSettings:
    endpoint: str
    key: str = field(repr=False)


@dataclass(frozen=True)
class FirstPeople:
    """The first deploy's people (ADR 0030): applied only while the People list is empty."""

    operator: str
    approvers: tuple[str, str]


SHORTEST_START_SECRET = 32
"""The fewest characters a simulation's start secret may have, on platform-api's side and the
gateway's. deploy/make-env.sh and scripts/simulation.sh make 64."""

MAX_BODY_BYTES_DEFAULT = 2 * 1024 * 1024
"""The largest request body the API reads, unless MAX_BODY_BYTES says otherwise. The largest
real body is a set-up card draft. Its content may be 32 KB (DRAFT_LIMIT_BYTES), which is about
100 KB as JSON even with every character escaped, so 2 MiB leaves about 20 times that."""


@dataclass(frozen=True)
class JiraSettings:
    """Which Jira the platform talks to (ADR 0035). No address means the practice Jira, which
    platform-api serves itself. browse_url is where people open a ticket, with {key} in it."""

    base_url: str | None = None
    flavor: JiraFlavor = "datacenter"
    token: str | None = field(default=None, repr=False)
    email: str | None = None
    issue_type: str = "Task"
    browse_url: str = "/jira/{key}"

    @property
    def practice(self) -> bool:
        return self.base_url is None


@dataclass(frozen=True)
class ConfluencePage:
    """A page the platform may read: its id, and its title as people name it."""

    id: str
    title: str


@dataclass(frozen=True)
class ConfluenceSettings:
    """Which Confluence the platform reads, and the only pages it may read (ENGINE-PLAN D2). No
    address means Confluence is not connected. base_url is the wiki's own address, such as
    https://your-site.atlassian.net/wiki. With an email the platform signs in as Atlassian Cloud
    does, with the email and an API token. Without one it sends the token as Data Center's
    personal access token."""

    base_url: str | None = None
    email: str | None = None
    token: str | None = None
    pages: tuple[ConfluencePage, ...] = ()


PRACTICE_JIRA_PROJECT = "MOCK"
"""The practice Jira's project, where the watchlist raises tickets unless told otherwise."""


type KeySystem = Literal["jira", "github", "slack"]
"""The systems the platform makes a key in n8n for, so n8n's own blocks can read them or post to
them (ADR 0045). Teams, Outlook and Gmail have none: see orchestration/n8n_credentials.py."""


@dataclass(frozen=True)
class N8nKey:
    """One key the platform makes in n8n for n8n's own blocks, from what Key Vault holds."""

    kind: str
    """n8n's credential type, such as slackApi."""
    data: Mapping[str, str] = field(repr=False)
    """What n8n keeps for it, the secret included."""
    asks: str
    """Where the platform asks the system what the key may do, before it makes the key."""


@dataclass(frozen=True)
class N8nOwner:
    """n8n's owner account, which the platform signs in as to lay out and publish workflows."""

    email: str
    password: str = field(repr=False)


@dataclass(frozen=True)
class SimulationSettings:
    """The simulation gateway (ADR 0054), which runs each drafted version through its scenarios
    in the simulation n8n. platform-api signs each call with the simulation's own start secret."""

    url: str
    start_secret: str = field(repr=False)
    uses_model: bool = False
    """SIMULATION_MODEL. Off, code's six templates run and no model is asked. On, the scenario
    writer writes the scenarios and the explainer explains each failure, both paid calls."""


@dataclass(frozen=True)
class LangfuseSettings:
    """The Langfuse project that platform-api writes code flags to (ADR 0050)."""

    base_url: str
    public_key: str
    secret_key: str = field(repr=False)
    environment: str | None = None
    """LANGFUSE_TRACING_ENVIRONMENT, sent with each score. Unset, Langfuse uses its default."""


@dataclass(frozen=True)
class Settings:
    auth: AuthConfig
    public_base_url: str
    database: DatabaseUrls
    agent_runtime_url: str
    agent_api_key: str = field(repr=False)
    n8n_base_url: str
    step_key: str = field(repr=False)
    platform_internal_url: str
    callback_signing_key: str = field(repr=False)
    teams_channel: str
    teams_webhook_url: str | None = field(default=None, repr=False)
    teams_requests_webhook_url: str | None = field(default=None, repr=False)
    teams_tell_webhook_url: str | None = field(default=None, repr=False)
    """The Tell flow, which posts a notice to the team's channel and emails the team's list (D1).
    Unset keeps the practice copy."""
    tell_email_to: tuple[str, ...] = ()
    """TELL_EMAIL_TO, the team's fixed email list that every Tell emails."""
    settings_encryption_key: str | None = field(default=None, repr=False)
    first_people: FirstPeople | None = None
    activity_reader: ActivityReader = "postgres"
    cosmos: CosmosSettings | None = None
    max_body_bytes: int = MAX_BODY_BYTES_DEFAULT
    practice_systems: bool = True
    watchlist_jira_project: str = PRACTICE_JIRA_PROJECT
    jira: JiraSettings = JiraSettings()
    confluence: ConfluenceSettings = ConfluenceSettings()
    team_time_zone: ZoneInfo = TEAM_TIME_ZONE
    planner_answers_per_minute: int = ANSWERS_PER_MINUTE
    """PLANNER_ANSWERS_PER_MINUTE: how many typed requests one person may send the Planner in a
    minute (ADR 0047). The end-to-end suite raises it, since it sends many as one person."""
    node_key: str | None = field(default=None, repr=False)
    """WAB_NODE_KEY, which our n8n node pack sends. Without it no node call is taken."""
    start_secret: str | None = field(default=None, repr=False)
    """WAB_START_SECRET, which signs each start the Portal sends to Start from the Portal."""
    n8n_owner: N8nOwner | None = None
    """N8N_OWNER_EMAIL and N8N_OWNER_PASSWORD. Without them the platform lays no workflow out
    in n8n, and new use cases run on the shared n8n workflow."""
    n8n_staff_access: bool = False
    """N8N_STAFF_ACCESS. Off, the platform makes no staff n8n account and opens no workflow in
    n8n (ENGINE-PLAN 2.9, M5). On, it still waits for a bootstrap that proved n8n's blocks and
    guards (ADR 0051)."""
    n8n_editor_url: str | None = None
    """N8N_EDITOR_URL, where people open n8n's editor, as ADR 0034's n8n_editor_url output. Each
    password link n8n makes is shown at this address."""
    n8n_keys: Mapping[KeySystem, N8nKey] = field(default_factory=dict[KeySystem, N8nKey])
    """The keys the platform makes in n8n for n8n's own blocks, from the N8N_KEY_ settings. A
    system with none set has no key, so its blocks never pass the check."""
    langfuse: LangfuseSettings | None = None
    """LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY. Without them no score is
    written."""
    trace_pseudonym_key: str | None = field(default=None, repr=False)
    """TRACE_PSEUDONYM_KEY, which keys the pseudonym a trace names the person by. Without it a
    trace names nobody."""
    simulation: SimulationSettings | None = None
    """SIMULATION_URL and SIMULATION_START_SECRET. Without them there is no simulation n8n here,
    and the drafted card says so."""
    fix_model: bool = False
    """FIX_MODEL. Off, nobody can start Fix it for me (ADR 0055), so its coordinator makes no paid
    call. On, an Operator may ask for a fix on a stopped run. The coordinator holds each fix to
    $2 in the runtime, and platform-api to one Scenario writer call and 4 explainer calls."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise ConfigError(f"{name} is not set.")
    return value


def first_people_from_env(env: Mapping[str, str]) -> FirstPeople | None:
    operator = env.get("FIRST_OPERATOR", "").strip()
    approvers = [a.strip() for a in env.get("FIRST_APPROVERS", "").split(",") if a.strip()]
    if not operator and not approvers:
        return None
    if not operator or not approvers:
        raise ConfigError(
            "FIRST_OPERATOR and FIRST_APPROVERS go together: one email, and two emails "
            "separated by a comma."
        )
    if len(approvers) != 2 or approvers[0].lower() == approvers[1].lower():
        raise ConfigError(
            "FIRST_APPROVERS must name two different people, separated by a comma, so nobody "
            "has to approve their own work."
        )
    for email in (operator, *approvers):
        local, at, domain = email.partition("@")
        if not (at and local and "." in domain):
            raise ConfigError(f"{email!r} in FIRST_OPERATOR or FIRST_APPROVERS is not an email.")
    return FirstPeople(operator, (approvers[0], approvers[1]))


def cosmos_from_env(env: Mapping[str, str]) -> CosmosSettings | None:
    endpoint = env.get("COSMOS_ENDPOINT", "").strip()
    key = env.get("COSMOS_KEY", "").strip()
    if not endpoint and not key:
        return None
    if not endpoint:
        raise ConfigError("COSMOS_KEY is set but COSMOS_ENDPOINT is not.")
    if not key:
        raise ConfigError("COSMOS_ENDPOINT is set but COSMOS_KEY is not.")
    return CosmosSettings(endpoint=endpoint.rstrip("/"), key=key)


def activity_reader_from_env(
    env: Mapping[str, str], cosmos: CosmosSettings | None
) -> ActivityReader:
    match env.get("ACTIVITY_READER") or "postgres":
        case "postgres":
            return "postgres"
        case "cosmos" if cosmos is not None:
            return "cosmos"
        case "cosmos":
            raise ConfigError("ACTIVITY_READER=cosmos needs COSMOS_ENDPOINT and COSMOS_KEY.")
        case other:
            raise ConfigError(f"ACTIVITY_READER takes postgres or cosmos, not {other!r}.")


def teams_webhook_from_env(env: Mapping[str, str], name: str = "TEAMS_WEBHOOK_URL") -> str | None:
    """A Teams Workflows webhook (ADR 0036). Unset keeps the practice copy. The address carries
    its own signature, so it comes from Key Vault and is never logged."""
    url = env.get(name, "").strip()
    if not url:
        return None
    if not url.startswith("https://") or len(url) <= len("https://"):
        raise ConfigError(f"{name} must be the https:// address Teams Workflows gave.")
    return url


def tell_email_from_env(env: Mapping[str, str], flow_set: bool) -> tuple[str, ...]:
    """The team's email list, separated by commas. With the Tell flow set it may not be empty,
    because the flow sends every Tell's email to this list."""
    emails = tuple(e.strip() for e in env.get("TELL_EMAIL_TO", "").split(",") if e.strip())
    for email in emails:
        local, at, domain = email.partition("@")
        if not (at and local and "." in domain) or any(c.isspace() or c == ";" for c in email):
            raise ConfigError(f"{email!r} in TELL_EMAIL_TO is not an email.")
    if flow_set and not emails:
        raise ConfigError("TEAMS_TELL_WEBHOOK_URL needs TELL_EMAIL_TO, the team's email list.")
    return emails


def max_body_bytes_from_env(env: Mapping[str, str]) -> int:
    raw = env.get("MAX_BODY_BYTES", "").strip()
    if not raw:
        return MAX_BODY_BYTES_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ConfigError(f"MAX_BODY_BYTES takes a whole number of bytes above 0, not {raw!r}.")
    return value


def practice_systems_from_env(env: Mapping[str, str]) -> bool:
    """Whether the practice copies' own routes are served (ADR 0035). On unless set to off."""
    match env.get("PRACTICE_SYSTEMS", "").strip().lower() or "on":
        case "on":
            return True
        case "off":
            return False
        case other:
            raise ConfigError(f"PRACTICE_SYSTEMS takes on or off, not {other!r}.")


def n8n_staff_access_from_env(env: Mapping[str, str]) -> bool:
    match env.get("N8N_STAFF_ACCESS", "").strip().lower() or "off":
        case "on":
            return True
        case "off":
            return False
        case other:
            raise ConfigError(f"N8N_STAFF_ACCESS takes on or off, not {other!r}.")


def n8n_editor_url_from_env(env: Mapping[str, str]) -> str | None:
    raw = env.get("N8N_EDITOR_URL", "").strip().rstrip("/")
    if not raw:
        return None
    if urlsplit(raw).scheme not in ("http", "https") or not urlsplit(raw).hostname:
        raise ConfigError(f"N8N_EDITOR_URL must be an http or https address, not {raw!r}.")
    return raw


def watchlist_jira_project_from_env(env: Mapping[str, str]) -> str:
    project = env.get("WATCHLIST_JIRA_PROJECT", "").strip() or PRACTICE_JIRA_PROJECT
    if JIRA_PROJECT_PATTERN.match(project) is None:
        raise ConfigError(
            "WATCHLIST_JIRA_PROJECT must be a Jira project key, such as MOCK or AB_1: a capital "
            "letter, then 1 or more capital letters, digits or underscores. "
            f"{project!r} is not one."
        )
    return project


def team_time_zone_from_env(env: Mapping[str, str]) -> ZoneInfo:
    name = env.get("TEAM_TIME_ZONE", "").strip()
    if not name:
        return TEAM_TIME_ZONE
    try:
        return ZoneInfo(name)
    except ValueError, ZoneInfoNotFoundError:
        raise ConfigError(
            f"TEAM_TIME_ZONE must be a time zone name, such as Asia/Singapore. {name!r} is not one."
        ) from None


def _web_address(name: str, value: str, *, https_only: bool) -> str:
    parts = urlsplit(value)
    schemes = {"https"} if https_only else {"http", "https"}
    if parts.scheme not in schemes or not parts.hostname:
        wanted = "an https address" if https_only else "an http or https address"
        raise ConfigError(f"{name} must be {wanted} with a host, not {value!r}.")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ConfigError(f"{name} must have no query, fragment or user in it.")
    return value.rstrip("/")


def jira_from_env(
    env: Mapping[str, str], public_base_url: str, practice_systems: bool
) -> JiraSettings:
    flavor_text = env.get("JIRA_API_FLAVOR", "").strip().lower() or "datacenter"
    if flavor_text not in ("datacenter", "cloud"):
        raise ConfigError(f"JIRA_API_FLAVOR takes datacenter or cloud, not {flavor_text!r}.")
    flavor: JiraFlavor = "cloud" if flavor_text == "cloud" else "datacenter"
    issue_type = env.get("JIRA_ISSUE_TYPE", "Task").strip()
    if not issue_type:
        raise ConfigError("JIRA_ISSUE_TYPE must name an issue type, such as Task.")
    raw_base = env.get("JIRA_BASE_URL", "").strip()
    raw_browse = env.get("JIRA_BROWSE_URL", "").strip()
    if not raw_base:
        if not practice_systems:
            raise ConfigError(
                "PRACTICE_SYSTEMS=off turns the practice Jira off, so set JIRA_BASE_URL, "
                "JIRA_API_FLAVOR and JIRA_API_TOKEN for a real one."
            )
        base_url, token, email = None, None, None
        # The Portal's own Practice Jira page, as a path, so the Portal opens it in place.
        default_browse = "/jira/{key}"
    else:
        # The token goes to this address with every call, so it is https only.
        base_url = _web_address("JIRA_BASE_URL", raw_base, https_only=True)
        token = env.get("JIRA_API_TOKEN", "").strip()
        if not token:
            raise ConfigError("JIRA_BASE_URL is set but JIRA_API_TOKEN is not.")
        if not all(33 <= ord(character) < 127 for character in token):
            raise ConfigError(
                "JIRA_API_TOKEN holds a space, a line break or a character that is not a plain "
                "letter, digit or symbol. Paste the token again."
            )
        email = env.get("JIRA_EMAIL", "").strip() or None
        if flavor == "cloud" and email is None:
            raise ConfigError("JIRA_API_FLAVOR=cloud signs in with JIRA_EMAIL and JIRA_API_TOKEN.")
        default_browse = f"{base_url}/browse/{{key}}"
    browse_url = default_browse
    if raw_browse:
        if "{key}" not in raw_browse:
            raise ConfigError("JIRA_BROWSE_URL must have {key} in it, where the ticket key goes.")
        _web_address("JIRA_BROWSE_URL", raw_browse.replace("{key}", "KEY"), https_only=False)
        browse_url = raw_browse
    return JiraSettings(base_url, flavor, token, email, issue_type, browse_url)


CONFLUENCE_PAGE_ID = re.compile(r"[0-9]{1,20}")
CONFLUENCE_TITLE_LIMIT = 255


def _confluence_address(value: str) -> str:
    """The token goes to this address with every call, so it is https, or plain http only to a
    host with no dot in its name, which is a service on the stack's own network."""
    parts = urlsplit(value)
    if parts.scheme == "http" and parts.hostname and "." not in parts.hostname:
        return _web_address("CONFLUENCE_BASE_URL", value, https_only=False)
    return _web_address("CONFLUENCE_BASE_URL", value, https_only=True)


def confluence_pages_from_env(raw: str) -> tuple[ConfluencePage, ...]:
    pages: list[ConfluencePage] = []
    for entry in (part.strip() for part in raw.split(";")):
        if not entry:
            continue
        page_id, equals, title = (part.strip() for part in entry.partition("="))
        if not equals or CONFLUENCE_PAGE_ID.fullmatch(page_id) is None:
            raise ConfigError(
                "CONFLUENCE_PAGES lists pages as id=title, separated by a semicolon, such as "
                f"123456=Software inventory. {entry!r} is not one."
            )
        if not 1 <= len(title) <= CONFLUENCE_TITLE_LIMIT or not title.isprintable():
            raise ConfigError(f"The title of page {page_id} in CONFLUENCE_PAGES is not one line.")
        pages.append(ConfluencePage(page_id, title))
    for name, values in (
        ("id", [p.id for p in pages]),
        ("title", [" ".join(p.title.split()).casefold() for p in pages]),
    ):
        if len(set(values)) < len(values):
            raise ConfigError(f"Two pages in CONFLUENCE_PAGES have the same {name}.")
    return tuple(pages)


def confluence_from_env(env: Mapping[str, str], jira: JiraSettings) -> ConfluenceSettings:
    """Unset keeps Confluence not connected. Without a token of its own it signs in with Jira's,
    when Jira is on the same site, as Atlassian Cloud allows."""
    raw_base = env.get("CONFLUENCE_BASE_URL", "").strip()
    if not raw_base:
        return ConfluenceSettings()
    base_url = _confluence_address(raw_base)
    email = env.get("CONFLUENCE_EMAIL", "").strip() or None
    token = env.get("CONFLUENCE_API_TOKEN", "").strip() or None
    same_site = jira.base_url is not None and (
        urlsplit(jira.base_url).hostname == urlsplit(base_url).hostname
    )
    if token is None and same_site:
        email, token = email or jira.email, jira.token
    if token is None:
        raise ConfigError("CONFLUENCE_BASE_URL is set but CONFLUENCE_API_TOKEN is not.")
    if not all(33 <= ord(character) < 127 for character in token):
        raise ConfigError(
            "CONFLUENCE_API_TOKEN holds a space, a line break or a character that is not a plain "
            "letter, digit or symbol. Paste the token again."
        )
    pages = confluence_pages_from_env(env.get("CONFLUENCE_PAGES", ""))
    if not pages:
        raise ConfigError(
            "CONFLUENCE_BASE_URL is set, so CONFLUENCE_PAGES must list the pages the platform "
            "may read, such as 123456=Software inventory."
        )
    return ConfluenceSettings(base_url, email, token, pages)


GITHUB_API = "https://api.github.com"
SLACK_API = "https://slack.com/api"


def _stack_or_https(name: str, value: str) -> str:
    """A key goes to this address, so it is https, or plain http only to a host with no dot in its
    name, which is a service on the stack's own network."""
    parts = urlsplit(value)
    if parts.scheme == "http" and parts.hostname and "." not in parts.hostname:
        return _web_address(name, value, https_only=False)
    return _web_address(name, value, https_only=True)


def _secret(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    if value and not all(33 <= ord(character) < 127 for character in value):
        raise ConfigError(
            f"{name} holds a space, a line break or a character that is not a plain letter, "
            "digit or symbol. Paste it again."
        )
    return value or None


def n8n_keys_from_env(env: Mapping[str, str], jira: JiraSettings) -> dict[KeySystem, N8nKey]:
    """Each N8N_KEY_ secret comes from Key Vault on Azure, and from deploy/.env or the e2e
    overlay elsewhere. The Jira key reads the platform's Jira unless N8N_KEY_JIRA_URL names
    another, as the same flavor."""
    keys: dict[KeySystem, N8nKey] = {}
    if (token := _secret(env, "N8N_KEY_JIRA_TOKEN")) is not None:
        raw = env.get("N8N_KEY_JIRA_URL", "").strip() or jira.base_url
        if raw is None:
            raise ConfigError("N8N_KEY_JIRA_TOKEN is set, so set N8N_KEY_JIRA_URL too.")
        url = _stack_or_https("N8N_KEY_JIRA_URL", raw)
        if jira.flavor == "cloud":
            email = env.get("N8N_KEY_JIRA_EMAIL", "").strip()
            if not email:
                raise ConfigError("A Cloud Jira key signs in with N8N_KEY_JIRA_EMAIL too.")
            data = {"domain": url, "email": email, "apiToken": token}
            keys["jira"] = N8nKey("jiraSoftwareCloudApi", data, url)
        else:
            data = {"domain": url, "personalAccessToken": token}
            keys["jira"] = N8nKey("jiraSoftwareServerPatApi", data, url)
    if (token := _secret(env, "N8N_KEY_GITHUB_TOKEN")) is not None:
        url = _stack_or_https("N8N_KEY_GITHUB_URL", env.get("N8N_KEY_GITHUB_URL", "") or GITHUB_API)
        keys["github"] = N8nKey("githubApi", {"server": url, "accessToken": token}, url)
    if (token := _secret(env, "N8N_KEY_SLACK_TOKEN")) is not None:
        asks = _stack_or_https("SLACK_API_URL", env.get("SLACK_API_URL", "") or SLACK_API)
        keys["slack"] = N8nKey("slackApi", {"accessToken": token}, asks)
    return keys


LANGFUSE_ENVIRONMENT = re.compile(r"[a-z0-9_-]{1,40}")


def langfuse_from_env(env: Mapping[str, str]) -> LangfuseSettings | None:
    raw_base = env.get("LANGFUSE_BASE_URL", "").strip()
    public_key = _secret(env, "LANGFUSE_PUBLIC_KEY")
    secret_key = _secret(env, "LANGFUSE_SECRET_KEY")
    if not raw_base and public_key is None and secret_key is None:
        return None
    if not raw_base or public_key is None or secret_key is None:
        raise ConfigError(
            "LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY go together."
        )
    environment = env.get("LANGFUSE_TRACING_ENVIRONMENT", "").strip() or None
    if environment is not None and (
        LANGFUSE_ENVIRONMENT.fullmatch(environment) is None or environment.startswith("langfuse")
    ):
        raise ConfigError(
            "LANGFUSE_TRACING_ENVIRONMENT takes lower case letters, digits, hyphens and "
            f"underscores, up to 40, and may not start with langfuse. {environment!r} is not one."
        )
    base_url = _stack_or_https("LANGFUSE_BASE_URL", raw_base)
    return LangfuseSettings(base_url, public_key, secret_key, environment)


def staff_access_from_env(env: Mapping[str, str], owner: N8nOwner | None) -> bool:
    on = n8n_staff_access_from_env(env)
    if on and (owner is None or not env.get("SETTINGS_ENCRYPTION_KEY")):
        raise ConfigError(
            "N8N_STAFF_ACCESS=on needs N8N_OWNER_EMAIL and N8N_OWNER_PASSWORD, which make each "
            "person's n8n account, and SETTINGS_ENCRYPTION_KEY, which seals their password link."
        )
    return on


def settings_from_env(env: Mapping[str, str]) -> Settings:
    auth = auth_config(env)
    n8n_owner = n8n_owner_from_env(env)
    cosmos = cosmos_from_env(env)
    public_base_url = auth.public_base_url.rstrip("/")
    practice_systems = practice_systems_from_env(env)
    jira = jira_from_env(env, public_base_url, practice_systems)
    tell_flow = teams_webhook_from_env(env, "TEAMS_TELL_WEBHOOK_URL")
    return Settings(
        auth=auth,
        first_people=first_people_from_env(env),
        public_base_url=public_base_url,
        database=DatabaseUrls(
            builder=_required(env, "DATABASE_URL_BUILDER"),
            orchestration=_required(env, "DATABASE_URL_ORCHESTRATION"),
            monitoring=_required(env, "DATABASE_URL_MONITORING"),
        ),
        agent_runtime_url=_required(env, "AGENT_RUNTIME_URL").rstrip("/"),
        agent_api_key=_required(env, "AGENT_API_KEY"),
        n8n_base_url=_required(env, "N8N_BASE_URL").rstrip("/"),
        step_key=_required(env, "STEP_KEY"),
        platform_internal_url=_required(env, "PLATFORM_INTERNAL_URL").rstrip("/"),
        callback_signing_key=_required(env, "CALLBACK_SIGNING_KEY"),
        teams_channel=env.get("TEAMS_CHANNEL") or "CODESparks Ops",
        teams_webhook_url=teams_webhook_from_env(env),
        teams_requests_webhook_url=teams_webhook_from_env(env, "TEAMS_REQUESTS_WEBHOOK_URL"),
        teams_tell_webhook_url=tell_flow,
        tell_email_to=tell_email_from_env(env, tell_flow is not None),
        settings_encryption_key=env.get("SETTINGS_ENCRYPTION_KEY") or None,
        activity_reader=activity_reader_from_env(env, cosmos),
        cosmos=cosmos,
        max_body_bytes=max_body_bytes_from_env(env),
        practice_systems=practice_systems,
        watchlist_jira_project=watchlist_jira_project_from_env(env),
        jira=jira,
        confluence=confluence_from_env(env, jira),
        team_time_zone=team_time_zone_from_env(env),
        planner_answers_per_minute=answers_per_minute_from_env(env),
        node_key=env.get("WAB_NODE_KEY", "").strip() or None,
        start_secret=env.get("WAB_START_SECRET", "").strip() or None,
        n8n_owner=n8n_owner,
        n8n_staff_access=staff_access_from_env(env, n8n_owner),
        n8n_editor_url=n8n_editor_url_from_env(env),
        n8n_keys=n8n_keys_from_env(env, jira),
        langfuse=langfuse_from_env(env),
        trace_pseudonym_key=_secret(env, "TRACE_PSEUDONYM_KEY"),
        simulation=simulation_from_env(env),
        fix_model=fix_model_from_env(env),
    )


def simulation_from_env(env: Mapping[str, str]) -> SimulationSettings | None:
    raw_url = env.get("SIMULATION_URL", "").strip()
    secret = _secret(env, "SIMULATION_START_SECRET")
    match env.get("SIMULATION_MODEL", "").strip().lower() or "off":
        case "on":
            uses_model = True
        case "off":
            uses_model = False
        case other:
            raise ConfigError(f"SIMULATION_MODEL takes on or off, not {other!r}.")
    if not raw_url and secret is None:
        if uses_model:
            raise ConfigError("SIMULATION_MODEL=on needs SIMULATION_URL and its start secret.")
        return None
    if not raw_url or secret is None:
        raise ConfigError("SIMULATION_URL and SIMULATION_START_SECRET go together.")
    if len(secret) < SHORTEST_START_SECRET:
        raise ConfigError(
            f"SIMULATION_START_SECRET needs at least {SHORTEST_START_SECRET} characters. "
            "Run deploy/make-env.sh for a new one."
        )
    url = _stack_or_https("SIMULATION_URL", raw_url)
    return SimulationSettings(url, secret, uses_model)


def fix_model_from_env(env: Mapping[str, str]) -> bool:
    match env.get("FIX_MODEL", "").strip().lower() or "off":
        case "on":
            return True
        case "off":
            return False
        case other:
            raise ConfigError(f"FIX_MODEL takes on or off, not {other!r}.")


def answers_per_minute_from_env(env: Mapping[str, str]) -> int:
    raw = env.get("PLANNER_ANSWERS_PER_MINUTE", "").strip()
    if not raw:
        return ANSWERS_PER_MINUTE
    if not raw.isdigit() or int(raw) < 1:
        raise ConfigError("PLANNER_ANSWERS_PER_MINUTE must be a whole number of at least 1.")
    return int(raw)


def n8n_owner_from_env(env: Mapping[str, str]) -> N8nOwner | None:
    email = env.get("N8N_OWNER_EMAIL", "").strip()
    password = env.get("N8N_OWNER_PASSWORD", "")
    if not email and not password:
        return None
    if not email or not password:
        raise ConfigError("N8N_OWNER_EMAIL and N8N_OWNER_PASSWORD go together.")
    return N8nOwner(email, password)


N8N_GUARDED = (
    "NODES_EXCLUDE",
    "N8N_BLOCK_ENV_ACCESS_IN_NODE",
    "N8N_RUNNERS_MODE",
    "N8N_DEPRECATED_NODES_BLOCK",
    "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES",
    "N8N_RESTRICT_FILE_ACCESS_TO",
    "NODE_FUNCTION_ALLOW_BUILTIN",
    "NODE_FUNCTION_ALLOW_EXTERNAL",
    "N8N_RUNNERS_INSECURE_MODE",
)
"""The n8n settings bootstrap reads from the block the deploy gives both n8n and bootstrap
(ADR 0051, spike P9). `platform_api.n8n_guard` says what each must be."""


@dataclass(frozen=True)
class BootstrapSettings:
    owner_database_url: str = field(repr=False)
    n8n_base_url: str
    n8n_owner_email: str
    n8n_owner_password: str = field(repr=False)
    step_key: str = field(repr=False)
    platform_internal_url: str
    team_time_zone: ZoneInfo = TEAM_TIME_ZONE
    """The self-test runs on it, as every workflow does."""
    n8n_settings: Mapping[str, str] = field(default_factory=dict[str, str])
    """The guards the deploy gives n8n, as it gives bootstrap the same block of settings, which
    bootstrap checks (`platform_api.n8n_guard.WATCHED`)."""


def owner_database_url_from_env(env: Mapping[str, str]) -> str:
    return _required(env, "DATABASE_URL_OWNER")


def bootstrap_settings_from_env(env: Mapping[str, str]) -> BootstrapSettings:
    return BootstrapSettings(
        owner_database_url=owner_database_url_from_env(env),
        n8n_base_url=_required(env, "N8N_BASE_URL").rstrip("/"),
        n8n_owner_email=_required(env, "N8N_OWNER_EMAIL"),
        n8n_owner_password=_required(env, "N8N_OWNER_PASSWORD"),
        step_key=_required(env, "STEP_KEY"),
        platform_internal_url=_required(env, "PLATFORM_INTERNAL_URL").rstrip("/"),
        team_time_zone=team_time_zone_from_env(env),
        n8n_settings={name: env[name] for name in N8N_GUARDED if name in env},
    )
