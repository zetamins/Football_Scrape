"""Squawka team-name resolution across every league it covers that this
project scrapes (7 of the 10 in team_aliases.py: Belgium, Portugal and Turkey
have no Squawka competition at all -- see the competition list captured
2026-09-21). SQUAWKA_TEAMS is the real, normalized participant list Squawka
returned for each league's 2026/27 season; the two name sets are
football-data.co.uk short names (from a real fixtures file) and Sofascore-
style full names."""

import pytest

from football.sites.squawka import resolve_squawka_team
from football.team_aliases import known_aliases_for

SQUAWKA_TEAMS = {
    "Premier League": ["afc bournemouth", "arsenal", "aston villa", "brentford", "brighton hove albion", "chelsea", "coventry city", "crystal palace", "everton", "fulham", "hull city", "ipswich town", "leeds united", "liverpool", "manchester city", "manchester united", "newcastle united", "nottingham forest", "sunderland", "tottenham hotspur"],
    "Championship": ["birmingham city", "blackburn rovers", "bolton wanderers", "bristol city", "burnley", "cardiff city", "charlton athletic", "derby county", "lincoln city", "middlesbrough", "millwall", "norwich city", "portsmouth", "preston north end", "queens park rangers", "sheffield united", "southampton", "stoke city", "swansea city", "watford", "west bromwich albion", "west ham united", "wolverhampton wanderers", "wrexham"],
    "Ligue 1": ["angers sco", "auxerre", "brest", "le havre", "le mans", "lens", "lille", "lorient", "monaco", "nice", "olympique lyonnais", "olympique marseille", "paris fc", "psg", "rennes", "strasbourg", "toulouse", "troyes"],
    "LaLiga": ["athletic club", "atletico madrid", "barcelona", "celta de vigo", "deportivo alaves", "deportivo de la coruna", "elche", "espanyol", "getafe", "levante", "malaga", "osasuna", "racing de santander", "rayo vallecano", "real betis", "real madrid", "real sociedad", "sevilla", "valencia", "villarreal"],
    "Bundesliga": ["augsburg", "bayer leverkusen", "bayern munchen", "borussia dortmund", "borussia m gladbach", "eintracht frankfurt", "freiburg", "hamburger sv", "hoffenheim", "koln", "mainz 05", "paderborn", "rb leipzig", "schalke 04", "stuttgart", "sv 07 elversberg", "union berlin", "werder bremen"],
    "Serie A": ["atalanta", "bologna", "cagliari", "como", "fiorentina", "frosinone", "genoa", "internazionale", "juventus", "lazio", "lecce", "milan", "monza", "napoli", "parma", "roma", "sassuolo", "torino", "udinese", "venezia"],
    "Eredivisie": ["ado den haag", "ajax", "az", "excelsior", "feyenoord", "fortuna sittard", "go ahead eagles", "groningen", "heerenveen", "nec", "pec zwolle", "psv", "sc cambuur leeuwarden", "sparta rotterdam", "telstar", "twente", "utrecht", "willem ii"],
}

FOOTBALL_DATA_NAMES = {
    "Bundesliga": ["Augsburg", "Bayern Munich", "Dortmund", "Ein Frankfurt", "Elversberg", "FC Koln", "Freiburg", "Hamburg", "Hoffenheim", "Leverkusen", "M'gladbach", "Mainz", "Paderborn", "RB Leipzig", "Schalke 04", "Stuttgart", "Union Berlin", "Werder Bremen"],
    "Premier League": ["Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea", "Coventry", "Crystal Palace", "Everton", "Fulham", "Hull", "Ipswich", "Leeds", "Liverpool", "Man City", "Man United", "Newcastle", "Nott'm Forest", "Sunderland", "Tottenham"],
    "Championship": ["Birmingham", "Blackburn", "Bolton", "Bristol City", "Burnley", "Cardiff", "Charlton", "Derby", "Lincoln", "Middlesbrough", "Millwall", "Norwich", "Portsmouth", "Preston", "QPR", "Sheffield United", "Southampton", "Stoke", "Swansea", "Watford", "West Brom", "West Ham", "Wolves", "Wrexham"],
    "Ligue 1": ["Angers", "Auxerre", "Brest", "Le Havre", "Le Mans", "Lens", "Lille", "Lorient", "Lyon", "Marseille", "Monaco", "Nice", "Paris FC", "Paris SG", "Rennes", "Strasbourg", "Toulouse", "Troyes"],
    "Serie A": ["Atalanta", "Bologna", "Cagliari", "Como", "Fiorentina", "Frosinone", "Genoa", "Inter", "Juventus", "Lazio", "Lecce", "Milan", "Monza", "Napoli", "Parma", "Roma", "Sassuolo", "Torino", "Udinese", "Venezia"],
    "Eredivisie": ["AZ Alkmaar", "Ajax", "Cambuur", "Den Haag", "Excelsior", "Feyenoord", "For Sittard", "Go Ahead Eagles", "Groningen", "Heerenveen", "Nijmegen", "PSV Eindhoven", "Sparta Rotterdam", "Telstar", "Twente", "Utrecht", "Willem II", "Zwolle"],
    "LaLiga": ["Alaves", "Ath Bilbao", "Ath Madrid", "Barcelona", "Betis", "Celta", "Elche", "Espanol", "Getafe", "La Coruna", "Levante", "Malaga", "Osasuna", "Real Madrid", "Santander", "Sevilla", "Sociedad", "Valencia", "Vallecano", "Villarreal"],
}

SOFASCORE_STYLE_NAMES = {
    "Premier League": ["AFC Bournemouth", "Arsenal", "Aston Villa", "Brentford", "Brighton & Hove Albion", "Chelsea", "Coventry City", "Crystal Palace", "Everton", "Fulham", "Hull City", "Ipswich Town", "Leeds United", "Liverpool", "Manchester City", "Manchester United", "Newcastle United", "Nottingham Forest", "Sunderland", "Tottenham Hotspur"],
    "Ligue 1": ["Angers", "AJ Auxerre", "Stade Brestois 29", "Le Havre", "Le Mans", "RC Lens", "LOSC Lille", "FC Lorient", "AS Monaco", "OGC Nice", "Olympique Lyonnais", "Olympique de Marseille", "Paris FC", "Paris Saint-Germain", "Stade Rennais", "RC Strasbourg", "Toulouse", "Troyes"],
    "LaLiga": ["Athletic Club", "Atlético Madrid", "FC Barcelona", "Celta Vigo", "Deportivo Alavés", "Deportivo La Coruña", "Elche", "Espanyol", "Getafe", "Levante UD", "Málaga", "CA Osasuna", "Real Racing Club de Santander", "Rayo Vallecano", "Real Betis", "Real Madrid", "Real Sociedad", "Sevilla", "Valencia", "Villarreal"],
    "Bundesliga": ["FC Augsburg", "Bayer 04 Leverkusen", "Bayern München", "Borussia Dortmund", "Borussia Mönchengladbach", "Eintracht Frankfurt", "SC Freiburg", "Hamburger SV", "TSG Hoffenheim", "1. FC Köln", "1. FSV Mainz 05", "SC Paderborn 07", "RB Leipzig", "FC Schalke 04", "VfB Stuttgart", "SV Elversberg", "1. FC Union Berlin", "SV Werder Bremen"],
    "Serie A": ["Atalanta", "Bologna", "Cagliari", "Como", "Fiorentina", "Frosinone", "Genoa", "Inter", "Juventus", "Lazio", "Lecce", "AC Milan", "Monza", "Napoli", "Parma", "AS Roma", "Sassuolo", "Torino", "Udinese", "Venezia"],
    "Eredivisie": ["ADO Den Haag", "Ajax", "AZ Alkmaar", "Excelsior", "Feyenoord", "Fortuna Sittard", "Go Ahead Eagles", "FC Groningen", "sc Heerenveen", "NEC Nijmegen", "PEC Zwolle", "PSV Eindhoven", "SC Cambuur", "Sparta Rotterdam", "Telstar", "FC Twente", "FC Utrecht", "Willem II"],
    "Championship": ["Birmingham City", "Blackburn Rovers", "Bolton Wanderers", "Bristol City", "Burnley", "Cardiff City", "Charlton Athletic", "Derby County", "Lincoln City", "Middlesbrough", "Millwall", "Norwich City", "Portsmouth", "Preston North End", "Queens Park Rangers", "Sheffield United", "Southampton", "Stoke City", "Swansea City", "Watford", "West Bromwich Albion", "West Ham United", "Wolverhampton", "Wrexham"],
}



def _resolve(name: str, league: str) -> str | None:
    return resolve_squawka_team(set(known_aliases_for(name)), set(SQUAWKA_TEAMS[league]))


@pytest.mark.parametrize("names_by_league", [FOOTBALL_DATA_NAMES, SOFASCORE_STYLE_NAMES], ids=["football-data", "sofascore-style"])
def test_every_team_in_every_covered_league_resolves_to_its_own_distinct_squawka_team(names_by_league):
    for league, names in names_by_league.items():
        resolved = {name: _resolve(name, league) for name in names}
        unresolved = [n for n, r in resolved.items() if r is None]
        assert unresolved == [], f"{league}: {unresolved}"
        assert len(set(resolved.values())) == len(names), f"{league}: two names claimed the same Squawka team"


@pytest.mark.parametrize("league", list(SQUAWKA_TEAMS))
def test_every_squawka_name_resolves_to_itself(league):
    for team in SQUAWKA_TEAMS[league]:
        assert resolve_squawka_team({team}, set(SQUAWKA_TEAMS[league])) == team


@pytest.mark.parametrize(
    ("name", "league", "expected"),
    [
        ("Coventry", "Premier League", "coventry city"),
        ("Tottenham", "Premier League", "tottenham hotspur"),
        ("Sociedad", "LaLiga", "real sociedad"),
        ("CA Osasuna", "LaLiga", "osasuna"),
        ("Celta Vigo", "LaLiga", "celta de vigo"),
        ("Den Haag", "Eredivisie", "ado den haag"),
        ("AZ Alkmaar", "Eredivisie", "az"),
        ("LOSC Lille", "Ligue 1", "lille"),
        ("Stade Brestois 29", "Ligue 1", "brest"),
        ("Inter", "Serie A", "internazionale"),
        ("Paris Saint-Germain", "Ligue 1", "psg"),
    ],
)
def test_specific_names_resolve_to_the_right_squawka_team(name, league, expected):
    assert _resolve(name, league) == expected


@pytest.mark.parametrize("ambiguous", ["Manchester", "United", "Real", "City", "Borussia"])
def test_an_ambiguous_name_matches_nothing_instead_of_guessing(ambiguous):
    teams = {t for league in SQUAWKA_TEAMS.values() for t in league}
    assert resolve_squawka_team({ambiguous.lower()}, teams) is None


def test_a_longer_extra_word_does_not_let_a_name_claim_another_teams_short_name():
    # "inter milan" contains AC Milan's whole name ("milan") but "inter" is
    # not a short decorative token, so it must NOT resolve to Milan.
    assert resolve_squawka_team({"inter milan"}, {"milan", "internazionale"}) is None


def test_exact_alias_match_wins_over_the_containment_fallback():
    assert resolve_squawka_team({"manchester united", "man utd"}, {"manchester united", "manchester city"}) == "manchester united"
