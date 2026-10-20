from collections.abc import Iterator

import pytest
from harness import PLATFORM_API_URL, Api, MockGithub


@pytest.fixture(scope="session")
def api() -> Iterator[Api]:
    client = Api(PLATFORM_API_URL)
    yield client
    client.client.close()


@pytest.fixture(autouse=True)
def github() -> Iterator[MockGithub]:
    mock = MockGithub()
    mock.set_mode("ok")
    yield mock
    mock.set_mode("ok")
