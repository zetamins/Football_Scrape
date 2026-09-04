import asyncio

from football.sites import refsradar
from football.sites.refsradar import (
    _extract_kpi,
    _find_referee_url,
    _normalize,
    _slug_to_name,
    get_referee_fouls_per_game,
    get_referee_kpis,
    get_referee_red_cards_per_game,
)


def test_normalize_strips_diacritics_and_punctuation():
    assert _normalize("Björn Kuipers!") == "bjorn kuipers"


def test_slug_to_name_strips_trailing_numeric_id():
    assert _slug_to_name("craig-pawson-367") == "craig pawson"


def test_slug_to_name_without_trailing_id():
    assert _slug_to_name("c-pawson") == "c pawson"


def test_extract_kpi_parses_real_shape():
    html = '<span class="lab">Fouls/g</span><span class="val num">22.08</span>'
    assert _extract_kpi(html, "Fouls/g") == 22.08


def test_extract_kpi_tolerates_extra_attributes_on_val_span():
    html = '<span class="lab">RED/g</span><span class="val num" style="color:var(--red)">0.12</span>'
    assert _extract_kpi(html, "RED/g") == 0.12


def test_extract_kpi_none_when_label_not_found():
    assert _extract_kpi("<html>no kpis here</html>", "Fouls/g") is None


def test_extract_kpi_does_not_collide_with_unrelated_page_text():
    # A bare label appearing elsewhere on the page (e.g. as a nav link)
    # must not be mistaken for the real KPI -- only the class="lab"
    # wrapper form counts.
    html = '<a>Matches</a><span class="lab">Fouls/g</span><span class="val num">10.5</span>'
    assert _extract_kpi(html, "Matches") is None


# --- _find_referee_url (async) ------------------------------------------------------------


_SITEMAP = (
    "<url><loc>https://refsradar.com/referees/craig-pawson-367</loc></url>"
    "<url><loc>https://refsradar.com/referees/c-pawson-1178</loc></url>"
    "<url><loc>https://refsradar.com/referees/michael-oliver-42</loc></url>"
)


def test_find_referee_url_prefers_the_longer_full_name_slug(monkeypatch):
    async def fake_fetch_text(_url):
        return _SITEMAP

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    url = asyncio.run(_find_referee_url("Craig Pawson"))
    assert url == "https://refsradar.com/referees/craig-pawson-367"


def test_find_referee_url_none_without_a_match(monkeypatch):
    async def fake_fetch_text(_url):
        return _SITEMAP

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    assert asyncio.run(_find_referee_url("Some Unrelated Ref")) is None


# --- get_referee_kpis / get_referee_fouls_per_game / get_referee_red_cards_per_game (async) --


_PROFILE_HTML = (
    '<span class="lab">Fouls/g</span><span class="val num">22.08</span>'
    '<span class="lab">RED/g</span><span class="val num">0.12</span>'
    '<span class="lab">Matches</span><span class="val num">30</span>'
    '<span class="lab">YEL/g</span><span class="val num">3.5</span>'
    '<span class="lab">Pens/g</span><span class="val num">0.2</span>'
    '<span class="lab">Cards/foul</span><span class="val num">0.15</span>'
    '<span class="lab">Avg total cards</span><span class="val num">4.1</span>'
)


def test_get_referee_kpis_none_without_a_referee_name():
    assert asyncio.run(get_referee_kpis(None)) is None


def test_get_referee_kpis_none_when_referee_url_not_found(monkeypatch):
    async def fake_fetch_text(_url):
        return _SITEMAP

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    assert asyncio.run(get_referee_kpis("Some Unrelated Ref")) is None


def test_get_referee_kpis_none_when_sitemap_fetch_raises(monkeypatch):
    async def failing_fetch_text(_url):
        raise RuntimeError("blocked")

    monkeypatch.setattr(refsradar, "fetch_text", failing_fetch_text)
    assert asyncio.run(get_referee_kpis("Craig Pawson")) is None


def test_get_referee_kpis_none_when_profile_fetch_raises(monkeypatch):
    async def fake_fetch_text(url):
        if "sitemap" in url:
            return _SITEMAP
        raise RuntimeError("blocked")

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    assert asyncio.run(get_referee_kpis("Craig Pawson")) is None


def test_get_referee_kpis_extracts_all_seven_kpis(monkeypatch):
    async def fake_fetch_text(url):
        return _SITEMAP if "sitemap" in url else _PROFILE_HTML

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    kpis = asyncio.run(get_referee_kpis("Craig Pawson"))
    assert kpis.fouls_per_game == 22.08
    assert kpis.red_cards_per_game == 0.12
    assert kpis.matches == 30
    assert kpis.yellow_cards_per_game == 3.5
    assert kpis.penalties_per_game == 0.2
    assert kpis.cards_per_foul == 0.15
    assert kpis.avg_total_cards == 4.1


def test_get_referee_kpis_matches_none_when_not_parseable(monkeypatch):
    async def fake_fetch_text(url):
        return _SITEMAP if "sitemap" in url else "<html>no kpis here</html>"

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    kpis = asyncio.run(get_referee_kpis("Craig Pawson"))
    assert kpis.matches is None
    assert kpis.fouls_per_game is None


def test_get_referee_fouls_per_game_reads_from_kpis(monkeypatch):
    async def fake_fetch_text(url):
        return _SITEMAP if "sitemap" in url else _PROFILE_HTML

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    assert asyncio.run(get_referee_fouls_per_game("Craig Pawson")) == 22.08


def test_get_referee_fouls_per_game_none_without_kpis(monkeypatch):
    async def fake_fetch_text(_url):
        return _SITEMAP

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    assert asyncio.run(get_referee_fouls_per_game("Some Unrelated Ref")) is None


def test_get_referee_red_cards_per_game_reads_from_kpis(monkeypatch):
    async def fake_fetch_text(url):
        return _SITEMAP if "sitemap" in url else _PROFILE_HTML

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    assert asyncio.run(get_referee_red_cards_per_game("Craig Pawson")) == 0.12


def test_get_referee_red_cards_per_game_none_without_kpis(monkeypatch):
    async def fake_fetch_text(_url):
        return _SITEMAP

    monkeypatch.setattr(refsradar, "fetch_text", fake_fetch_text)
    assert asyncio.run(get_referee_red_cards_per_game("Some Unrelated Ref")) is None
