import pytest

from agent_runtime.tags import UnparseableTag, family_of, highest, newer_than


@pytest.mark.parametrize(
    ("tag", "family"),
    [
        ("1.2.14", ""),
        ("v1.2.14", "v"),
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
    ],
)
def test_newer_than_stays_in_the_family_and_orders_by_semver(
    last: str, tags: list[str], expected: list[str]
):
    assert newer_than(last, tags) == expected


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
