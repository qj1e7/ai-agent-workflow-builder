import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

type Resolver = Callable[[str], Iterable[str]]


def resolve(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]


@dataclass(frozen=True)
class AddressRefused:
    reason: Literal["address_not_allowed", "unreachable"]
    message: str


class AddressRefusedError(Exception):
    def __init__(self, refused: AddressRefused) -> None:
        super().__init__(refused.message)
        self.refused = refused


# Where the runtime may send a model's key and prompts (ADR 0022). A host the deployment lists may
# be private or plain http, for example Ollama on a developer's machine or a model inside DevNet.
@dataclass(frozen=True)
class AddressPolicy:
    listed_hosts: frozenset[str] = frozenset()
    resolver: Resolver = resolve

    def check(self, base_url: str) -> AddressRefused | None:
        parts = urlsplit(base_url)
        host = (parts.hostname or "").lower()
        if not host or parts.username or parts.password or parts.query or parts.fragment:
            return AddressRefused(
                "address_not_allowed",
                "Use a plain address such as https://api.example.com/v1, with no user name, "
                "password or query.",
            )
        listed = host in self.listed_hosts
        if parts.scheme != "https" and not (parts.scheme == "http" and listed):
            return AddressRefused(
                "address_not_allowed",
                "Use an address that starts with https://. Plain http is allowed only for "
                "addresses the deployment lists.",
            )
        if listed:
            return None
        checked = self._resolve(host)
        return checked if isinstance(checked, AddressRefused) else None

    def pin(self, host: str) -> str | None:
        """The checked IP to connect to for host, or None for a listed host, which needs no pin.

        Run at connect time, so a name that answers differently after check() cannot reach an
        inside address, and neither can a redirect.
        """
        name = host.lower()
        if name in self.listed_hosts:
            return None
        checked = self._resolve(name)
        if isinstance(checked, AddressRefused):
            raise AddressRefusedError(checked)
        return checked[0]

    def _resolve(self, host: str) -> list[str] | AddressRefused:
        try:
            answers = list(self.resolver(host))
        except OSError:
            return AddressRefused("unreachable", f"Nobody answers for {host}. Check the address.")
        if not answers or any(_inside_a_network(answer) for answer in answers):
            return AddressRefused(
                "address_not_allowed",
                f"{host} is inside a private network, and the deployment does not list it. "
                "Ask the team to add it.",
            )
        return answers


def _inside_a_network(answer: str) -> bool:
    ip = ipaddress.ip_address(answer.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast
