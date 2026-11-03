"""Local storage in a single SQLite file.

Everything Tally knows lives in one file on your own computer (by default
~/.tally/tally.db). Nothing is ever sent anywhere.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path

from tally.importer import ParsedTransaction
from tally.rules import Rule

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY,
    date            TEXT    NOT NULL,          -- ISO format: YYYY-MM-DD
    description     TEXT    NOT NULL,
    amount          INTEGER NOT NULL,          -- minor units; negative = money out
    category        TEXT,                      -- NULL = uncategorised
    category_manual INTEGER NOT NULL DEFAULT 0,-- 1 = set by hand; rules won't overwrite
    source          TEXT,                      -- file it was imported from
    fingerprint     TEXT    NOT NULL UNIQUE    -- stops duplicate imports
);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);

CREATE TABLE IF NOT EXISTS rules (
    id       INTEGER PRIMARY KEY,
    pattern  TEXT    NOT NULL,
    category TEXT    NOT NULL,
    is_regex INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    UNIQUE (pattern, is_regex)
);

CREATE TABLE IF NOT EXISTS budgets (
    category      TEXT    PRIMARY KEY,
    monthly_limit INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    """$TALLY_DB if set, otherwise ~/.tally/tally.db."""
    env = os.environ.get("TALLY_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".tally" / "tally.db"


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- settings ---------------------------------------------------------

    def get_setting(self, key: str, default: str) -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # -- transactions -----------------------------------------------------

    def add_transactions(
        self,
        transactions: Iterable[ParsedTransaction],
        fingerprints: Iterable[str],
        source: str,
        categorize: Callable[[str], str | None],
    ) -> tuple[int, int]:
        """Insert new transactions. Returns (added, duplicates_skipped)."""
        added = duplicates = 0
        with self.conn:
            for t, fp in zip(transactions, fingerprints, strict=True):
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO transactions "
                    "(date, description, amount, category, source, fingerprint) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (t.date.isoformat(), t.description, t.amount, categorize(t.description), source, fp),
                )
                if cur.rowcount:
                    added += 1
                else:
                    duplicates += 1
        return added, duplicates

    def transactions(
        self,
        month: str | None = None,
        category: str | None = None,
        search: str | None = None,
        uncategorised: bool = False,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch transactions, newest first, with optional filters."""
        where, params = [], []
        if month:
            where.append("substr(date, 1, 7) = ?")
            params.append(month)
        if category:
            where.append("category = ?")
            params.append(category)
        if uncategorised:
            where.append("category IS NULL")
        if search:
            where.append("description LIKE ?")
            params.append(f"%{search}%")
        sql = "SELECT * FROM transactions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date DESC, id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def set_category(self, transaction_id: int, category: str | None) -> bool:
        """Set a category by hand. Passing None hands it back to the rules."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE transactions SET category = ?, category_manual = ? WHERE id = ?",
                (category, 1 if category else 0, transaction_id),
            )
        return cur.rowcount > 0

    def recategorize(self, categorize: Callable[[str], str | None]) -> int:
        """Re-run rules over every transaction not categorised by hand."""
        changed = 0
        rows = self.conn.execute(
            "SELECT id, description, category FROM transactions WHERE category_manual = 0"
        ).fetchall()
        with self.conn:
            for row in rows:
                new = categorize(row["description"])
                if new != row["category"]:
                    self.conn.execute("UPDATE transactions SET category = ? WHERE id = ?", (new, row["id"]))
                    changed += 1
        return changed

    def months(self) -> list[str]:
        """Every YYYY-MM that has at least one transaction, oldest first."""
        rows = self.conn.execute(
            "SELECT DISTINCT substr(date, 1, 7) AS m FROM transactions ORDER BY m"
        ).fetchall()
        return [r["m"] for r in rows]

    # -- rules ------------------------------------------------------------

    def add_rule(self, pattern: str, category: str, is_regex: bool = False, priority: int = 0) -> int:
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO rules (pattern, category, is_regex, priority) VALUES (?, ?, ?, ?)",
                    (pattern, category, int(is_regex), priority),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"a rule for {pattern!r} already exists") from None
        return int(cur.lastrowid)

    def rules(self) -> list[Rule]:
        rows = self.conn.execute("SELECT * FROM rules ORDER BY id").fetchall()
        return [Rule(r["id"], r["pattern"], r["category"], bool(r["is_regex"]), r["priority"]) for r in rows]

    def remove_rule(self, rule_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        return cur.rowcount > 0

    # -- budgets ----------------------------------------------------------

    def set_budget(self, category: str, monthly_limit: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?) "
                "ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit",
                (category, monthly_limit),
            )

    def budgets(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT category, monthly_limit FROM budgets ORDER BY category").fetchall()
        return {r["category"]: r["monthly_limit"] for r in rows}

    def remove_budget(self, category: str) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM budgets WHERE category = ?", (category,))
        return cur.rowcount > 0
