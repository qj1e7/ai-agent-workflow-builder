import pytest

from platform_api.auth import ConfigError
from platform_api.settings import CosmosSettings, settings_from_env
from tests.support import LOCAL_ENV

COSMOS = {"COSMOS_ENDPOINT": "http://cosmos:8081", "COSMOS_KEY": "a2V5"}


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


def test_teams_stays_the_practice_copy_until_a_webhook_is_set():
    settings = settings_from_env(LOCAL_ENV)
    assert (settings.teams_channel, settings.teams_webhook_url) == ("CODESparks Ops", None)


def test_a_teams_webhook_and_channel_name_come_from_the_environment():
    hook = "https://prod.example.logic.azure.com/workflows/abc/triggers/manual/run?sig=x"
    settings = settings_from_env(
        {**LOCAL_ENV, "TEAMS_WEBHOOK_URL": hook, "TEAMS_CHANNEL": "CODESparks Support"}
    )
    assert (settings.teams_channel, settings.teams_webhook_url) == ("CODESparks Support", hook)


@pytest.mark.parametrize("hook", ["http://hook.example/run?sig=x", "hook.example", "https://"])
def test_a_teams_webhook_that_is_not_https_refuses_to_start(hook: str):
    with pytest.raises(ConfigError, match="TEAMS_WEBHOOK_URL must be the https:// address"):
        settings_from_env({**LOCAL_ENV, "TEAMS_WEBHOOK_URL": hook})
