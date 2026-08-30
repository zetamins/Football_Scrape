from dataclasses import fields as _dc_fields

from football.insights import _parse_xg_stat_value, compute_data_completeness
from football.types import MatchDetails, MatchInsights


def _all_none(cls, **overrides):
    """Constructs a dataclass instance with every field defaulted to
    None, overridden as needed -- MatchDetails/MatchInsights are entirely
    Optional[...] fields, so this avoids hand-listing dozens of them just
    to test one function that only cares about a handful."""
    base = {f.name: None for f in _dc_fields(cls)}
    base.update(overrides)
    return cls(**base)


def test_parses_genuine_zero_xg_as_zero_not_none():
    # Regression test: a prior `float(raw) or None` implementation turned
    # a real 0.0 xG (Python falsy-zero) into a misleading null, silently
    # conflating "the team had 0.00 xG" with "xG wasn't published".
    assert _parse_xg_stat_value("0") == 0.0
    assert _parse_xg_stat_value("0.0") == 0.0


def test_parses_real_nonzero_xg():
    assert _parse_xg_stat_value("1.85") == 1.85


def test_returns_none_for_unparseable_value():
    assert _parse_xg_stat_value("N/A") is None


def test_returns_none_for_missing_value():
    assert _parse_xg_stat_value(None) is None


def test_completeness_does_not_count_outcome_only_fields_for_an_unplayed_match():
    # An upcoming fixture's real analytical value is pre-match
    # (difficulty/rest/form comparisons) -- fields that can only exist
    # once a match is live or finished (attendance, in-match stats,
    # timeline, player of the match) shouldn't count against its
    # completeness at all when the match genuinely hasn't kicked off,
    # the same way home_score/away_score already didn't
    # (_COMPLETENESS_EXCLUDE, unconditionally) -- this extends that same
    # idea to the rest of the TRUE outcome-only fields, but only while
    # not-yet-started, since they become real data once the match is
    # live or finished. Lineup/bench/formation are deliberately NOT in
    # this set -- see the next test.
    merged = _all_none(MatchDetails, status="notstarted", referee="Some Ref")
    insights = _all_none(MatchInsights)
    result = compute_data_completeness(merged, insights)

    merged_finished = _all_none(MatchDetails, status="finished", referee="Some Ref")
    result_finished = compute_data_completeness(merged_finished, insights)

    # Same underlying (all-null) data, but the not-started run should
    # have a strictly smaller total -- outcome-only fields were removed
    # from the denominator, not merely scored as unpopulated.
    assert result["total"] < result_finished["total"]


def test_completeness_still_counts_lineup_and_bench_info_for_an_unplayed_match():
    # Sofascore's own lineups payload goes absent -> predicted ->
    # confirmed (football/sites/sofascore.py's `lineup_confirmed`
    # field/comment) -- a predicted starting XI, built from recent
    # matches and injury news, can legitimately exist well before
    # kickoff. So unlike attendance/match_stats/event_timeline/
    # player_of_the_match, home_lineup/away_lineup/home_bench/
    # away_bench/home_formation/away_formation (and the insights-level
    # home_bench_info/away_bench_info computed from them) must NOT be
    # excluded from the denominator for a not-started match -- their
    # absence there is real, informative "not published yet", the same
    # as referee/odds, not a category error.
    merged_not_started = _all_none(MatchDetails, status="notstarted")
    merged_finished = _all_none(MatchDetails, status="finished")
    insights = _all_none(MatchInsights)

    result_not_started = compute_data_completeness(merged_not_started, insights)
    result_finished = compute_data_completeness(merged_finished, insights)

    # The not-started total is still smaller than finished's -- but only
    # by the 4 TRUE outcome-only fields (attendance, match_stats,
    # event_timeline, player_of_the_match), not by lineup/bench/
    # formation/bench_info too. If those were still being excluded
    # pre-kickoff, the gap would be larger than 4.
    assert result_finished["total"] - result_not_started["total"] == 4


def test_completeness_counts_a_real_checked_empty_card_risks_list_as_populated():
    # Confirmed live: a Liverpool/Ipswich run returned home_card_risks
    # == away_card_risks == [] (not None) -- both squads genuinely have
    # no player at 4+ yellows or a red card yet this season, a real,
    # checked result from compute_card_risks, not missing data. The
    # generic list-emptiness check in _is_populated would otherwise
    # score this identically to never having squad data at all.
    merged = _all_none(MatchDetails, status="finished")
    insights_with_real_empty = _all_none(MatchInsights, home_card_risks=[], away_card_risks=[])
    insights_with_none = _all_none(MatchInsights, home_card_risks=None, away_card_risks=None)

    result_with = compute_data_completeness(merged, insights_with_real_empty)
    result_without = compute_data_completeness(merged, insights_with_none)

    assert result_with["total"] == result_without["total"]
    assert result_with["populated"] == result_without["populated"] + 2


def test_completeness_counts_duel_vulnerabilities_and_fullback_exposure_the_same_way():
    merged = _all_none(MatchDetails, status="finished")
    insights = _all_none(
        MatchInsights,
        home_duel_vulnerabilities=[], away_duel_vulnerabilities=[],
        home_fullback_exposure=[], away_fullback_exposure=[],
    )
    insights_none = _all_none(MatchInsights)

    result = compute_data_completeness(merged, insights)
    result_none = compute_data_completeness(merged, insights_none)

    assert result["populated"] == result_none["populated"] + 4


def test_completeness_credits_a_real_predicted_formation_for_a_not_started_match():
    # A predicted formation published ahead of kickoff is real,
    # meaningful data -- it should raise the populated count for a
    # not-started match, not be discarded/ignored just because the
    # match hasn't happened yet.
    merged_with = _all_none(MatchDetails, status="notstarted", home_formation="4-3-3")
    merged_without = _all_none(MatchDetails, status="notstarted", home_formation=None)
    insights = _all_none(MatchInsights)

    result_with = compute_data_completeness(merged_with, insights)
    result_without = compute_data_completeness(merged_without, insights)

    # Same total either way (the field is always counted at every
    # status now), but populated is strictly higher when a real
    # predicted formation is present.
    assert result_with["total"] == result_without["total"]
    assert result_with["populated"] > result_without["populated"]
