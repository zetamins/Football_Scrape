"""The full fetch/merge/compute pipeline -- run_search() ties together
every site scraper, the merge layer, form computation, and every insight.
Ported from src/search.ts's runSearch() and its immediate helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from . import insights as ins
from .elo import compute_elo_rating
from .prediction import compute_match_prediction
from .form import compute_form_summary, enrich_form_with_venue_classification, is_team_home, next_match
from .insights import OpponentContext, SeasonMatchStatsEstimate
from .merge import (
    MergedMatch,
    MergedProfile,
    SOURCE_ORDER,
    apply_deep_recent_meetings,
    compute_bench_regulars,
    compute_recent_form_leaders,
    compute_role_form_breakdown,
    compute_top_defenders,
    compute_top_performers,
    is_defender_role,
    is_midfield_role,
    merge_match_details,
    merge_team_profile,
)
from .sites import (
    footballdata,
    fotmob,
    goal,
    refsradar,
    soccerdesk,
    squawka,
    stadiumdb,
    statsultra,
    three65scores,
    wikipedia,
    worldfootball,
    wttrin,
)
from .sites import sofascore as sofascore_site
from .types import ManagerTenureRecord, MatchDetails, MatchInfo, MatchInsights, Source, TeamProfile, VenueDetails


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


def _age_from_iso_date(iso_date: Optional[str]) -> Optional[int]:
    if not iso_date:
        return None
    try:
        dob = datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int((datetime.now(tz=timezone.utc) - dob).days / 365.25)


async def fetch_opponent_context(base_source: Source, opponent_name: str) -> OpponentContext:
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
    profile -- up to 5 requests either way, same as the main team."""
    now = datetime.now(tz=timezone.utc)
    rest_days: Optional[int] = None
    matches: list[MatchInfo] = []
    matches_source: Optional[Source] = None
    error: Optional[str] = None

    for source in (base_source, *[s for s in SOURCE_ORDER if s != base_source]):
        try:
            candidate = await SCRAPERS[source].run(opponent_name)
        except Exception as err:  # noqa: BLE001 - mirrors TS's catch (err: any)
            error = f"{error}; {err}" if error else str(err)
            continue
        if candidate:
            matches = candidate
            matches_source = source
            break

    played = sorted(
        (m for m in matches if m.kickoff_utc and datetime.fromisoformat(m.kickoff_utc.replace("Z", _UTC_OFFSET_SUFFIX)) < now),
        key=lambda m: m.kickoff_utc,
        reverse=True,
    )
    if played and played[0].kickoff_utc:
        last_dt = datetime.fromisoformat(played[0].kickoff_utc.replace("Z", _UTC_OFFSET_SUFFIX))
        rest_days = round((now - last_dt).total_seconds() / 86400)

    opponent_profile_by_source: dict[Source, TeamProfile] = {}
    for source in SOURCE_ORDER:
        try:
            opponent_profile_by_source[source] = await SCRAPERS[source].profile(opponent_name)
        except Exception as err:  # noqa: BLE001
            error = f"{error}; {err}" if error else str(err)

    merged_profile = merge_team_profile(opponent_profile_by_source) if opponent_profile_by_source else None

    return OpponentContext(
        rest_days=rest_days,
        average_age=(merged_profile.average_age if merged_profile else None),
        merged_profile=merged_profile,
        matches=matches,
        error=error,
        matches_source=matches_source,
    )


async def fetch_venue_details(merged: MergedMatch, venue_country: Optional[str]) -> Optional[VenueDetails]:
    """Tries the home club first, then the away club -- StadiumDB is
    indexed by club, so a neutral-venue match correctly resolves to
    nothing rather than a wrong guess."""
    try:
        result = await stadiumdb.get_stadium_db_venue_details(merged.home_team, venue_country)
        if result:
            return result
        return await stadiumdb.get_stadium_db_venue_details(merged.away_team, venue_country)
    except Exception:  # noqa: BLE001 - mirrors TS's catch { return null }
        return None


@dataclass
class SourceStatus:
    source: Source
    fixtures_scraped: int = 0
    matches_error: Optional[str] = None
    details_error: Optional[str] = None
    profile_error: Optional[str] = None


@dataclass
class RunSearchResult:
    """Everything run_search() returns, keyed exactly the way the CLI's
    JSON output file already shapes it (see report.build_report_json) --
    both the CLI and any other caller (e.g. a future Android UI) consume
    the same shape, computed by the same single code path."""

    team: str
    generated_at: str
    statuses: list[SourceStatus]
    merged: Optional[MergedMatch]
    opponent_name: Optional[str]
    form: Optional[object]
    form_source: Optional[Source]
    opponent_form: Optional[object]
    opponent_form_source: Optional[Source]
    merged_profile: Optional[MergedProfile]
    opponent_profile: Optional[MergedProfile]
    insights: Optional[MatchInsights]
    venue_details: Optional[VenueDetails]


_NOOP_PROGRESS: Callable[[str], None] = lambda msg: None  # noqa: E731
_NOOP_SOURCE_PROGRESS: Callable[[SourceStatus], None] = lambda status: None  # noqa: E731

# datetime.fromisoformat() can't parse a trailing "Z" directly -- swapped
# for an explicit UTC offset it does understand.
_UTC_OFFSET_SUFFIX = "+00:00"


async def run_search(
    team_name: str,
    on_progress: Callable[[str], None] = _NOOP_PROGRESS,
    on_source_progress: Callable[[SourceStatus], None] = _NOOP_SOURCE_PROGRESS,
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
    on_progress(f'Searching for "{team_name}" (base: Sofascore, supplemented by Fotmob, SoccerDesk, Goal.com, 365Scores)...')

    matches_by_source: dict[Source, list[MatchInfo]] = {}
    details_by_source: dict[Source, MatchDetails] = {}
    profile_by_source: dict[Source, TeamProfile] = {}
    statuses: list[SourceStatus] = []

    # Sequential, not parallel -- Sofascore is rate-sensitive (Cloudflare),
    # so we never want another source's traffic overlapping with its
    # requests.
    for source in SOURCE_ORDER:
        on_progress(f"Scraping {source}...")
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
                    status.details_error = str(err)
        except Exception as err:  # noqa: BLE001
            status.matches_error = str(err)

        try:
            profile_by_source[source] = await scraper.profile(team_name)
        except Exception as err:  # noqa: BLE001
            status.profile_error = str(err)

        statuses.append(status)
        on_progress(f"{source}: {status.fixtures_scraped} fixtures" + (f" -- {status.matches_error}" if status.matches_error else ""))
        on_source_progress(status)

    merged = merge_match_details(details_by_source) if details_by_source else None
    form_source = next((s for s in SOURCE_ORDER if matches_by_source.get(s)), None)
    form = compute_form_summary(team_name, matches_by_source[form_source]) if form_source else None
    merged_profile = merge_team_profile(profile_by_source) if profile_by_source else None

    insights_result: Optional[MatchInsights] = None
    venue_details: Optional[VenueDetails] = None
    opponent_name: Optional[str] = None
    opponent_profile: Optional[MergedProfile] = None
    opponent_form = None

    if merged:
        own_is_home = is_team_home(merged, team_name)
        opponent_name = merged.home_team if own_is_home is False else merged.away_team
        own_rest_days = form.next5_with_gaps[0].days_since_previous if form and form.next5_with_gaps else None

        if form_source and form:
            # The deep Sofascore-based computation (formations/xG per
            # meeting, from the already-fetched last20Overall enrichment)
            # is richer than any other source's own recent_meetings field,
            # so it takes priority when it succeeds -- but doesn't clobber
            # a decent fallback the field-merge already filled in (e.g.
            # from SoccerDesk) when it comes back empty.
            try:
                deep_recent_meetings = await ins.compute_recent_meetings(matches_by_source[form_source], form.last20_overall, opponent_name, form_source)
            except Exception:  # noqa: BLE001
                deep_recent_meetings = None
            apply_deep_recent_meetings(merged, deep_recent_meetings, form_source)

        own_advanced_stats = None
        if form_source and form:
            try:
                enriched_own = await enrich_form_with_venue_classification(matches_by_source[form_source], form, form_source)
            except Exception:  # noqa: BLE001
                from .form import VenueEnrichmentResult

                enriched_own = VenueEnrichmentResult(form=form, advanced_stats=None, usage_by_player={})
            form = enriched_own.form
            own_advanced_stats = enriched_own.advanced_stats
            if merged_profile:
                merged_profile.squad = ins.apply_usage_pattern(merged_profile.squad, enriched_own.usage_by_player)

        on_progress(f"Next match found: {merged.home_team} vs {merged.away_team}. Fetching opponent ({opponent_name}) and computing insights...")
        opponent_context = await fetch_opponent_context(merged.base_source, opponent_name)
        opponent_profile = opponent_context.merged_profile

        insights_result = ins.compute_insights(merged, merged_profile.average_age if merged_profile else None, own_rest_days, opponent_context)
        venue_details = await fetch_venue_details(merged, merged.venue_country)

        try:
            strength_ratings = await statsultra.get_club_strength_ratings(merged.home_team, merged.away_team)
        except Exception:  # noqa: BLE001
            strength_ratings = {"home": None, "away": None}
        insights_result.home_club_strength = strength_ratings["home"]
        insights_result.away_club_strength = strength_ratings["away"]

        if merged.home_manager:
            try:
                tenure_row = await wikipedia.get_current_tenure_row(merged.home_manager.name)
            except Exception:  # noqa: BLE001
                tenure_row = None
            appointed_date = wikipedia.parse_wiki_date(tenure_row.from_date) if tenure_row and tenure_row.from_date else None
            record_at_club = (
                ManagerTenureRecord(played=tenure_row.played, wins=tenure_row.wins, draws=tenure_row.draws, losses=tenure_row.losses, win_pct=tenure_row.win_pct)
                if tenure_row and tenure_row.played is not None and tenure_row.wins is not None and tenure_row.draws is not None and tenure_row.losses is not None
                else None
            )
            manager_age = _age_from_iso_date(tenure_row.date_of_birth) if tenure_row else None
            try:
                previous_manager = await wikipedia.get_previous_manager(merged.home_team)
            except Exception:  # noqa: BLE001
                previous_manager = None
            from dataclasses import replace as _replace

            merged.home_manager = _replace(
                merged.home_manager, appointed_date=appointed_date, previous_manager=previous_manager,
                recent_appointment=ins.is_recent_appointment(appointed_date), record_at_club=record_at_club,
                age=manager_age,
            )
        if merged.away_manager:
            try:
                tenure_row = await wikipedia.get_current_tenure_row(merged.away_manager.name)
            except Exception:  # noqa: BLE001
                tenure_row = None
            appointed_date = wikipedia.parse_wiki_date(tenure_row.from_date) if tenure_row and tenure_row.from_date else None
            record_at_club = (
                ManagerTenureRecord(played=tenure_row.played, wins=tenure_row.wins, draws=tenure_row.draws, losses=tenure_row.losses, win_pct=tenure_row.win_pct)
                if tenure_row and tenure_row.played is not None and tenure_row.wins is not None and tenure_row.draws is not None and tenure_row.losses is not None
                else None
            )
            manager_age = _age_from_iso_date(tenure_row.date_of_birth) if tenure_row else None
            try:
                previous_manager = await wikipedia.get_previous_manager(merged.away_team)
            except Exception:  # noqa: BLE001
                previous_manager = None
            from dataclasses import replace as _replace

            merged.away_manager = _replace(
                merged.away_manager, appointed_date=appointed_date, previous_manager=previous_manager,
                recent_appointment=ins.is_recent_appointment(appointed_date), record_at_club=record_at_club,
                age=manager_age,
            )

        if merged.referee_stats:
            try:
                worldfootball_stats = await worldfootball.get_referee_worldfootball_stats(merged.competition, merged.referee)
            except Exception:  # noqa: BLE001
                worldfootball_stats = None
            try:
                home_away_bias = await footballdata.get_referee_home_away_bias(merged.competition, merged.referee)
            except Exception:  # noqa: BLE001
                home_away_bias = None
            try:
                refsradar_kpis = await refsradar.get_referee_kpis(merged.referee)
            except Exception:  # noqa: BLE001
                refsradar_kpis = None
            from dataclasses import replace as _replace

            merged.referee_stats = _replace(
                merged.referee_stats,
                penalties_awarded=(worldfootball_stats.penalties if worldfootball_stats else None),
                second_yellow_cards=(worldfootball_stats.second_yellow if worldfootball_stats else None),
                home_away_bias=home_away_bias,
                fouls_per_game=(refsradar_kpis.fouls_per_game if refsradar_kpis else None),
                red_cards_per_game=(refsradar_kpis.red_cards_per_game if refsradar_kpis else None),
                referee_matches=(refsradar_kpis.matches if refsradar_kpis else None),
                penalties_per_game=(refsradar_kpis.penalties_per_game if refsradar_kpis else None),
                cards_per_foul=(refsradar_kpis.cards_per_foul if refsradar_kpis else None),
                avg_total_cards=(refsradar_kpis.avg_total_cards if refsradar_kpis else None),
            )

        # Both teams get the full-depth xG/possession-matchup/losing-streak
        # treatment, not just the searched team -- costs 2 extra
        # fixture-list fetches (Fotmob + Goal.com) for the opponent.
        try:
            opponent_fotmob_matches = await fotmob.get_fotmob_matches(opponent_name)
        except Exception:  # noqa: BLE001
            opponent_fotmob_matches = []
        try:
            opponent_goal_matches = await goal.get_goal_matches(opponent_name)
        except Exception:  # noqa: BLE001
            opponent_goal_matches = []
        own_match_stats = await ins.compute_season_match_stats_estimate(team_name, matches_by_source.get("fotmob", []))
        opponent_match_stats = await ins.compute_season_match_stats_estimate(opponent_name, opponent_fotmob_matches)
        own_xg_estimate = own_match_stats.xg
        opponent_xg_estimate = opponent_match_stats.xg
        insights_result.home_xg_estimate = own_xg_estimate if own_is_home else opponent_xg_estimate
        insights_result.away_xg_estimate = opponent_xg_estimate if own_is_home else own_xg_estimate
        insights_result.home_shots_estimate = own_match_stats.shots if own_is_home else opponent_match_stats.shots
        insights_result.away_shots_estimate = opponent_match_stats.shots if own_is_home else own_match_stats.shots
        insights_result.home_card_discipline_venue_split = own_match_stats.card_split if own_is_home else opponent_match_stats.card_split
        insights_result.away_card_discipline_venue_split = opponent_match_stats.card_split if own_is_home else own_match_stats.card_split
        insights_result.home_aerial_estimate = own_match_stats.aerial if own_is_home else opponent_match_stats.aerial
        insights_result.away_aerial_estimate = opponent_match_stats.aerial if own_is_home else own_match_stats.aerial
        insights_result.home_big_chances_estimate = own_match_stats.big_chances if own_is_home else opponent_match_stats.big_chances
        insights_result.away_big_chances_estimate = opponent_match_stats.big_chances if own_is_home else own_match_stats.big_chances
        insights_result.home_passing_style = own_match_stats.passing_style if own_is_home else opponent_match_stats.passing_style
        insights_result.away_passing_style = opponent_match_stats.passing_style if own_is_home else own_match_stats.passing_style
        insights_result.home_fouls_estimate = own_match_stats.fouls if own_is_home else opponent_match_stats.fouls
        insights_result.away_fouls_estimate = opponent_match_stats.fouls if own_is_home else own_match_stats.fouls
        insights_result.home_goalkeeping_estimate = own_match_stats.goalkeeping if own_is_home else opponent_match_stats.goalkeeping
        insights_result.away_goalkeeping_estimate = opponent_match_stats.goalkeeping if own_is_home else own_match_stats.goalkeeping

        own_poss_corners = await ins.compute_possession_matchup(team_name, matches_by_source.get("goal", []))
        opponent_poss_corners = await ins.compute_possession_matchup(opponent_name, opponent_goal_matches)
        insights_result.home_possession_matchup = own_poss_corners.possession if own_is_home else opponent_poss_corners.possession
        insights_result.away_possession_matchup = opponent_poss_corners.possession if own_is_home else own_poss_corners.possession
        insights_result.home_corners_estimate = own_poss_corners.corners if own_is_home else opponent_poss_corners.corners
        insights_result.away_corners_estimate = opponent_poss_corners.corners if own_is_home else own_poss_corners.corners
        insights_result.home_defensive_errors_estimate = own_poss_corners.defensive_errors if own_is_home else opponent_poss_corners.defensive_errors
        insights_result.away_defensive_errors_estimate = opponent_poss_corners.defensive_errors if own_is_home else own_poss_corners.defensive_errors

        insights_result.home_set_piece_threat = ins.compute_set_piece_threat_flag(insights_result.home_corners_estimate, insights_result.away_aerial_estimate)
        insights_result.away_set_piece_threat = ins.compute_set_piece_threat_flag(insights_result.away_corners_estimate, insights_result.home_aerial_estimate)
        insights_result.home_direct_play_exposure = ins.compute_direct_play_exposure_flag(insights_result.home_passing_style, insights_result.away_aerial_estimate)
        insights_result.away_direct_play_exposure = ins.compute_direct_play_exposure_flag(insights_result.away_passing_style, insights_result.home_aerial_estimate)

        own_position = (merged.home_team_standing if own_is_home else merged.away_team_standing)
        own_position = own_position.position if own_position else None
        opponent_position = (merged.away_team_standing if own_is_home else merged.home_team_standing)
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
            except Exception:  # noqa: BLE001
                from .form import VenueEnrichmentResult

                enriched_opponent = VenueEnrichmentResult(form=opponent_form, advanced_stats=None, usage_by_player={})
        else:
            from .form import VenueEnrichmentResult

            enriched_opponent = VenueEnrichmentResult(form=opponent_form, advanced_stats=None, usage_by_player={})
        opponent_form = enriched_opponent.form
        opponent_advanced_stats = enriched_opponent.advanced_stats
        if opponent_profile:
            opponent_profile.squad = ins.apply_usage_pattern(opponent_profile.squad, enriched_opponent.usage_by_player)
        insights_result.home_advanced_stats = own_advanced_stats if own_is_home else opponent_advanced_stats
        insights_result.away_advanced_stats = opponent_advanced_stats if own_is_home else own_advanced_stats
        own_rank_record = ins.compute_opponent_rank_record(form.last20_overall if form else [], merged.competition, merged.standings_table, own_position)
        opponent_rank_record = ins.compute_opponent_rank_record(opponent_form.last20_overall, merged.competition, merged.standings_table, opponent_position)

        own_elo = compute_elo_rating(form.last20_overall if form else [])
        opponent_elo = compute_elo_rating(opponent_form.last20_overall)
        insights_result.home_elo_rating = own_elo if own_is_home else opponent_elo
        insights_result.away_elo_rating = opponent_elo if own_is_home else own_elo

        try:
            merged.betting_odds = await footballdata.get_upcoming_match_odds(merged.home_team, merged.away_team)
        except Exception:  # noqa: BLE001
            merged.betting_odds = None

        # Candidate names are each team's OWN recent competitions, not the
        # upcoming match's specific competition.
        from .merge import enrich_squad_with_defensive_stats

        if merged_profile and merged_profile.squad:
            merged_profile.squad = await enrich_squad_with_defensive_stats(merged_profile.squad, team_name, form.recent_competitions if form else [])
        if opponent_profile and opponent_profile.squad:
            opponent_profile.squad = await enrich_squad_with_defensive_stats(opponent_profile.squad, opponent_name, opponent_form.recent_competitions)

        # Leaderboards/breakdowns derived purely from each profile's own
        # now-fully-enriched squad (season stats, defensive stats, recent
        # usage all populated above) -- zero extra requests. Previously
        # computed only inside format_markdown.py and never stored, so a
        # JSON consumer had no way to see them.
        for profile in (merged_profile, opponent_profile):
            if not profile or not profile.squad:
                continue
            profile.top_scorers = compute_top_performers(profile.squad, "goals")
            profile.top_assists = compute_top_performers(profile.squad, "assists")
            profile.top_defenders = compute_top_defenders(profile.squad)
            profile.bench_regulars = compute_bench_regulars(profile.squad)
            profile.midfielders_form = compute_role_form_breakdown(profile.squad, is_midfield_role)
            profile.defenders_form = compute_role_form_breakdown(profile.squad, is_defender_role)
            profile.recent_form_leaders = compute_recent_form_leaders(profile.squad)

        own_duel_vulnerabilities = ins.compute_duel_vulnerabilities(merged_profile.squad if merged_profile else None)
        opponent_duel_vulnerabilities = ins.compute_duel_vulnerabilities(opponent_profile.squad if opponent_profile else None)
        insights_result.home_duel_vulnerabilities = own_duel_vulnerabilities if own_is_home else opponent_duel_vulnerabilities
        insights_result.away_duel_vulnerabilities = opponent_duel_vulnerabilities if own_is_home else own_duel_vulnerabilities

        own_fullback_exposure = ins.compute_fullback_exposure(merged_profile.squad if merged_profile else None)
        opponent_fullback_exposure = ins.compute_fullback_exposure(opponent_profile.squad if opponent_profile else None)
        insights_result.home_fullback_exposure = own_fullback_exposure if own_is_home else opponent_fullback_exposure
        insights_result.away_fullback_exposure = opponent_fullback_exposure if own_is_home else own_fullback_exposure

        own_presence = ins.compute_presence(
            merged_profile.squad if merged_profile else None,
            merged.home_lineup if own_is_home else merged.away_lineup,
            merged.home_bench if own_is_home else merged.away_bench,
            merged_profile.injuries if merged_profile else None,
            merged.home_suspended_players if own_is_home else merged.away_suspended_players,
        )
        opponent_presence = ins.compute_presence(
            opponent_profile.squad if opponent_profile else None,
            merged.away_lineup if own_is_home else merged.home_lineup,
            merged.away_bench if own_is_home else merged.home_bench,
            opponent_profile.injuries if opponent_profile else None,
            merged.away_suspended_players if own_is_home else merged.home_suspended_players,
        )

        insights_result.home_bench_info = ins.compute_bench_info(merged.home_bench, merged.home_lineup, (merged_profile.squad if own_is_home else opponent_profile.squad if opponent_profile else None) if merged_profile or opponent_profile else None)
        insights_result.away_bench_info = ins.compute_bench_info(merged.away_bench, merged.away_lineup, (opponent_profile.squad if own_is_home else merged_profile.squad if merged_profile else None) if merged_profile or opponent_profile else None)

        own_squad_strength = ins.compute_squad_strength(merged_profile.squad if merged_profile else None, merged_profile.injuries if merged_profile else None, merged.home_suspended_players if own_is_home else merged.away_suspended_players)
        opponent_squad_strength = ins.compute_squad_strength(opponent_profile.squad if opponent_profile else None, opponent_profile.injuries if opponent_profile else None, merged.away_suspended_players if own_is_home else merged.home_suspended_players)
        insights_result.home_squad_strength = own_squad_strength if own_is_home else opponent_squad_strength
        insights_result.away_squad_strength = opponent_squad_strength if own_is_home else own_squad_strength

        # After squad_strength (needs the fully-enriched squad/injuries
        # above) and rest_comparison (already set inside insights_result
        # by compute_insights near the top of this function) are both
        # available -- see prediction.py's own module docstring for why
        # rest-days and available-squad-value specifically feed the
        # heuristic model, and why xg_model is deliberately computed
        # without them.
        home_rest_days = own_rest_days if own_is_home else opponent_context.rest_days
        away_rest_days = opponent_context.rest_days if own_is_home else own_rest_days
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

        insights_result.home_opponent_rank_record = own_rank_record if own_is_home else opponent_rank_record
        insights_result.away_opponent_rank_record = opponent_rank_record if own_is_home else own_rank_record
        insights_result.home_presence = own_presence if own_is_home else opponent_presence
        insights_result.away_presence = opponent_presence if own_is_home else own_presence
        insights_result.home_rotation = own_rotation if own_is_home else opponent_rotation
        insights_result.away_rotation = opponent_rotation if own_is_home else own_rotation

        own_resilience = ins.compute_resilience(form.last20_overall if form else [])
        opponent_resilience = ins.compute_resilience(opponent_form.last20_overall)
        insights_result.home_resilience = own_resilience if own_is_home else opponent_resilience
        insights_result.away_resilience = opponent_resilience if own_is_home else own_resilience

        own_rest_performance = ins.compute_rest_performance(team_name, matches_by_source.get(form_source, []) if form_source else [])
        opponent_rest_performance = ins.compute_rest_performance(opponent_name, opponent_context.matches)
        insights_result.home_rest_performance = own_rest_performance if own_is_home else opponent_rest_performance
        insights_result.away_rest_performance = opponent_rest_performance if own_is_home else own_rest_performance

        insights_result.experience_h2h = ins.compute_experience_h2h(insights_result.experience_comparison, merged.head_to_head_summary, own_is_home)

        own_fatigue_flag = ins.compute_fatigue_flag(form.recent_competitions if form else [], form.gaps_between_last_three if form else [])
        opponent_fatigue_flag = ins.compute_fatigue_flag(opponent_form.recent_competitions, opponent_form.gaps_between_last_three)
        insights_result.home_fatigue_flag = own_fatigue_flag if own_is_home else opponent_fatigue_flag
        insights_result.away_fatigue_flag = opponent_fatigue_flag if own_is_home else own_fatigue_flag

        own_advantage = ins.compute_home_advantage(form)
        opponent_advantage = ins.compute_home_advantage(opponent_form)
        insights_result.home_advantage = own_advantage if own_is_home else opponent_advantage
        insights_result.away_advantage = opponent_advantage if own_is_home else own_advantage

        own_streak_stability = ins.compute_streak_stability(form.current_streak if form else None, own_rotation)
        opponent_streak_stability = ins.compute_streak_stability(opponent_form.current_streak, opponent_rotation)
        insights_result.home_streak_stability = own_streak_stability if own_is_home else opponent_streak_stability
        insights_result.away_streak_stability = opponent_streak_stability if own_is_home else own_streak_stability

        own_losing_streak_context = ins.compute_losing_streak_context(form.current_streak if form else None, own_xg_estimate)
        opponent_losing_streak_context = ins.compute_losing_streak_context(opponent_form.current_streak, opponent_xg_estimate)
        insights_result.home_losing_streak_context = own_losing_streak_context if own_is_home else opponent_losing_streak_context
        insights_result.away_losing_streak_context = opponent_losing_streak_context if own_is_home else own_losing_streak_context

        own_card_risks = ins.compute_card_risks(merged_profile.squad if merged_profile else None)
        opponent_card_risks = ins.compute_card_risks(opponent_profile.squad if opponent_profile else None)
        insights_result.home_card_risks = own_card_risks if own_is_home else opponent_card_risks
        insights_result.away_card_risks = opponent_card_risks if own_is_home else own_card_risks

        insights_result.referee_card_risk_note = ins.compute_referee_card_risk_note(merged.referee, merged.referee_stats, insights_result.home_card_risks, insights_result.away_card_risks)

        weather_query_city = merged.venue_city or merged.venue_name
        if weather_query_city:
            try:
                weather_detail = await wttrin.get_wttr_weather_detail(weather_query_city, merged.kickoff_utc, merged.venue_country)
            except Exception:  # noqa: BLE001
                weather_detail = None
            if weather_detail:
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

    on_progress("Done.")
    generated_at = datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace(_UTC_OFFSET_SUFFIX, "Z")
    # opponent_context only exists inside the `if merged:` block above --
    # when no upcoming match was found from any source, there's no
    # opponent to have looked up, so opponent_form_source is genuinely
    # None rather than an unset local variable. (Pre-existing bug: this
    # unconditional reference used to raise UnboundLocalError for any
    # "no upcoming match" search -- crashing the whole pipeline instead
    # of returning the graceful empty result callers already expect,
    # e.g. android_test.py's `if not result.merged: return "OK (no
    # upcoming match found...)"` check could never actually be reached.)
    opponent_form_source = opponent_context.matches_source if merged else None
    return RunSearchResult(
        team=team_name, generated_at=generated_at, statuses=statuses, merged=merged, opponent_name=opponent_name,
        form=form, form_source=form_source, opponent_form=opponent_form, opponent_form_source=opponent_form_source,
        merged_profile=merged_profile, opponent_profile=opponent_profile, insights=insights_result, venue_details=venue_details,
    )
