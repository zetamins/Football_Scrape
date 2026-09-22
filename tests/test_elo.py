from football.elo import compute_elo_rating
from football.types import FormResult


def _result(result: str, margin: int = 1, competition: str = "Test League") -> FormResult:
    return FormResult(
        opponent="Opponent",
        competition=competition,
        date="2026-01-01T00:00:00.000Z",
        result=result,
        scoreline="1-0" if result == "W" else "0-1" if result == "L" else "0-0",
        venue="home",
        margin=margin,
        neutral_venue=None,
        ht_scoreline=None,
        xg_for=None,
        xg_against=None,
    )


def test_empty_results_returns_none():
    assert compute_elo_rating([]) is None


def test_all_wins_ends_above_baseline():
    results = [_result("W") for _ in range(5)]
    rating = compute_elo_rating(results)
    assert rating is not None
    assert rating.elo > 1500.0


def test_all_losses_ends_below_baseline():
    results = [_result("L") for _ in range(5)]
    rating = compute_elo_rating(results)
    assert rating is not None
    assert rating.elo < 1500.0


def test_all_draws_stays_at_baseline():
    results = [_result("D") for _ in range(5)]
    rating = compute_elo_rating(results)
    assert rating is not None
    assert rating.elo == 1500.0


def test_bigger_margin_wins_move_rating_more():
    small_margin = compute_elo_rating([_result("W", margin=1)])
    big_margin = compute_elo_rating([_result("W", margin=4)])
    assert big_margin.elo > small_margin.elo


def test_friendlies_are_excluded_from_the_rating():
    # Confirmed live this matters a lot: a real team's last20_overall
    # window can be roughly a third preseason "Club Friendly Games"
    # entries, which flattened every team's rating toward the same
    # ~1500-1515 band regardless of actual recent competitive form.
    competitive_losses = [_result("L", competition="Bundesliga") for _ in range(5)]
    friendly_wins = [_result("W", margin=4, competition="Club Friendly Games") for _ in range(5)]
    with_friendlies = compute_elo_rating([*friendly_wins, *competitive_losses])
    without_friendlies = compute_elo_rating(competitive_losses)
    assert with_friendlies.elo == without_friendlies.elo


def test_friendly_label_variants_are_all_excluded():
    for label in ["Club Friendly Games", "Club Friendlies", "Friendlies", "Emirates Cup (Friendly)"]:
        losses = [_result("L", competition="Bundesliga") for _ in range(3)]
        friendlies = [_result("W", margin=4, competition=label) for _ in range(3)]
        assert compute_elo_rating([*friendlies, *losses]) == compute_elo_rating(losses)


def test_falls_back_to_unfiltered_results_when_everything_is_a_friendly():
    all_friendly = [_result("W", competition="Club Friendly Games") for _ in range(3)]
    rating = compute_elo_rating(all_friendly)
    assert rating is not None
    assert rating.elo > 1500.0


def test_none_competition_is_not_treated_as_a_friendly():
    results = [_result("W", competition=None) for _ in range(3)]
    rating = compute_elo_rating(results)
    assert rating is not None
    assert rating.elo > 1500.0


# --- league_elo_rank / with_league_rank -----------------------------------------------------


def _row(position, wins, draws, losses, goal_difference=0, points=None):
    from football.types import StandingsTableRow

    played = wins + draws + losses
    return StandingsTableRow(
        team_name=f"Team{position}", position=position, points=points if points is not None else 3 * wins + draws,
        played=played, wins=wins, draws=draws, losses=losses, goal_difference=goal_difference,
    )


def test_league_elo_rank_orders_by_season_score_fraction():
    from football.elo import league_elo_rank

    table = [_row(1, 6, 1, 1), _row(2, 4, 2, 2), _row(3, 1, 1, 6)]
    assert league_elo_rank(table, 1) == (1, 3, 8)
    assert league_elo_rank(table, 2) == (2, 3, 8)
    assert league_elo_rank(table, 3) == (3, 3, 8)


def test_league_elo_rank_can_differ_from_table_position():
    from football.elo import league_elo_rank

    # A team below in points-per-match terms... position 1 has a worse
    # W/D/L record than position 2 here (fewer matches played, more draws).
    table = [_row(1, 2, 4, 0), _row(2, 5, 0, 1)]
    assert league_elo_rank(table, 2)[0] == 1


def test_league_elo_rank_breaks_ties_by_goal_difference():
    from football.elo import league_elo_rank

    table = [_row(1, 3, 0, 1, goal_difference=2), _row(2, 3, 0, 1, goal_difference=6)]
    assert league_elo_rank(table, 2)[0] == 1


def test_league_elo_rank_none_without_usable_data():
    from football.elo import league_elo_rank
    from football.types import StandingsTableRow

    assert league_elo_rank(None, 1) is None
    assert league_elo_rank([_row(1, 1, 0, 0)], None) is None
    assert league_elo_rank([_row(1, 1, 0, 0)], 9) is None  # position not in table
    no_wdl = StandingsTableRow(team_name="X", position=1, points=3)
    assert league_elo_rank([no_wdl], 1) is None
    assert league_elo_rank([_row(1, 0, 0, 0)], 1) is None  # nothing played yet


def test_with_league_rank_attaches_rank_and_an_honest_basis():
    from football.elo import with_league_rank
    from football.types import EloRating

    elo = EloRating(elo=1500.0, as_of="2026-09-21")
    result = with_league_rank(elo, [_row(1, 6, 1, 1), _row(2, 4, 2, 2)], 2)
    assert (result.rank, result.rank_of) == (2, 2)
    assert "not a world rank" in result.rank_basis
    assert result.elo == 1500.0


def test_with_league_rank_leaves_elo_untouched_without_a_table_and_passes_none_through():
    from football.elo import with_league_rank
    from football.types import EloRating

    elo = EloRating(elo=1500.0, as_of="2026-09-21")
    assert with_league_rank(elo, None, 1).rank is None
    assert with_league_rank(None, [_row(1, 1, 0, 0)], 1) is None
