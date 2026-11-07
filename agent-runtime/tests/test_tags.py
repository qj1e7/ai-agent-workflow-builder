import pytest

from agent_runtime.tags import UnparseableTag, family_of, highest, newer_than


@pytest.mark.parametrize(
    ("tag", "family"),
    [
        ("1.2.14", ""),
        ("v1.2.14", ""),
        ("V1.2.14", ""),
        ("vv1.2.14", "vv"),
        ("v2.14.0b2", None),
        ("cli==0.4.37", "cli=="),
        ("sdk==0.4.8", "sdk=="),
        ("prebuilt==1.0.2", "prebuilt=="),
        ("2.0.0-rc.1", ""),
        ("nightly", None),
        ("1.2", None),
        ("", None),
    ],
)
def test_family_is_what_comes_before_the_version(tag: str, family: str | None):
    assert family_of(tag) == family


@pytest.mark.parametrize(
    ("last", "tags", "expected"),
    [
        ("1.2.14", ["1.2.16", "1.2.15", "1.2.14", "1.2.13"], ["1.2.16", "1.2.15"]),
        ("1.2.14", ["1.2.14", "1.2.13"], []),
        ("1.2.14", ["1.2.13", "1.2.15", "1.2.16"], ["1.2.16", "1.2.15"]),
        ("1.2.9", ["1.2.10", "1.2.9", "1.2.8"], ["1.2.10"]),
        ("1.9.9", ["1.10.0", "2.0.0", "1.9.10"], ["2.0.0", "1.10.0", "1.9.10"]),
        ("1.2.14", ["cli==0.4.37", "sdk==0.4.9", "1.2.15"], ["1.2.15"]),
        ("cli==0.4.36", ["cli==0.4.37", "1.2.16", "sdk==0.9.0", "cli==0.4.36"], ["cli==0.4.37"]),
        ("1.2.14", ["1.2.15", "1.2.15", "latest"], ["1.2.15"]),
        ("1.0.0", ["1.0.1-rc.1", "1.0.0-rc.1"], ["1.0.1-rc.1"]),
        (
            "1.0.0-rc.1",
            ["1.0.0", "1.0.0-rc.2", "1.0.0-beta.3", "1.0.0-rc.1"],
            ["1.0.0", "1.0.0-rc.2"],
        ),
        ("1.0.0-rc.2", ["1.0.0-rc.10", "1.0.0-rc.1"], ["1.0.0-rc.10"]),
        ("2.0.0", ["v2.14.2", "v2.14.1", "v2.0.0", "v1.10.19"], ["v2.14.2", "v2.14.1"]),
        ("v2.0.0", ["v2.14.2", "2.1.0", "V2.0.1", "2.0.0"], ["v2.14.2", "2.1.0", "V2.0.1"]),
        ("v2.14.2", ["2.14.2", "v2.14.1"], []),
        ("1.2.19", ["sdk==0.4.11", "v1.2.20"], ["v1.2.20"]),
        ("sdk==0.4.11", ["1.2.19", "v1.2.20", "sdk==0.4.12"], ["sdk==0.4.12"]),
    ],
)
def test_newer_than_stays_in_the_family_and_orders_by_semver(
    last: str, tags: list[str], expected: list[str]
):
    assert newer_than(last, tags) == expected


@pytest.mark.parametrize(
    ("last", "tags", "expected"),
    [
        ("29.1.0", ["docker-v29.2.0", "docker-v29.1.0", "docker-v29.0.4"], ["docker-v29.2.0"]),
        ("v2.4.1", ["n8n@2.4.2", "n8n@2.4.1"], ["n8n@2.4.2"]),
        ("0.3.1", ["langchain==0.3.2", "langchain==0.3.1"], ["langchain==0.3.2"]),
        ("docker-v29.1.0", ["docker-v29.2.0", "v30.0.0"], ["docker-v29.2.0"]),
    ],
)
def test_a_bare_number_meets_the_prefixed_tags_when_the_caller_chose_which_tags_count(
    last: str, tags: list[str], expected: list[str]
):
    assert newer_than(last, tags, any_family=True) == expected


def test_a_bare_number_stays_in_its_own_family_unless_the_caller_says_otherwise():
    assert newer_than("29.1.0", ["docker-v29.2.0"]) == []


def test_newer_than_refuses_a_last_tag_it_cannot_read():
    with pytest.raises(UnparseableTag):
        newer_than("nightly", ["1.2.15"])


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (["1.2.15", "1.2.16", "1.2.9"], "1.2.16"),
        (["1.2.15", "nightly"], "1.2.15"),
        (["nightly"], None),
        ([], None),
    ],
)
def test_highest_picks_the_greatest_readable_version(tags: list[str], expected: str | None):
    assert highest(tags) == expected
