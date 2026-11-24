"""Check that the simulation n8n (ADR 0054) holds no real key and has no way out but to the mocks.

With no argument it checks deploy/compose.simulation.yaml, as compose renders it:
- the file reads only its own SIM_ settings, which scripts/simulation.sh makes up at each start,
  so no key from deploy/.env or the shell can reach the simulation;
- it runs only the services listed below, and each holds only the settings listed for it. It is an
  allow list, so a key added later fails the check;
- every key, password and secret comes from its own SIM_ setting, never from a value in the file;
- every address a service holds names a service on the simulation's own network: its database,
  its mocks, itself, or the simulation gateway;
- the simulation gateway runs platform-api's image as its own service, with its own command, on
  the simulation's network and the link, which no other service here joins;
- every network is internal, nothing publishes a port, no service joins another network or the
  host's, and no volume belongs to another stack;
- deploy/compose.simulation-link.yaml, laid over deploy/compose.yaml, changes platform-api alone:
  it joins the link the simulation makes, calls the gateway by its name there, and reads its start
  secret from deploy/.env (ADR 0054, "What the link chose");
- it runs the platform n8n's image, task runner, PostgreSQL and bootstrap, with the same guards
  (deploy/compose.yaml). It builds each image from the platform's sources under its own tag, sim,
  so it never replaces an image the platform's stack runs.

With --project NAME, the compose project scripts/simulation.sh started, it also checks that stack:
- bootstrap ended ready;
- each container holds only the settings listed for its service, and its image's own;
- no container holds the value of one of the platform's keys: those in deploy/.env, and any key,
  token, secret, password, webhook or database address in the caller's environment;
- every key n8n holds is a mock key: none holds a platform key's value, and each address in one
  names a service on the simulation's network;
- from inside n8n and the gateway the internet, the host and the platform's stack are out of
  reach, and the simulation's own services are in reach, which shows the check can see a route;
- from inside n8n and the gateway the host is out of reach at the address each of the project's
  networks gives it, on the platform's ports and on each port a linked platform publishes, since
  the name host.docker.internal never resolves on an internal network;
- the project's networks are internal, and only the project's own containers sit on them, but for
  a platform's platform-api on the link.

With --platform NAME too, the compose project of the platform linked to the simulation, it checks
from inside the running containers of both stacks:
- that platform runs platform-api, PostgreSQL, n8n and the agent runtime, and its platform-api, and
  nothing else of it, sits on the link;
- the simulation n8n reaches none of those four at any of their addresses, and the gateway none
  but platform-api, with which it shares the link;
- platform-api reaches the gateway by its name on the link, and the platform's n8n and agent
  runtime reach the gateway at none of its addresses;
- each container that probes reaches a service of its own stack by address, which shows its probe
  can see a route.
The start secret is the one value the two stacks share: deploy/.env's SIMULATION_START_SECRET, of
at least 32 characters, may be the start secret of the simulation n8n and of the gateway, and
nothing else.

It prints names and addresses, never a key's value, as the CI log is public.

usage: python3 -I -B scripts/simulation_isolation.py [--project NAME [--platform NAME]]
Exits 0 when every check passes, and 1 when one fails.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SIM_FILE = ROOT / "deploy" / "compose.simulation.yaml"
PLATFORM_FILE = ROOT / "deploy" / "compose.yaml"
LINK_FILE = ROOT / "deploy" / "compose.simulation-link.yaml"
PLATFORM_ENV = ROOT / "deploy" / ".env"

# deploy/compose.yaml's x-n8n-guards (ADR 0051). The simulation n8n and its bootstrap must hold the
# platform n8n's values.
GUARDS = frozenset(
    {
        "NODES_EXCLUDE",
        "N8N_COMMUNITY_PACKAGES_ENABLED",
        "N8N_BLOCK_ENV_ACCESS_IN_NODE",
        "N8N_RUNNERS_MODE",
        "N8N_DEPRECATED_NODES_BLOCK",
        "N8N_RESTRICT_FILE_ACCESS_TO",
        "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES",
    }
)


@dataclass(frozen=True)
class Service:
    settings: frozenset[str]
    networks: frozenset[str]


SERVICES = {
    "postgres": Service(
        frozenset(
            {
                "POSTGRES_PASSWORD",
                "N8N_DB_PASSWORD",
                "WAB_OWNER_PASSWORD",
                "WAB_BUILDER_PASSWORD",
                "WAB_ORCHESTRATION_PASSWORD",
                "WAB_MONITORING_PASSWORD",
            }
        ),
        frozenset({"sim"}),
    ),
    "n8n": Service(
        GUARDS
        | {
            "DB_TYPE",
            "DB_POSTGRESDB_HOST",
            "DB_POSTGRESDB_PORT",
            "DB_POSTGRESDB_DATABASE",
            "DB_POSTGRESDB_USER",
            "DB_POSTGRESDB_PASSWORD",
            "WEBHOOK_URL",
            "GENERIC_TIMEZONE",
            "N8N_ENCRYPTION_KEY",
            "N8N_DIAGNOSTICS_ENABLED",
            "N8N_VERSION_NOTIFICATIONS_ENABLED",
            "N8N_PERSONALIZATION_ENABLED",
            "N8N_HIRING_BANNER_ENABLED",
            "N8N_SECURE_COOKIE",
            "N8N_DISABLED_MODULES",
            "N8N_RUNNERS_AUTH_TOKEN",
            "EXECUTIONS_DATA_SAVE_ON_SUCCESS",
            "WAB_API_URL",
            "WAB_NODE_KEY",
            "WAB_START_SECRET",
            "NODE_EXTRA_CA_CERTS",
            "WAB_REQUEST_TIMEOUT_SECONDS",
        },
        frozenset({"sim", "runners"}),
    ),
    "n8n-runners": Service(
        frozenset(
            {
                "N8N_RUNNERS_TASK_BROKER_URI",
                "N8N_RUNNERS_AUTH_TOKEN",
                "N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT",
                "GENERIC_TIMEZONE",
            }
        ),
        frozenset({"runners"}),
    ),
    "bootstrap": Service(
        GUARDS
        | {
            "DATABASE_URL_OWNER",
            "N8N_BASE_URL",
            "N8N_OWNER_EMAIL",
            "N8N_OWNER_PASSWORD",
            "STEP_KEY",
            "PLATFORM_INTERNAL_URL",
            "TEAM_TIME_ZONE",
        },
        frozenset({"sim"}),
    ),
    "gateway": Service(
        frozenset(
            {
                "WAB_NODE_KEY",
                "WAB_START_SECRET",
                "N8N_BASE_URL",
                "N8N_OWNER_EMAIL",
                "N8N_OWNER_PASSWORD",
                "MOCK_GITHUB_URL",
                "MOCK_SLACK_TOKEN",
            }
        ),
        frozenset({"sim", "link"}),
    ),
    "mock-github": Service(frozenset(), frozenset({"sim"})),
    "mock-slack": Service(frozenset({"MOCK_SLACK_TOKEN"}), frozenset({"sim"})),
}
"""Every service the simulation runs, the settings it may hold, and the networks it sits on."""

GATEWAY = "gateway"
"""Where the simulation n8n's blocks and bootstrap send the platform's calls: the simulation
gateway (ADR 0054, PR 3)."""
LINK = "link"
"""The network the gateway shares with a linked platform's platform-api alone (ADR 0054, "What the
link chose"). The simulation makes it, and platform-api joins it by its name."""
LINK_ALIAS = "simulation-gateway"
"""The gateway's name on the link, which platform-api calls."""
LINKED = "platform-api"
"""The one service of a platform that may sit on the link."""
SHARED = "SIMULATION_START_SECRET"
"""The one value a linked platform shares with the simulation, from deploy/.env: the start secret
platform-api signs the gateway's routes with."""
SHARED_AS = frozenset({("n8n", "WAB_START_SECRET"), ("gateway", "WAB_START_SECRET")})
"""The settings that may hold it: the start secret of the simulation n8n and of the gateway."""
LINK_SETTINGS = frozenset({"SIMULATION_URL", SHARED})
"""What the link file gives platform-api."""
GATEWAY_COMMAND = [
    "uvicorn",
    "platform_api.orchestration.simulation_gateway:create_app",
    "--factory",
    "--host",
    "0.0.0.0",
    "--port",
    "8600",
]
"""The gateway runs platform-api's image, but only the gateway's own app, never the platform's."""
SAME_AS_PLATFORM = {
    "postgres": "postgres",
    "n8n": "n8n",
    "n8n-runners": "n8n-runners",
    "bootstrap": "bootstrap",
    "gateway": "platform-api",
}
"""Services that run the platform's own image, or build it from the same sources, by the name the
platform's compose file gives that service."""
SIM_TAG = "sim"
"""The tag of every image the simulation builds, so it never replaces one the platform runs."""
MOUNTS = {
    "postgres": {("bind", "deploy/postgres/init.sh")},
    "n8n": {("volume", "slack-ca")},
    "mock-slack": {("volume", "slack-ca")},
}
"""What each service mounts, besides an in-memory folder. A bind mount is a path in the repo."""
MADE_UP = "made-up-"
KEYED = re.compile(r"(?:_KEY|_TOKEN|_SECRET|_PASSWORD)$")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|WEBHOOK|DATABASE_URL")
SHORTEST_SECRET = 8
SHORTEST_START_SECRET = 32
"""The fewest characters the shared start secret may have, as platform-api and the gateway
insist (platform_api.settings.SHORTEST_START_SECRET)."""
URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)
ADDRESS_FIELD = re.compile(r"host|domain|server|url", re.IGNORECASE)
READY = "bootstrap: ready: all workflows loaded, active and linted"
OUT_OF_REACH = ("https://api.github.com/", "http://1.1.1.1/", "http://host.docker.internal/")
ROUTES = {
    "n8n": (
        (
            *OUT_OF_REACH,
            "http://platform-api:8000/healthz",
            "http://wab-platform-api-1:8000/healthz",
        ),
        (
            "http://mock-github:8200/healthz",
            "https://slack.com/api/api.test",
            "http://gateway:8600/healthz",
        ),
    ),
    # The gateway shares the link with platform-api, so platform-api's name may answer it there.
    # With --platform, the check probes every address of the linked platform's other services.
    "gateway": (OUT_OF_REACH, ("http://n8n:5678/healthz", "http://mock-github:8200/healthz")),
}
"""What each service that calls out may not reach, and what it must reach."""
PORTS = {"platform-api": 8000, "postgres": 5432, "n8n": 5678, "agent-runtime": 8100, GATEWAY: 8600}
"""Where each service listens, in the platform's stack and the simulation's."""
KEPT_FROM = {
    "n8n": ("platform-api", "postgres", "n8n", "agent-runtime"),
    GATEWAY: ("postgres", "n8n", "agent-runtime"),
}
"""What each of the simulation's services may not reach of a linked platform, at any address."""
KEPT_OUT = ("n8n", "agent-runtime")
"""The linked platform's services that may not reach the gateway, at any of its addresses."""
PROBE = """
const url = process.argv[1];
fetch(url, { signal: AbortSignal.timeout(5000) }).then(
  (res) => { console.log(`answered ${res.status}`); },
  (err) => {
    console.log(String(err.cause?.code ?? err.cause?.message ?? err.name));
    process.exit(1);
  },
);
"""
PYTHON_PROBE = """
import sys, urllib.error, urllib.request
try:
    answer = urllib.request.urlopen(sys.argv[1], timeout=5)
    print(f"answered {answer.status}")
except urllib.error.HTTPError as error:
    print(f"answered {error.code}")
except Exception as error:
    reason = getattr(error, "reason", error)
    print(reason if isinstance(reason, str) else type(reason).__name__)
    sys.exit(1)
"""
PROBES = {"n8n": ("node", "-e", PROBE), "gateway": ("python", "-I", "-c", PYTHON_PROBE)}
CONNECT = """
const socket = require('net').connect({ host: process.argv[1], port: Number(process.argv[2]) });
socket.setTimeout(3000);
socket.on('connect', () => { console.log('connected'); socket.destroy(); });
socket.on('timeout', () => { console.log('timed out'); socket.destroy(); process.exit(1); });
socket.on('error', (err) => { console.log(String(err.code ?? err.message)); process.exit(1); });
"""
PYTHON_CONNECT = """
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3).close()
    print("connected")
except OSError as error:
    print(error.strerror or type(error).__name__)
    sys.exit(1)
"""
CONNECTS = {"n8n": ("node", "-e", CONNECT)}
"""How a service opens a connection to an address: node in n8n's image, python in the others."""
PYTHON_CONNECTS = ("python", "-I", "-c", PYTHON_CONNECT)


class CheckError(Exception):
    """Docker could not show what the check needs."""


# What compose renders


def settings_read(text: str) -> set[str]:
    """The settings a compose file reads, written ${NAME} or $NAME. $$ is a dollar sign."""
    return set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", text.replace("$$", "")))


def file_findings(text: str) -> list[str]:
    other = sorted(name for name in settings_read(text) if not name.startswith("SIM_"))
    if not other:
        return []
    return [f"the file reads {', '.join(other)}, not only its own SIM_ settings"]


def sim_hosts(config: Mapping[str, Any]) -> set[str]:
    """The names a container on the simulation's networks can reach: its services, their aliases,
    and the gateway."""
    hosts = {GATEWAY, *config.get("services", {})}
    for service in config.get("services", {}).values():
        for network in (service.get("networks") or {}).values():
            hosts.update((network or {}).get("aliases") or [])
    return hosts


def addresses(field: str, value: str) -> Iterator[str]:
    """The hosts a value names: those of the URLs in it, else the value itself when the field's
    name says it holds an address and the value looks like a host."""
    found = [urlsplit(url).hostname or "" for url in URL.findall(value)]
    yield from found
    names = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", field)
    last = names[-1] if names else ""
    bare = re.split(r"[/:]", value.strip(), maxsplit=1)[0].lower()
    if found or not bare or re.search(r"\s", bare) or not ADDRESS_FIELD.search(last):
        return
    if "." in bare or last.upper().endswith("HOST"):
        yield bare


def service_findings(name: str, service: Mapping[str, Any], hosts: set[str]) -> list[str]:
    allowed = SERVICES[name]
    env: Mapping[str, str | None] = service.get("environment") or {}
    findings: list[str] = []
    unlisted = sorted(set(env) - allowed.settings)
    if unlisted:
        findings.append(f"{name} holds {', '.join(unlisted)}, which its list here doesn't name")
    for setting, value in sorted(env.items()):
        value = value or ""
        if KEYED.search(setting) and not value.startswith(MADE_UP + "SIM_"):
            findings.append(f"{name}'s {setting} is not made from its own SIM_ setting")
        if setting.startswith("DATABASE_URL") and not (urlsplit(value).password or "").startswith(
            MADE_UP + "SIM_"
        ):
            findings.append(f"{name}'s {setting} signs in with a password not from a SIM_ setting")
        for host in addresses(setting, value):
            if host not in hosts:
                findings.append(
                    f"{name}'s {setting} points at {host}, outside the simulation's network"
                )
    networks = set(service.get("networks") or {})
    if networks != allowed.networks:
        findings.append(
            f"{name} sits on {sorted(networks)}, not on {sorted(allowed.networks)} alone"
        )
    for key in ("ports", "network_mode", "extra_hosts", "dns", "external_links", "links"):
        if service.get(key):
            findings.append(f"{name} sets {key}, which can open a way out")
    mounts = MOUNTS.get(name, set())
    for volume in service.get("volumes") or []:
        kind, source = volume.get("type"), str(volume.get("source") or "")
        if kind == "bind":
            ok = any(k == "bind" and Path(source) == ROOT / path for k, path in mounts)
        else:
            ok = (kind, source) in mounts
        if not ok:
            findings.append(f"{name} mounts the {kind} {source}, which its list here doesn't name")
    return findings


def network_findings(config: Mapping[str, Any]) -> list[str]:
    findings: list[str] = []
    for name, network in sorted((config.get("networks") or {}).items()):
        network = network or {}
        if network.get("external"):
            findings.append(f"the network {name} belongs to another stack")
        if not network.get("internal"):
            findings.append(f"the network {name} is not internal, so it has a way out")
    for name, volume in sorted((config.get("volumes") or {}).items()):
        if (volume or {}).get("external"):
            findings.append(f"the volume {name} belongs to another stack")
    return findings


def repository(image: object) -> str:
    """An image's name without its tag or digest, such as wab/n8n."""
    name = str(image or "").split("@", 1)[0]
    head, sep, tag = name.rpartition(":")
    return head if sep and "/" not in tag else name


def platform_findings(sim: Mapping[str, Any], platform: Mapping[str, Any]) -> list[str]:
    sim_services = sim.get("services", {})
    platform_services = platform.get("services", {})
    findings: list[str] = []
    # A service may run the image another service here builds, as the gateway runs bootstrap's.
    builders = {str(s.get("image")): s for s in sim_services.values() if "build" in s}
    for name, platform_name in SAME_AS_PLATFORM.items():
        ours, theirs = sim_services.get(name, {}), platform_services.get(platform_name, {})
        built = ours if "build" in ours else builders.get(str(ours.get("image")), ours)
        if "build" not in theirs and ours.get("image") != theirs.get("image"):
            findings.append(
                f"{name} runs {ours.get('image')}, not the platform's {theirs.get('image')}"
            )
        if "build" in theirs and (
            built.get("build") != theirs["build"]
            or repository(ours.get("image")) != repository(theirs.get("image"))
        ):
            findings.append(
                f"{name} doesn't build the platform's {repository(theirs.get('image'))}"
            )
    for name, service in sorted(sim_services.items()):
        image = str(service.get("image"))
        if "build" in service and image != f"{repository(image)}:{SIM_TAG}":
            findings.append(
                f"{name} builds {image}, not a {SIM_TAG} image, so it can replace one the "
                "platform runs"
            )
    sim_n8n = sim_services.get("n8n", {}).get("environment") or {}
    platform_n8n = platform_services.get("n8n", {}).get("environment") or {}
    bootstrap = sim_services.get("bootstrap", {}).get("environment") or {}
    differ = sorted(g for g in GUARDS if g not in sim_n8n or sim_n8n[g] != platform_n8n.get(g))
    if differ:
        findings.append(f"n8n's {', '.join(differ)} differ from the platform n8n's")
    unchecked = sorted(g for g in GUARDS if bootstrap.get(g) != sim_n8n.get(g))
    if unchecked:
        findings.append(
            f"bootstrap's {', '.join(unchecked)} differ from n8n's, so it checks another n8n"
        )
    return findings


def compose_findings(sim: Mapping[str, Any], platform: Mapping[str, Any]) -> list[str]:
    services = sim.get("services", {})
    findings: list[str] = []
    extra = sorted(set(services) - set(SERVICES))
    if extra:
        findings.append(f"the simulation runs {', '.join(extra)}, which its list here doesn't name")
    missing = sorted(set(SERVICES) - set(services))
    if missing:
        findings.append(f"the simulation lacks {', '.join(missing)}")
    hosts = sim_hosts(sim)
    for name in sorted(set(services) & set(SERVICES)):
        findings += service_findings(name, services[name], hosts)
    gateway = services.get(GATEWAY)
    if gateway is not None and gateway.get("command") != GATEWAY_COMMAND:
        findings.append(f"the gateway runs {gateway.get('command')}, not the simulation gateway")
    return findings + network_findings(sim) + platform_findings(sim, platform)


def link_findings(
    sim: Mapping[str, Any], platform: Mapping[str, Any], linked: Mapping[str, Any]
) -> list[str]:
    """deploy/compose.simulation-link.yaml over deploy/compose.yaml: platform-api alone joins the
    link the simulation makes, and is given only the gateway's name there and the start secret."""
    link_name = ((sim.get("networks") or {}).get(LINK) or {}).get("name")
    added = {
        key: network or {}
        for key, network in (linked.get("networks") or {}).items()
        if key not in (platform.get("networks") or {})
    }
    findings: list[str] = []
    others = sorted(key for key, network in added.items() if network.get("name") != link_name)
    if others:
        findings.append(f"the link file adds {', '.join(others)}, not only the simulation's link")
    joins = [key for key, network in added.items() if network.get("name") == link_name]
    for key in joins:
        if not added[key].get("external"):
            findings.append(f"the link file makes {link_name} itself, not the simulation's link")
    services, before = linked.get("services", {}), platform.get("services", {})
    changed = sorted(
        n for n in set(services) | set(before) if n != LINKED and services.get(n) != before.get(n)
    )
    if changed:
        findings.append(f"the link file changes {', '.join(changed)}, not {LINKED} alone")
    api, api_before = services.get(LINKED, {}), before.get(LINKED, {})
    networks = set(api.get("networks") or {})
    if len(joins) != 1 or networks != set(api_before.get("networks") or {}) | set(joins):
        findings.append(f"{LINKED} sits on {sorted(networks)}, not on its own and {link_name}")
    env, env_before = api.get("environment") or {}, api_before.get("environment") or {}
    given = {name for name in set(env) | set(env_before) if env.get(name) != env_before.get(name)}
    if given != LINK_SETTINGS:
        findings.append(f"the link file gives {LINKED} {', '.join(sorted(given))}")
    gateway = sim.get("services", {}).get(GATEWAY, {})
    names = {GATEWAY, *(((gateway.get("networks") or {}).get(LINK) or {}).get("aliases") or [])}
    host = urlsplit(str(env.get("SIMULATION_URL") or "")).hostname
    if host not in names:
        findings.append(f"{LINKED}'s SIMULATION_URL points at {host}, not the gateway on the link")
    if not str(env.get(SHARED) or "").startswith(MADE_UP + SHARED):
        findings.append(f"{LINKED}'s {SHARED} is not read from deploy/.env")
    rest = {k: v for k, v in api.items() if k not in ("networks", "environment")}
    rest_before = {k: v for k, v in api_before.items() if k not in ("networks", "environment")}
    if rest != rest_before:
        findings.append(f"the link file changes more of {LINKED} than its networks and settings")
    return findings


# What runs


def secret_values(env_file: str, environ: Mapping[str, str]) -> dict[str, str]:
    """The platform's keys by name: deploy/.env's, and the caller's, never the simulation's own."""
    values: dict[str, str] = {}
    for line in env_file.splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and not name.startswith("#"):
            values[name.strip()] = value.strip()
    values.update(environ)
    return {
        name: value
        for name, value in values.items()
        if SECRET_NAME.search(name)
        and not name.startswith("SIM_")
        and len(value) >= SHORTEST_SECRET
    }


def held_findings(
    where: str, held: Mapping[str, str], secrets: Mapping[str, str], *, service: str = ""
) -> list[str]:
    """Each platform key a value holds, but the start secret where a linked simulation's service
    holds it as its own start secret."""
    return [
        f"{where} holds the platform's {secret} in {name}"
        for name, value in sorted(held.items())
        for secret, secret_value in sorted(secrets.items())
        if secret_value in value
        and not (secret == SHARED and (service, name) in SHARED_AS and value == secret_value)
    ]


def strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{path}[{index}]")


def credential_findings(
    credentials: list[Mapping[str, Any]], secrets: Mapping[str, str], hosts: set[str]
) -> list[str]:
    findings: list[str] = []
    for credential in credentials:
        label = f"n8n's key '{credential.get('name')}' ({credential.get('type')})"
        fields = dict(strings(credential.get("data") or {}))
        findings += held_findings(label, fields, secrets)
        for field, value in sorted(fields.items()):
            for host in addresses(field, value):
                if host not in hosts:
                    findings.append(
                        f"{label} points {field} at {host}, outside the simulation's network"
                    )
    return findings


def route_findings(service: str, reached: Mapping[str, tuple[bool, str]]) -> list[str]:
    out_of_reach, in_reach = ROUTES[service]
    findings: list[str] = []
    for url in out_of_reach:
        ok, how = reached[url]
        if ok:
            findings.append(f"{service} reaches {url} ({how})")
    for url in in_reach:
        ok, how = reached[url]
        if not ok:
            findings.append(f"{service} can't reach {url} ({how}), so the check sees no route")
    return findings


def labels(container: Mapping[str, Any]) -> tuple[str, str]:
    """A container's compose project and service, or empty words for one compose didn't start."""
    found = container["Config"].get("Labels") or {}
    return found.get("com.docker.compose.project", ""), found.get("com.docker.compose.service", "")


def container_findings(
    containers: list[Mapping[str, Any]],
    networks: list[Mapping[str, Any]],
    image_env: Mapping[str, set[str]],
    secrets: Mapping[str, str],
    *,
    strangers: Mapping[str, Mapping[str, Any]] | None = None,
    platform: str | None = None,
) -> list[str]:
    """strangers holds each container from outside the project on the link, by its id. Only a
    platform's platform-api may sit there, and only the named platform's when one is named."""
    strangers = strangers or {}
    findings: list[str] = []
    ours = {c["Id"] for c in containers}
    our_networks = {n["Name"] for n in networks}
    for container in containers:
        name = container["Name"].lstrip("/")
        service = container["Config"]["Labels"].get("com.docker.compose.service", "")
        env = dict(item.partition("=")[::2] for item in container["Config"].get("Env") or [])
        if service not in SERVICES:
            findings.append(
                f"{name} runs {service or 'no service'}, which the list here doesn't name"
            )
        else:
            allowed = SERVICES[service].settings | image_env.get(container["Image"], set())
            unlisted = sorted(set(env) - allowed)
            if unlisted:
                findings.append(f"{name} holds {', '.join(unlisted)}, which its list doesn't name")
        findings += held_findings(name, env, secrets, service=service)
        host = container["HostConfig"]
        mode = host.get("NetworkMode") or ""
        if mode not in our_networks:
            findings.append(f"{name} uses the network mode {mode or 'none'}")
        if any(host.get("PortBindings") or {}):
            findings.append(f"{name} publishes a port")
        joined = set(container["NetworkSettings"].get("Networks") or {})
        if joined - our_networks:
            findings.append(f"{name} also sits on {', '.join(sorted(joined - our_networks))}")
    for network in networks:
        if not network.get("Internal"):
            findings.append(f"the network {network['Name']} is not internal")
        outside = sorted(set(network.get("Containers") or {}) - ours)
        if (network.get("Labels") or {}).get("com.docker.compose.network") == LINK:
            for cid in outside:
                project, service = labels(strangers[cid]) if cid in strangers else ("", "")
                if service != LINKED or not project or (platform and project != platform):
                    who = (
                        f"{project}'s {service}" if service else "a container compose didn't start"
                    )
                    findings.append(
                        f"{who} sits on {network['Name']}, where only the gateway and "
                        f"{platform or 'a platform'}'s {LINKED} may"
                    )
        elif outside:
            findings.append(
                f"{len(outside)} container(s) from outside the project sit on {network['Name']}"
            )
    return findings


def addresses_of(container: Mapping[str, Any]) -> list[str]:
    networks = container["NetworkSettings"].get("Networks") or {}
    return sorted({n["IPAddress"] for n in networks.values() if (n or {}).get("IPAddress")})


def linked_platform_findings(
    platform: str, by_service: Mapping[str, Mapping[str, Any]], link_name: str
) -> list[str]:
    findings = [
        f"the platform {platform} runs no {service}"
        for service in sorted(set(KEPT_FROM["n8n"]) - set(by_service))
    ]
    api = by_service.get(LINKED)
    if api is not None and link_name not in (api["NetworkSettings"].get("Networks") or {}):
        findings.append(f"{platform}'s {LINKED} is not on the link, {link_name}")
    return findings


@dataclass(frozen=True)
class Probe:
    """A connection one container opens to an address, which it must or must not reach."""

    origin: str
    container: str
    command: tuple[str, ...]
    host: str
    port: int
    target: str
    reach: bool


def probe_from(
    stack: Mapping[str, Mapping[str, Any]], service: str, label: str = ""
) -> Callable[[str, int, str, bool], Probe]:
    """Probes from one service's container, by node in n8n's image and python in the others."""
    container, command = stack[service]["Id"], CONNECTS.get(service, PYTHON_CONNECTS)
    return lambda host, port, target, reach: Probe(
        label or service, container, command, host, port, target, reach
    )


def own_database(stack: Mapping[str, Mapping[str, Any]]) -> str:
    return (addresses_of(stack["postgres"]) or [""])[0] if "postgres" in stack else ""


def host_probes(
    sim: Mapping[str, Mapping[str, Any]], hosts: Sequence[str], ports: Sequence[int]
) -> list[Probe]:
    """From the simulation's n8n and gateway to the host, at the address each simulation network
    gives it, on each port, with the simulation's own PostgreSQL as the route each must see."""
    probes: list[Probe] = []
    for service in sorted(set(KEPT_FROM) & set(sim)):
        probe = probe_from(sim, service)
        probes.append(probe(own_database(sim), PORTS["postgres"], "its own postgres", True))
        probes += [probe(host, port, "the host", False) for host in hosts for port in ports]
    return probes


def platform_probes(
    sim: Mapping[str, Mapping[str, Any]], platform: Mapping[str, Mapping[str, Any]]
) -> list[Probe]:
    """From the simulation's n8n and gateway into a linked platform, and back from its
    platform-api, n8n and agent runtime, each of those with a route of its own it must see."""
    probes: list[Probe] = []
    for service in sorted(set(KEPT_FROM) & set(sim)):
        probe = probe_from(sim, service)
        for target in KEPT_FROM[service]:
            for host in addresses_of(platform.get(target, {"NetworkSettings": {}})):
                probes.append(probe(host, PORTS[target], f"the platform's {target}", False))
    if LINKED in platform:
        probe = probe_from(platform, LINKED, f"the platform's {LINKED}")
        probes.append(probe(LINK_ALIAS, PORTS[GATEWAY], "the gateway on the link", True))
    for service in sorted(set(KEPT_OUT) & set(platform)):
        probe = probe_from(platform, service, f"the platform's {service}")
        probes.append(probe(own_database(platform), PORTS["postgres"], "its own postgres", True))
        for host in addresses_of(sim.get(GATEWAY, {"NetworkSettings": {}})):
            probes.append(probe(host, PORTS[GATEWAY], "the gateway", False))
    return probes


def network_gateways(networks: list[Mapping[str, Any]]) -> list[str]:
    """The host's address on each network, which Docker gives as the network's gateway."""
    return sorted(
        {
            config["Gateway"]
            for network in networks
            for config in ((network.get("IPAM") or {}).get("Config") or [])
            if config.get("Gateway")
        }
    )


def host_ports(platform: Mapping[str, Mapping[str, Any]]) -> list[int]:
    """The ports the platform's services listen on, and each a linked platform publishes."""
    ports = {PORTS["platform-api"], PORTS["n8n"], PORTS["postgres"]}
    for container in platform.values():
        for bindings in ((container.get("HostConfig") or {}).get("PortBindings") or {}).values():
            ports.update(int(b["HostPort"]) for b in bindings or [] if b.get("HostPort"))
    return sorted(ports)


def shared_secret_findings(secrets: Mapping[str, str]) -> list[str]:
    """A linked platform's start secret, from deploy/.env, as long as both sides insist."""
    secret = secrets.get(SHARED)
    if secret is None:
        return [f"deploy/.env has no {SHARED}. Run deploy/make-env.sh."]
    if len(secret) < SHORTEST_START_SECRET:
        return [f"deploy/.env's {SHARED} is shorter than {SHORTEST_START_SECRET} characters"]
    return []


def probe_findings(results: list[tuple[Probe, bool, str]]) -> list[str]:
    findings: list[str] = []
    for probe, ok, how in results:
        where = f"{probe.target} at {probe.host}:{probe.port}"
        if ok and not probe.reach:
            findings.append(f"{probe.origin} reaches {where} ({how})")
        if probe.reach and not ok:
            findings.append(
                f"{probe.origin} can't reach {where} ({how}), so the check sees no route"
            )
    return findings


# Docker


def docker(*args: str, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False, env=env)


def must(run: subprocess.CompletedProcess[str], what: str) -> str:
    if run.returncode != 0:
        raise CheckError(f"could not {what}: {run.stderr.strip()[:300]}")
    return run.stdout


def render(*paths: Path) -> dict[str, Any]:
    """The files as compose renders them, one over another, with each setting they insist on made
    up as made-up-NAME. Its own env file stands in for deploy/.env. The caller's SIM_ settings and
    the name of the link it uses are left out, so the files are read as written."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("SIM_") and k != "SIMULATION_LINK_NETWORK"
    }
    made_up = sorted({name for path in paths for name in insisted(path.read_text())})
    files = [arg for path in paths for arg in ("-f", str(path))]
    with tempfile.NamedTemporaryFile("w", suffix=".env") as env_file:
        env_file.write("".join(f"{name}={MADE_UP}{name}\n" for name in made_up))
        env_file.flush()
        out = must(
            docker(
                "compose",
                "--env-file",
                env_file.name,
                *files,
                "config",
                "--format",
                "json",
                env=env,
            ),
            f"render {', '.join(str(path.relative_to(ROOT)) for path in paths)}",
        )
    return json.loads(out)


def insisted(text: str) -> list[str]:
    return sorted(set(re.findall(r"\$\{([A-Z0-9_]+):\?", text)))


def static_findings() -> list[str]:
    missing = [path for path in (SIM_FILE, LINK_FILE) if not path.exists()]
    if missing:
        return [f"{path.relative_to(ROOT)} does not exist" for path in missing]
    sim = render(SIM_FILE)
    platform = render(PLATFORM_FILE)
    linked = render(PLATFORM_FILE, LINK_FILE)
    return (
        file_findings(SIM_FILE.read_text())
        + compose_findings(sim, platform)
        + link_findings(sim, platform, linked)
    )


def inspect(kind: str, ids: list[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    return json.loads(must(docker(kind, "inspect", *ids), f"inspect the project's {kind}s"))


def n8n_credentials(container: str) -> list[dict[str, Any]]:
    """Every key n8n holds, decrypted with its own encryption key, inside its own container."""
    path = "/tmp/simulation-isolation-keys.json"
    try:
        run = docker(
            "exec",
            container,
            "n8n",
            "export:credentials",
            "--all",
            "--decrypted",
            f"--output={path}",
        )
        if "No credentials found" in run.stdout + run.stderr:
            return []
        must(run, "export n8n's keys")
        return json.loads(must(docker("exec", container, "cat", path), "read n8n's keys"))
    finally:
        docker("exec", container, "rm", "-f", path)


def reach(container: str, service: str, url: str) -> tuple[bool, str]:
    run = docker("exec", container, *PROBES[service], url)
    return run.returncode == 0, (run.stdout.strip() or run.stderr.strip())[:80]


def connect(probe: Probe) -> tuple[bool, str]:
    run = docker("exec", probe.container, *probe.command, probe.host, str(probe.port))
    return run.returncode == 0, (run.stdout.strip() or run.stderr.strip())[:80]


def project_containers(project: str) -> list[dict[str, Any]]:
    label = f"label=com.docker.compose.project={project}"
    ids = must(docker("ps", "--all", "--quiet", "--filter", label), f"list {project}").split()
    return inspect("container", ids)


def probed_findings(probes: list[Probe]) -> list[str]:
    results = [(probe, *connect(probe)) for probe in probes]
    for probe, ok, how in results:
        where = f"{probe.target} at {probe.host}:{probe.port}"
        print(f"  from {probe.origin}, {where}: {'reached' if ok else 'not reached'} ({how})")
    return probe_findings(results)


def live_findings(project: str, platform: str | None = None) -> list[str]:
    label = f"label=com.docker.compose.project={project}"
    containers = project_containers(project)
    if not containers:
        return [f"the project {project} runs no container"]
    network_ids = must(
        docker("network", "ls", "--quiet", "--filter", label), "list the project's networks"
    ).split()
    networks = inspect("network", network_ids)
    by_service = {c["Config"]["Labels"].get("com.docker.compose.service"): c for c in containers}
    link = next(
        (n for n in networks if (n.get("Labels") or {}).get("com.docker.compose.network") == LINK),
        None,
    )
    ours = {c["Id"] for c in containers}
    outside = sorted(set((link or {}).get("Containers") or {}) - ours)
    strangers = {c["Id"]: c for c in inspect("container", outside)}
    findings: list[str] = []

    bootstrap = by_service.get("bootstrap")
    if bootstrap is None:
        findings.append("bootstrap never ran")
    else:
        state = bootstrap["State"]
        logs = docker("logs", bootstrap["Id"])
        if state.get("Status") != "exited" or state.get("ExitCode") != 0:
            findings.append(
                f"bootstrap is {state.get('Status')} with exit code {state.get('ExitCode')}"
            )
        if READY not in logs.stdout + logs.stderr:
            findings.append("bootstrap never said the simulation n8n is ready")

    images = {c["Image"] for c in containers}
    image_env = {
        image["Id"]: {item.partition("=")[0] for item in image["Config"].get("Env") or []}
        for image in inspect("image", sorted(images))
    }
    env_file = PLATFORM_ENV.read_text() if PLATFORM_ENV.exists() else ""
    secrets = secret_values(env_file, os.environ)
    findings += container_findings(
        containers, networks, image_env, secrets, strangers=strangers, platform=platform
    )

    gateway = by_service.get(GATEWAY)
    if gateway is not None and gateway["Config"].get("Cmd") != GATEWAY_COMMAND:
        findings.append(
            f"the gateway runs {gateway['Config'].get('Cmd')}, not the simulation gateway"
        )
    running = {
        service: container
        for service, container in by_service.items()
        if service in ROUTES and container["State"].get("Running")
    }
    findings += [f"{service} is not running" for service in sorted(set(ROUTES) - set(running))]
    if "n8n" not in running:
        return findings
    hosts = sim_hosts(render(SIM_FILE))
    credentials = n8n_credentials(running["n8n"]["Id"])
    findings += credential_findings(credentials, secrets, hosts)
    routes = 0
    for service, container in sorted(running.items()):
        out_of_reach, in_reach = ROUTES[service]
        reached = {url: reach(container["Id"], service, url) for url in (*out_of_reach, *in_reach)}
        findings += route_findings(service, reached)
        routes += len(reached)
        for url, (ok, how) in reached.items():
            print(f"  from {service}, {url}: {'reached' if ok else 'not reached'} ({how})")
    print(
        f"checked {len(containers)} containers, {len(networks)} networks, {len(credentials)} keys "
        f"in n8n, and {routes} routes from n8n and the gateway, against {len(secrets)} of the "
        "platform's keys"
    )
    sim = {**running, **{s: c for s, c in by_service.items() if s == "postgres"}}
    linked: dict[str, Any] = {}
    if platform:
        findings += shared_secret_findings(secrets)
        linked = {
            labels(c)[1]: c for c in project_containers(platform) if c["State"].get("Running")
        }
        if link is None:
            findings.append("the simulation has no link")
        else:
            findings += linked_platform_findings(platform, linked, link["Name"])
    probes = host_probes(sim, network_gateways(networks), host_ports(linked))
    if platform:
        probes += platform_probes(sim, linked)
    findings += probed_findings(probes)
    print(
        f"probed {len(probes)} addresses: the host's on each network"
        + (f", and those between the simulation and the platform {platform}" if platform else "")
    )
    return findings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -I -B scripts/simulation_isolation.py",
        description="Check the simulation n8n holds no real key and reaches only the mocks.",
    )
    parser.add_argument("--project", help="the simulation's compose project, to check it running")
    parser.add_argument("--platform", help="the compose project of the platform linked to it")
    args = parser.parse_args(argv)
    if args.platform and not args.project:
        parser.error("--platform needs --project")
    try:
        findings = static_findings()
        if args.project:
            findings += live_findings(args.project, args.platform)
    except CheckError as error:
        findings = [str(error)]
    for finding in findings:
        print(f"FAIL: {finding}")
    if findings:
        return 1
    where = "deploy/compose.simulation.yaml and its link file"
    if args.project:
        where += f", and the project {args.project}"
    if args.platform:
        where += f" linked to {args.platform}"
    print(f"PASS: {where}: the simulation n8n holds no real key and reaches only the mocks.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
