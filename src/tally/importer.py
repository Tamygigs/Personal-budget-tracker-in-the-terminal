"""Reading bank statement CSV files.

Every bank exports CSVs a little differently: different column names,
date formats, a single signed "Amount" column or separate "Money in" /
"Money out" columns, and sometimes a few lines of account details before
the real header row. This module copes with all of that and turns each
row into a ParsedTransaction.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from tally.money import parse_amount

# Tried in order. UK day-first formats come before US month-first ones, but
# we only pick a format if it parses *every* date in the file, so a file
# containing "10/31/2026" will correctly be detected as month-first.
DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%m/%d/%y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
]

# Header names we recognise, after lower-casing and tidying whitespace.
COLUMN_ALIASES: dict[str, list[str]] = {
    "date": [
        "date", "transaction date", "posted date", "posting date",
        "booking date", "value date", "completed date", "started date",
    ],
    "description": [
        "description", "transaction description", "details", "name",
        "merchant", "payee", "narrative", "memo", "reference",
    ],
    "amount": ["amount", "value", "amount (gbp)", "amount (usd)", "amount (eur)"],
    "debit": ["debit", "debit amount", "money out", "paid out", "withdrawal", "withdrawals", "out"],
    "credit": ["credit", "credit amount", "money in", "paid in", "deposit", "deposits", "in"],
}

# How many lines at the top of a file to search for the header row.
HEADER_SEARCH_LINES = 20


class CSVFormatError(ValueError):
    """The file can't be understood as a bank statement."""


@dataclass(frozen=True)
class ParsedTransaction:
    date: date
    description: str
    amount: int  # minor units; negative = money out


@dataclass
class ColumnMap:
    date: str
    description: str
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None


@dataclass
class ImportResult:
    transactions: list[ParsedTransaction]
    columns: ColumnMap
    date_format: str | None
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (line number, reason)


def _norm(header: str) -> str:
    return " ".join(header.strip().lower().replace("_", " ").split())


def detect_columns(headers: list[str], overrides: dict[str, str | None] | None = None) -> ColumnMap:
    """Work out which column holds what, honouring any user overrides."""
    overrides = overrides or {}
    by_norm = {_norm(h): h for h in headers}

    def find(kind: str) -> str | None:
        wanted = overrides.get(kind)
        if wanted:
            if wanted in headers:
                return wanted
            if _norm(wanted) in by_norm:
                return by_norm[_norm(wanted)]
            raise CSVFormatError(
                f"column {wanted!r} not found. Columns in this file: {', '.join(headers)}"
            )
        for alias in COLUMN_ALIASES[kind]:
            if alias in by_norm:
                return by_norm[alias]
        return None

    date_col = find("date")
    desc_col = find("description")
    amount_col = find("amount")
    debit_col = credit_col = None
    user_wants_split = bool(overrides.get("debit") or overrides.get("credit"))
    if user_wants_split and not overrides.get("amount"):
        amount_col = None  # explicit in/out columns beat an auto-detected amount
    if amount_col is None:
        debit_col = find("debit")
        credit_col = find("credit")

    missing = []
    if not date_col:
        missing.append("a date column (use --date-col)")
    if not desc_col:
        missing.append("a description column (use --desc-col)")
    if not (amount_col or debit_col or credit_col):
        missing.append("an amount column (use --amount-col, or --debit-col/--credit-col)")
    if missing:
        raise CSVFormatError(
            "couldn't find " + " and ".join(missing) + f". Columns in this file: {', '.join(headers)}"
        )

    return ColumnMap(date_col, desc_col, amount_col, debit_col, credit_col)


def detect_date_format(samples: list[str]) -> str:
    """Return the first known format that parses every sample."""
    samples = [s.strip() for s in samples if s and s.strip()]
    if not samples:
        raise CSVFormatError("no dates found in file")
    for fmt in DATE_FORMATS:
        try:
            for s in samples:
                datetime.strptime(s, fmt)
        except ValueError:
            continue
        return fmt
    raise CSVFormatError(
        f"couldn't recognise the date format (example: {samples[0]!r}). "
        "Pass one with --date-format, e.g. --date-format '%d/%m/%Y'"
    )


def _find_header(rows: list[list[str]]) -> int:
    """Index of the header row: the first row that names a date column."""
    date_aliases = set(COLUMN_ALIASES["date"])
    for i, row in enumerate(rows[:HEADER_SEARCH_LINES]):
        if any(_norm(cell) in date_aliases for cell in row):
            return i
    return 0


def parse_rows(
    rows: list[list[str]],
    overrides: dict[str, str | None] | None = None,
    date_format: str | None = None,
    invert: bool = False,
) -> ImportResult:
    """Parse already-split CSV rows (header included) into transactions."""
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if not rows:
        raise CSVFormatError("file is empty")

    header_idx = _find_header(rows)
    headers = [h.strip() for h in rows[header_idx]]
    columns = detect_columns(headers, overrides)
    index = {h: i for i, h in enumerate(headers)}

    def cell(row: list[str], col: str | None) -> str:
        if col is None:
            return ""
        i = index[col]
        return row[i].strip() if i < len(row) else ""

    # +1 for 1-based line numbers, +1 more because data starts after the header.
    data = [(header_idx + 2 + n, row) for n, row in enumerate(rows[header_idx + 1:])]

    if date_format is None:
        date_format = detect_date_format([cell(r, columns.date) for _, r in data])

    result = ImportResult(transactions=[], columns=columns, date_format=date_format)
    for line_no, row in data:
        try:
            raw_date = cell(row, columns.date)
            if not raw_date:
                raise ValueError("missing date")
            when = datetime.strptime(raw_date, date_format).date()

            description = " ".join(cell(row, columns.description).split())
            if not description:
                raise ValueError("missing description")

            if columns.amount:
                amount = parse_amount(cell(row, columns.amount))
            else:
                out_text = cell(row, columns.debit)
                in_text = cell(row, columns.credit)
                if not out_text and not in_text:
                    raise ValueError("no amount in money in/out columns")
                amount = 0
                if out_text:
                    amount -= abs(parse_amount(out_text))
                if in_text:
                    amount += abs(parse_amount(in_text))

            if invert:
                amount = -amount
            result.transactions.append(ParsedTransaction(when, description, amount))
        except ValueError as exc:
            result.skipped.append((line_no, str(exc)))

    return result


def parse_csv(
    path: str | Path,
    overrides: dict[str, str | None] | None = None,
    date_format: str | None = None,
    invert: bool = False,
) -> ImportResult:
    """Read and parse a CSV statement from disk."""
    path = Path(path)
    if not path.is_file():
        raise CSVFormatError(f"file not found: {path}")
    # utf-8-sig quietly removes the invisible "byte order mark" Excel adds.
    with path.open(newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(fh, dialect))
    return parse_rows(rows, overrides, date_format, invert)


def fingerprints(transactions: list[ParsedTransaction]) -> list[str]:
    """A stable ID for each transaction so re-importing a file adds nothing.

    Two identical coffees on the same day are both real, so we number
    repeats within the file ("the 2nd £3.20 Costa on 2026-10-01").
    """
    seen: Counter[str] = Counter()
    out = []
    for t in transactions:
        key = f"{t.date.isoformat()}|{' '.join(t.description.lower().split())}|{t.amount}"
        seen[key] += 1
        out.append(hashlib.sha256(f"{key}|{seen[key]}".encode()).hexdigest()[:32])
    return out
