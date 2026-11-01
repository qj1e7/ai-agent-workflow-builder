import re

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


def test_practice_systems_are_on_and_the_watchlist_writes_to_mock_by_default():
    settings = settings_from_env(LOCAL_ENV)
    assert settings.practice_systems is True
    assert settings.watchlist_jira_project == "MOCK"


@pytest.mark.parametrize(
    ("raw", "on"), [("on", True), ("off", False), (" OFF ", False), ("", True)]
)
def test_practice_systems_take_on_or_off(raw: str, on: bool):
    env = {**LOCAL_ENV, **REAL_JIRA, "PRACTICE_SYSTEMS": raw}
    assert settings_from_env(env).practice_systems is on


def test_practice_systems_refuse_any_other_word():
    with pytest.raises(ConfigError, match="PRACTICE_SYSTEMS takes on or off"):
        settings_from_env({**LOCAL_ENV, "PRACTICE_SYSTEMS": "yes"})


@pytest.mark.parametrize("project", ["OPS", "AB_1", "A", "A" + "B" * 254])
def test_the_watchlist_project_takes_any_jira_project_key(project: str):
    settings = settings_from_env({**LOCAL_ENV, "WATCHLIST_JIRA_PROJECT": project})
    assert settings.watchlist_jira_project == project


@pytest.mark.parametrize("project", ["ops", "1AB", "_AB", "AB-1", "A B", "A" + "B" * 255])
def test_the_watchlist_project_refuses_what_jira_would(project: str):
    with pytest.raises(ConfigError, match="WATCHLIST_JIRA_PROJECT"):
        settings_from_env({**LOCAL_ENV, "WATCHLIST_JIRA_PROJECT": project})


REAL_JIRA = {"JIRA_BASE_URL": "https://jira.example.com/", "JIRA_API_TOKEN": "pat-123"}


def test_without_a_jira_address_the_platform_uses_the_practice_jira():
    jira = settings_from_env(LOCAL_ENV).jira
    assert jira.practice and jira.base_url is None
    assert (jira.flavor, jira.issue_type) == ("datacenter", "Task")
    assert jira.browse_url == "/jira/{key}"


def test_a_data_center_jira_needs_only_its_address_and_a_token():
    jira = settings_from_env({**LOCAL_ENV, **REAL_JIRA}).jira
    assert not jira.practice
    assert (jira.base_url, jira.flavor, jira.token) == (
        "https://jira.example.com",
        "datacenter",
        "pat-123",
    )
    assert jira.browse_url == "https://jira.example.com/browse/{key}"


def test_a_cloud_jira_takes_an_email_an_issue_type_and_a_browse_address():
    env = {
        **LOCAL_ENV,
        **REAL_JIRA,
        "JIRA_API_FLAVOR": "cloud",
        "JIRA_EMAIL": "bot@example.com",
        "JIRA_ISSUE_TYPE": "Story",
        "JIRA_BROWSE_URL": "https://jira.example.com/jira/browse/{key}",
    }
    jira = settings_from_env(env).jira
    assert (jira.flavor, jira.email, jira.issue_type) == ("cloud", "bot@example.com", "Story")
    assert jira.browse_url == "https://jira.example.com/jira/browse/{key}"


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        pytest.param({"JIRA_API_FLAVOR": "server"}, "datacenter or cloud", id="unknown flavor"),
        pytest.param(
            {"JIRA_BASE_URL": "https://jira.example.com"}, "JIRA_API_TOKEN", id="no token"
        ),
        pytest.param({**REAL_JIRA, "JIRA_BASE_URL": "http://jira.example.com"}, "https", id="http"),
        pytest.param(
            {**REAL_JIRA, "JIRA_BASE_URL": "https://jira.example.com/?a=1"}, "query", id="query"
        ),
        pytest.param({**REAL_JIRA, "JIRA_API_FLAVOR": "cloud"}, "JIRA_EMAIL", id="cloud no email"),
        pytest.param(
            {**REAL_JIRA, "JIRA_BROWSE_URL": "https://j.example.com/"}, "{key}", id="no key"
        ),
        pytest.param({**REAL_JIRA, "JIRA_ISSUE_TYPE": " "}, "JIRA_ISSUE_TYPE", id="blank type"),
        pytest.param({"PRACTICE_SYSTEMS": "off"}, "JIRA_BASE_URL", id="no Jira at all"),
    ],
)
def test_jira_settings_that_cannot_work_refuse_to_start(env: dict[str, str], reason: str):
    with pytest.raises(ConfigError, match=re.escape(reason)):
        settings_from_env({**LOCAL_ENV, **env})


def test_a_real_jira_with_practice_systems_off_starts():
    settings = settings_from_env({**LOCAL_ENV, **REAL_JIRA, "PRACTICE_SYSTEMS": "off"})
    assert not settings.practice_systems and not settings.jira.practice
