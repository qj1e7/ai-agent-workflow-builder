import pytest

from platform_api.auth import ConfigError
from platform_api.settings import (
    CosmosSettings,
    bootstrap_settings_from_env,
    settings_from_env,
)
from tests.support import LOCAL_ENV

COSMOS = {"COSMOS_ENDPOINT": "http://cosmos:8081", "COSMOS_KEY": "a2V5"}
BOOTSTRAP = {
    "DATABASE_URL_OWNER": "postgresql://wab_owner:x@localhost/platform",
    "N8N_BASE_URL": "http://n8n:5678",
    "N8N_OWNER_EMAIL": "owner@example.com",
    "N8N_OWNER_PASSWORD": "pw",
    "STEP_KEY": "k",
    "PLATFORM_INTERNAL_URL": "http://platform-api:8000",
}


def test_readers_use_postgresql_and_nothing_is_copied_without_cosmos_db():
    settings = settings_from_env(LOCAL_ENV)
    assert (settings.activity_reader, settings.cosmos) == ("postgres", None)


def test_cosmos_db_settings_copy_the_log_while_readers_stay_on_postgresql():
    settings = settings_from_env({**LOCAL_ENV, **COSMOS})
    assert settings.activity_reader == "postgres"
    assert settings.cosmos == CosmosSettings(endpoint="http://cosmos:8081", key="a2V5")


def test_activity_reader_cosmos_moves_the_readers():
    settings = settings_from_env({**LOCAL_ENV, **COSMOS, "ACTIVITY_READER": "cosmos"})
    assert settings.activity_reader == "cosmos"


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        pytest.param({"ACTIVITY_READER": "cosmos"}, "COSMOS_ENDPOINT", id="cosmos without one"),
        pytest.param({"ACTIVITY_READER": "mongo"}, "postgres or cosmos", id="unknown reader"),
        pytest.param({"COSMOS_ENDPOINT": "http://cosmos:8081"}, "COSMOS_KEY", id="no key"),
        pytest.param({"COSMOS_KEY": "a2V5"}, "COSMOS_ENDPOINT", id="key without endpoint"),
    ],
)
def test_bad_activity_settings_refuse_to_start(env: dict[str, str], reason: str):
    with pytest.raises(ConfigError, match=reason):
        settings_from_env({**LOCAL_ENV, **env})


def test_bootstrap_reads_the_cosmos_db_account_when_one_is_set():
    assert bootstrap_settings_from_env(BOOTSTRAP).cosmos is None
    settings = bootstrap_settings_from_env({**BOOTSTRAP, **COSMOS})
    assert settings.cosmos == CosmosSettings(endpoint="http://cosmos:8081", key="a2V5")
