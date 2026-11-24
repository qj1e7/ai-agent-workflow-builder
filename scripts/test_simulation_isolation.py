"""scripts/simulation_isolation.py fails when the simulation n8n (ADR 0054) could hold a real key
or reach past the mocks, and names what it found without ever showing a key's value.

Run from the repo root:
    python3 -I -B -m unittest discover -s scripts -p test_simulation_isolation.py
"""

import unittest
from typing import Any

import simulation_isolation as check

# Built at run time, as scripts/simulation.sh makes the simulation's own keys. None is a real key.
PLATFORM_KEY = "pk" + "7f3a9c" * 8
SIM_KEY = "sk" + "1b2e4d" * 8


def made_up(name: str) -> str:
    return f"{check.MADE_UP}{name}"


def good_sim() -> dict[str, Any]:
    """deploy/compose.simulation.yaml as compose renders it, with made-up settings."""
    guards = {name: f"value of {name}" for name in check.GUARDS}
    return {
        "services": {
            "postgres": {
                "image": "postgres:17@sha256:0",
                "environment": {
                    "POSTGRES_PASSWORD": made_up("SIM_POSTGRES_PASSWORD"),
                    "N8N_DB_PASSWORD": made_up("SIM_N8N_DB_PASSWORD"),
                    "WAB_OWNER_PASSWORD": made_up("SIM_OWNER_PASSWORD"),
                    "WAB_BUILDER_PASSWORD": made_up("SIM_OTHER_PASSWORD"),
                    "WAB_ORCHESTRATION_PASSWORD": made_up("SIM_OTHER_PASSWORD"),
                    "WAB_MONITORING_PASSWORD": made_up("SIM_OTHER_PASSWORD"),
                },
                "networks": {"sim": None},
                "tmpfs": ["/var/lib/postgresql/data"],
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(check.ROOT / "deploy/postgres/init.sh"),
                        "target": "/docker-entrypoint-initdb.d/init.sh",
                        "read_only": True,
                    }
                ],
            },
            "n8n": {
                "image": "wab/n8n:sim",
                "build": {"context": str(check.ROOT), "dockerfile": "deploy/n8n/Dockerfile"},
                "environment": {
                    **guards,
                    "DB_TYPE": "postgresdb",
                    "DB_POSTGRESDB_HOST": "postgres",
                    "DB_POSTGRESDB_PORT": "5432",
                    "DB_POSTGRESDB_DATABASE": "n8n",
                    "DB_POSTGRESDB_USER": "n8n",
                    "DB_POSTGRESDB_PASSWORD": made_up("SIM_N8N_DB_PASSWORD"),
                    "WEBHOOK_URL": "http://n8n:5678/",
                    "GENERIC_TIMEZONE": "Asia/Singapore",
                    "N8N_ENCRYPTION_KEY": made_up("SIM_N8N_ENCRYPTION_KEY"),
                    "N8N_RUNNERS_AUTH_TOKEN": made_up("SIM_RUNNERS_TOKEN"),
                    "WAB_API_URL": "http://gateway:8600",
                    "WAB_NODE_KEY": made_up("SIM_NODE_KEY"),
                    "WAB_START_SECRET": made_up("SIM_START_SECRET"),
                    "NODE_EXTRA_CA_CERTS": "/wab-test-ca/ca.pem",
                    "WAB_REQUEST_TIMEOUT_SECONDS": "30",
                },
                "networks": {"sim": None, "runners": {"aliases": ["n8n-broker"]}},
                "volumes": [{"type": "volume", "source": "slack-ca", "target": "/wab-test-ca"}],
            },
            "n8n-runners": {
                "image": "n8nio/runners:2.42.6@sha256:0",
                "environment": {
                    "N8N_RUNNERS_TASK_BROKER_URI": "http://n8n-broker:5679",
                    "N8N_RUNNERS_AUTH_TOKEN": made_up("SIM_RUNNERS_TOKEN"),
                    "N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT": "15",
                    "GENERIC_TIMEZONE": "Asia/Singapore",
                },
                "networks": {"runners": None},
            },
            "bootstrap": {
                "image": "wab/platform-api:sim",
                "build": {"context": str(check.ROOT / "platform-api"), "target": "runtime"},
                "environment": {
                    **guards,
                    "DATABASE_URL_OWNER": "postgresql://wab_owner:"
                    + made_up("SIM_OWNER_PASSWORD")
                    + "@postgres:5432/platform",
                    "N8N_BASE_URL": "http://n8n:5678",
                    "N8N_OWNER_EMAIL": "owner@simulation.example",
                    "N8N_OWNER_PASSWORD": made_up("SIM_OWNER_LOGIN"),
                    "STEP_KEY": made_up("SIM_STEP_KEY"),
                    "PLATFORM_INTERNAL_URL": "http://gateway:8600",
                },
                "networks": {"sim": None},
            },
            "gateway": {
                "image": "wab/platform-api:sim",
                "command": check.GATEWAY_COMMAND,
                "environment": {
                    "WAB_NODE_KEY": made_up("SIM_NODE_KEY"),
                    "WAB_START_SECRET": made_up("SIM_START_SECRET"),
                    "N8N_BASE_URL": "http://n8n:5678",
                    "N8N_OWNER_EMAIL": "owner@simulation.example",
                    "N8N_OWNER_PASSWORD": made_up("SIM_N8N_OWNER_PASSWORD"),
                    "MOCK_GITHUB_URL": "http://mock-github:8200",
                    "MOCK_SLACK_TOKEN": made_up("SIM_MOCK_SLACK_TOKEN"),
                },
                "networks": {"sim": None, "link": {"aliases": ["simulation-gateway"]}},
            },
            "mock-github": {
                "image": "wab/mock-github:sim",
                "build": {"context": str(check.ROOT / "e2e/mock_github"), "target": "runtime"},
                "networks": {"sim": None},
            },
            "mock-slack": {
                "image": "wab/mock-slack:sim",
                "build": {"context": str(check.ROOT / "e2e/mock_slack"), "target": "runtime"},
                "environment": {"MOCK_SLACK_TOKEN": made_up("SIM_MOCK_SLACK_TOKEN")},
                "networks": {"sim": {"aliases": ["slack.com"]}},
                "volumes": [{"type": "volume", "source": "slack-ca", "target": "/ca"}],
            },
        },
        "networks": {
            "sim": {"name": "simn8n_sim", "internal": True},
            "runners": {"name": "simn8n_runners", "internal": True},
            "link": {"name": "simn8n_link", "internal": True},
        },
        "volumes": {"slack-ca": {"name": "simn8n_slack-ca"}},
    }


def platform_of(sim: dict[str, Any]) -> dict[str, Any]:
    """deploy/compose.yaml as far as the check reads it: the same pins, sources and guards, and
    the platform's own tag on what it builds."""
    services = sim["services"]
    builders = {s["image"]: s for s in services.values() if "build" in s}
    platform: dict[str, Any] = {"services": {}}
    for name, theirs in check.SAME_AS_PLATFORM.items():
        service = {
            "image": services[name]["image"].replace(":sim", ":dev"),
            "environment": {g: services["n8n"]["environment"][g] for g in check.GUARDS},
        }
        built = builders.get(services[name]["image"], services[name])
        if "build" in built:
            service["build"] = dict(built["build"])
        platform["services"][theirs] = service
    return platform


def findings(sim: dict[str, Any]) -> list[str]:
    return check.compose_findings(sim, platform_of(good_sim()))


class ComposeTest(unittest.TestCase):
    def test_the_simulation_as_built_passes(self) -> None:
        self.assertEqual(findings(good_sim()), [])

    def test_the_file_reads_only_its_own_settings(self) -> None:
        text = 'a: ${SIM_NODE_KEY:?run} b: "$$(node -e x)" c: wab/n8n:sim'
        self.assertEqual(check.file_findings(text), [])
        for other in (
            "${N8N_ENCRYPTION_KEY:?x}",
            "$GITHUB_TOKEN",
            "${N8N_KEY_JIRA_TOKEN:-}",
            "${WAB_IMAGE_TAG:-dev}",
        ):
            with self.subTest(other=other):
                self.assertTrue(check.file_findings(text + " " + other))

    def test_a_real_key_on_n8n_fails(self) -> None:
        for name in ("GITHUB_TOKEN", "N8N_KEY_SLACK_TOKEN", "AGENT_MODEL_API_KEY", "HTTPS_PROXY"):
            with self.subTest(name=name):
                sim = good_sim()
                sim["services"]["n8n"]["environment"][name] = made_up("SIM_X")
                self.assertIn(name, " ".join(findings(sim)))

    def test_a_real_key_or_the_platforms_database_on_the_gateway_fails(self) -> None:
        for name in ("DATABASE_URL", "JIRA_API_TOKEN", "TEAMS_WEBHOOK_URL", "AGENT_API_KEY"):
            with self.subTest(name=name):
                sim = good_sim()
                sim["services"]["gateway"]["environment"][name] = made_up("SIM_X")
                self.assertIn(f"gateway holds {name}", " ".join(findings(sim)))

    def test_a_key_not_made_up_for_the_simulation_fails(self) -> None:
        for service, name, value in (
            ("n8n", "N8N_ENCRYPTION_KEY", made_up("N8N_ENCRYPTION_KEY")),
            ("n8n", "WAB_NODE_KEY", "a-key-written-in-the-file"),
            ("n8n-runners", "N8N_RUNNERS_AUTH_TOKEN", made_up("N8N_RUNNERS_AUTH_TOKEN")),
            ("bootstrap", "STEP_KEY", ""),
            ("gateway", "WAB_START_SECRET", made_up("WAB_START_SECRET")),
            ("gateway", "N8N_OWNER_PASSWORD", "a-password-written-in-the-file"),
            ("gateway", "MOCK_SLACK_TOKEN", "mock-slack-token"),
            ("mock-slack", "MOCK_SLACK_TOKEN", "mock-slack-token"),
            (
                "bootstrap",
                "DATABASE_URL_OWNER",
                "postgresql://wab_owner:" + made_up("WAB_OWNER_PASSWORD") + "@postgres/platform",
            ),
        ):
            with self.subTest(name=name):
                sim = good_sim()
                sim["services"][service]["environment"][name] = value
                self.assertIn(f"{service}'s {name}", " ".join(findings(sim)))

    def test_an_address_outside_the_simulation_fails(self) -> None:
        for service, name, value in (
            ("n8n", "WAB_API_URL", "http://platform-api:8000"),
            ("n8n", "DB_POSTGRESDB_HOST", "wab-postgres-1"),
            ("n8n", "WEBHOOK_URL", "https://n8n.example.com/"),
            ("bootstrap", "N8N_BASE_URL", "http://wab-n8n-1:5678"),
            ("n8n-runners", "N8N_RUNNERS_TASK_BROKER_URI", "http://n8n.internal.example:5679"),
            ("gateway", "N8N_BASE_URL", "http://wab-n8n-1:5678"),
            ("gateway", "MOCK_GITHUB_URL", "https://api.github.com"),
        ):
            with self.subTest(name=name):
                sim = good_sim()
                sim["services"][service]["environment"][name] = value
                self.assertIn("outside the simulation's network", " ".join(findings(sim)))

    def test_a_way_out_of_the_network_fails(self) -> None:
        cases = {
            "a network that is not internal": lambda s: s["networks"]["sim"].update(internal=False),
            "another stack's network": lambda s: s["networks"]["sim"].update(external=True),
            "a published port": lambda s: s["services"]["n8n"].update(
                ports=[{"target": 5678, "published": "5678"}]
            ),
            "the host's network": lambda s: s["services"]["mock-github"].update(
                network_mode="host"
            ),
            "a name pointed outside": lambda s: s["services"]["n8n"].update(
                extra_hosts=["mock-github=203.0.113.7"]
            ),
            "n8n on one more network": lambda s: s["services"]["n8n"]["networks"].update(
                default=None
            ),
            "the task runner beside the mocks": lambda s: s["services"]["n8n-runners"][
                "networks"
            ].update(sim=None),
            "the gateway beside the task runner": lambda s: s["services"]["gateway"][
                "networks"
            ].update(runners=None),
            "the gateway's port published": lambda s: s["services"]["gateway"].update(
                ports=[{"target": 8600, "published": "8600"}]
            ),
            "no gateway": lambda s: s["services"].pop("gateway"),
            "another service": lambda s: s["services"].update(
                {"platform-api": {"networks": {"sim": None}}}
            ),
            "another stack's volume": lambda s: s["volumes"]["slack-ca"].update(external=True),
        }
        for label, change in cases.items():
            with self.subTest(label):
                sim = good_sim()
                change(sim)
                self.assertTrue(findings(sim))

    def test_a_mount_outside_its_list_fails(self) -> None:
        for service, volume in (
            ("n8n", {"type": "bind", "source": str(check.ROOT / "deploy/.env"), "target": "/e"}),
            ("bootstrap", {"type": "bind", "source": "/var/run/docker.sock", "target": "/s"}),
            ("postgres", {"type": "volume", "source": "pgdata", "target": "/var/lib/data"}),
        ):
            with self.subTest(service=service):
                sim = good_sim()
                sim["services"][service].setdefault("volumes", []).append(volume)
                self.assertIn(f"{service} mounts", " ".join(findings(sim)))

    def test_n8n_runs_the_platform_image_and_guards(self) -> None:
        sim = good_sim()
        sim["services"]["n8n-runners"]["image"] = "n8nio/runners:latest"
        self.assertIn("n8n-runners runs n8nio/runners:latest", " ".join(findings(sim)))
        for change in (
            lambda s: s["services"]["n8n"].update(image="n8nio/n8n:sim"),
            lambda s: s["services"]["n8n"]["build"].update(dockerfile="other/Dockerfile"),
            lambda s: s["services"]["bootstrap"].pop("build"),
            lambda s: s["services"]["gateway"].update(build={"context": "e2e/mock_github"}),
            lambda s: s["services"]["gateway"].update(image="wab/other:sim"),
            lambda s: s["services"]["gateway"].update(image="wab/platform-api:dev"),
            lambda s: s["services"]["bootstrap"]["build"].update(target="test"),
        ):
            sim = good_sim()
            change(sim)
            self.assertIn("doesn't build the platform's", " ".join(findings(sim)))
        sim = good_sim()
        sim["services"]["n8n"]["environment"]["N8N_RUNNERS_MODE"] = "internal"
        sim["services"]["bootstrap"]["environment"]["N8N_RUNNERS_MODE"] = "internal"
        self.assertIn("N8N_RUNNERS_MODE differ from the platform", " ".join(findings(sim)))
        sim = good_sim()
        sim["services"]["bootstrap"]["environment"]["NODES_EXCLUDE"] = "[]"
        self.assertIn("checks another n8n", " ".join(findings(sim)))

    def test_an_image_built_under_the_platforms_tag_fails(self) -> None:
        for name, image in (
            ("n8n", "wab/n8n:dev"),
            ("bootstrap", "wab/platform-api:dev"),
            ("mock-slack", "wab/mock-slack:dev"),
        ):
            with self.subTest(name=name):
                sim = good_sim()
                sim["services"][name]["image"] = image
                self.assertIn(f"{name} builds {image}, not a sim image", " ".join(findings(sim)))

    def test_only_the_gateway_sits_on_the_link(self) -> None:
        cases = {
            "n8n on the link": lambda s: s["services"]["n8n"]["networks"].update(link=None),
            "postgres on the link": lambda s: s["services"]["postgres"]["networks"].update(
                link=None
            ),
            "a mock on the link": lambda s: s["services"]["mock-github"]["networks"].update(
                link=None
            ),
            "the gateway off the link": lambda s: s["services"]["gateway"]["networks"].pop("link"),
            "a link with a way out": lambda s: s["networks"]["link"].update(internal=False),
            "a link from another stack": lambda s: s["networks"]["link"].update(external=True),
        }
        for label, change in cases.items():
            with self.subTest(label):
                sim = good_sim()
                change(sim)
                self.assertTrue(findings(sim))


def platform_files() -> dict[str, Any]:
    """deploy/compose.yaml as compose renders it, as far as the link check reads it."""
    return {
        "services": {
            "platform-api": {
                "image": "wab/platform-api:dev",
                "environment": {"WAB_NODE_KEY": made_up("WAB_NODE_KEY")},
                "networks": {"default": None},
                "ports": [{"target": 8000, "published": "8000"}],
            },
            "n8n": {"image": "wab/n8n:dev", "networks": {"default": None, "runners": None}},
            "postgres": {"image": "postgres:17", "networks": {"default": None}},
            "agent-runtime": {"image": "wab/agent-runtime:dev", "networks": {"default": None}},
        },
        "networks": {
            "default": {"name": "wab_default"},
            "runners": {"name": "wab_runners", "internal": True},
        },
    }


def linked_files() -> dict[str, Any]:
    """deploy/compose.yaml with deploy/compose.simulation-link.yaml over it."""
    linked = platform_files()
    api = linked["services"]["platform-api"]
    api["networks"]["simulation-link"] = None
    api["environment"] |= {
        "SIMULATION_URL": "http://simulation-gateway:8600",
        "SIMULATION_START_SECRET": made_up("SIMULATION_START_SECRET"),
    }
    linked["networks"]["simulation-link"] = {"name": "simn8n_link", "external": True}
    return linked


def link_findings(linked: dict[str, Any]) -> list[str]:
    return check.link_findings(good_sim(), platform_files(), linked)


class LinkFileTest(unittest.TestCase):
    def test_platform_api_alone_on_the_simulations_link_passes(self) -> None:
        self.assertEqual(link_findings(linked_files()), [])

    def test_another_platform_service_on_the_link_fails(self) -> None:
        for service in ("n8n", "postgres", "agent-runtime"):
            with self.subTest(service=service):
                linked = linked_files()
                linked["services"][service]["networks"]["simulation-link"] = None
                self.assertIn(service, " ".join(link_findings(linked)))

    def test_a_link_that_is_not_the_simulations_fails(self) -> None:
        cases = {
            "a network the platform makes": lambda f: f["networks"]["simulation-link"].pop(
                "external"
            ),
            "another stack's network": lambda f: f["networks"]["simulation-link"].update(
                name="simn8n_sim"
            ),
            "one more network": lambda f: (
                f["networks"].update(other={"name": "x", "external": True}),
                f["services"]["platform-api"]["networks"].update(other=None),
            ),
            "platform-api off the link": lambda f: f["services"]["platform-api"]["networks"].pop(
                "simulation-link"
            ),
        }
        for label, change in cases.items():
            with self.subTest(label):
                linked = linked_files()
                change(linked)
                self.assertTrue(link_findings(linked))

    def test_platform_api_calls_the_gateway_by_its_name_on_the_link(self) -> None:
        for url in (
            "http://n8n:5678",
            "http://platform-api:8000",
            "https://gateway.example.com",
            "",
        ):
            with self.subTest(url=url):
                linked = linked_files()
                linked["services"]["platform-api"]["environment"]["SIMULATION_URL"] = url
                self.assertIn("SIMULATION_URL", " ".join(link_findings(linked)))
        linked = linked_files()
        linked["services"]["platform-api"]["environment"]["SIMULATION_URL"] = "http://gateway:8600"
        self.assertEqual(link_findings(linked), [])

    def test_a_start_secret_written_in_the_file_fails(self) -> None:
        linked = linked_files()
        linked["services"]["platform-api"]["environment"]["SIMULATION_START_SECRET"] = "abc123"
        self.assertIn("SIMULATION_START_SECRET", " ".join(link_findings(linked)))

    def test_the_link_file_changes_platform_api_and_nothing_else(self) -> None:
        cases = {
            "another setting": lambda f: f["services"]["platform-api"]["environment"].update(
                JIRA_API_TOKEN=made_up("JIRA_API_TOKEN")
            ),
            "the model turned on": lambda f: f["services"]["platform-api"]["environment"].update(
                SIMULATION_MODEL="on"
            ),
            "another port": lambda f: f["services"]["platform-api"].update(ports=[]),
            "another service": lambda f: f["services"].update(debug={"image": "busybox"}),
            "n8n changed": lambda f: f["services"]["n8n"].update(image="wab/n8n:other"),
        }
        for label, change in cases.items():
            with self.subTest(label):
                linked = linked_files()
                change(linked)
                self.assertTrue(link_findings(linked))


class RunningTest(unittest.TestCase):
    def secrets(self) -> dict[str, str]:
        env_file = (
            f"N8N_ENCRYPTION_KEY={PLATFORM_KEY}\nN8N_OWNER_EMAIL=owner@example.com\n"
            "GITHUB_TOKEN=\n# STEP_KEY=commented-out-value\nTEAM_TIME_ZONE=Asia/Singapore\n"
        )
        environ = {"SIM_NODE_KEY": SIM_KEY, "GITHUB_TOKEN": "gh" + "x" * 20, "PATH": "/bin:/usr"}
        return check.secret_values(env_file, environ)

    def test_the_platform_keys_are_its_own_and_never_the_simulations(self) -> None:
        self.assertEqual(sorted(self.secrets()), ["GITHUB_TOKEN", "N8N_ENCRYPTION_KEY"])

    def test_a_platform_key_in_a_container_is_named_but_not_shown(self) -> None:
        held = {"DATABASE_URL_OWNER": f"postgresql://wab_owner:{PLATFORM_KEY}@postgres/platform"}
        found = check.held_findings("simn8n-bootstrap-1", held, self.secrets())
        self.assertEqual(
            found,
            ["simn8n-bootstrap-1 holds the platform's N8N_ENCRYPTION_KEY in DATABASE_URL_OWNER"],
        )
        self.assertNotIn(PLATFORM_KEY, " ".join(found))
        self.assertEqual(check.held_findings("n8n", {"WAB_NODE_KEY": SIM_KEY}, self.secrets()), [])

    def test_only_mock_keys_pass(self) -> None:
        hosts = check.sim_hosts(good_sim())
        mock = [
            {
                "name": "GitHub",
                "type": "githubApi",
                "data": {"server": "http://mock-github:8200", "accessToken": SIM_KEY},
            },
            {
                "name": "Jira",
                "type": "jiraSoftwareServerPatApi",
                "data": {"domain": "http://gateway:8600", "personalAccessToken": SIM_KEY},
            },
            {
                "name": "Slack",
                "type": "slackApi",
                "data": {"accessToken": "mock-slack-token", "allowedHttpRequestDomains": "all"},
            },
        ]
        self.assertEqual(check.credential_findings(mock, self.secrets(), hosts), [])

    def test_a_real_key_in_n8n_fails(self) -> None:
        hosts = check.sim_hosts(good_sim())
        for data, said in (
            ({"server": "https://api.github.com", "accessToken": SIM_KEY}, "api.github.com"),
            ({"domain": "jira.example.com", "token": SIM_KEY}, "jira.example.com"),
            (
                {"server": "http://mock-github:8200", "accessToken": PLATFORM_KEY},
                "N8N_ENCRYPTION_KEY",
            ),
            ({"headers": [{"value": f"Bearer {PLATFORM_KEY}"}]}, "N8N_ENCRYPTION_KEY"),
        ):
            with self.subTest(said=said):
                key = [{"name": "Real", "type": "githubApi", "data": data}]
                found = " ".join(check.credential_findings(key, self.secrets(), hosts))
                self.assertIn(said, found)
                self.assertNotIn(PLATFORM_KEY, found)

    def test_a_route_out_fails_and_a_mock_out_of_reach_fails(self) -> None:
        for service, (out_of_reach, in_reach) in check.ROUTES.items():
            with self.subTest(service=service):
                reached = {url: (False, "ENOTFOUND") for url in out_of_reach}
                reached |= {url: (True, "answered 200") for url in in_reach}
                self.assertEqual(check.route_findings(service, reached), [])
                out = dict(reached, **{"https://api.github.com/": (True, "answered 200")})
                self.assertIn(
                    f"{service} reaches https://api.github.com/",
                    " ".join(check.route_findings(service, out)),
                )
                blind = dict(reached, **{in_reach[0]: (False, "ENOTFOUND")})
                self.assertIn("sees no route", " ".join(check.route_findings(service, blind)))

    def test_n8n_must_reach_the_gateway_and_the_gateway_only_the_simulation(self) -> None:
        n8n_out, n8n_in = check.ROUTES["n8n"]
        gateway_out, gateway_in = check.ROUTES["gateway"]
        self.assertIn("http://gateway:8600/healthz", n8n_in)
        self.assertIn("http://n8n:5678/healthz", gateway_in)
        self.assertIn("http://platform-api:8000/healthz", n8n_out)
        for out in (n8n_out, gateway_out):
            self.assertIn("https://api.github.com/", out)
            self.assertIn("http://host.docker.internal/", out)
        # The gateway shares the link with platform-api, so platform-api's own name may answer it.
        # The linked platform's other services are checked by address (platform_probes).
        self.assertFalse([url for url in gateway_out if "platform-api" in url])

    def containers(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        def container(cid: str, service: str, env: list[str], networks: list[str]) -> dict:
            return {
                "Id": cid,
                "Name": f"/simn8n-{service}-1",
                "Image": f"sha256:{service}",
                "Config": {"Labels": {"com.docker.compose.service": service}, "Env": env},
                "HostConfig": {"NetworkMode": networks[0], "PortBindings": {}},
                "NetworkSettings": {"Networks": {n: {} for n in networks}},
            }

        containers = [
            container(
                "c1",
                "n8n",
                ["PATH=/bin", f"WAB_NODE_KEY={SIM_KEY}"],
                ["simn8n_sim", "simn8n_runners"],
            ),
            container("c2", "mock-github", ["PATH=/bin"], ["simn8n_sim"]),
        ]
        networks = [
            {"Name": "simn8n_sim", "Internal": True, "Containers": {"c1": {}, "c2": {}}},
            {"Name": "simn8n_runners", "Internal": True, "Containers": {"c1": {}}},
        ]
        return containers, networks

    def container_findings(self, change: Any = None) -> list[str]:
        containers, networks = self.containers()
        if change:
            change(containers, networks)
        image_env = {"sha256:n8n": {"PATH"}, "sha256:mock-github": {"PATH"}}
        return check.container_findings(containers, networks, image_env, self.secrets())

    def test_the_running_stack_as_built_passes(self) -> None:
        self.assertEqual(self.container_findings(), [])

    def test_a_way_out_or_a_stranger_in_the_running_stack_fails(self) -> None:
        cases = {
            "a container from another project": lambda c, n: n[0]["Containers"].update(x={}),
            "a network that is not internal": lambda c, n: n[0].update(Internal=False),
            "n8n also on the bridge": lambda c, n: c[0]["NetworkSettings"]["Networks"].update(
                bridge={}
            ),
            "the host's network": lambda c, n: c[1]["HostConfig"].update(NetworkMode="host"),
            "a published port": lambda c, n: c[0]["HostConfig"].update(
                PortBindings={"5678/tcp": [{"HostPort": "5678"}]}
            ),
            "a setting not on the list": lambda c, n: c[0]["Config"]["Env"].append(
                "GITHUB_TOKEN=x"
            ),
            "a platform key": lambda c, n: c[1]["Config"]["Env"].append(f"X={PLATFORM_KEY}"),
            "a service not on the list": lambda c, n: c[1]["Config"]["Labels"].update(
                {"com.docker.compose.service": "platform-api"}
            ),
        }
        for label, change in cases.items():
            with self.subTest(label):
                found = self.container_findings(change)
                self.assertTrue(found)
                self.assertNotIn(PLATFORM_KEY, " ".join(found))


START_SECRET = "ss" + "5c8e0a" * 8
"""The simulation's start secret, as deploy/make-env.sh makes it for a laptop or a CI run."""


def platform_container(cid: str, service: str, project: str, addresses: dict[str, str]) -> dict:
    return {
        "Id": cid,
        "Name": f"/{project}-{service}-1",
        "Config": {
            "Labels": {
                "com.docker.compose.service": service,
                "com.docker.compose.project": project,
            }
        },
        "State": {"Running": True},
        "NetworkSettings": {
            "Networks": {name: {"IPAddress": ip} for name, ip in addresses.items()}
        },
    }


def linked_platform() -> dict[str, dict]:
    """A platform linked to the simulation: platform-api on its own network and the link."""
    return {
        "platform-api": platform_container(
            "p1", "platform-api", "wab", {"wab_default": "172.20.0.5", "simn8n_link": "172.30.0.3"}
        ),
        "postgres": platform_container("p2", "postgres", "wab", {"wab_default": "172.20.0.2"}),
        "n8n": platform_container(
            "p3", "n8n", "wab", {"wab_default": "172.20.0.3", "wab_runners": "172.21.0.2"}
        ),
        "agent-runtime": platform_container(
            "p4", "agent-runtime", "wab", {"wab_default": "172.20.0.4"}
        ),
    }


def simulation_running() -> dict[str, dict]:
    return {
        "n8n": platform_container(
            "s1", "n8n", "simn8n", {"simn8n_sim": "172.40.0.4", "simn8n_runners": "172.41.0.2"}
        ),
        "gateway": platform_container(
            "s2", "gateway", "simn8n", {"simn8n_sim": "172.40.0.5", "simn8n_link": "172.30.0.2"}
        ),
        "postgres": platform_container("s3", "postgres", "simn8n", {"simn8n_sim": "172.40.0.2"}),
    }


class LinkedTest(unittest.TestCase):
    def secrets(self) -> dict[str, str]:
        env_file = f"N8N_ENCRYPTION_KEY={PLATFORM_KEY}\nSIMULATION_START_SECRET={START_SECRET}\n"
        return check.secret_values(env_file, {})

    def test_the_start_secret_is_shared_only_as_the_start_secret(self) -> None:
        secrets = self.secrets()
        for service in ("n8n", "gateway"):
            held = {"WAB_START_SECRET": START_SECRET}
            self.assertEqual(check.held_findings(service, held, secrets, service=service), [])
        for service, name, value in (
            ("mock-slack", "WAB_START_SECRET", START_SECRET),
            ("n8n", "WAB_NODE_KEY", START_SECRET),
            ("gateway", "N8N_OWNER_PASSWORD", START_SECRET),
            ("gateway", "WAB_START_SECRET", START_SECRET + "x"),
        ):
            with self.subTest(service=service, name=name):
                found = check.held_findings(service, {name: value}, secrets, service=service)
                self.assertEqual(
                    found, [f"{service} holds the platform's SIMULATION_START_SECRET in {name}"]
                )

    def test_n8n_never_holds_the_start_secret_as_a_key(self) -> None:
        hosts = check.sim_hosts(good_sim())
        key = [{"name": "Hook", "type": "httpHeaderAuth", "data": {"value": START_SECRET}}]
        found = check.credential_findings(key, self.secrets(), hosts)
        self.assertIn("SIMULATION_START_SECRET", " ".join(found))
        self.assertNotIn(START_SECRET, " ".join(found))

    def link_findings(self, change: Any = None, platform: str | None = "wab") -> list[str]:
        sim = simulation_running()
        gateway = dict(sim["gateway"], Image="sha256:gateway", HostConfig={"PortBindings": {}})
        gateway["HostConfig"]["NetworkMode"] = "simn8n_sim"
        gateway["Config"] = dict(gateway["Config"], Env=["PATH=/bin"])
        networks = [
            {"Name": "simn8n_sim", "Internal": True, "Containers": {"s2": {}}},
            {
                "Name": "simn8n_link",
                "Internal": True,
                "Labels": {"com.docker.compose.network": "link"},
                "Containers": {"s2": {}, "p1": {}},
            },
        ]
        strangers = {"p1": linked_platform()["platform-api"]}
        if change:
            change(networks, strangers)
        return check.container_findings(
            [gateway],
            networks,
            {"sha256:gateway": {"PATH"}},
            self.secrets(),
            strangers=strangers,
            platform=platform,
        )

    def test_platform_api_alone_beside_the_gateway_on_the_link_passes(self) -> None:
        self.assertEqual(self.link_findings(), [])
        self.assertEqual(self.link_findings(platform=None), [])

    def test_anything_else_on_the_link_fails(self) -> None:
        def stranger(service: str, project: str = "wab") -> Any:
            def change(networks: list[dict], strangers: dict[str, dict]) -> None:
                networks[1]["Containers"]["p9"] = {}
                strangers["p9"] = platform_container("p9", service, project, {})

            return change

        cases = {
            "the platform's n8n": stranger("n8n"),
            "the platform's postgres": stranger("postgres"),
            "the platform's agent-runtime": stranger("agent-runtime"),
            "another stack's platform-api": stranger("platform-api", "wab-e2e"),
            "a container compose didn't start": stranger(""),
            "a stranger on the simulation's own network": lambda n, s: n[0]["Containers"].update(
                p1={}
            ),
            "a link with a way out": lambda n, s: n[1].update(Internal=False),
        }
        for label, change in cases.items():
            with self.subTest(label):
                self.assertTrue(self.link_findings(change))

    def test_a_linked_platform_is_whole_and_on_the_link(self) -> None:
        self.assertEqual(
            check.linked_platform_findings("wab", linked_platform(), "simn8n_link"), []
        )
        missing = linked_platform()
        missing.pop("agent-runtime")
        self.assertIn(
            "agent-runtime",
            " ".join(check.linked_platform_findings("wab", missing, "simn8n_link")),
        )
        unlinked = linked_platform()
        unlinked["platform-api"]["NetworkSettings"]["Networks"].pop("simn8n_link")
        self.assertIn(
            "not on the link",
            " ".join(check.linked_platform_findings("wab", unlinked, "simn8n_link")),
        )

    def probes(self) -> list[Any]:
        return check.platform_probes(simulation_running(), linked_platform())

    def test_each_platform_address_is_probed_from_the_simulation(self) -> None:
        kept = {(p.origin, p.host, p.port) for p in self.probes() if not p.reach}
        for host, port in (
            ("172.20.0.5", 8000),
            ("172.30.0.3", 8000),
            ("172.20.0.2", 5432),
            ("172.20.0.3", 5678),
            ("172.21.0.2", 5678),
            ("172.20.0.4", 8100),
        ):
            with self.subTest(host=host):
                self.assertIn(("n8n", host, port), kept)
        for host, port in (
            ("172.20.0.2", 5432),
            ("172.20.0.3", 5678),
            ("172.21.0.2", 5678),
            ("172.20.0.4", 8100),
        ):
            with self.subTest(host=host):
                self.assertIn(("gateway", host, port), kept)
        self.assertFalse([p for p in kept if p[0] == "gateway" and p[2] == 8000])
        for origin in ("the platform's n8n", "the platform's agent-runtime"):
            for host in ("172.40.0.5", "172.30.0.2"):
                self.assertIn((origin, host, 8600), kept)

    def test_each_probe_has_a_route_it_must_see(self) -> None:
        seen = {(p.origin, p.host, p.port) for p in self.probes() if p.reach}
        self.assertEqual(
            seen,
            {
                ("n8n", "172.40.0.2", 5432),
                ("gateway", "172.40.0.2", 5432),
                ("the platform's platform-api", "simulation-gateway", 8600),
                ("the platform's n8n", "172.20.0.2", 5432),
                ("the platform's agent-runtime", "172.20.0.2", 5432),
            },
        )

    def test_a_route_across_fails_and_a_blind_probe_fails(self) -> None:
        probes = self.probes()
        answered = [(p, p.reach, "connected" if p.reach else "ENETUNREACH") for p in probes]
        self.assertEqual(check.probe_findings(answered), [])
        across = [
            (p, True, "connected") if p.port == 5432 and not p.reach else (p, ok, how)
            for p, ok, how in answered
        ]
        found = " ".join(check.probe_findings(across))
        self.assertIn("n8n reaches the platform's postgres at 172.20.0.2:5432", found)
        self.assertIn("gateway reaches the platform's postgres", found)
        blind = [(p, False, "ENETUNREACH") if p.reach else (p, ok, how) for p, ok, how in answered]
        self.assertIn("sees no route", " ".join(check.probe_findings(blind)))


if __name__ == "__main__":
    unittest.main()
