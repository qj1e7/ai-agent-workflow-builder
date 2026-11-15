import os
from collections.abc import Iterator

import pytest
from harness import PLATFORM_API_URL, Api, MockGithub

SEEDED = os.environ.get("E2E_SEED") == "old-engine"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "old_engine: needs the stack started from the old-engine seed"
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """A stack started from the old-engine seed runs only the move's test, and no other stack
    runs it."""
    for item in items:
        if (item.get_closest_marker("old_engine") is not None) != SEEDED:
            item.add_marker(pytest.mark.skip(reason="runs only on the other kind of stack"))


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


@pytest.fixture
def mock_model(api: Api) -> Iterator[None]:
    """The mock model is the team's model for one test, and off again after it, so the other
    tests run as they did before agent cards."""
    api.connect_mock_model()
    yield
    api.turn_model_off()
