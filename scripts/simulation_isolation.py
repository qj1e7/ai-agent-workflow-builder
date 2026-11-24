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
  the simulation's network alone, so only the simulation n8n can reach it;
- every network is internal, nothing publishes a port, no service joins another network or the
  host's, and no volume belongs to another stack;
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
- the project's networks are internal, and only the project's own containers sit on them.

It prints names and addresses, never a key's value, as the CI log is public.

usage: python3 -I -B scripts/simulation_isolation.py [--project NAME]
Exits 0 when every check passes, and 1 when one fails.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SIM_FILE = ROOT / "deploy" / "compose.simulation.yaml"
PLATFORM_FILE = ROOT / "deploy" / "compose.yaml"
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
            }
        ),
        frozenset({"sim"}),
    ),
    "mock-github": Service(frozenset(), frozenset({"sim"})),
    "mock-slack": Service(frozenset(), frozenset({"sim"})),
}
"""Every service the simulation runs, the settings it may hold, and the networks it sits on."""

GATEWAY = "gateway"
"""Where the simulation n8n's blocks and bootstrap send the platform's calls: the simulation
gateway (ADR 0054, PR 3)."""
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
URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)
ADDRESS_FIELD = re.compile(r"host|domain|server|url", re.IGNORECASE)
READY = "bootstrap: ready: all workflows loaded, active and linted"
OUT_OF_REACH = (
    "https://api.github.com/",
    "http://1.1.1.1/",
    "http://host.docker.internal/",
    "http://platform-api:8000/healthz",
    "http://wab-platform-api-1:8000/healthz",
)
ROUTES = {
    "n8n": (
        OUT_OF_REACH,
        (
            "http://mock-github:8200/healthz",
            "https://slack.com/api/api.test",
            "http://gateway:8600/healthz",
        ),
    ),
    "gateway": (OUT_OF_REACH, ("http://n8n:5678/healthz", "http://mock-github:8200/healthz")),
}
"""What each service that calls out may not reach, and what it must reach."""
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


def held_findings(where: str, held: Mapping[str, str], secrets: Mapping[str, str]) -> list[str]:
    return [
        f"{where} holds the platform's {secret} in {name}"
        for name, value in sorted(held.items())
        for secret, secret_value in sorted(secrets.items())
        if secret_value in value
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


def container_findings(
    containers: list[Mapping[str, Any]],
    networks: list[Mapping[str, Any]],
    image_env: Mapping[str, set[str]],
    secrets: Mapping[str, str],
) -> list[str]:
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
        findings += held_findings(name, env, secrets)
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
        strangers = sorted(set(network.get("Containers") or {}) - ours)
        if strangers:
            findings.append(
                f"{len(strangers)} container(s) from outside the project sit on {network['Name']}"
            )
    return findings


# Docker


def docker(*args: str, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False, env=env)


def must(run: subprocess.CompletedProcess[str], what: str) -> str:
    if run.returncode != 0:
        raise CheckError(f"could not {what}: {run.stderr.strip()[:300]}")
    return run.stdout


def render(path: Path, made_up: list[str]) -> dict[str, Any]:
    """The file as compose renders it, with each setting it insists on made up as made-up-NAME.
    Its own env file stands in for deploy/.env, and the SIM_ settings of the caller are left out."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SIM_")}
    with tempfile.NamedTemporaryFile("w", suffix=".env") as env_file:
        env_file.write("".join(f"{name}={MADE_UP}{name}\n" for name in made_up))
        env_file.flush()
        out = must(
            docker(
                "compose",
                "--env-file",
                env_file.name,
                "-f",
                str(path),
                "config",
                "--format",
                "json",
                env=env,
            ),
            f"render {path.relative_to(ROOT)}",
        )
    return json.loads(out)


def insisted(text: str) -> list[str]:
    return sorted(set(re.findall(r"\$\{([A-Z0-9_]+):\?", text)))


def static_findings() -> list[str]:
    if not SIM_FILE.exists():
        return [f"{SIM_FILE.relative_to(ROOT)} does not exist"]
    text = SIM_FILE.read_text()
    sim = render(SIM_FILE, insisted(text))
    platform = render(PLATFORM_FILE, insisted(PLATFORM_FILE.read_text()))
    return file_findings(text) + compose_findings(sim, platform)


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


def live_findings(project: str) -> list[str]:
    label = f"label=com.docker.compose.project={project}"
    ids = must(docker("ps", "--all", "--quiet", "--filter", label), "list the project").split()
    containers = inspect("container", ids)
    if not containers:
        return [f"the project {project} runs no container"]
    network_ids = must(
        docker("network", "ls", "--quiet", "--filter", label), "list the project's networks"
    ).split()
    networks = inspect("network", network_ids)
    by_service = {c["Config"]["Labels"].get("com.docker.compose.service"): c for c in containers}
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
    findings += container_findings(containers, networks, image_env, secrets)

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
    hosts = sim_hosts(render(SIM_FILE, insisted(SIM_FILE.read_text())))
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
    return findings


def main(argv: list[str]) -> int:
    if argv and (len(argv) != 2 or argv[0] != "--project"):
        print(
            "usage: python3 -I -B scripts/simulation_isolation.py [--project NAME]", file=sys.stderr
        )
        return 2
    try:
        findings = static_findings()
        if argv:
            findings += live_findings(argv[1])
    except CheckError as error:
        findings = [str(error)]
    for finding in findings:
        print(f"FAIL: {finding}")
    if findings:
        return 1
    where = "deploy/compose.simulation.yaml" + (f" and the project {argv[1]}" if argv else "")
    print(f"PASS: {where}: the simulation n8n holds no real key and reaches only the mocks.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
