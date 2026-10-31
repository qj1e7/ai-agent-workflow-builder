"""Tries the internet from inside one container of the locked stack, through the proxy and around it.

Run inside a container that has httpx: docker compose ... exec -T agent-runtime python - < lockdown-probe.py
"""

import os
import socket

import httpx

THROUGH_THE_PROXY = [
    ("https://api.github.com/zen", "on the allow list"),
    ("https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration", "on the allow list"),
    ("https://llm-gateway.aisg.sg/", "on the allow list"),
    ("https://api.openai.com/v1/models", "off the list"),
    ("https://pypi.org/simple/", "off the list"),
    ("https://registry.npmjs.org/", "off the list"),
    ("https://example.com/", "off the list"),
    ("http://example.com/", "off the list, plain http"),
]

print(f"container {socket.gethostname()}, HTTPS_PROXY={os.environ.get('HTTPS_PROXY')}")
for url, note in THROUGH_THE_PROXY:
    try:
        answer = httpx.get(url, timeout=15)
        refused = " (the proxy's refusal page)" if answer.headers.get("server", "").startswith("squid") else ""
        print(f"through the proxy, {note}: {url} -> HTTP {answer.status_code}{refused}")
    except httpx.ProxyError as error:
        print(f"through the proxy, {note}: {url} -> refused by the proxy: {error}")
    except httpx.HTTPError as error:
        print(f"through the proxy, {note}: {url} -> {type(error).__name__}: {error}")

try:
    answer = httpx.get("https://api.github.com/zen", timeout=10, trust_env=False)
    print(f"around the proxy: https://api.github.com/zen -> HTTP {answer.status_code}")
except httpx.HTTPError as error:
    print(f"around the proxy: https://api.github.com/zen -> {type(error).__name__}: {error}")

try:
    print(f"name lookup of api.github.com -> {socket.getaddrinfo('api.github.com', 443)[0][4][0]}")
except OSError as error:
    print(f"name lookup of api.github.com -> {type(error).__name__}: {error}")

for address in ("1.1.1.1", "140.82.112.6"):
    with socket.socket() as raw:
        raw.settimeout(5)
        try:
            raw.connect((address, 443))
            print(f"TCP straight to {address}:443 -> connected")
        except OSError as error:
            print(f"TCP straight to {address}:443 -> {type(error).__name__}: {error}")
