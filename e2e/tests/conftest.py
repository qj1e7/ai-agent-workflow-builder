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


@pytest.fixture
def mock_model(api: Api) -> Iterator[None]:
    """The mock model is the team's model for one test, and off again after it, so the other
    tests run as they did before agent cards."""
    api.connect_mock_model()
    yield
    api.turn_model_off()
