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
        return None


def _inside_a_network(answer: str) -> bool:
    ip = ipaddress.ip_address(answer.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast
