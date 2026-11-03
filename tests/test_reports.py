import pytest

from tally.reports import (
    Style,
    bar,
    render_month,
    render_trend,
    shift_month,
    summarize,
    validate_month,
)


def row(amount, category=None):
    return {"amount": amount, "category": category}


def test_summary_nets_refunds_within_category():
    s = summarize(
        "2026-10",
        [
            row(-5000, "shopping"),
            row(2000, "shopping"),  # refund
            row(300000, "salary"),
            row(-1500),  # uncategorised out
            row(700),  # uncategorised in
        ],
        budgets={"groceries": 25000},
    )
    spending = {line.category: line.amount for line in s.spending}
    income = {line.category: line.amount for line in s.income}
    assert spending == {"shopping": 3000, "uncategorised": 1500, "groceries": 0}
    assert income == {"salary": 300000, "uncategorised": 700}
    assert s.money_out == 4500
    assert s.money_in == 300700
    assert s.net == 300700 - 4500
    assert s.uncategorised_count == 2
    assert s.transaction_count == 5


def test_net_always_equals_sum_of_amounts():
    amounts = [row(-100, "a"), row(250, "a"), row(-75, "b"), row(30), row(-10)]
    s = summarize("2026-10", amounts)
    assert s.net == sum(r["amount"] for r in amounts)


def test_spending_sorted_largest_first():
    s = summarize("2026-10", [row(-100, "small"), row(-900, "big")])
    assert [line.category for line in s.spending] == ["big", "small"]


def test_bar():
    assert bar(10, 10, 4) == "████"
    assert bar(5, 10, 4) == "██"
    assert bar(1, 1000, 4) == "▏"  # tiny but visible
    assert bar(0, 10, 4) == ""
    assert bar(5, 0, 4) == ""


def test_months():
    assert shift_month("2026-01", -1) == "2025-12"
    assert shift_month("2026-12", 1) == "2027-01"
    assert validate_month("2026-10") == "2026-10"
    for bad in ["2026-13", "2026-1", "Oct", "2026/10"]:
        with pytest.raises(ValueError):
            validate_month(bad)


def test_render_month_plain_text():
    s = summarize("2026-10", [row(-30000, "groceries"), row(200000, "salary"), row(-500)], {"groceries": 25000})
    text = render_month(s, "£", Style(False))
    assert "October 2026" in text
    assert "120% of £250.00  over budget" in text
    assert "1 transaction is uncategorised" in text
    assert "\033[" not in text  # no colour codes when colour is off


def test_render_month_colour():
    s = summarize("2026-10", [row(-100, "x")])
    assert "\033[31m" in render_month(s, "£", Style(True))  # negative net is red


def test_render_trend():
    months = [summarize("2026-09", [row(-100, "x")]), summarize("2026-10", [])]
    text = render_trend(months, "$", Style(False))
    assert "Sep 2026" in text and "Oct 2026" in text
    assert "-$1.00" in text
