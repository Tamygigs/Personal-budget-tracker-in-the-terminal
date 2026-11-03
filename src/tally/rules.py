"""Categorisation rules.

A rule says "if a transaction's description contains PATTERN, put it in
CATEGORY". Patterns are case-insensitive text by default, or regular
expressions when you need more control. When several rules match, the one
with the highest priority wins; ties go to the rule that was added first.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

UNCATEGORISED = "uncategorised"


def normalize_category(name: str) -> str:
    """'  Eating  Out ' -> 'eating out', so categories never split by typo-case."""
    cleaned = " ".join(name.strip().lower().split())
    if not cleaned:
        raise ValueError("category name can't be empty")
    return cleaned


@dataclass(frozen=True)
class Rule:
    id: int
    pattern: str
    category: str
    is_regex: bool = False
    priority: int = 0

    def matches(self, description: str) -> bool:
        if self.is_regex:
            return re.search(self.pattern, description, re.IGNORECASE) is not None
        return self.pattern.lower() in description.lower()


def validate_pattern(pattern: str, is_regex: bool) -> str:
    """Check a pattern is usable before it is saved.

    Surrounding spaces are kept on purpose: " DD" (with a space) matches
    "COUNCIL TAX DD" but not "ADDISON LEE".
    """
    if not pattern.strip():
        raise ValueError("pattern can't be empty")
    if is_regex:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from None
    return pattern


def ordered(rules: Iterable[Rule]) -> list[Rule]:
    """Rules in the order they should be tried."""
    return sorted(rules, key=lambda r: (-r.priority, r.id))


def make_categorizer(rules: Iterable[Rule]) -> Callable[[str], str | None]:
    """Build a function that maps a description to a category (or None)."""
    ranked = ordered(rules)

    def categorize(description: str) -> str | None:
        for rule in ranked:
            if rule.matches(description):
                return rule.category
        return None

    return categorize
