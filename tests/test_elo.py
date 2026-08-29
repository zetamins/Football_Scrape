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


def test_rank_is_always_none():
    rating = compute_elo_rating([_result("W")])
    assert rating.rank is None


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
