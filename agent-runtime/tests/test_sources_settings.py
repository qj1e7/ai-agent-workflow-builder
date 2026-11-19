import pytest

from agent_runtime.api import Settings, SettingsError, build_runtime
from tests.test_api import BASE_ENV


def test_every_source_defaults_to_its_public_address_and_nvd_needs_no_key():
    sources = Settings.from_env(BASE_ENV).sources
    assert (sources.maven_base, sources.npm_base) == (
        "https://repo1.maven.org/maven2",
        "https://registry.npmjs.org",
    )
    assert (sources.osv_base, sources.nvd_base) == (
        "https://api.osv.dev",
        "https://services.nvd.nist.gov",
    )
    assert sources.nvd_api_key is None


def test_a_mirror_and_a_key_can_be_set_and_the_key_never_shows_in_a_repr():
    env = {
        **BASE_ENV,
        "MAVEN_REPO_BASE": "https://mirror.internal/maven2",
        "NVD_API_KEY": "nvd-key-1234\n",
    }
    sources = Settings.from_env(env).sources
    assert sources.maven_base == "https://mirror.internal/maven2"
    assert sources.nvd_api_key == "nvd-key-1234"
    assert "nvd-key-1234" not in repr(sources)


@pytest.mark.parametrize("key", ["two words", "line\nbreak", "tab\there"])
def test_a_key_pasted_with_a_space_or_break_inside_is_refused_by_name(key: str):
    with pytest.raises(SettingsError, match="NVD_API_KEY"):
        Settings.from_env({**BASE_ENV, "NVD_API_KEY": key})


def test_the_runtime_is_built_with_every_reader():
    runtime = build_runtime(Settings.from_env(BASE_ENV))
    assert runtime.checker is not None
