"""Parsing and formatting money.

All amounts are stored as whole numbers of *minor units* (pence, cents).
Using integers instead of floats means 0.10 + 0.20 is always exactly 0.30.
Negative amounts are money going out; positive amounts are money coming in.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Currency symbols/codes, thousands separators and spaces we can safely ignore.
_NOISE = re.compile(r"[£$€¥,\s]|GBP|USD|EUR", re.IGNORECASE)


def parse_amount(text: str | None) -> int:
    """Turn a bank-style amount string into minor units.

    Handles things like "12.30", "-£1,234.56", "(45.00)" (accounting
    negative), "+5", "12.30 CR" and "12.30 DR".
    """
    if text is None or not text.strip():
        raise ValueError("empty amount")

    s = text.strip()
    negative = False

    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]

    s = _NOISE.sub("", s)

    upper = s.upper()
    if upper.endswith("CR"):
        s = s[:-2]
    elif upper.endswith("DR"):
        negative = not negative
        s = s[:-2]

    if s.startswith("-"):
        negative = not negative
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not an amount: {text!r}") from None
    if not value.is_finite():
        raise ValueError(f"not an amount: {text!r}")

    minor = int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -minor if negative else minor


def format_money(minor: int, symbol: str = "£", signed: bool = False) -> str:
    """Format minor units for display, e.g. -123456 -> "-£1,234.56"."""
    if minor < 0:
        sign = "-"
    elif signed and minor > 0:
        sign = "+"
    else:
        sign = ""
    whole, frac = divmod(abs(minor), 100)
    return f"{sign}{symbol}{whole:,}.{frac:02d}"
