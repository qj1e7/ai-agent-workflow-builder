"""Recorded samples (ADR 0054, section 6). A real answer is kept only as its allow list says: every
field the list doesn't name is left out, text people wrote is replaced, a value that breaks its
field's shape is left out, and key shapes are masked. Code varies the samples for odd data.

Every person here is made up at run time, and none is a real person."""

import json
import secrets
from typing import Any

import pytest

from platform_api.orchestration.recorded_samples import (
    ALLOW_LISTS,
    FAKE_LINK,
    LONG_TEXT_LENGTH,
    MADE_UP,
    MASKED,
    PAGE_ID,
    PAGE_TITLE,
    RELEASE_NOTES,
    SAMPLE_ITEMS,
    SUFFIX,
    AnswerKind,
    RecordedSamples,
    answer_of,
    record_run,
    scrub,
    vary,
)


def person() -> dict[str, str]:
    tag = secrets.token_hex(4)
    return {
        "name": f"Person {tag}",
        "email": f"person.{tag}@example.com",
        "login": f"user-{tag}",
        "id": str(secrets.randbelow(10**9) + 10**8),
    }


def github_release(tag: str = "1.2.16", someone: dict[str, str] | None = None) -> dict[str, Any]:
    """GitHub's answer for one release, with a person in each place GitHub puts one."""
    who = someone or person()
    return {
        "url": "https://api.github.com/repos/acme/tool/releases/1",
        "html_url": f"https://github.com/{who['login']}/tool/releases/tag/{tag}",
        "id": int(who["id"]),
        "node_id": "RE_made_up",
        "tag_name": tag,
        "target_commitish": "main",
        "name": tag,
        "body": f"Thanks {who['name']} ({who['email']}) for this one.",
        "draft": False,
        "prerelease": True,
        "created_at": "2026-10-28T08:00:00Z",
        "published_at": "2026-10-28T09:00:00Z",
        "author": {"login": who["login"], "id": int(who["id"]), "avatar_url": "https://a/u/1"},
        "assets": [{"uploader": {"login": who["login"], "email": who["email"]}}],
    }


def read_release(tag: str = "1.2.16") -> dict[str, Any]:
    return {"kind": "release", "id": tag, "name": tag, "published_at": "2026-10-28T09:00:00Z"}


def page(someone: dict[str, str]) -> dict[str, Any]:
    return {
        "kind": "page",
        "id": "40001",
        "title": f"Notes by {someone['name']}",
        "version": 7,
        "url": f"https://wiki.example/spaces/{someone['login']}/pages/40001",
        "text": f"Ask {someone['email']} before you patch.",
    }


def jira_issue(someone: dict[str, str]) -> dict[str, Any]:
    return {
        "id": someone["id"],
        "key": "SUP-12",
        "self": f"https://jira.example/rest/api/2/issue/{someone['id']}",
        "fields": {
            "summary": f"Patch the servers for {someone['name']}",
            "description": f"Call {someone['email']}.",
            "status": {"name": "In Progress", "id": "3"},
            "assignee": {"displayName": someone["name"], "emailAddress": someone["email"]},
            "reporter": {"accountId": someone["id"]},
            "created": "2026-10-28T09:00:00.000+0800",
            "updated": "2026-10-29T10:30:00.000+0800",
        },
    }


def holds_any(scrubbed: object, someone: dict[str, str]) -> list[str]:
    text = json.dumps(scrubbed)
    return [value for value in someone.values() if value in text]


# The allow lists


def test_a_github_release_keeps_only_the_fields_on_its_allow_list() -> None:
    [kept] = scrub("github.release", [github_release()])
    assert kept == {
        "tag_name": "1.2.16",
        "name": "1.2.16",
        "published_at": "2026-10-28T09:00:00Z",
        "created_at": "2026-10-28T08:00:00Z",
        "html_url": "https://github.com/sample/sample/releases/tag/1.2.16",
        "prerelease": True,
        "draft": False,
        "body": RELEASE_NOTES,
    }


@pytest.mark.parametrize(
    ("answer", "raw"),
    [
        ("github.release", lambda who: github_release(someone=who)),
        ("read.page", page),
        ("jira.issue", jira_issue),
    ],
)
def test_no_name_email_or_account_id_survives_a_scrub(answer: AnswerKind, raw: Any) -> None:
    someone = person()
    scrubbed = scrub(answer, [raw(someone)])
    assert holds_any(scrubbed, someone) == []
    assert set(scrubbed[0]) <= {path.split(".")[0] for path in ALLOW_LISTS[answer].fields}


@pytest.mark.parametrize("answer", list(ALLOW_LISTS))
def test_a_person_in_every_allowed_field_is_left_out_or_replaced(answer: AnswerKind) -> None:
    """Even where the allow list keeps a value, a person can't pass its shape."""
    someone = person()
    raw: dict[str, Any] = {}
    for path in ALLOW_LISTS[answer].fields:
        for value in someone.values():
            *parents, last = path.split(".")
            where = raw
            for part in parents:
                where = where.setdefault(part, {})
            where[last] = value
            assert holds_any(scrub(answer, [raw]), someone) == [], (path, value)


def test_the_text_people_wrote_is_replaced_by_a_fixed_value() -> None:
    someone = person()
    [scrubbed] = scrub("read.page", [page(someone)])
    assert scrubbed["title"] == PAGE_TITLE
    assert scrubbed["url"] == FAKE_LINK
    assert scrubbed["id"] == PAGE_ID, "a number alone can't show what it names"
    assert scrubbed["version"] == 7


def test_a_release_name_is_kept_only_when_it_is_its_tag() -> None:
    release = {**github_release(), "name": "Spring release, thanks to all"}
    assert scrub("github.release", [release])[0]["name"] == "1.2.16"
    item = {**read_release("2.0.1"), "name": "2.0.1"}
    assert scrub("read.release", [item])[0]["name"] == "2.0.1"


def test_a_jira_status_outside_the_fixed_words_becomes_to_do() -> None:
    issue = jira_issue(person())
    issue["fields"]["status"]["name"] = "Waiting on a person"
    fields: Any = scrub("jira.issue", [issue])[0]["fields"]
    assert fields["status"] == {"name": "To Do"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("published_at", "yesterday"),
        ("published_at", 1_793_000_000),
        ("prerelease", "false"),
        ("tag_name", "release with spaces"),
        ("tag_name", "no-version-here"),
    ],
)
def test_a_value_that_breaks_its_fields_shape_is_left_out(field: str, value: object) -> None:
    [kept] = scrub("github.release", [{**github_release(), field: value}])
    assert field not in kept


def test_a_value_with_the_shape_of_a_key_is_masked() -> None:
    made_up_key = "1.0.0+" + secrets.token_hex(20)
    [kept] = scrub("github.release", [github_release(tag=made_up_key)])
    assert kept["tag_name"] == MASKED
    assert made_up_key not in json.dumps(kept)


def test_a_scrub_of_a_scrubbed_answer_changes_nothing() -> None:
    for answer, sample in MADE_UP.items():
        assert scrub(answer, sample.items) == sample.items, answer
        assert scrub(answer, scrub(answer, sample.items)) == sample.items


def test_anything_but_an_object_is_left_out() -> None:
    assert scrub("read.release", [read_release(), "1.2.16", None, [1]]) == (
        scrub("read.release", [read_release()])
    )


# What each read block gives


def node(node_type: str, **parameters: Any) -> dict[str, Any]:
    return {"name": "Block", "type": node_type, "typeVersion": 1, "parameters": parameters}


@pytest.mark.parametrize(
    ("block", "answer"),
    [
        (node("CUSTOM.wabRead"), "read.release"),
        (node("CUSTOM.wabRead", source="github_releases"), "read.release"),
        (node("CUSTOM.wabRead", source="confluence_page"), "read.page"),
        (node("CUSTOM.wabRead", source="jira_tickets"), None),
        (node("n8n-nodes-base.github", resource="release", operation="getAll"), "github.release"),
        (node("n8n-nodes-base.github", resource="issue", operation="get"), None),
        (node("n8n-nodes-base.github"), None),
        (node("n8n-nodes-base.jira", resource="issue", operation="getAll"), "jira.issue"),
        (node("n8n-nodes-base.jira", operation="get"), "jira.issue"),
        (node("n8n-nodes-base.jira", operation="changelog"), None),
        (node("n8n-nodes-base.slack"), None),
        (node("n8n-nodes-base.httpRequest", url="https://api.github.com"), None),
    ],
)
def test_each_read_block_gives_one_answer_kind_or_none(
    block: dict[str, Any], answer: str | None
) -> None:
    assert answer_of(block) == answer


# Variations, which code makes


def test_each_variation_changes_the_newest_item_only() -> None:
    sample = MADE_UP["github.release"]
    varied = vary(sample.items, "github.release", ["suffix", "empty_field", "long_text"])
    assert isinstance(varied, tuple)
    first, *rest = varied
    assert first["tag_name"] == str(sample.items[0]["tag_name"]) + SUFFIX
    assert first["name"] == ""
    assert len(str(first["body"])) == LONG_TEXT_LENGTH
    assert rest == list(sample.items[1:])
    assert vary(sample.items, "github.release", []) == sample.items


@pytest.mark.parametrize("answer", list(ALLOW_LISTS))
def test_every_variation_an_answer_takes_keeps_it_a_valid_item(answer: AnswerKind) -> None:
    sample = MADE_UP[answer]
    for variation in ALLOW_LISTS[answer].varies:
        varied = vary(sample.items, answer, [variation])
        assert isinstance(varied, tuple) and varied != sample.items, (answer, variation)


def test_a_variation_an_answer_has_no_field_for_is_refused_in_words() -> None:
    refused = vary(MADE_UP["read.page"].items, "read.page", ["suffix"])
    assert refused == 'A Confluence page has no version to vary with "suffix".'
    assert vary((), "read.release", ["long_text"]) == "This sample has nothing to vary."


# The store


def test_the_store_starts_with_the_made_up_samples() -> None:
    store = RecordedSamples()
    for answer, sample in MADE_UP.items():
        assert store.for_block("Any block", answer) == sample
        assert store.get(sample.id) == sample
        assert sample.origin == "made_up"


def test_the_store_scrubs_before_it_keeps() -> None:
    someone = person()
    store = RecordedSamples()
    kept = store.record("github.release", [github_release(someone=someone)], "real_run")
    assert holds_any(kept.items, someone) == []
    assert store.get(kept.id) == kept
    assert kept.id.startswith("smp_")


def test_the_store_prefers_a_blocks_own_sample_then_one_of_its_kind() -> None:
    store = RecordedSamples()
    any_block = store.record("read.release", [read_release("3.0.0")], "mock")
    assert store.for_block("Read releases", "read.release") == any_block
    own = store.record("read.release", [read_release("3.1.0")], "real_run", block="Read releases")
    assert store.for_block("Read releases", "read.release") == own
    assert store.for_block("Other", "read.release") == own, "the newest of its kind"
    store.record("read.release", [read_release("3.2.0")], "real_run", block="Other")
    assert store.for_block("Read releases", "read.release") == own


def test_a_sample_keeps_at_most_its_limit_of_items() -> None:
    many = [read_release(f"1.{n}.0") for n in range(SAMPLE_ITEMS + 5)]
    kept = RecordedSamples().record("read.release", many, "real_run")
    assert len(kept.items) == SAMPLE_ITEMS
    assert kept.items[0]["id"] == "1.0.0", "newest first, as read"


def test_the_store_forgets_its_oldest_recorded_sample_past_its_limit() -> None:
    store = RecordedSamples(limit=2)
    first = store.record("read.release", [read_release("1.0.0")], "real_run")
    store.record("read.release", [read_release("2.0.0")], "real_run")
    store.record("read.release", [read_release("3.0.0")], "real_run")
    assert store.get(first.id) is None
    assert store.get(MADE_UP["read.release"].id) is not None, "made-up samples stay"


def test_a_given_id_names_the_sample() -> None:
    kept = RecordedSamples().record(
        "read.release", [read_release()], "real_run", sample_id="langgraph-1"
    )
    assert kept.id == "langgraph-1"


# A real run's reads


def test_a_real_run_records_what_each_read_block_returned_scrubbed() -> None:
    someone = person()
    version = {
        "nodes": [
            {**node("CUSTOM.wabRead", source="github_releases"), "name": "Read releases"},
            {
                **node("n8n-nodes-base.github", resource="release", operation="getAll"),
                "name": "GitHub releases",
            },
            {**node("n8n-nodes-base.slack"), "name": "Post in Slack"},
            {**node("CUSTOM.wabRead", source="jira_tickets"), "name": "Read tickets"},
        ]
    }

    def ran(*items: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"data": {"main": [[{"json": item} for item in items]]}}]

    run_data = {
        "Read releases": ran(read_release("1.2.16")),
        "GitHub releases": ran(github_release(someone=someone)),
        "Post in Slack": ran({"ok": True, "channel": someone["login"]}),
        "Read tickets": ran({"key": "SUP-1", "summary": someone["name"]}),
    }
    store = RecordedSamples()
    kept = record_run(store, version, run_data)
    assert [(s.block, s.answer, s.origin) for s in kept] == [
        ("Read releases", "read.release", "real_run"),
        ("GitHub releases", "github.release", "real_run"),
    ]
    assert holds_any([s.items for s in kept], someone) == []
    assert store.for_block("GitHub releases", "github.release") == kept[1]


def test_a_block_that_ran_with_nothing_or_failed_records_nothing() -> None:
    version = {"nodes": [{**node("CUSTOM.wabRead"), "name": "Read releases"}]}
    for run_data in ({}, {"Read releases": []}, {"Read releases": [{"error": {"message": "x"}}]}):
        assert record_run(RecordedSamples(), version, run_data) == ()
