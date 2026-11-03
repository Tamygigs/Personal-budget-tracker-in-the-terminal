"""End-to-end tests: run the real `tally` command against a temporary database."""

from pathlib import Path

import pytest

from tally.cli import main

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample-statement.csv"


@pytest.fixture
def tally(tmp_path, capsys):
    db = tmp_path / "test.db"

    def run(*args):
        code = main(["--db", str(db), *args])
        out, err = capsys.readouterr()
        return code, out, err

    return run


def test_help_with_no_command(tally):
    code, out, _ = tally()
    assert code == 0
    assert "import" in out


def test_empty_database_is_friendly(tally):
    for command in (["report"], ["trend"], ["list"]):
        code, out, _ = tally(*command)
        assert code == 0
        assert "Import a bank statement first" in out


def test_full_workflow(tally):
    code, out, _ = tally("import", str(SAMPLE))
    assert code == 0
    assert "Added 104 new transactions" in out

    code, out, _ = tally("import", str(SAMPLE))
    assert "Added 0 new transactions (104 already imported)" in out

    code, out, _ = tally("rules", "add", "TESCO", "Groceries")
    assert code == 0
    assert "→ groceries" in out
    assert "Re-categorised" in out

    tally("budget", "set", "groceries", "50")
    code, out, _ = tally("report", "--month", "2026-10")
    assert code == 0
    assert "October 2026" in out
    assert "groceries" in out
    assert "over budget" in out

    code, out, _ = tally("list", "--category", "groceries", "--month", "2026-10")
    assert "TESCO" in out
    assert "SAINSBURY" not in out

    code, out, _ = tally("trend", "--months", "3")
    assert "Aug 2026" in out and "Oct 2026" in out


def test_manual_categorize(tally):
    tally("import", str(SAMPLE))
    _, out, _ = tally("list", "--search", "FARMERS")
    tx_id = out.split()[0]
    code, out, _ = tally("categorize", tx_id, "groceries")
    assert code == 0
    _, out, _ = tally("list", "--search", "FARMERS")
    assert "groceries*" in out


def test_dry_run_saves_nothing(tally):
    code, out, _ = tally("import", str(SAMPLE), "--dry-run")
    assert "Dry run" in out
    _, out, _ = tally("list")
    assert "Import a bank statement first" in out


def test_errors_are_short_and_exit_1(tally, tmp_path):
    code, _, err = tally("import", str(tmp_path / "missing.csv"))
    assert code == 1
    assert err.startswith("error: file not found")

    code, _, err = tally("report", "--month", "October")
    assert code == 1
    assert "2026-10" in err

    code, _, err = tally("rules", "add", "(bad", "x", "--regex")
    assert code == 1
    assert "invalid regular expression" in err

    code, _, err = tally("budget", "set", "food", "-5")
    assert code == 1


def test_config_currency(tally):
    tally("config", "--currency", "$")
    tally("import", str(SAMPLE))
    _, out, _ = tally("report")
    assert "$2,450.00" in out
