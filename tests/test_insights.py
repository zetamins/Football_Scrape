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
    # once a match is live or finished (formations, lineups, bench,
    # in-match stats, timeline, player of the match, and the
    # insights-level bench_info derived from bench/lineup) shouldn't
    # count against its completeness at all when the match genuinely
    # hasn't kicked off, the same way home_score/away_score already
    # didn't (_COMPLETENESS_EXCLUDE, unconditionally) -- this extends
    # that same idea to the rest of the outcome-only fields, but only
    # while not-yet-started, since they become real data once the match
    # is live or finished.
    merged = _all_none(MatchDetails, status="notstarted", referee="Some Ref")
    insights = _all_none(MatchInsights)
    result = compute_data_completeness(merged, insights)

    merged_finished = _all_none(MatchDetails, status="finished", referee="Some Ref")
    result_finished = compute_data_completeness(merged_finished, insights)

    # Same underlying (all-null) data, but the not-started run should
    # have a strictly smaller total -- outcome-only fields were removed
    # from the denominator, not merely scored as unpopulated.
    assert result["total"] < result_finished["total"]


def test_completeness_still_counts_outcome_only_fields_once_a_match_is_live_or_finished():
    merged_live = _all_none(MatchDetails, status="inprogress", home_formation="4-3-3")
    insights = _all_none(MatchInsights)
    result = compute_data_completeness(merged_live, insights)

    merged_finished = _all_none(MatchDetails, status="finished", home_formation="4-3-3")
    result2 = compute_data_completeness(merged_finished, insights)

    # Both count home_formation in the total (and as populated, since a
    # real value is set) -- outcome-only exclusion only applies to
    # not-started matches.
    assert result["total"] == result2["total"]


def test_completeness_never_undercounts_a_real_populated_outcome_field():
    # Confirmed live this matters: home_formation/away_formation are
    # Optional[str], so an unplayed match's genuinely-empty value is ""
    # -- this isn't about that bug directly, but confirms a REAL
    # early-announced formation for a not-started match is still
    # excluded from the denominator by design (it's an outcome-only
    # field regardless of whether it happens to be populated early).
    merged = _all_none(MatchDetails, status="notstarted", home_formation="4-3-3")
    insights = _all_none(MatchInsights)
    result = compute_data_completeness(merged, insights)

    merged_without = _all_none(MatchDetails, status="notstarted", home_formation=None)
    result_without = compute_data_completeness(merged_without, insights)

    assert result["total"] == result_without["total"]
