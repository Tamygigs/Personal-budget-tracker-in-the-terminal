from datetime import date

import pytest

from tally.importer import (
    CSVFormatError,
    ParsedTransaction,
    detect_date_format,
    fingerprints,
    parse_csv,
    parse_rows,
)


def write(tmp_path, text, name="s.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_signed_amount_column(tmp_path):
    path = write(tmp_path, "Date,Description,Amount\n01/10/2026,TESCO,-12.50\n02/10/2026,SALARY,2000\n")
    result = parse_csv(path)
    assert result.date_format == "%d/%m/%Y"
    assert result.transactions == [
        ParsedTransaction(date(2026, 10, 1), "TESCO", -1250),
        ParsedTransaction(date(2026, 10, 2), "SALARY", 200000),
    ]
    assert result.skipped == []


def test_money_in_money_out_columns(tmp_path):
    path = write(
        tmp_path,
        "Date,Transaction Description,Money Out,Money In,Balance\n"
        "2026-10-01,COFFEE,3.20,,100.00\n"
        "2026-10-02,REFUND,,5.00,105.00\n",
    )
    result = parse_csv(path)
    assert result.columns.debit == "Money Out"
    assert result.columns.credit == "Money In"
    assert [t.amount for t in result.transactions] == [-320, 500]


def test_preamble_before_header_is_skipped(tmp_path):
    path = write(
        tmp_path,
        "Account,12345678\nSort code,00-00-00\n\nDate,Description,Amount\n2026-10-01,X,-1.00\n",
    )
    result = parse_csv(path)
    assert len(result.transactions) == 1


def test_us_dates_detected_when_unambiguous(tmp_path):
    path = write(tmp_path, "Date,Description,Amount\n10/31/2026,A,-1\n11/01/2026,B,-1\n")
    result = parse_csv(path)
    assert result.date_format == "%m/%d/%Y"
    assert result.transactions[0].date == date(2026, 10, 31)


def test_excel_bom_and_semicolons(tmp_path):
    path = tmp_path / "s.csv"
    path.write_bytes("﻿Date;Description;Amount\n2026-10-01;BAKERY;-4.00\n".encode())
    result = parse_csv(path)
    assert result.transactions[0].description == "BAKERY"


def test_bad_rows_are_reported_not_fatal():
    rows = [
        ["Date", "Description", "Amount"],
        ["2026-10-01", "OK", "-1.00"],
        ["2026-10-02", "", "-1.00"],
        ["2026-10-03", "BAD AMOUNT", "lots"],
    ]
    result = parse_rows(rows)
    assert len(result.transactions) == 1
    assert [line for line, _ in result.skipped] == [3, 4]


def test_invert_flips_signs():
    rows = [["Date", "Description", "Amount"], ["2026-10-01", "CARD SPEND", "20.00"]]
    assert parse_rows(rows, invert=True).transactions[0].amount == -2000


def test_column_overrides():
    rows = [["When", "What", "How much"], ["2026-10-01", "THING", "-3"]]
    result = parse_rows(rows, overrides={"date": "When", "description": "What", "amount": "How much"})
    assert result.transactions[0].amount == -300


def test_missing_columns_explained():
    with pytest.raises(CSVFormatError, match="description column"):
        parse_rows([["Date", "Amount"], ["2026-10-01", "1"]])


def test_unknown_override_column():
    with pytest.raises(CSVFormatError, match="not found"):
        parse_rows([["Date", "Description", "Amount"]], overrides={"amount": "Nope"})


def test_detect_date_format_failure():
    with pytest.raises(CSVFormatError, match="date format"):
        detect_date_format(["yesterday"])


def test_fingerprints_stable_and_count_repeats():
    coffee = ParsedTransaction(date(2026, 10, 1), "COSTA", -320)
    first = fingerprints([coffee, coffee])
    assert first[0] != first[1]  # two real coffees, both kept
    assert fingerprints([coffee, coffee]) == first  # same file again -> same ids
