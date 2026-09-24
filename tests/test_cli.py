import asyncio
from dataclasses import fields as _dc_fields

import pytest

from football import cli
from football.cli import _main, _parse_team_names, _run_one, main


def test_single_team_no_comma():
    assert _parse_team_names("Real Madrid") == ["Real Madrid"]


def test_multiple_teams_comma_separated():
    assert _parse_team_names("Real Madrid, Liverpool, Bayern Munich") == [
        "Real Madrid",
        "Liverpool",
        "Bayern Munich",
    ]


def test_extra_whitespace_and_commas_are_ignored():
    assert _parse_team_names(" Real Madrid ,, Liverpool ,") == ["Real Madrid", "Liverpool"]


def test_empty_string_yields_empty_list():
    assert _parse_team_names("") == []
    assert _parse_team_names("   ") == []


def _all_none(cls, **overrides):
    base = {f.name: None for f in _dc_fields(cls)}
    base.update(overrides)
    return cls(**base)


def _fake_result(team="Arsenal"):
    from football.orchestrate import RunSearchResult

    return _all_none(
        RunSearchResult, team=team, generated_at="2026-01-01T00-00-00-000Z", statuses=[],
        merged=None, opponent_name=None, form=None, opponent_form=None,
    )


# --- _run_one -----------------------------------------------------------------


def test_run_one_writes_json_and_markdown_files(monkeypatch, tmp_path, capsys):
    async def fake_run_search(team_name, on_progress):
        on_progress("scraping...")
        return _fake_result(team_name)

    monkeypatch.setattr(cli, "run_search", fake_run_search)
    monkeypatch.setattr(cli, "_OUTPUT_DIR", tmp_path)

    asyncio.run(_run_one("Arsenal", announce=False))

    written = list(tmp_path.iterdir())
    assert any(p.suffix == ".json" for p in written)
    assert any(p.suffix == ".md" for p in written)
    out = capsys.readouterr().out
    assert "scraping..." in out
    assert "Saved:" in out


def test_run_one_progress_and_report_prints_are_flushed(monkeypatch, tmp_path, capsys):
    """Piped stdout is block-buffered; without flush=True a multi-minute
    run looks hung (regression: enrichment phase produced zero visible
    lines until exit)."""
    seen_flush: list[bool] = []
    real_print = print

    def spy_print(*args, **kwargs):
        seen_flush.append(bool(kwargs.get("flush")))
        return real_print(*args, **kwargs)

    async def fake_run_search(team_name, on_progress):
        on_progress("scraping...")
        return _fake_result(team_name)

    monkeypatch.setattr(cli, "run_search", fake_run_search)
    monkeypatch.setattr(cli, "_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("builtins.print", spy_print)

    asyncio.run(_run_one("Arsenal", announce=False))
    assert seen_flush, "expected print calls"
    assert all(seen_flush), "every CLI print must pass flush=True"
    capsys.readouterr()


def test_run_one_announces_team_when_running_a_batch(monkeypatch, tmp_path, capsys):
    async def fake_run_search(team_name, on_progress):
        return _fake_result(team_name)

    monkeypatch.setattr(cli, "run_search", fake_run_search)
    monkeypatch.setattr(cli, "_OUTPUT_DIR", tmp_path)

    asyncio.run(_run_one("Chelsea", announce=True))
    out = capsys.readouterr().out
    assert "=== Chelsea ===" in out


# --- _main ----------------------------------------------------------------------


def test_main_exits_with_usage_message_when_no_team_given(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["football-search"])
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(_main())
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().err


def test_main_exits_1_when_parse_yields_no_team_names(monkeypatch, capsys):
    # Comma-only garbage (", ,") parses to [] -- previously a silent
    # zero-iteration batch that exited 0 with no output.
    monkeypatch.setattr("sys.argv", ["football-search", ", ,"])
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(_main())
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().err


def test_main_continues_batch_after_one_team_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.argv", ["football-search", "Good Team, Bad Team"])
    monkeypatch.setattr(cli, "_OUTPUT_DIR", tmp_path)

    async def fake_run_search(team_name, on_progress):
        if team_name == "Bad Team":
            raise RuntimeError("no data found")
        return _fake_result(team_name)

    monkeypatch.setattr(cli, "run_search", fake_run_search)

    asyncio.run(_main())  # must not raise/exit -- one failure out of two is a partial success
    out = capsys.readouterr().out
    assert "Done: 1/2 succeeded" in out
    assert "failed: Bad Team" in out


def test_main_exits_1_when_every_team_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["football-search", "Bad Team"])
    monkeypatch.setattr(cli, "_OUTPUT_DIR", tmp_path)

    async def failing_run_search(team_name, on_progress):
        raise RuntimeError("no data found")

    monkeypatch.setattr(cli, "run_search", failing_run_search)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(_main())
    assert exc_info.value.code == 1


def test_main_runs_the_asyncio_entry_point(monkeypatch, capsys):
    # main() is the actual console-script entry point -- exercises the
    # real asyncio.run(_main()) wiring, not just _main() called directly
    # the way every other test in this file does.
    monkeypatch.setattr("sys.argv", [])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().err
