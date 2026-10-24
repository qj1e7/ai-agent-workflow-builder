from collections.abc import Iterable

import pytest

from agent_runtime.addresses import AddressPolicy, AddressRefused


def resolving_to(*addresses: str):
    def resolve(host: str) -> Iterable[str]:
        return addresses

    return resolve


def unresolvable(host: str) -> Iterable[str]:
    raise OSError("no such host")


PUBLIC = resolving_to("8.8.8.8")


def test_a_public_https_address_is_allowed():
    assert AddressPolicy(resolver=PUBLIC).check("https://llm-gateway.example/v1") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://llm-gateway.example",
        "ftp://llm-gateway.example",
        "https://user:pass@llm-gateway.example",
        "https://llm-gateway.example/v1?key=abc",
        "https://llm-gateway.example/v1#part",
        "llm-gateway.example",
        "",
    ],
)
def test_anything_but_a_plain_https_address_is_refused(url: str):
    refused = AddressPolicy(resolver=PUBLIC).check(url)
    assert isinstance(refused, AddressRefused)
    assert refused.reason == "address_not_allowed"


@pytest.mark.parametrize(
    "resolved",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.20",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:10.0.0.1",
        "224.0.0.1",
    ],
)
def test_an_address_inside_a_private_network_is_refused(resolved: str):
    refused = AddressPolicy(resolver=resolving_to(resolved)).check("https://sneaky.example")
    assert isinstance(refused, AddressRefused)
    assert refused.reason == "address_not_allowed"
    assert "sneaky.example" in refused.message


def test_one_private_answer_among_public_ones_is_enough_to_refuse():
    policy = AddressPolicy(resolver=resolving_to("8.8.8.8", "10.0.0.5"))
    assert isinstance(policy.check("https://mixed.example"), AddressRefused)


def test_a_listed_host_may_be_private_and_plain_http():
    policy = AddressPolicy(
        listed_hosts=frozenset({"host.docker.internal"}), resolver=resolving_to("192.168.65.254")
    )
    assert policy.check("http://host.docker.internal:11434/v1") is None
    assert policy.check("https://HOST.docker.internal/v1") is None


def test_listing_a_host_does_not_allow_other_hosts():
    policy = AddressPolicy(listed_hosts=frozenset({"ollama.internal"}), resolver=PUBLIC)
    refused = policy.check("http://other.example")
    assert isinstance(refused, AddressRefused)


def test_a_host_nobody_answers_for_is_unreachable():
    refused = AddressPolicy(resolver=unresolvable).check("https://nowhere.example")
    assert isinstance(refused, AddressRefused)
    assert refused.reason == "unreachable"
