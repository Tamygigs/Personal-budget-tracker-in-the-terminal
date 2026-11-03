"""Turning transactions into monthly summaries, and drawing them.

How money in / money out is counted
-----------------------------------
Transactions are grouped by category first and each category is netted.
A £40 refund in "shopping" therefore *reduces* shopping spend instead of
being counted as income. A category whose net is negative is spending; one
whose net is positive is income. Uncategorised transactions are split by
sign, because we can't tell what they are yet.
"""

from __future__ import annotations

import calendar
import os
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TextIO

from tally.money import format_money
from tally.rules import UNCATEGORISED

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_BLOCKS = " ▏▎▍▌▋▊▉"


# -- months -----------------------------------------------------------------


def validate_month(text: str) -> str:
    if not _MONTH_RE.match(text):
        raise ValueError(f"month must look like 2026-10, got {text!r}")
    return text


def shift_month(month: str, delta: int) -> str:
    """shift_month('2026-01', -1) -> '2025-12'."""
    year, mon = map(int, month.split("-"))
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_label(month: str, short: bool = False) -> str:
    year, mon = map(int, month.split("-"))
    names = calendar.month_abbr if short else calendar.month_name
    return f"{names[mon]} {year}"


# -- summaries --------------------------------------------------------------


@dataclass
class CategoryLine:
    category: str
    amount: int  # always positive
    budget: int | None = None


@dataclass
class MonthSummary:
    month: str
    money_in: int
    money_out: int
    spending: list[CategoryLine]
    income: list[CategoryLine]
    transaction_count: int
    uncategorised_count: int

    @property
    def net(self) -> int:
        return self.money_in - self.money_out


def summarize(month: str, rows: Iterable[Mapping], budgets: Mapping[str, int] | None = None) -> MonthSummary:
    """Build a MonthSummary from transaction rows (anything with
    'category' and 'amount' keys)."""
    budgets = budgets or {}
    nets: dict[str, int] = defaultdict(int)
    uncat_in = uncat_out = uncat_count = count = 0

    for row in rows:
        count += 1
        if row["category"] is None:
            uncat_count += 1
            if row["amount"] > 0:
                uncat_in += row["amount"]
            else:
                uncat_out -= row["amount"]
        else:
            nets[row["category"]] += row["amount"]

    spending = {c: -n for c, n in nets.items() if n < 0}
    income = {c: n for c, n in nets.items() if n > 0}
    if uncat_out:
        spending[UNCATEGORISED] = uncat_out
    if uncat_in:
        income[UNCATEGORISED] = uncat_in
    for category in budgets:
        spending.setdefault(category, 0)  # show budgets even before any spend

    def lines(totals: dict[str, int]) -> list[CategoryLine]:
        out = [CategoryLine(c, a, budgets.get(c)) for c, a in totals.items()]
        return sorted(out, key=lambda line: (-line.amount, line.category))

    return MonthSummary(
        month=month,
        money_in=sum(income.values()),
        money_out=sum(spending.values()),
        spending=lines(spending),
        income=lines(income),
        transaction_count=count,
        uncategorised_count=uncat_count,
    )


def summarize_month(store, month: str) -> MonthSummary:
    return summarize(month, store.transactions(month=month), store.budgets())


def trend(store, end_month: str, months: int) -> list[MonthSummary]:
    """Summaries for `months` months ending at `end_month`, oldest first.
    Months with no transactions are included as zeros."""
    budgets = store.budgets()
    return [
        summarize(m, store.transactions(month=m), budgets)
        for m in (shift_month(end_month, -i) for i in range(months - 1, -1, -1))
    ]


# -- drawing ----------------------------------------------------------------


class Style:
    """Optional terminal colours. Off when piping to a file or if NO_COLOR is set."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    @classmethod
    def for_stream(cls, stream: TextIO) -> Style:
        is_tty = hasattr(stream, "isatty") and stream.isatty()
        return cls(is_tty and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb")

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)


def bar(value: int, maximum: int, width: int) -> str:
    """A horizontal bar using eighth-blocks for smooth lengths."""
    if maximum <= 0 or value <= 0 or width <= 0:
        return ""
    eighths = max(1, round(value / maximum * width * 8))
    full, rest = divmod(eighths, 8)
    return "█" * full + (_BLOCKS[rest] if rest else "")


def _category_table(lines: list[CategoryLine], symbol: str, style: Style, bar_width: int) -> list[str]:
    name_w = max(len(line.category) for line in lines)
    amount_w = max(len(format_money(line.amount, symbol)) for line in lines)
    biggest = max(line.amount for line in lines)
    out = []
    for line in lines:
        text = (
            f"  {line.category:<{name_w}}  {format_money(line.amount, symbol):>{amount_w}}  "
            f"{bar(line.amount, biggest, bar_width):<{bar_width}}"
        )
        if line.budget:
            pct = round(line.amount * 100 / line.budget)
            info = f"{pct:>3}% of {format_money(line.budget, symbol)}"
            if pct > 100:
                info = style.red(info + "  over budget")
            elif pct >= 90:
                info = style.yellow(info)
            else:
                info = style.dim(info)
            text += "  " + info
        out.append(text.rstrip())
    return out


def render_month(summary: MonthSummary, symbol: str, style: Style, bar_width: int = 24) -> str:
    out = [style.bold(month_label(summary.month)), "─" * 44]

    net_text = format_money(summary.net, symbol, signed=True)
    figures = [
        ("Money in", format_money(summary.money_in, symbol)),
        ("Money out", format_money(summary.money_out, symbol)),
        ("Net", net_text),
    ]
    width = max(len(v) for _, v in figures)
    for label, value in figures:
        padded = f"{value:>{width}}"
        if label == "Net":
            padded = style.green(padded) if summary.net >= 0 else style.red(padded)
        out.append(f"{label:<11}{padded}")

    if summary.spending:
        out += ["", style.bold("Spending by category")]
        out += _category_table(summary.spending, symbol, style, bar_width)
    if summary.income:
        out += ["", style.bold("Money in by category")]
        out += _category_table(summary.income, symbol, style, bar_width)

    if summary.uncategorised_count:
        n = summary.uncategorised_count
        out += [
            "",
            style.dim(
                f"{n} transaction{'s are' if n != 1 else ' is'} uncategorised. "
                f"See {'them' if n != 1 else 'it'} with: tally list --uncategorised --month {summary.month}"
            ),
        ]
    return "\n".join(out)


def render_trend(summaries: list[MonthSummary], symbol: str, style: Style, bar_width: int = 24) -> str:
    rows = [
        (
            month_label(s.month, short=True),
            format_money(s.money_in, symbol),
            format_money(s.money_out, symbol),
            format_money(s.net, symbol, signed=True),
            s,
        )
        for s in summaries
    ]
    headers = ("Month", "Money in", "Money out", "Net")
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(4)]
    biggest = max((s.money_out for s in summaries), default=0)

    out = [
        style.bold(
            f"{headers[0]:<{widths[0]}}  {headers[1]:>{widths[1]}}  "
            f"{headers[2]:>{widths[2]}}  {headers[3]:>{widths[3]}}  Spending"
        )
    ]
    for label, money_in, money_out, net, s in rows:
        net_cell = f"{net:>{widths[3]}}"
        net_cell = style.green(net_cell) if s.net >= 0 else style.red(net_cell)
        out.append(
            f"{label:<{widths[0]}}  {money_in:>{widths[1]}}  {money_out:>{widths[2]}}  "
            f"{net_cell}  {bar(s.money_out, biggest, bar_width)}".rstrip()
        )
    return "\n".join(out)
