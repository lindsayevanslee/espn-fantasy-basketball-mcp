"""Nothing under tests/fixtures may contain ESPN credentials or account identifiers.

ESPN_S2 and SWID cookies grant full access to the ESPN account. SWIDs are GUIDs and also appear
inside league payloads (members, team owners), so recorded fixtures are scanned for cookie
names, cookie-shaped tokens and GUIDs on every test run. The sanitiser used by
scripts/record_fixtures.py is tested here too, against a payload seeded with fake secrets.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.record_fixtures import GUID_RE, sanitize
from tests.fixture_espn import FIXTURE_DIR

FORBIDDEN = {
    "espn_s2 cookie name": re.compile(r"espn_s2", re.IGNORECASE),
    "SWID cookie name": re.compile(r"\bswid\b", re.IGNORECASE),
    "cookie header": re.compile(r"\bset-cookie\b|\bcookie:", re.IGNORECASE),
    "GUID (SWID-shaped)": GUID_RE,
    "espn_s2-shaped token": re.compile(r"AE[A-Za-z0-9%+/=_-]{60,}"),
}

FIXTURE_FILES = sorted(p for p in FIXTURE_DIR.rglob("*") if p.is_file() and p.suffix != ".py")


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: str(p.relative_to(FIXTURE_DIR)))
def test_fixture_has_no_credentials(path: Path):
    text = path.read_text(errors="replace")
    for label, pattern in FORBIDDEN.items():
        match = pattern.search(text)
        assert match is None, f"{path.name} contains a {label} at offset {match.start()}"


def test_fixture_directory_is_populated():
    assert any(p.name == "league_mSettings.json" for p in FIXTURE_FILES)


FAKE_SWID = "{DEADBEEF-1234-5678-9ABC-DEF012345678}"
FAKE_S2 = "AEB" + "x" * 80


def test_sanitizer_strips_identifiers_everywhere():
    payload = {
        "members": [{"id": FAKE_SWID, "displayName": "Me"}],
        "teams": [
            {
                "id": 8,
                "abbrev": "SA",
                "name": "Statistical Anomalies",
                "owners": [FAKE_SWID],
                "primaryOwner": FAKE_SWID,
                "record": {"overall": {"wins": 1, "losses": 0}},
            }
        ],
        "transactions": [{"memberId": FAKE_SWID, "note": f"posted by {FAKE_SWID}"}],
        "debug": {"cookies": {"espn_s2": FAKE_S2, "SWID": FAKE_SWID}, "token": FAKE_S2},
        "nested": [[FAKE_SWID], {"deep": {"deeper": f"id={FAKE_SWID}"}}],
    }
    clean = sanitize(payload)
    text = str(clean)
    for label, pattern in FORBIDDEN.items():
        assert not pattern.search(text), f"sanitiser left a {label}"
    assert "members" not in clean and "cookies" not in clean["debug"]
    assert clean["teams"][0]["owners"] == ["REDACTED-ID"]
    assert clean["teams"][0]["name"] == "Statistical Anomalies", "names kept by default"
    assert clean["teams"][0]["record"]["overall"]["wins"] == 1
    assert clean["nested"][1]["deep"]["deeper"] == "id=REDACTED-ID"


def test_sanitizer_can_redact_names():
    payload = {"teams": [{"id": 8, "abbrev": "SA", "name": "Real Name", "owners": []}]}
    assert sanitize(payload, redact_names=True)["teams"][0]["name"] == "Team 8"


def test_client_never_logs_cookie_values(caplog):
    """Request logging names the URL only; cookies travel in the request, never in a log line."""
    import logging

    from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient

    client = ESPNFantasyBasketballClient(1, 2027, espn_s2=FAKE_S2, swid=FAKE_SWID)
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("espn_fantasy_basketball_mcp.client").debug(
            f"Making request to {client.BASE_URL}/seasons/2027"
        )
    assert FAKE_S2 not in caplog.text and FAKE_SWID not in caplog.text
    assert client.cookies["SWID"] == FAKE_SWID, "cookies are still sent on the request"
