"""ClubElo page parser -- the sample is the shape of a live https://clubelo.com/Lille page (2026-10-13)."""

import asyncio

import pytest

from football.sites import clubelo

PAGE = (
    '<div class="blatt"><h1><a href="/2026-10-13/Lille">Lille</a></h1><p>France, Europe, <p>Elo: <b>1779</b> '
    "(Best: 1833, reached on 2024-12-20),                     Golo: 1.01</p>"
    '<script>var vegaJson = {"datasets": {"d": ['
    '{"Date": "2026-06-01T00:00:00", "Elo": 1760.5, "Golo": 1.1, "segment_id": 0},'
    '{"Date": "2026-07-10T00:00:00", "Elo": 1777.7, "Golo": 1.1, "segment_id": 0},'
    '{"Date": "2026-10-13T00:00:00", "Elo": 1779.0, "Golo": 1.0, "segment_id": 0}]}}</script>'
)


def test_parse_header_and_trend():
    r = clubelo.parse_club_page(PAGE)
    assert (r.elo, r.golo, r.best, r.best_date, r.as_of) == (1779.0, 1.01, 1833.0, "2024-12-20", "2026-10-13")
    assert r.change_90d == pytest.approx(1779.0 - 1777.7, abs=0.05)        # 2026-07-15 cutoff -> the 2026-07-10 point


def test_empty_page_for_unknown_club_is_none():
    assert clubelo.parse_club_page('<h1><a href="/2026-10-13/"></a></h1><h2>Fixtures</h2>') is None


def test_slug_candidates():
    assert clubelo.slug_candidates("Real Madrid")[:2] == ["RealMadrid", "realmadrid"]      # some clubs live under a lowercase name
    assert "Hajduk" in clubelo.slug_candidates("Hajduk Split")                            # ClubElo's short name
    assert len(clubelo.slug_candidates("Paris Saint-Germain")) <= 8
    assert "ManCity" in clubelo.slug_candidates("Manchester City")
    assert "AtleticoMadrid" in clubelo.slug_candidates("Atlético Madrid")                  # accents folded, not dropped ("AtlticoMadrid")
    assert {"Koeln", "Forest", "Frankfurt", "Sociedad"} <= set(clubelo.slug_candidates("1. FC Köln") + clubelo.slug_candidates("Nottingham Forest") + clubelo.slug_candidates("Eintracht Frankfurt") + clubelo.slug_candidates("Real Sociedad"))


def test_fallback_page_must_be_the_same_club():
    assert clubelo._page_is_this_club(PAGE, "Lille OSC")
    assert not clubelo._page_is_this_club(PAGE, "Arsenal")
    assert clubelo._page_is_this_club('<h1><a href="/2026-10-12/Bayern">Bayern München</a></h1>', "Bayern Munich")


def test_missing_club_resolves_none_and_a_block_raises(monkeypatch):
    async def empty(url):
        return '<h1><a href="/2026-10-13/"></a></h1>'

    monkeypatch.setattr(clubelo, "fetch_text", empty)
    assert asyncio.run(clubelo.get_club_elo("Nowhere United")) is None

    async def blocked(url):
        raise RuntimeError("HTTP 403")

    monkeypatch.setattr(clubelo, "fetch_text", blocked)
    with pytest.raises(RuntimeError):
        asyncio.run(clubelo.get_club_elo("Lille"))


# --- front page ranking (every rated club, one fetch) and opponent matching --------------------------------

RANK_ROWS = (
    '<tr><td class="l"><a href="/NED"><img alt="NED" decoding="async" loading="lazy" src="x/nld.png" style="width:20px; opacity:0.8;"/></a> <span class="min481"><small> 153 </small></span> <a href="/Ajax"><span class="NonAst">AJA</span><span class="Ast">Ajax</span></a></td><td class="r">1686</td></tr>'
    '<tr><td class="l"><a href="/NED"><img alt="NED" decoding="async" loading="lazy" src="x/nld.png" style="width:20px; opacity:0.8;"/></a> <span class="min481"></span> <span class="NonAst">SIT</span><span class="Ast">Sittard</span></td><td class="r">1496</td></tr>'
)


def test_parse_ranking_reads_linked_and_plain_rows_with_their_country():
    assert clubelo.parse_ranking(RANK_ROWS) == [("NED", "Ajax", 1686.0), ("NED", "Sittard", 1496.0)]


RANKING = [
    ("NED", "PSV", 1781.0), ("NED", "Eindhoven", 1420.0), ("NED", "Sittard", 1496.0), ("NED", "Nijmegen", 1586.0),
    ("CRO", "Dinamo Zagreb", 1677.0), ("CRO", "Lok Zagreb", 1437.0), ("MKD", "Vardar", 1396.0),
    ("THA", "Port FC", 1426.0), ("POR", "Porto", 1890.0), ("FRA", "Paris FC", 1705.0), ("POL", "Rakow", 1579.0),
    ("ESP", "Barcelona", 2031.0), ("ECU", "Barcelona", 1550.0),
]


def test_match_ranked_club_reads_short_names_abbreviations_and_accents():
    m = lambda n, c=None: clubelo.match_ranked_club(n, RANKING, c)  # noqa: E731
    assert m("Fortuna Sittard") == ("NED", 1496.0)
    assert m("NEC Nijmegen") == ("NED", 1586.0)
    assert m("GNK Dinamo Zagreb") == ("CRO", 1677.0)
    assert m("NK Lokomotiva Zagreb") == ("CRO", 1437.0)
    assert m("Raków Częstochowa") == ("POL", 1579.0)


def test_match_ranked_club_never_guesses_a_wrong_club():
    m = lambda n, c=None: clubelo.match_ranked_club(n, RANKING, c)  # noqa: E731
    assert m("PSV Eindhoven") == ("NED", 1781.0)          # first word breaks the tie with "Eindhoven"
    assert m("NK Vardarac") is None                       # "Vardar" is another club
    assert m("FC Porto") == ("POR", 1890.0)               # not Thailand's "Port FC"
    assert m("Paris Saint-Germain") is None               # not "Paris FC"
    assert m("FC Barcelona") is None                      # two clubs, no country to settle it
    assert m("FC Barcelona", "ESP") == ("ESP", 2031.0)


def _row(opponent):
    from football.types import FormResult
    return FormResult(opponent=opponent, competition="L", date="2026-10-01", result="W", scoreline="1-0", venue="home", margin=1,
                      neutral_venue=None, ht_scoreline=None, xg_for=None, xg_against=None)


class _Summary:
    def __init__(self, rows):
        self.last5_overall, self.last10_overall, self.last20_overall, self.last5_home, self.last5_away = rows[:1], rows, rows, rows[:1], []


class _Merged:
    def __init__(self, home, away, kickoff="2099-01-01T18:00:00Z"):
        self.home_team, self.away_team, self.kickoff_utc = home, away, kickoff


class _Ins:
    def __init__(self, home=1, away=1):
        self.home_club_elo, self.away_club_elo = home, away


def test_opponent_club_elo_is_filled_on_every_form_list_from_one_fetch(monkeypatch):
    import asyncio
    from football import orchestrate
    calls = []

    async def fake_ranking():
        calls.append(1)
        return [("NED", "Ajax", 1686.0), ("NED", "Sittard", 1496.0), ("CRO", "Hajduk", 1595.0), ("CRO", "Dinamo Zagreb", 1677.0)]

    monkeypatch.setattr(orchestrate.clubelo, "get_ranking", fake_ranking)
    own, opp = _Summary([_row("Fortuna Sittard"), _row("Nobody FC")]), _Summary([_row("GNK Dinamo Zagreb")])
    asyncio.run(orchestrate._apply_opponent_club_elo_safe(_Merged("HNK Hajduk Split", "AFC Ajax"), "AFC Ajax", "HNK Hajduk Split", own, opp, _Ins()))
    assert len(calls) == 1
    assert [r.opponent_club_elo for r in own.last10_overall] == [1496.0, None] and own.last5_overall[0].opponent_club_elo == 1496.0
    assert opp.last10_overall[0].opponent_club_elo == 1677.0


def test_opponent_club_elo_is_skipped_for_national_teams_and_survives_a_failed_fetch(monkeypatch):
    import asyncio
    from football import orchestrate

    async def boom():
        raise RuntimeError("timeout")

    monkeypatch.setattr(orchestrate.clubelo, "get_ranking", boom)
    s = _Summary([_row("Fortuna Sittard")])
    asyncio.run(orchestrate._apply_opponent_club_elo_safe(_Merged("Spain", "Italy"), "Spain", "Italy", s, None, _Ins(None, None)))      # no ClubElo for either side: no fetch at all
    asyncio.run(orchestrate._apply_opponent_club_elo_safe(_Merged("AFC Ajax", "X"), "AFC Ajax", "X", s, None, _Ins()))               # fetch fails: recorded, rows left unrated
    assert s.last10_overall[0].opponent_club_elo is None


def test_a_club_page_that_redirects_is_rated_from_the_front_page(monkeypatch):
    import asyncio
    from football import orchestrate

    async def fake_ranking():
        return [("NED", "Sparta", 1502.0), ("CZE", "Sparta Praha", 1647.0), ("NED", "Ajax", 1697.0)]

    monkeypatch.setattr(orchestrate.clubelo, "get_ranking", fake_ranking)
    ins = _Ins(None, 1697.0)
    asyncio.run(orchestrate._apply_opponent_club_elo_safe(_Merged("Sparta Rotterdam", "AFC Ajax"), "AFC Ajax", "Sparta Rotterdam", _Summary([]), _Summary([]), ins))
    assert ins.home_club_elo.elo == 1502.0 and ins.away_club_elo == 1697.0


def test_both_club_pages_redirecting_still_fetch_the_ranking_but_a_played_match_does_not(monkeypatch):
    import asyncio
    from football import orchestrate
    calls = []

    async def fake_ranking():
        calls.append(1)
        return [("NED", "Sparta", 1502.0), ("NED", "Ajax", 1697.0)]

    monkeypatch.setattr(orchestrate.clubelo, "get_ranking", fake_ranking)
    ins = _Ins(None, None)
    asyncio.run(orchestrate._apply_opponent_club_elo_safe(_Merged("Sparta Rotterdam", "AFC Ajax"), "AFC Ajax", "Sparta Rotterdam", _Summary([]), _Summary([]), ins))
    assert ins.home_club_elo.elo == 1502.0 and ins.away_club_elo.elo == 1697.0
    played = _Ins(None, None)      # today's ratings would already include a played match's result
    asyncio.run(orchestrate._apply_opponent_club_elo_safe(_Merged("Sparta Rotterdam", "AFC Ajax", "2026-10-01T18:00:00Z"), "AFC Ajax", "Sparta Rotterdam", _Summary([]), _Summary([]), played))
    assert len(calls) == 1 and played.home_club_elo is None
