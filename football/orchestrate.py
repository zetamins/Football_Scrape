"""The full fetch/merge/compute pipeline -- run_search() ties together
every site scraper, the merge layer, form computation, and every insight.
Ported from src/search.ts's runSearch() and its immediate helpers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from . import insights as ins
from .calibration import compute_calibration
from .elo import compute_elo_rating, with_league_rank
from .fetch_log import record_step_failure
from .form import (
    NOT_STARTED_STATUSES,
    all_form_results,
    compute_form_summary,
    enrich_form_with_venue_classification,
    is_team_home,
    next_match,
)
from .insights import OpponentContext
from .merge import (
    SOURCE_ORDER,
    MergedMatch,
    MergedProfile,
    SourceConflict,
    SourceValue,
    apply_deep_recent_meetings,
    compute_bench_regulars,
    compute_recent_form_leaders,
    compute_role_form_breakdown,
    compute_top_defenders,
    compute_top_performers,
    is_attacker_role,
    is_defender_role,
    is_goalkeeper_role,
    is_match_details_complete,
    is_midfield_role,
    is_profile_complete,
    merge_match_details,
    merge_team_profile,
    reconcile_missing_by_role,
    reconcile_missing_players,
)
from .prediction import compute_match_prediction
from .sites import (
    footballdata,
    fotmob,
    goal,
    refsradar,
    soccerdesk,
    stadiumdb,
    statsultra,
    three65scores,
    wikipedia,
    worldfootball,
    wttrin,
)
from .sites import sofascore as sofascore_site
from .team_aliases import same_team
from .types import (
    CalibrationSummary,
    ManagerTenureRecord,
    MatchDetails,
    MatchInfo,
    MatchInsights,
    Source,
    TeamProfile,
    VenueDetails,
)


@dataclass
class _Scraper:
    run: Callable[[str], Awaitable[list[MatchInfo]]]
    details: Callable[[MatchInfo], Awaitable[MatchDetails]]
    profile: Callable[[str], Awaitable[TeamProfile]]


# The one place all 5 per-team sources are registered. Sofascore is the
# base/primary source for the merged report -- every other source only
# supplements fields Sofascore doesn't have (see merge.SOURCE_ORDER).
SCRAPERS: dict[Source, _Scraper] = {
    "sofascore": _Scraper(sofascore_site.get_sofascore_matches, sofascore_site.get_sofascore_match_details, sofascore_site.get_sofascore_team_profile),
    "fotmob": _Scraper(fotmob.get_fotmob_matches, fotmob.get_fotmob_match_details, fotmob.get_fotmob_team_profile),
    "soccerdesk": _Scraper(soccerdesk.get_soccerdesk_matches, soccerdesk.get_soccerdesk_match_details, soccerdesk.get_soccerdesk_team_profile),
    "goal": _Scraper(goal.get_goal_matches, goal.get_goal_match_details, goal.get_goal_team_profile),
    "365scores": _Scraper(three65scores.get365_scores_matches, three65scores.get365_scores_match_details, three65scores.get365_scores_team_profile),
}


def _error_text(err: BaseException) -> str:
    """str(err) is "" for an exception raised with no message, which would
    read as "no error" in SourceStatus -- fall back to the class name."""
    return str(err) or type(err).__name__


def _age_from_iso_date(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    try:
        dob = datetime.fromisoformat(iso_date).replace(tzinfo=UTC)
    except ValueError:
        return None
    return int((datetime.now(tz=UTC) - dob).days / 365.25)


async def _fetch_opponent_matches(base_source: Source, opponent_name: str) -> tuple[list[MatchInfo], Source | None, str | None]:
    """First source (base_source, then the rest of SOURCE_ORDER) whose
    matches() call succeeds wins. Extracted from fetch_opponent_context to
    keep its own cognitive complexity down (python:S3776) -- behavior
    unchanged."""
    matches: list[MatchInfo] = []
    matches_source: Source | None = None
    error: str | None = None
    for source in (base_source, *[s for s in SOURCE_ORDER if s != base_source]):
        try:
            candidate = await SCRAPERS[source].run(opponent_name)
        except Exception as err:  # noqa: BLE001 - mirrors TS's catch (err: any)
            # str(err) is "" for an exception raised with no message --
            # falling back to the class name keeps this a real signal
            # instead of an empty string that later reads as "no error"
            # (see fetch_opponent_context's error-combination logic).
            msg = str(err) or type(err).__name__
            error = f"{error}; {msg}" if error else msg
            continue
        if candidate:
            matches = candidate
            matches_source = source
            break
    return matches, matches_source, error


def _compute_rest_days(matches: list[MatchInfo], now: datetime) -> int | None:
    """Days since the opponent's most recent already-played match, if any."""
    played = sorted(
        (m for m in matches if m.kickoff_utc and datetime.fromisoformat(m.kickoff_utc.replace("Z", _UTC_OFFSET_SUFFIX)) < now),
        key=lambda m: m.kickoff_utc,
        reverse=True,
    )
    if played and played[0].kickoff_utc:
        last_dt = datetime.fromisoformat(played[0].kickoff_utc.replace("Z", _UTC_OFFSET_SUFFIX))
        return round((now - last_dt).total_seconds() / 86400)
    return None


async def _fetch_opponent_profiles(opponent_name: str) -> tuple[dict[Source, TeamProfile], str | None]:
    """Every source's profile() call, best-effort -- same multi-source
    fetch the searched team's own profile already goes through (see
    merge_team_profile's call sites)."""
    profile_by_source: dict[Source, TeamProfile] = {}
    error: str | None = None
    for source in SOURCE_ORDER:
        try:
            profile_by_source[source] = await SCRAPERS[source].profile(opponent_name)
        except Exception as err:  # noqa: BLE001
            # See _fetch_opponent_matches' identical fallback for why.
            msg = str(err) or type(err).__name__
            error = f"{error}; {msg}" if error else msg
    return profile_by_source, error


async def fetch_opponent_context(base_source: Source, opponent_name: str, as_of: datetime | None = None) -> OpponentContext:
    """Matches try base_source first, then fall back through the rest of
    SOURCE_ORDER -- same "first source that actually has it wins" pattern
    already used for the searched team's own form_source (see run_search
    below), and for the profile merge just below this. Previously this
    was base_source-only with no fallback: whenever base_source alone
    couldn't find the opponent (blocked, rate-limited, name-match miss),
    opponent form -- and everything derived from it (rotation, resilience,
    rest performance, advanced stats, roughly a third of MatchInsights)
    -- went empty for the whole run, even though other sources often still
    had the opponent's fixture list. The profile already goes through the
    exact same multi-source fetch-then-merge as the searched team's own
    profile -- up to 5 requests either way, same as the main team.

    as_of: the reference point for rest_days ("days since the opponent's
    last match"). Defaults to wall-clock now for callers that don't have
    a specific match in mind, but run_search passes the upcoming match's
    own kickoff time -- confirmed live: using wall-clock now instead made
    the searched team's own rest days (computed relative to its next
    fixture's kickoff, via next5_with_gaps) and the opponent's rest days
    (previously always relative to whenever the report happened to run)
    silently disagree by however long had elapsed since generation,
    typically off by a day from the true kickoff-relative count."""
    as_of = as_of or datetime.now(tz=UTC)
    matches, matches_source, matches_error = await _fetch_opponent_matches(base_source, opponent_name)
    rest_days = _compute_rest_days(matches, as_of)
    opponent_profile_by_source, profile_error = await _fetch_opponent_profiles(opponent_name)
    # Same joined-string shape the original single-loop version produced
    # (both loops used to share one `error` accumulator sequentially).
    error = f"{matches_error}; {profile_error}" if matches_error and profile_error else (matches_error or profile_error)

    merged_profile = merge_team_profile(opponent_profile_by_source) if opponent_profile_by_source else None

    return OpponentContext(
        rest_days=rest_days,
        average_age=(merged_profile.average_age if merged_profile else None),
        merged_profile=merged_profile,
        matches=matches,
        error=error,
        matches_source=matches_source,
    )


async def fetch_venue_details(merged: MergedMatch, venue_country: str | None) -> VenueDetails | None:
    """Tries the home club first, then the away club -- StadiumDB is
    indexed by club, so a neutral-venue match correctly resolves to
    nothing rather than a wrong guess."""
    try:
        result = await stadiumdb.get_stadium_db_venue_details(merged.home_team, venue_country)
        if result:
            return result
        return await stadiumdb.get_stadium_db_venue_details(merged.away_team, venue_country)
    except Exception as err:  # noqa: BLE001 - mirrors TS's catch { return null }
        record_step_failure("venue details (StadiumDB)", err)
        return None


@dataclass
class SourceStatus:
    source: Source
    fixtures_scraped: int = 0
    matches_error: str | None = None
    details_error: str | None = None
    profile_error: str | None = None
    # True when this source was never queried because the base source
    # (first in SOURCE_ORDER, normally Sofascore) already had everything
    # a fallback source could have contributed -- see _scrape_all_sources.
    skipped: bool = False


@dataclass
class RunSearchResult:
    """Everything run_search() returns, keyed exactly the way the CLI's
    JSON output file already shapes it (see report.build_report_json) --
    both the CLI and any other caller (e.g. a future Android UI) consume
    the same shape, computed by the same single code path."""

    team: str
    generated_at: str
    statuses: list[SourceStatus]
    merged: MergedMatch | None
    opponent_name: str | None
    form: object | None
    form_source: Source | None
    opponent_form: object | None
    opponent_form_source: Source | None
    merged_profile: MergedProfile | None
    opponent_profile: MergedProfile | None
    insights: MatchInsights | None
    venue_details: VenueDetails | None
    # None unless the caller supplied past predictions to score (see
    # calibration.py).
    calibration: CalibrationSummary | None = None


@dataclass
class _MatchContext:
    """Return shape of _compute_match_context() -- everything run_search
    needs once an upcoming match was found, gathered in one place so that
    function can stay a single, flat, easily-testable return."""

    opponent_name: str | None
    opponent_profile: MergedProfile | None
    opponent_form: object | None
    opponent_form_source: Source | None
    insights_result: MatchInsights
    venue_details: VenueDetails | None
    form: object | None


_NOOP_PROGRESS: Callable[[str], None] = lambda msg: None
_NOOP_SOURCE_PROGRESS: Callable[[SourceStatus], None] = lambda status: None

# datetime.fromisoformat() can't parse a trailing "Z" directly -- swapped
# for an explicit UTC offset it does understand.
_UTC_OFFSET_SUFFIX = "+00:00"

# Fixed total for the post-scrape "insights" phase specifically (the
# 5-source scrape loop already has its own good progress signal in the
# UI -- a per-source checkmark list -- so this counter is scoped to the
# phase that previously had NO numeric indicator at all: a search could
# sit on one static message for minutes with nothing visibly advancing,
# indistinguishable from a hang. See _step_message()'s call sites for
# what each of the 6 steps covers.
_INSIGHTS_TOTAL_STEPS = 6


def _step_message(step: int, message: str) -> str:
    """`(step/6) message` -- a fixed, always-advancing counter prefix so
    a caller watching on_progress text (e.g. Android's SearchScreen) has
    a numeric "how far along is this" signal even during a stretch where
    the message text itself wouldn't otherwise change for a while."""
    return f"({step}/{_INSIGHTS_TOTAL_STEPS}) {message}"


def _home_away(own_is_home: bool, own_val, opponent_val):
    """Every per-team stat computed as (own vs opponent) but stored as
    (home vs away) in MatchInsights follows this exact swap -- pulled out
    once so run_search's many "X if own_is_home else Y" / "Y if
    own_is_home else X" pairs collapse to a single flat call each,
    instead of contributing two branches apiece to cognitive complexity
    (python:S3776)."""
    return (own_val, opponent_val) if own_is_home else (opponent_val, own_val)


def _base_source_already_complete(
    base_source: Source, matches_by_source: dict, details_by_source: dict, profile_by_source: dict
) -> bool:
    """True once the base source (SOURCE_ORDER[0], normally Sofascore) has
    fixtures AND a fully-populated upcoming match's details AND a fully-
    populated team profile -- at that point no other source has anything
    left to contribute (see is_match_details_complete/is_profile_complete),
    so _scrape_all_sources skips them entirely rather than scraping and
    then discarding all five sources' worth of data every run."""
    return (
        bool(matches_by_source.get(base_source))
        and base_source in details_by_source and is_match_details_complete(details_by_source[base_source])
        and base_source in profile_by_source and is_profile_complete(profile_by_source[base_source])
    )


async def _scrape_one_source(
    source: Source, team_name: str, matches_by_source: dict, details_by_source: dict, profile_by_source: dict
) -> SourceStatus:
    """The single-source fetch body of _scrape_all_sources, extracted to
    keep that function's own cognitive complexity down (python:S3776);
    behavior unchanged."""
    scraper = SCRAPERS[source]
    status = SourceStatus(source=source)

    try:
        matches = await scraper.run(team_name)
        matches_by_source[source] = matches
        status.fixtures_scraped = len(matches)

        next_m = next_match(matches)
        if next_m:
            try:
                details_by_source[source] = await scraper.details(next_m)
            except Exception as err:  # noqa: BLE001
                status.details_error = _error_text(err)
                record_step_failure(f"{source} match details", err)
    except Exception as err:  # noqa: BLE001
        status.matches_error = _error_text(err)
        record_step_failure(f"{source} matches", err)

    try:
        profile_by_source[source] = await scraper.profile(team_name)
    except Exception as err:  # noqa: BLE001
        status.profile_error = _error_text(err)
        record_step_failure(f"{source} team profile", err)

    return status


async def _scrape_all_sources(
    team_name: str,
    on_progress: Callable[[str], None],
    on_source_progress: Callable[[SourceStatus], None],
) -> tuple[dict[Source, list[MatchInfo]], dict[Source, MatchDetails], dict[Source, TeamProfile], list[SourceStatus]]:
    """The sequential-not-parallel per-source scrape loop -- extracted
    from run_search purely to keep its own cognitive complexity low
    (python:S3776). Sequential, not parallel -- Sofascore is rate-
    sensitive (Cloudflare), so we never want another source's traffic
    overlapping with its requests.

    Sofascore (SOURCE_ORDER[0], always tried first) is the base source;
    every source after it is skipped entirely once Sofascore's own
    fixtures/details/profile already cover everything a fallback source
    exists to fill in (see _base_source_already_complete) -- there is
    nothing left for another source to contribute, so there is no reason
    to fetch and then discard its data."""
    matches_by_source: dict[Source, list[MatchInfo]] = {}
    details_by_source: dict[Source, MatchDetails] = {}
    profile_by_source: dict[Source, TeamProfile] = {}
    statuses: list[SourceStatus] = []
    base_source = SOURCE_ORDER[0]

    for source in SOURCE_ORDER:
        if source != base_source and _base_source_already_complete(base_source, matches_by_source, details_by_source, profile_by_source):
            status = SourceStatus(source=source, skipped=True)
            on_progress(f"{source}: skipped -- {base_source} already has everything needed")
        else:
            on_progress(f"Scraping {source}...")
            status = await _scrape_one_source(source, team_name, matches_by_source, details_by_source, profile_by_source)
            on_progress(f"{source}: {status.fixtures_scraped} fixtures" + (f" -- {status.matches_error}" if status.matches_error else ""))

        statuses.append(status)
        on_source_progress(status)

    return matches_by_source, details_by_source, profile_by_source, statuses


_FLIPPED_VENUE = {"home": "away", "away": "home"}


async def _refine_undetailed_meetings(team_name, merged, opponent_name, form_source) -> None:
    """Meetings only a fallback source (Fotmob/SoccerDesk) knows -- too old
    for the deep computation's fixture window -- carry no venue facts, so a
    neutral-ground final was labelled plain home/away. Look those up in
    Sofascore's older event pages (see get_sofascore_older_meeting_info)
    and correct venue + who hosted. Only when Sofascore is the form source;
    a failure leaves the fallback labels as they were, and is reported."""
    if form_source != "sofascore" or not merged.recent_meetings:
        return
    wanted = {m.date[:10] for m in merged.recent_meetings if m.date and m.home_lineup is None and m.home_formation is None}
    if not wanted:
        return
    try:
        info_by_day = await sofascore_site.get_sofascore_older_meeting_info(team_name, opponent_name, wanted)
    except Exception as err:  # noqa: BLE001
        record_step_failure("older meetings venue (Sofascore)", err)
        return
    refined = []
    for m in merged.recent_meetings:
        info = info_by_day.get(m.date[:10]) if m.date else None
        if info is None:
            refined.append(m)
            continue
        if info.neutral:
            venue = "neutral"
        elif same_team(info.home_team, merged.home_team):
            venue = "home"
        else:
            venue = "away"
        refined.append(replace(m, venue=venue, home_team=info.home_team, away_team=info.away_team))
    merged.recent_meetings = refined


def _meetings_in_fixture_frame(meetings, own_is_home: bool | None):
    """The deep computation labels each meeting's venue from the SEARCHED
    team's side; every other source (and HeadToHeadMeeting.venue's
    documented frame) uses the upcoming fixture's HOME team. They only
    coincide when the searched team is the fixture's home side, so flip
    when it's the away side ("neutral" is side-independent)."""
    if not meetings or own_is_home is not False:
        return meetings
    return [replace(m, venue=_FLIPPED_VENUE.get(m.venue, m.venue)) for m in meetings]


async def _apply_own_recent_meetings_and_form(team_name, merged, form_source, form, matches_by_source, opponent_name, merged_profile):
    """Deep Sofascore recent-meetings + venue-classified form enrichment
    for the searched team. Returns the (possibly re-enriched) form plus
    own_advanced_stats, since both feed later steps."""
    if form_source and form:
        # The deep Sofascore-based computation (formations/xG per
        # meeting, from the already-fetched last20Overall enrichment)
        # is richer than any other source's own recent_meetings field,
        # so it takes priority when it succeeds -- but doesn't clobber
        # a decent fallback the field-merge already filled in (e.g.
        # from SoccerDesk) when it comes back empty. Searches the full
        # match history (all_form_results), not just last20_overall --
        # two teams often haven't met within that smaller window at all.
        try:
            full_history = all_form_results(team_name, matches_by_source[form_source])
            deep_recent_meetings = await ins.compute_recent_meetings(matches_by_source[form_source], full_history, opponent_name, form_source)
        except Exception as err:  # noqa: BLE001
            record_step_failure("recent meetings", err)
            deep_recent_meetings = None
        apply_deep_recent_meetings(merged, _meetings_in_fixture_frame(deep_recent_meetings, is_team_home(merged, team_name)), form_source)
        await _refine_undetailed_meetings(team_name, merged, opponent_name, form_source)

    own_advanced_stats = None
    if form_source and form:
        try:
            enriched_own = await enrich_form_with_venue_classification(matches_by_source[form_source], form, form_source)
        except Exception as err:  # noqa: BLE001
            record_step_failure("form enrichment (own team)", err)
            from .form import VenueEnrichmentResult

            enriched_own = VenueEnrichmentResult(form=form, advanced_stats=None, usage_by_player={})
        form = enriched_own.form
        own_advanced_stats = enriched_own.advanced_stats
        if merged_profile:
            merged_profile.squad = ins.apply_usage_pattern(merged_profile.squad, enriched_own.usage_by_player)

    return form, own_advanced_stats


async def _enrich_manager_tenure(manager, team_name: str):
    """Tenure/appointment/previous-manager lookups against Wikipedia for
    one manager -- shared by both home_manager and away_manager, which
    previously duplicated this whole block inline in run_search once per
    side."""
    if not manager:
        return manager
    try:
        tenure_row = await wikipedia.get_current_tenure_row(manager.name)
    except Exception as err:  # noqa: BLE001
        record_step_failure("manager tenure (Wikipedia)", err)
        tenure_row = None
    appointed_date = wikipedia.parse_wiki_date(tenure_row.from_date) if tenure_row and tenure_row.from_date else None
    record_at_club = (
        ManagerTenureRecord(played=tenure_row.played, wins=tenure_row.wins, draws=tenure_row.draws, losses=tenure_row.losses, win_pct=tenure_row.win_pct)
        if tenure_row and tenure_row.played is not None and tenure_row.wins is not None and tenure_row.draws is not None and tenure_row.losses is not None
        else None
    )
    manager_age = _age_from_iso_date(tenure_row.date_of_birth) if tenure_row else None
    try:
        previous_manager = await wikipedia.get_previous_manager(team_name)
    except Exception as err:  # noqa: BLE001
        record_step_failure("previous manager (Wikipedia)", err)
        previous_manager = None
    from dataclasses import replace as _replace

    return _replace(
        manager, appointed_date=appointed_date, previous_manager=previous_manager,
        recent_appointment=ins.is_recent_appointment(appointed_date), record_at_club=record_at_club,
        age=manager_age,
    )


async def _fetch_referee_source_stats(merged):
    """Extracted from _enrich_referee_stats to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    try:
        worldfootball_stats = await worldfootball.get_referee_worldfootball_stats(merged.competition, merged.referee)
    except Exception as err:  # noqa: BLE001
        record_step_failure("referee stats (WorldFootball)", err)
        worldfootball_stats = None
    try:
        home_away_bias = await footballdata.get_referee_home_away_bias(merged.competition, merged.referee)
    except Exception as err:  # noqa: BLE001
        record_step_failure("referee bias (football-data)", err)
        home_away_bias = None
    try:
        refsradar_kpis = await refsradar.get_referee_kpis(merged.referee)
    except Exception as err:  # noqa: BLE001
        record_step_failure("referee KPIs (RefsRadar)", err)
        refsradar_kpis = None
    return worldfootball_stats, home_away_bias, refsradar_kpis


def _worldfootball_referee_fields(worldfootball_stats) -> dict:
    """Extracted from _referee_stat_replacements to keep its own
    cognitive complexity down (python:S3776); behavior unchanged."""
    if not worldfootball_stats:
        return {"penalties_awarded": None, "second_yellow_cards": None, "penalties_source": None}
    return {
        "penalties_awarded": worldfootball_stats.penalties,
        "second_yellow_cards": worldfootball_stats.second_yellow,
        "penalties_source": "worldfootball",
    }


def _refsradar_referee_fields(refsradar_kpis) -> dict:
    """Extracted from _referee_stat_replacements to keep its own
    cognitive complexity down (python:S3776); behavior unchanged."""
    if not refsradar_kpis:
        return {
            "fouls_per_game": None, "red_cards_per_game": None, "referee_matches": None,
            "penalties_per_game": None, "cards_per_foul": None, "avg_total_cards": None,
            "fouls_per_game_source": None, "red_cards_per_game_source": None,
            "referee_matches_source": None, "penalties_per_game_source": None,
            "cards_per_foul_source": None, "avg_total_cards_source": None,
        }
    return {
        "fouls_per_game": refsradar_kpis.fouls_per_game,
        "red_cards_per_game": refsradar_kpis.red_cards_per_game,
        "referee_matches": refsradar_kpis.matches,
        "penalties_per_game": refsradar_kpis.penalties_per_game,
        "cards_per_foul": refsradar_kpis.cards_per_foul,
        "avg_total_cards": refsradar_kpis.avg_total_cards,
        "fouls_per_game_source": "refsradar", "red_cards_per_game_source": "refsradar",
        "referee_matches_source": "refsradar", "penalties_per_game_source": "refsradar",
        "cards_per_foul_source": "refsradar", "avg_total_cards_source": "refsradar",
    }


def _referee_stat_replacements(worldfootball_stats, home_away_bias, refsradar_kpis) -> dict:
    """Extracted from _enrich_referee_stats to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    return {
        **_worldfootball_referee_fields(worldfootball_stats),
        "home_away_bias": home_away_bias,
        "home_away_bias_source": ("football-data.co.uk" if home_away_bias else None),
        **_refsradar_referee_fields(refsradar_kpis),
    }


async def _enrich_referee_stats(merged) -> None:
    """Referee card/foul/penalty enrichment from 3 independent
    third-party sources, each optional -- guarded on merged.referee_stats
    already existing (from the base merge)."""
    if not merged.referee_stats:
        return
    worldfootball_stats, home_away_bias, refsradar_kpis = await _fetch_referee_source_stats(merged)
    from dataclasses import replace as _replace

    merged.referee_stats = _replace(
        merged.referee_stats,
        **_referee_stat_replacements(worldfootball_stats, home_away_bias, refsradar_kpis),
    )


async def _compute_and_apply_match_stat_estimates(team_name, opponent_name, own_is_home, insights_result, matches_by_source, on_progress):
    """Both teams get the full-depth xG/possession-matchup/losing-streak
    treatment, not just the searched team -- costs 2 extra fixture-list
    fetches (Fotmob + Goal.com) for the opponent. Returns
    (own_xg_estimate, opponent_xg_estimate) since those two are the only
    outputs this block produces that run_search still needs after this
    point; everything else it computes is written straight into
    insights_result.

    Takes on_progress (not just called around this function) so the
    long stretch it covers gets a SECOND message partway through,
    right at its own natural season-stats/possession boundary --
    previously this whole function ran under one single caller-side
    message with no update in between, the single longest silent
    stretch a search would sit at."""
    try:
        opponent_fotmob_matches = await fotmob.get_fotmob_matches(opponent_name)
    except Exception as err:  # noqa: BLE001
        record_step_failure("opponent matches (Fotmob)", err)
        opponent_fotmob_matches = []
    try:
        opponent_goal_matches = await goal.get_goal_matches(opponent_name)
    except Exception as err:  # noqa: BLE001
        record_step_failure("opponent matches (Goal.com)", err)
        opponent_goal_matches = []
    own_match_stats = await ins.compute_season_match_stats_estimate(team_name, matches_by_source.get("fotmob", []))
    opponent_match_stats = await ins.compute_season_match_stats_estimate(opponent_name, opponent_fotmob_matches)
    own_xg_estimate = own_match_stats.xg
    opponent_xg_estimate = opponent_match_stats.xg

    insights_result.home_xg_estimate, insights_result.away_xg_estimate = _home_away(own_is_home, own_xg_estimate, opponent_xg_estimate)
    insights_result.home_shots_estimate, insights_result.away_shots_estimate = _home_away(own_is_home, own_match_stats.shots, opponent_match_stats.shots)
    insights_result.home_card_discipline_venue_split, insights_result.away_card_discipline_venue_split = _home_away(
        own_is_home, own_match_stats.card_split, opponent_match_stats.card_split
    )
    insights_result.home_aerial_estimate, insights_result.away_aerial_estimate = _home_away(own_is_home, own_match_stats.aerial, opponent_match_stats.aerial)
    insights_result.home_big_chances_estimate, insights_result.away_big_chances_estimate = _home_away(
        own_is_home, own_match_stats.big_chances, opponent_match_stats.big_chances
    )
    insights_result.home_passing_style, insights_result.away_passing_style = _home_away(own_is_home, own_match_stats.passing_style, opponent_match_stats.passing_style)
    insights_result.home_fouls_estimate, insights_result.away_fouls_estimate = _home_away(own_is_home, own_match_stats.fouls, opponent_match_stats.fouls)
    insights_result.home_goalkeeping_estimate, insights_result.away_goalkeeping_estimate = _home_away(
        own_is_home, own_match_stats.goalkeeping, opponent_match_stats.goalkeeping
    )

    on_progress(_step_message(4, "Computing possession and corners..."))
    own_poss_corners = await ins.compute_possession_matchup(team_name, matches_by_source.get("goal", []))
    opponent_poss_corners = await ins.compute_possession_matchup(opponent_name, opponent_goal_matches)
    insights_result.home_possession_matchup, insights_result.away_possession_matchup = _home_away(
        own_is_home, own_poss_corners.possession, opponent_poss_corners.possession
    )
    insights_result.home_corners_estimate, insights_result.away_corners_estimate = _home_away(own_is_home, own_poss_corners.corners, opponent_poss_corners.corners)
    insights_result.home_defensive_errors_estimate, insights_result.away_defensive_errors_estimate = _home_away(
        own_is_home, own_poss_corners.defensive_errors, opponent_poss_corners.defensive_errors
    )

    insights_result.home_set_piece_threat = ins.compute_set_piece_threat_flag(insights_result.home_corners_estimate, insights_result.away_aerial_estimate)
    insights_result.away_set_piece_threat = ins.compute_set_piece_threat_flag(insights_result.away_corners_estimate, insights_result.home_aerial_estimate)
    insights_result.home_direct_play_exposure = ins.compute_direct_play_exposure_flag(insights_result.home_passing_style, insights_result.away_aerial_estimate)
    insights_result.away_direct_play_exposure = ins.compute_direct_play_exposure_flag(insights_result.away_passing_style, insights_result.home_aerial_estimate)

    return own_xg_estimate, opponent_xg_estimate


async def _enrich_opponent_form_and_ranks(merged, opponent_name, opponent_context, opponent_profile, own_is_home, form, own_advanced_stats, insights_result, form_source):
    """Opponent's own venue-classified form, plus the rank/Elo comparisons
    against the searched team. Returns the (possibly re-enriched)
    opponent_form, since later steps (resilience, fatigue flag, home
    advantage, streak stability, losing-streak context) all need it;
    everything else this computes is written straight into
    insights_result or opponent_profile."""
    own_position = merged.home_team_standing if own_is_home else merged.away_team_standing
    own_position = own_position.position if own_position else None
    opponent_position = merged.away_team_standing if own_is_home else merged.home_team_standing
    opponent_position = opponent_position.position if opponent_position else None

    opponent_form = compute_form_summary(opponent_name, opponent_context.matches)
    # opponent_context.matches_source (not merged.base_source) -- the
    # opponent's matches may have come from a fallback source when
    # base_source couldn't find the opponent; enriching against the
    # wrong scraper would silently fail to match its own match
    # objects. None means every source failed, so there's nothing to
    # enrich against.
    if opponent_context.matches_source:
        try:
            enriched_opponent = await enrich_form_with_venue_classification(
                opponent_context.matches, opponent_form, opponent_context.matches_source
            )
        except Exception as err:  # noqa: BLE001
            record_step_failure("form enrichment (opponent)", err)
            from .form import VenueEnrichmentResult

            enriched_opponent = VenueEnrichmentResult(form=opponent_form, advanced_stats=None, usage_by_player={})
    else:
        from .form import VenueEnrichmentResult

        enriched_opponent = VenueEnrichmentResult(form=opponent_form, advanced_stats=None, usage_by_player={})
    opponent_form = enriched_opponent.form
    opponent_advanced_stats = enriched_opponent.advanced_stats
    if opponent_profile:
        opponent_profile.squad = ins.apply_usage_pattern(opponent_profile.squad, enriched_opponent.usage_by_player)

    insights_result.home_advanced_stats, insights_result.away_advanced_stats = _home_away(own_is_home, own_advanced_stats, opponent_advanced_stats)

    own_rank_record = ins.compute_opponent_rank_record(form.last20_overall if form else [], merged.competition, merged.standings_table, own_position)
    opponent_rank_record = ins.compute_opponent_rank_record(opponent_form.last20_overall, merged.competition, merged.standings_table, opponent_position)
    insights_result.home_opponent_rank_record, insights_result.away_opponent_rank_record = _home_away(own_is_home, own_rank_record, opponent_rank_record)

    _apply_standings_derived_insights(
        merged, insights_result, own_is_home, form, opponent_form, own_position, opponent_position, form_source, opponent_context.matches_source
    )

    return opponent_form


def _apply_standings_derived_insights(
    merged, insights_result, own_is_home, form, opponent_form, own_position, opponent_position, form_source, opponent_matches_source
) -> None:
    """Standings-form filling, the clean-sheets cross-check, and Elo --
    extracted from _enrich_opponent_form_and_ranks to keep its own
    cognitive complexity down (python:S3776); behavior unchanged."""
    own_results = form.last20_overall if form else None
    opponent_results = opponent_form.last20_overall

    ins.fill_standings_form(merged.standings_table, own_position, own_results, merged.competition)
    ins.fill_standings_form(merged.standings_table, opponent_position, opponent_results, merged.competition)
    ins.add_clean_sheets_recent_check(merged.home_team_season_stats if own_is_home else merged.away_team_season_stats, own_results, form_source)
    ins.add_clean_sheets_recent_check(merged.away_team_season_stats if own_is_home else merged.home_team_season_stats, opponent_results, opponent_matches_source)
    # Same pattern as the clean-sheet cross-check: season avg possession
    # (sofascore, season-to-date) next to the form window's venue-split
    # average can look contradictory without saying which window each is.
    own_stats = merged.home_team_season_stats if own_is_home else merged.away_team_season_stats
    opp_stats = merged.away_team_season_stats if own_is_home else merged.home_team_season_stats
    ins.add_possession_venue_split_check(own_stats, form.detailed_venue_split if form else None, form_source)
    ins.add_possession_venue_split_check(opp_stats, opponent_form.detailed_venue_split if opponent_form else None, opponent_matches_source)

    own_elo = with_league_rank(compute_elo_rating(own_results or []), merged.standings_table, own_position)
    opponent_elo = with_league_rank(compute_elo_rating(opponent_results), merged.standings_table, opponent_position)
    if own_elo:
        own_elo.sample_source = form_source
    if opponent_elo:
        opponent_elo.sample_source = opponent_matches_source
    insights_result.home_elo_rating, insights_result.away_elo_rating = _home_away(own_is_home, own_elo, opponent_elo)


def _compute_squad_leaderboards(profiles) -> None:
    """Leaderboards/breakdowns derived purely from each profile's own
    now-fully-enriched squad (season stats, defensive stats, recent
    usage all populated above) -- zero extra requests. Previously
    computed only inside format_markdown.py and never stored, so a
    JSON consumer had no way to see them."""
    for profile in profiles:
        if not profile or not profile.squad:
            continue
        profile.top_scorers = compute_top_performers(profile.squad, "goals")
        profile.top_assists = compute_top_performers(profile.squad, "assists")
        profile.top_defenders = compute_top_defenders(profile.squad)
        profile.bench_regulars = compute_bench_regulars(profile.squad)
        profile.midfielders_form = compute_role_form_breakdown(profile.squad, is_midfield_role)
        profile.defenders_form = compute_role_form_breakdown(profile.squad, is_defender_role)
        profile.recent_form_leaders = compute_recent_form_leaders(profile.squad)


def _squad_for_bench_info(prefer_own: bool, merged_profile, opponent_profile):
    """Squad to pass to compute_bench_info for one side (home or away) --
    picks the searched team's own squad when prefer_own, else the
    opponent's, each null-safe independently. Extracted from a nested
    ternary expression (python:S3358) that also had a latent bug: the
    original unconditionally accessed `merged_profile.squad` /
    `opponent_profile.squad` on the preferred branch, guarded only by
    "either profile exists" rather than by the PREFERRED one existing --
    reachable (AttributeError on None) whenever e.g. own_is_home is True
    but merged_profile itself is None (all 5 profile sources failed)
    while opponent_profile still succeeded."""
    profile = merged_profile if prefer_own else opponent_profile
    return profile.squad if profile else None


def _apply_duel_and_fullback_insights(insights_result, own_is_home, merged_profile, opponent_profile) -> None:
    own_duel_vulnerabilities = ins.compute_duel_vulnerabilities(merged_profile.squad if merged_profile else None)
    opponent_duel_vulnerabilities = ins.compute_duel_vulnerabilities(opponent_profile.squad if opponent_profile else None)
    insights_result.home_duel_vulnerabilities, insights_result.away_duel_vulnerabilities = _home_away(own_is_home, own_duel_vulnerabilities, opponent_duel_vulnerabilities)

    own_fullback_exposure = ins.compute_fullback_exposure(merged_profile.squad if merged_profile else None)
    opponent_fullback_exposure = ins.compute_fullback_exposure(opponent_profile.squad if opponent_profile else None)
    insights_result.home_fullback_exposure, insights_result.away_fullback_exposure = _home_away(own_is_home, own_fullback_exposure, opponent_fullback_exposure)


def _apply_projected_xi(insights_result, own_presence, opponent_presence, merged_profile, opponent_profile) -> tuple[list | None, list | None]:
    """Extracted from _apply_presence_and_bench_insights to keep its own
    cognitive complexity down (python:S3776). Returns the (own, opponent)
    selected-starter lists so _apply_derived_lineup_if_none_published can
    build home_lineup/away_lineup from the exact same selection, rather
    than re-scanning presence for projected_starter afterwards."""
    own_selected = ins.mark_projected_starters(own_presence, merged_profile.squad if merged_profile else None)
    opponent_selected = ins.mark_projected_starters(opponent_presence, opponent_profile.squad if opponent_profile else None)
    if own_selected or opponent_selected:
        insights_result.projected_xi_basis = "Projected, not a published lineup: one goalkeeper plus the ten available outfield players with the most starts in the recent matches whose lineups were read"
    return own_selected, opponent_selected


def _derive_side_lineup(existing_lineup, selected, squad):
    """None when a real lineup already exists (nothing to derive) or when
    derive_lineup itself has nothing to project from."""
    if existing_lineup:
        return None
    return ins.derive_lineup(selected, squad)


def _apply_derived_lineup_if_none_published(insights_result, merged, own_is_home, merged_profile, opponent_profile, own_selected, opponent_selected) -> None:
    """Fills merged.home_lineup/away_lineup (NOT home_formation/
    away_formation -- see derive_lineup's own docstring for why) from the
    exact projected XI _apply_projected_xi already selected, when NO
    source (real or predicted) has published a lineup at all -- confirmed
    live, Sofascore doesn't publish even a prediction until close to
    kickoff and real lineups only appear ~1 hour before it, so a report
    generated further out than that would otherwise show null lineups for
    the whole pre-match window. Only for a not-yet-started fixture; a
    played/live match's missing lineup is a real data gap, not something
    to paper over with a guess."""
    if merged.status not in NOT_STARTED_STATUSES:
        return
    own_squad = merged_profile.squad if merged_profile else None
    opponent_squad = opponent_profile.squad if opponent_profile else None
    home_selected, away_selected = _home_away(own_is_home, own_selected, opponent_selected)
    home_squad, away_squad = _home_away(own_is_home, own_squad, opponent_squad)

    home_derived = _derive_side_lineup(merged.home_lineup, home_selected, home_squad)
    away_derived = _derive_side_lineup(merged.away_lineup, away_selected, away_squad)
    if home_derived:
        merged.home_lineup = home_derived
        merged.field_sources["home_lineup"] = "derived"
    if away_derived:
        merged.away_lineup = away_derived
        merged.field_sources["away_lineup"] = "derived"
    if home_derived or away_derived:
        prefix = f"{insights_result.projected_xi_basis}; " if insights_result.projected_xi_basis else ""
        insights_result.projected_xi_basis = prefix + "home_lineup/away_lineup below is this same projection, shown because no source has published a real lineup yet"


def _apply_presence_and_bench_insights(insights_result, own_is_home, merged, merged_profile, opponent_profile) -> None:
    own_presence = ins.compute_presence(
        merged_profile.squad if merged_profile else None,
        merged.home_lineup if own_is_home else merged.away_lineup,
        merged.home_bench if own_is_home else merged.away_bench,
        merged_profile.injuries if merged_profile else None,
        merged.home_suspended_players if own_is_home else merged.away_suspended_players,
        additional_notes=merged.additional_notes if hasattr(merged, 'additional_notes') else None,
        missing_players=merged.home_missing_players if own_is_home else merged.away_missing_players,
    )
    opponent_presence = ins.compute_presence(
        opponent_profile.squad if opponent_profile else None,
        merged.away_lineup if own_is_home else merged.home_lineup,
        merged.away_bench if own_is_home else merged.home_bench,
        opponent_profile.injuries if opponent_profile else None,
        merged.away_suspended_players if own_is_home else merged.home_suspended_players,
        additional_notes=merged.additional_notes if hasattr(merged, 'additional_notes') else None,
        missing_players=merged.away_missing_players if own_is_home else merged.home_missing_players,
    )
    insights_result.home_presence, insights_result.away_presence = _home_away(own_is_home, own_presence, opponent_presence)
    own_selected, opponent_selected = _apply_projected_xi(insights_result, own_presence, opponent_presence, merged_profile, opponent_profile)
    _apply_derived_lineup_if_none_published(insights_result, merged, own_is_home, merged_profile, opponent_profile, own_selected, opponent_selected)

    insights_result.home_bench_info = ins.compute_bench_info(merged.home_bench, merged.home_lineup, _squad_for_bench_info(own_is_home, merged_profile, opponent_profile))
    insights_result.away_bench_info = ins.compute_bench_info(merged.away_bench, merged.away_lineup, _squad_for_bench_info(not own_is_home, merged_profile, opponent_profile))


def _apply_squad_strength_insights(insights_result, own_is_home, merged, merged_profile, opponent_profile) -> None:
    own_squad_strength = ins.compute_squad_strength(
        merged_profile.squad if merged_profile else None,
        merged_profile.injuries if merged_profile else None,
        merged.home_suspended_players if own_is_home else merged.away_suspended_players,
        merged.home_missing_players if own_is_home else merged.away_missing_players,
    )
    opponent_squad_strength = ins.compute_squad_strength(
        opponent_profile.squad if opponent_profile else None,
        opponent_profile.injuries if opponent_profile else None,
        merged.away_suspended_players if own_is_home else merged.home_suspended_players,
        merged.away_missing_players if own_is_home else merged.home_missing_players,
    )
    insights_result.home_squad_strength, insights_result.away_squad_strength = _home_away(own_is_home, own_squad_strength, opponent_squad_strength)
    insights_result.squad_value_basis_note = _squad_value_basis_note(own_squad_strength, opponent_squad_strength, merged_profile, opponent_profile)


def _squad_value_basis_note(own_strength, opponent_strength, merged_profile, opponent_profile) -> str | None:
    if not (own_strength and opponent_strength and merged_profile and opponent_profile):
        return None
    own_source, opponent_source = getattr(merged_profile, "base_source", None), getattr(opponent_profile, "base_source", None)
    if not own_source or not opponent_source or own_source == opponent_source:
        return None
    return (
        f"home/away squad market values came from different sources ({own_source} vs {opponent_source}, "
        "see teamProfile/opponentProfile field_sources) -- each runs its own valuation model, so the two "
        "totals are not directly comparable or summable"
    )


def _apply_squad_derived_insights(insights_result, own_is_home, merged, merged_profile, opponent_profile) -> None:
    """Duel vulnerabilities, fullback exposure, presence (availability),
    bench info, and squad strength -- all derived purely from the two
    already-enriched squads/injuries/lineups, no extra requests. Split
    into the 3 helpers above purely to keep each one's own cognitive
    complexity low (python:S3776); behavior unchanged."""
    _apply_duel_and_fullback_insights(insights_result, own_is_home, merged_profile, opponent_profile)
    _apply_presence_and_bench_insights(insights_result, own_is_home, merged, merged_profile, opponent_profile)
    _apply_squad_strength_insights(insights_result, own_is_home, merged, merged_profile, opponent_profile)


async def _compute_prediction_and_trend_insights(
    team_name, merged, merged_profile, opponent_profile, opponent_name, insights_result, own_is_home,
    own_rest_days, opponent_context, forms, form_source, matches_by_source,
    xg_estimates,
) -> None:
    """Prediction, rotation, and the remaining per-team trend insights
    (resilience, rest performance, experience h2h, fatigue, home
    advantage, streak stability, losing-streak context, card risks) --
    grouped together purely to keep run_search's own cognitive complexity
    low (python:S3776); each step here is independent and reads only
    already-computed state. See prediction.py's own module docstring for
    why rest-days and available-squad-value specifically feed the
    heuristic model, and why xg_model is deliberately computed without
    them.

    forms is (form, opponent_form) and xg_estimates is (own_xg_estimate,
    opponent_xg_estimate) -- bundled into 2-tuples (not their own
    parameters) purely to bring this function's own parameter count
    under python:S107's threshold; both pairs are otherwise used
    independently below, same as before."""
    form, opponent_form = forms
    own_xg_estimate, opponent_xg_estimate = xg_estimates
    home_rest_days, away_rest_days = _home_away(own_is_home, own_rest_days, opponent_context.rest_days)
    insights_result.prediction = compute_match_prediction(
        merged.betting_odds,
        insights_result.home_elo_rating,
        insights_result.away_elo_rating,
        home_rest_days,
        away_rest_days,
        insights_result.home_squad_strength,
        insights_result.away_squad_strength,
        insights_result.home_xg_estimate,
        insights_result.away_xg_estimate,
    )

    own_rotation = await ins.compute_rotation_info(team_name, merged.base_source, matches_by_source.get(form_source, []) if form_source else [])
    opponent_rotation = (
        await ins.compute_rotation_info(opponent_name, opponent_context.matches_source, opponent_context.matches)
        if opponent_context.matches_source
        else None
    )
    insights_result.home_rotation, insights_result.away_rotation = _home_away(own_is_home, own_rotation, opponent_rotation)

    own_resilience = ins.compute_resilience(form.last20_overall if form else [])
    opponent_resilience = ins.compute_resilience(opponent_form.last20_overall)
    insights_result.home_resilience, insights_result.away_resilience = _home_away(own_is_home, own_resilience, opponent_resilience)

    own_rest_performance = ins.compute_rest_performance(team_name, matches_by_source.get(form_source, []) if form_source else [])
    opponent_rest_performance = ins.compute_rest_performance(opponent_name, opponent_context.matches)
    insights_result.home_rest_performance, insights_result.away_rest_performance = _home_away(own_is_home, own_rest_performance, opponent_rest_performance)

    insights_result.experience_h2h = ins.compute_experience_h2h(insights_result.experience_comparison, merged.head_to_head_summary, own_is_home)

    own_fatigue_flag = ins.compute_fatigue_flag(form.recent_competitions if form else [], form.gaps_between_last_three if form else [])
    opponent_fatigue_flag = ins.compute_fatigue_flag(opponent_form.recent_competitions, opponent_form.gaps_between_last_three)
    insights_result.home_fatigue_flag, insights_result.away_fatigue_flag = _home_away(own_is_home, own_fatigue_flag, opponent_fatigue_flag)

    own_advantage = ins.compute_home_advantage(form)
    opponent_advantage = ins.compute_home_advantage(opponent_form)
    insights_result.home_advantage, insights_result.away_advantage = _home_away(own_is_home, own_advantage, opponent_advantage)

    own_streak_stability = ins.compute_streak_stability(form.current_streak if form else None, own_rotation)
    opponent_streak_stability = ins.compute_streak_stability(opponent_form.current_streak, opponent_rotation)
    insights_result.home_streak_stability, insights_result.away_streak_stability = _home_away(own_is_home, own_streak_stability, opponent_streak_stability)

    own_losing_streak_context = ins.compute_losing_streak_context(form.current_streak if form else None, own_xg_estimate)
    opponent_losing_streak_context = ins.compute_losing_streak_context(opponent_form.current_streak, opponent_xg_estimate)
    insights_result.home_losing_streak_context, insights_result.away_losing_streak_context = _home_away(
        own_is_home, own_losing_streak_context, opponent_losing_streak_context
    )

    own_card_risks = ins.compute_card_risks(merged_profile.squad if merged_profile else None)
    opponent_card_risks = ins.compute_card_risks(opponent_profile.squad if opponent_profile else None)
    insights_result.home_card_risks, insights_result.away_card_risks = _home_away(own_is_home, own_card_risks, opponent_card_risks)

    insights_result.referee_card_risk_note = ins.compute_referee_card_risk_note(merged.referee, merged.referee_stats, insights_result.home_card_risks, insights_result.away_card_risks)


async def _enrich_weather(merged) -> None:
    """Best-effort weather enrichment for the venue/kickoff -- optional,
    swallows errors same as every other third-party enrichment step."""
    weather_query_city = merged.venue_city or merged.venue_name
    if not weather_query_city:
        return
    try:
        weather_detail = await wttrin.get_wttr_weather_detail(weather_query_city, merged.kickoff_utc, merged.venue_country)
    except Exception as err:  # noqa: BLE001
        record_step_failure("weather (wttr.in)", err)
        weather_detail = None
    if not weather_detail:
        return
    from .types import WeatherDetail

    merged.weather_detail = WeatherDetail(
        temp_c=weather_detail.temp_c,
        humidity_pct=weather_detail.humidity_pct,
        wind_speed_kmph=weather_detail.wind_speed_kmph,
        precip_mm=weather_detail.precip_mm,
        chance_of_rain_pct=weather_detail.chance_of_rain_pct,
        wind_gust_kmph=weather_detail.wind_gust_kmph,
        cloud_cover_pct=weather_detail.cloud_cover_pct,
        feels_like_c=weather_detail.feels_like_c,
        kickoff_hour_matched=weather_detail.kickoff_hour_matched,
    )
    merged.field_sources["weather_detail"] = "wttr.in"
    if not merged.weather and weather_detail.description:
        approx = "" if weather_detail.kickoff_hour_matched else " (same-day approximation, local midday)"
        merged.weather = f"{weather_detail.description}, {weather_detail.temp_c}°C{approx}"
        merged.field_sources["weather"] = "wttr.in"


async def _get_club_strength_ratings_safe(merged) -> dict:
    """Extracted from _compute_match_context to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    try:
        return await statsultra.get_club_strength_ratings(merged.home_team, merged.away_team)
    except Exception as err:  # noqa: BLE001
        record_step_failure("club strength (StatsUltra)", err)
        return {"home": None, "away": None}


async def _get_upcoming_match_odds_safe(merged):
    """Extracted from _compute_match_context to keep its own cognitive
    complexity down (python:S3776); behavior unchanged."""
    try:
        return await footballdata.get_upcoming_match_odds(merged.home_team, merged.away_team)
    except Exception as err:  # noqa: BLE001
        record_step_failure("match odds (football-data)", err)
        return None


async def _enrich_squads_with_defensive_stats(merged_profile, opponent_profile, team_name, opponent_name, form, opponent_form) -> None:
    """Extracted from _compute_match_context to keep its own cognitive
    complexity down (python:S3776); behavior unchanged.

    Candidate names are each team's OWN recent competitions, not the
    upcoming match's specific competition."""
    from .merge import enrich_squad_with_defensive_stats

    if merged_profile and merged_profile.squad:
        own_name = merged_profile.team_name or team_name
        merged_profile.squad = await enrich_squad_with_defensive_stats(merged_profile.squad, own_name, form.recent_competitions if form else [])
        _note_missing_defensive_stats(merged_profile, own_name)
    if opponent_profile and opponent_profile.squad:
        opponent_profile.squad = await enrich_squad_with_defensive_stats(opponent_profile.squad, opponent_name, opponent_form.recent_competitions)
        _note_missing_defensive_stats(opponent_profile, opponent_name)


def _note_missing_defensive_stats(profile, team_name: str) -> None:
    if any(m.defensive_stats for m in profile.squad):
        return
    profile.defensive_stats_note = (
        f"Squawka defensive stats unavailable for {team_name} (fetch failed or team not found in its competitions) -- top_defenders is empty for that reason, not because the squad has no defenders."
    )


def _reconcile_venue_capacity(merged, venue_details) -> None:
    """Extracted from _compute_match_context to keep its own cognitive
    complexity down (python:S3776); behavior unchanged.

    When both sofascore (venue_capacity) and StadiumDB
    (venueDetails.capacity) provide a capacity value and they disagree,
    prefer StadiumDB's value since it's a dedicated stadium database.
    This resolves bug #75 (capacity mismatch)."""
    if not (venue_details and venue_details.capacity and merged.venue_capacity):
        return
    if venue_details.capacity != merged.venue_capacity:
        previous = SourceValue(from_source=merged.field_sources.get("venue_capacity", merged.base_source), value=merged.venue_capacity)
        alternatives = [a for c in merged.source_conflicts if c.field == "venue_capacity" for a in c.alternatives]
        merged.source_conflicts = [c for c in merged.source_conflicts if c.field != "venue_capacity"]
        merged.source_conflicts.append(SourceConflict(
            field="venue_capacity", kept=venue_details.capacity, kept_source="stadiumdb",
            alternatives=[previous, *alternatives], resolution="StadiumDB preferred: dedicated stadium database",
        ))
        merged.venue_capacity = venue_details.capacity
        merged.field_sources["venue_capacity"] = "stadiumdb"


async def _compute_match_context(team_name, merged, merged_profile, form, form_source, matches_by_source, on_progress) -> _MatchContext:
    """Everything run_search does once an upcoming match (`merged`) is
    known -- opponent lookup, every insight/enrichment step, and the
    final prediction. Extracted purely to keep run_search's own cognitive
    complexity low (python:S3776); this function and the helpers it calls
    are the direct, behavior-preserving decomposition of what used to be
    run_search's single `if merged:` block."""
    own_is_home = is_team_home(merged, team_name)
    opponent_name = merged.home_team if own_is_home is False else merged.away_team
    own_rest_days = form.next5_with_gaps[0].days_since_previous if form and form.next5_with_gaps else None

    form, own_advanced_stats = await _apply_own_recent_meetings_and_form(team_name, merged, form_source, form, matches_by_source, opponent_name, merged_profile)

    on_progress(_step_message(1, f"Next match found: {merged.home_team} vs {merged.away_team}. Fetching opponent ({opponent_name})..."))
    match_kickoff = datetime.fromisoformat(merged.kickoff_utc.replace("Z", _UTC_OFFSET_SUFFIX)) if merged.kickoff_utc else None
    opponent_context = await fetch_opponent_context(merged.base_source, opponent_name, as_of=match_kickoff)
    opponent_profile = opponent_context.merged_profile

    # Reconcile match-level missing_players (Sofascore's match-specific
    # lineups.missingPlayers) with each team's own profile-level
    # injuries -- two independently-sourced lists that confirmed live
    # (repeatedly) disagree. Done here, before compute_insights and
    # everything downstream, so the reconciled lists are what both the
    # presence computation and the final JSON output actually see.
    own_injuries = merged_profile.injuries if merged_profile else None
    opponent_injuries = opponent_profile.injuries if opponent_profile else None
    home_injuries, away_injuries = (own_injuries, opponent_injuries) if own_is_home else (opponent_injuries, own_injuries)
    merged.home_missing_players = reconcile_missing_players(merged.home_missing_players, home_injuries)
    merged.away_missing_players = reconcile_missing_players(merged.away_missing_players, away_injuries)

    # Same reconciliation, one level down: teamProfile.missing_attackers/
    # defenders/midfielders/goalkeepers were computed from `injuries`
    # alone, before missing_players even existed in the pipeline -- so a
    # player ruled out for a non-injury reason (Richarlison, "coach_
    # decision") was absent from missing_attackers despite being a
    # forward and genuinely unavailable. Confirmed live.
    home_profile, away_profile = (merged_profile, opponent_profile) if own_is_home else (opponent_profile, merged_profile)
    for profile, injuries, missing_players in (
        (home_profile, home_injuries, merged.home_missing_players),
        (away_profile, away_injuries, merged.away_missing_players),
    ):
        if not profile:
            continue
        profile.missing_midfielders = reconcile_missing_by_role(profile.squad, injuries, missing_players, is_midfield_role)
        profile.missing_attackers = reconcile_missing_by_role(profile.squad, injuries, missing_players, is_attacker_role)
        profile.missing_defenders = reconcile_missing_by_role(profile.squad, injuries, missing_players, is_defender_role)
        profile.missing_goalkeepers = reconcile_missing_by_role(profile.squad, injuries, missing_players, is_goalkeeper_role)

    insights_result = ins.compute_insights(merged, merged_profile.average_age if merged_profile else None, own_rest_days, opponent_context)
    venue_details = await fetch_venue_details(merged, merged.venue_country)

    # These milestone messages exist purely so a UI showing on_progress
    # text (e.g. Android's SearchScreen) has something fresher than a
    # generic spinner during this stretch -- individually enriching
    # referee/manager/squad/prediction data is a lot of sequential
    # network calls with no other progress signal of their own. Each is
    # numbered out of a fixed total (_step_message/_INSIGHTS_TOTAL_STEPS)
    # so the UI can show real, always-advancing "X/6" progress rather
    # than just changing text a caller has to notice on its own.
    on_progress(_step_message(2, f"Opponent found ({opponent_name}). Fetching venue, referee, and manager info..."))

    strength_ratings = await _get_club_strength_ratings_safe(merged)
    insights_result.home_club_strength = strength_ratings["home"]
    insights_result.away_club_strength = strength_ratings["away"]

    merged.home_manager = await _enrich_manager_tenure(merged.home_manager, merged.home_team)
    merged.away_manager = await _enrich_manager_tenure(merged.away_manager, merged.away_team)

    await _enrich_referee_stats(merged)

    on_progress(_step_message(3, "Computing season stats and shot data..."))
    own_xg_estimate, opponent_xg_estimate = await _compute_and_apply_match_stat_estimates(
        team_name, opponent_name, own_is_home, insights_result, matches_by_source, on_progress
    )

    opponent_form = await _enrich_opponent_form_and_ranks(merged, opponent_name, opponent_context, opponent_profile, own_is_home, form, own_advanced_stats, insights_result, form_source)

    merged.betting_odds = await _get_upcoming_match_odds_safe(merged)

    await _enrich_squads_with_defensive_stats(merged_profile, opponent_profile, team_name, opponent_name, form, opponent_form)

    on_progress(_step_message(5, "Computing squad strength and availability..."))
    _compute_squad_leaderboards((merged_profile, opponent_profile))
    _apply_squad_derived_insights(insights_result, own_is_home, merged, merged_profile, opponent_profile)

    on_progress(_step_message(6, "Computing prediction and form trends..."))
    await _compute_prediction_and_trend_insights(
        team_name, merged, merged_profile, opponent_profile, opponent_name, insights_result, own_is_home,
        own_rest_days, opponent_context, (form, opponent_form), form_source, matches_by_source,
        (own_xg_estimate, opponent_xg_estimate),
    )

    await _enrich_weather(merged)

    _reconcile_venue_capacity(merged, venue_details)

    return _MatchContext(
        opponent_name=opponent_name,
        opponent_profile=opponent_profile,
        opponent_form=opponent_form,
        opponent_form_source=opponent_context.matches_source,
        insights_result=insights_result,
        venue_details=venue_details,
        form=form,
    )


def _score_past_predictions(past_predictions, matches_by_source) -> CalibrationSummary | None:
    """Scores the caller's saved predictions against every match this run
    fetched. A failure here must never sink the report -- it is reported
    in the failure list and calibration is simply omitted."""
    if past_predictions is None:
        return None
    try:
        return compute_calibration(past_predictions, [m for matches in matches_by_source.values() for m in matches])
    except Exception as err:  # noqa: BLE001
        record_step_failure("calibration", err)
        return None


async def run_search(
    team_name: str,
    on_progress: Callable[[str], None] = _NOOP_PROGRESS,
    on_source_progress: Callable[[SourceStatus], None] = _NOOP_SOURCE_PROGRESS,
    past_predictions: list[dict] | None = None,
) -> RunSearchResult:
    """The full fetch/merge/compute pipeline, decoupled from the CLI's own
    printing/file-writing (see cli.py) so it can be called from anywhere
    -- e.g. a future Android UI. on_progress is optional and purely
    cosmetic (streams "scraping X..." free-text updates to a caller).

    on_source_progress is separate from on_progress, not a duplicate of
    it: it fires once per source with the actual structured SourceStatus
    record (fixtures_scraped, matches_error, details_error,
    profile_error), for a caller that needs real per-source state (e.g.
    a UI showing "Sofascore blocked / Fotmob: 42 fixtures" -- see
    android_report.py) rather than parsing on_progress's free text."""
    # Confirmed live: a trailing/leading space typed into the app's search
    # box (or pasted) propagated all the way through to result.team in the
    # final JSON ("Tottenham " with a trailing space) -- stripped once
    # here, at the top, rather than wherever `team` happens to get read
    # out later.
    team_name = team_name.strip()
    sofascore_site.reset_block_state()  # a block from a previous run says nothing about this one
    on_progress(f'Searching for "{team_name}" (base: Sofascore, supplemented by Fotmob, SoccerDesk, Goal.com, 365Scores)...')

    matches_by_source, details_by_source, profile_by_source, statuses = await _scrape_all_sources(team_name, on_progress, on_source_progress)

    merged = merge_match_details(details_by_source) if details_by_source else None
    form_source = next((s for s in SOURCE_ORDER if matches_by_source.get(s)), None)
    form = compute_form_summary(team_name, matches_by_source[form_source]) if form_source else None
    merged_profile = merge_team_profile(profile_by_source) if profile_by_source else None

    # Confirmed live (Android), two distinct cases, both silently
    # produced a "successful" report with match=null and no insights
    # instead of a clear error:
    #  1. Unrecognized name (e.g. "manutd" -- no source's fuzzy match
    #     handles a squished/no-space abbreviation, unlike "man utd"):
    #     every source's own matches_error/profile_error already said
    #     "No <Source> team found matching ..." (each source's search
    #     itself works correctly), but that signal never propagated up.
    #  2. Recognized name, no upcoming fixture (e.g. "westham" -- confirmed
    #     live: Sofascore's own profile lookup succeeds with zero errors,
    #     `merged_profile` is populated, but no source has a next match to
    #     report). Different situation from #1 -- the team genuinely
    #     exists, there's just nothing to predict right now -- so gets its
    #     own message rather than being told "not found".
    # Both raise rather than falling through to `_compute_match_context`
    # (which needs a real `merged` match to do anything). android_report.py
    # doesn't catch either, so they propagate as a PyException to Kotlin,
    # where ReportRepository.search()'s existing `catch (e: PyException)`
    # already turns it into SearchState.Error -- no Kotlin change needed,
    # that path was already there for exactly this shape of failure.
    if not merged:
        if merged_profile:
            raise RuntimeError(f'Found "{team_name}", but no upcoming match is currently scheduled.')
        raise RuntimeError(f'Could not find a team matching "{team_name}". Check the spelling and try again.')

    ctx: _MatchContext | None = None
    if merged:
        ctx = await _compute_match_context(team_name, merged, merged_profile, form, form_source, matches_by_source, on_progress)

    on_progress("Done.")
    calibration = _score_past_predictions(past_predictions, matches_by_source)
    generated_at = datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace(_UTC_OFFSET_SUFFIX, "Z")
    return RunSearchResult(
        team=team_name,
        generated_at=generated_at,
        statuses=statuses,
        merged=merged,
        opponent_name=ctx.opponent_name if ctx else None,
        form=ctx.form if ctx else form,
        form_source=form_source,
        opponent_form=ctx.opponent_form if ctx else None,
        opponent_form_source=ctx.opponent_form_source if ctx else None,
        merged_profile=merged_profile,
        opponent_profile=ctx.opponent_profile if ctx else None,
        insights=ctx.insights_result if ctx else None,
        venue_details=ctx.venue_details if ctx else None,
        calibration=calibration,
    )
