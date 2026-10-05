from football.oracle import context as C
from football.oracle.facts import audit_facts, extract_facts
from football.oracle.lineup import lineup_picture
from test_oracle import _report


def _xi(names):
    return [{"name": n, "position": "M", "substitute": False} for n in names]


def _facts(**kw):
    return extract_facts(_report(**kw))


def test_absentees_are_classified_by_playing_time_and_unknown_is_not_zero():
    rep = _report(home_missing=[{"name": "H1", "description": "Knee"}, {"name": "Nobody"}])
    rep["teamProfile"]["squad"][2]["recent_usage"]["total_minutes"] = 60  # H2: rotation-level minutes
    pic = lineup_picture(extract_facts(rep))
    status = {a["name"]: a["status"] for a in pic["home"]["absentees"]}
    assert status == {"H1": "starter", "Nobody": "unknown"}
    assert pic["home"]["starters_out"] == ["H1"]


def test_fringe_and_rotation_thresholds():
    rep = _report(home_missing=[{"name": "H1"}, {"name": "H2"}])
    rep["teamProfile"]["squad"][1]["recent_usage"]["total_minutes"] = 150  # 33%
    rep["teamProfile"]["squad"][2]["recent_usage"]["total_minutes"] = 20
    status = {a["name"]: a["status"] for a in lineup_picture(extract_facts(rep))["home"]["absentees"]}
    assert status == {"H1": "rotation", "H2": "fringe"}


def test_audit_flags_overlap_missing_in_xi_and_unlisted_names():
    rep = _report(home_lineup=_xi(["H1", "Zed"]), away_lineup=_xi(["H1", "A1"]), home_missing=[{"name": "H1"}])
    codes = {f["code"] for f in audit_facts(extract_facts(rep))["findings"]}
    assert {"xi_overlap", "missing_in_xi", "xi_not_in_squad"} <= codes


def test_injured_in_xi_and_empty_absentee_list():
    rep = _report(home_lineup=_xi(["H1"]))
    rep["teamProfile"]["squad"][1]["injury"] = {"type": "Hamstring"}
    findings = audit_facts(extract_facts(rep))["findings"]
    codes = {f["code"] for f in findings}
    assert {"injured_in_xi", "empty_absentee_list"} <= codes


def test_clean_lineup_has_no_lineup_warnings():
    codes = {f["code"] for f in audit_facts(_facts())["findings"]}
    assert not codes & {"xi_overlap", "missing_in_xi", "injured_in_xi", "xi_not_in_squad", "empty_absentee_list", "heavy_rotation"}


def test_heavy_rotation_only_when_it_is_not_a_whole_xi_artefact():
    rep = _report()
    rep["insights"]["home_rotation"] = {"changed_players": 8, "starting_xi_size": 11}
    rep["insights"]["away_rotation"] = {"changed_players": 11, "starting_xi_size": 11}
    pic = lineup_picture(extract_facts(rep))
    assert pic["home"]["heavy_rotation"] is True and pic["away"]["heavy_rotation"] is False


def test_brief_shows_availability_and_warns_when_the_xi_is_unconfirmed():
    rep = _report(home_missing=[{"name": "H1"}, {"name": "Nobody"}], lineup_confirmed=False, home_lineup=_xi(["H3"]))
    facts = extract_facts(rep)
    text, tags = C.build_brief(facts, {"lam_home": 1.4, "lam_away": 1.0, "home": 0.45, "draw": 0.27, "away": 0.28}, "independent")[:2]
    assert "[H.availability]" in tags
    assert "H1 = starter" in text and "Nobody = unknown" in text
    assert "guesses" in text
