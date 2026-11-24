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
                "build": {"context": str(check.ROOT / "platform-api"), "target": "runtime"},
                "command": check.GATEWAY_COMMAND,
                "environment": {
                    "WAB_NODE_KEY": made_up("SIM_NODE_KEY"),
                    "WAB_START_SECRET": made_up("SIM_START_SECRET"),
                    "N8N_BASE_URL": "http://n8n:5678",
                    "N8N_OWNER_EMAIL": "owner@simulation.example",
                    "N8N_OWNER_PASSWORD": made_up("SIM_N8N_OWNER_PASSWORD"),
                    "MOCK_GITHUB_URL": "http://mock-github:8200",
                },
                "networks": {"sim": None},
            },
            "mock-github": {
                "image": "wab/mock-github:sim",
                "build": {"context": str(check.ROOT / "e2e/mock_github"), "target": "runtime"},
                "networks": {"sim": None},
            },
            "mock-slack": {
                "image": "wab/mock-slack:sim",
                "build": {"context": str(check.ROOT / "e2e/mock_slack"), "target": "runtime"},
                "networks": {"sim": {"aliases": ["slack.com"]}},
                "volumes": [{"type": "volume", "source": "slack-ca", "target": "/ca"}],
            },
        },
        "networks": {
            "sim": {"name": "simn8n_sim", "internal": True},
            "runners": {"name": "simn8n_runners", "internal": True},
        },
        "volumes": {"slack-ca": {"name": "simn8n_slack-ca"}},
    }


def platform_of(sim: dict[str, Any]) -> dict[str, Any]:
    """deploy/compose.yaml as far as the check reads it: the same pins, sources and guards, and
    the platform's own tag on what it builds."""
    services = sim["services"]
    platform: dict[str, Any] = {"services": {}}
    for name, theirs in check.SAME_AS_PLATFORM.items():
        service = {
            "image": services[name]["image"].replace(":sim", ":dev"),
            "environment": {g: services["n8n"]["environment"][g] for g in check.GUARDS},
        }
        if "build" in services[name]:
            service["build"] = dict(services[name]["build"])
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
            lambda s: s["services"]["gateway"]["build"].update(context="e2e/mock_github"),
            lambda s: s["services"]["gateway"].update(image="wab/other:sim"),
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
            ("gateway", "wab/platform-api:dev"),
        ):
            with self.subTest(name=name):
                sim = good_sim()
                sim["services"][name]["image"] = image
                self.assertIn(f"{name} builds {image}, not a sim image", " ".join(findings(sim)))


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
        for out in (n8n_out, gateway_out):
            self.assertIn("http://platform-api:8000/healthz", out)
            self.assertIn("https://api.github.com/", out)

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


if __name__ == "__main__":
    unittest.main()
