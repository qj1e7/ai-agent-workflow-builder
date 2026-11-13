"""The cert list parser against Qingtao's own test (n8n-project/scripts/parse-test.js) and his
script's own output.

Each of his assertions is one test below, in his order, with his message as its name. His test
reads today's date, so its counts drift as the days pass. Here the clock is fixed on the day the
fixture was written. `fixtures/cert_list/make-golden.mjs` rebuilds the fixture and the record of
his script's output.
"""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.cert_list import (
    CertListError,
    CertReport,
    Dated,
    Where,
    parse_cert_list,
    read_validity_end,
    short_date,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cert_list"
HTML = (FIXTURES / "cert-list.html").read_text().strip()
HIS: dict[str, Any] = json.loads((FIXTURES / "parse-build.out.json").read_text())
NOW = datetime.fromisoformat(HIS["now"])
WHERE = Where(page_url=HIS["pageUrl"], email_to=HIS["emailTo"])


@pytest.fixture(scope="module")
def out() -> CertReport:
    return parse_cert_list(HTML, NOW, WHERE)


def card_text(report: CertReport) -> str:
    return json.dumps(report.payload["attachments"][0]["content"], ensure_ascii=False)


def test_expected_4_confirmed_rows(out: CertReport):
    assert len(out.confirmed) == 4


def test_expected_2_rows_without_env(out: CertReport):
    assert len(out.missing_env) == 2


def test_expected_1_unreadable_row(out: CertReport):
    assert len(out.unreadable) == 1


def test_expected_1_stale_row(out: CertReport):
    assert len(out.stale) == 1


def test_expected_1_duplicate_row(out: CertReport):
    assert len(out.duplicates) == 1


def test_expected_2_rows_tracked_elsewhere_or_non_expiring(out: CertReport):
    assert out.not_tracked_count == 2


def test_card_must_not_contain_the_no_env_group(out: CertReport):
    assert "(no env)" not in card_text(out)


def test_email_must_contain_the_unreadable_section(out: CertReport):
    assert "Cannot read a date" in out.payload["emailHtml"]


def test_email_must_contain_the_duplicate_section(out: CertReport):
    assert "Duplicate rows" in out.payload["emailHtml"]


def test_top_level_email_html_must_match_the_payload_copy(out: CertReport):
    assert out.email_html == out.payload["emailHtml"]


def test_needs_rows_must_cover_every_needs_confirm_row(out: CertReport):
    assert len(out.needs_rows) == out.needs_confirm_count


def test_needs_rows_entries_need_id_bucket_name_cell(out: CertReport):
    assert all(r.id and r.bucket and r.name and isinstance(r.cell, str) for r in out.needs_rows)


def test_unreadable_row_must_carry_its_raw_cell_text(out: CertReport):
    assert any(r.bucket == "unreadable-date" and "yearly" in r.cell.lower() for r in out.needs_rows)


def test_email_html_must_carry_the_ai_placeholder_for_the_downstream_ai_step(out: CertReport):
    assert "<!--AI-->" in out.email_html


def test_the_port_makes_what_his_script_makes(out: CertReport):
    item = out.item()
    assert item["card"] == HIS["teamsCard"]
    assert item["email_html"] == HIS["emailHtml"]
    for his, ours in (
        ("hasAlerts", "has_alerts"),
        ("subject", "subject"),
        ("emailSubject", "email_subject"),
        ("checkedAt", "checked_at"),
        ("rowsRead", "rows_read"),
        ("confirmedCount", "confirmed_count"),
        ("needsConfirmCount", "needs_confirm_count"),
        ("expiredCount", "expired_count"),
        ("soonCount", "soon_count"),
        ("laterCount", "later_count"),
        ("notTrackedCount", "not_tracked_count"),
    ):
        assert item[ours] == HIS[his], his
    assert list(item["by_env_counts"].items()) == list(HIS["byEnvCounts"].items())
    assert item["needs_rows"] == HIS["needsRows"]
    assert [
        (c["env"], c["name"], c["validity_end"], c["days_left"]) for c in item["confirmed"]
    ] == [(c["env"], c["name"], c["validityEnd"], c["daysLeft"]) for c in HIS["confirmed"]]
    assert json.loads(HIS["teamsWebhookPayload"])["emailHtml"] == out.payload["emailHtml"]


def test_the_split_reads_like_his_printout(out: CertReport):
    assert out.subject == "⚠️ 4 certificates need action"
    assert [f"{c.env}/{c.name}={c.validity_end}" for c in out.confirmed] == [
        "DEV/gccdev-intra.example-certs.internal=24 Mar 2026",
        "PRD/intranet.example-certs.internal=04 Dec 2026",
        "UAT/gccuat-intra.example-certs.internal=04 Dec 2026",
        "UAT/gccuat.example-certs.internal=15 Dec 2026",
    ]
    assert [r.name for r in out.missing_env] == [
        "Digital Sign API - for Client Cert via mTLS call",
        "API Gateway",
    ]
    assert list(out.by_env) == ["DEV", "PRD", "UAT"]


@pytest.mark.parametrize(
    ("cell", "day", "basis"),
    [
        ("renewed on 14 May 2026, was 01 Jan 2026", date(2026, 5, 14), "renewal date"),
        ("01 Jan 2026 then 05/03/2027", date(2027, 3, 5), "last date in cell"),
        ("2026-02-31", date(2026, 3, 3), "as written"),
        ("4 Sept 26", date(2026, 9, 4), "as written"),
        ("Dec 31, 2026", date(2026, 12, 31), "as written"),
    ],
)
def test_a_cell_is_read_like_a_person_reads_it(cell: str, day: date, basis: str):
    found = read_validity_end(cell)
    assert isinstance(found, Dated)
    assert (found.day, found.basis) == (day, basis)


@pytest.mark.parametrize(
    ("cell", "kind"),
    [
        ("", "empty"),
        ("never expires", "no-expiry"),
        ("15 Dec 2026, pending finance", "no-expiry"),
        ("kept in Keycloak", "stored-elsewhere"),
        ("renewed yearly", "unreadable"),
    ],
)
def test_a_cell_with_no_date_to_track_says_why(cell: str, kind: str):
    assert read_validity_end(cell) == kind


def test_september_is_written_as_javascript_writes_it():
    assert short_date(date(2026, 9, 4)) == "04 Sept 2026"


def test_the_day_is_today_in_singapore():
    late = datetime(2026, 11, 13, 16, 30, tzinfo=UTC)
    report = parse_cert_list(HTML, late, WHERE)
    assert report.checked_at == "14 Nov 2026, 00:30"
    assert [c.days_left for c in report.confirmed][:2] == [-235, 20]


@pytest.mark.parametrize(
    ("html", "said"),
    [
        ("", "No page body in the Confluence response"),
        ("<p>No list here.</p>", "No <table> found on the Cert List page."),
        ("<table><tr><th>Owner</th></tr></table>", 'No column matching "VALIDITY END"'),
    ],
)
def test_a_page_without_the_list_is_refused_in_his_words(html: str, said: str):
    with pytest.raises(CertListError, match=re.escape(said)):
        parse_cert_list(html, NOW, WHERE)
