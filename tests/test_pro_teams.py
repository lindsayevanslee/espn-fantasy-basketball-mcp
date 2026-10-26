"""Tests for NBA team abbreviation handling and today's-game lookups.

Regression coverage for a bug where the scoreboard feed's abbreviations (GS, UTAH, WSH)
were normalized to one spelling while the static proTeamId map used another, so players
on those teams never received a ``todaysGame``.
"""

import pytest

from espn_fantasy_basketball_mcp.client import ESPNFantasyBasketballClient


@pytest.fixture
def client():
    return ESPNFantasyBasketballClient(league_id=12345, year=2027)


def _scoreboard(*games):
    """Build a minimal ESPN scoreboard payload. Each game is (away_abbr, home_abbr, nba_ids)."""
    events = []
    for away, home, (away_id, home_id) in games:
        events.append(
            {
                "id": f"{away}-{home}",
                "date": "2026-10-25T23:30:00Z",
                "competitions": [
                    {
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"id": str(home_id), "abbreviation": home},
                            },
                            {
                                "homeAway": "away",
                                "team": {"id": str(away_id), "abbreviation": away},
                            },
                        ]
                    }
                ],
            }
        )
    return {"events": events}


class TestNormalizeAbbrev:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("GS", "GSW"),
            ("UTAH", "UTA"),
            ("WSH", "WAS"),
            ("NO", "NOP"),
            ("NY", "NYK"),
            ("SA", "SAS"),
            ("PHO", "PHX"),
            ("LAL", "LAL"),  # already canonical
            ("gsw", "GSW"),  # case-insensitive
            (" bos ", "BOS"),  # whitespace tolerated
        ],
    )
    def test_normalizes_known_variants(self, raw, expected):
        assert ESPNFantasyBasketballClient._normalize_nba_abbrev(raw) == expected

    def test_static_map_is_canonical_and_complete(self):
        mapping = ESPNFantasyBasketballClient._get_pro_team_id_to_abbrev()
        assert sorted(mapping) == list(range(1, 31)), "ESPN proTeamIds run 1..30"
        assert len(set(mapping.values())) == 30, "abbreviations must be unique"
        for code in mapping.values():
            assert code == ESPNFantasyBasketballClient._normalize_nba_abbrev(code), code
            assert len(code) == 3 and code.isupper(), code


class TestResolveProTeamAbbrev:
    def test_api_value_is_normalized(self, client):
        assert client._resolve_pro_team_abbrev(9, "GS") == "GSW"

    def test_static_fallback(self, client):
        assert client._resolve_pro_team_abbrev(26) == "UTA"
        assert client._resolve_pro_team_abbrev(3) == "NOP"

    def test_unknown_id_returns_none(self, client):
        assert client._resolve_pro_team_abbrev(999) is None
        assert client._resolve_pro_team_abbrev(None) is None

    def test_unsigned_player_is_fa(self, client):
        """ESPN reports proTeamId 0 for players without an NBA team (shown as FA in its UI)."""
        assert client._resolve_pro_team_abbrev(0) == "FA"
        # and FA never matches a scoreboard team, so such a player gets no todaysGame
        games, _ = client._parse_todays_games(_scoreboard(("BOS", "MIA", (2, 14))))
        assert "FA" not in games


class TestParseTodaysGames:
    def test_cache_keys_match_resolved_abbreviations(self, client):
        """The end-to-end bug: a roster player's resolved abbreviation must find their game."""
        nba_data = _scoreboard(("GS", "UTAH", (9, 26)), ("WSH", "LAL", (27, 13)))

        games, team_id_to_abbrev = client._parse_todays_games(nba_data)

        assert set(games) == {"GSW", "UTA", "WAS", "LAL"}
        assert games["GSW"].opponent == "UTA" and games["GSW"].home is False
        assert games["UTA"].opponent == "GSW" and games["UTA"].home is True
        assert games["WAS"].opponent == "LAL"
        assert team_id_to_abbrev == {9: "GSW", 26: "UTA", 27: "WAS", 13: "LAL"}

        # Every one of these proTeamIds must resolve to a key present in the cache,
        # both with the today's-games mapping and with the static fallback alone.
        for pro_team_id in (9, 26, 27, 13):
            with_map = client._resolve_pro_team_abbrev(pro_team_id, None, team_id_to_abbrev)
            static_only = client._resolve_pro_team_abbrev(pro_team_id)
            assert with_map in games, pro_team_id
            assert static_only in games, pro_team_id

    def test_game_time_is_converted_to_configured_timezone(self, client, monkeypatch):
        monkeypatch.setenv("MY_TIMEZONE", "America/Chicago")
        games, _ = client._parse_todays_games(_scoreboard(("BOS", "MIA", (2, 14))))
        assert games["BOS"].time == "6:30 PM"
        assert games["BOS"].timeISO == "2026-10-25T18:30:00-05:00"

    def test_malformed_payload_returns_empty(self, client):
        games, mapping = client._parse_todays_games({"events": [{"competitions": []}]})
        assert games == {} and mapping == {}
