import pytest

from tally.rules import Rule, make_categorizer, normalize_category, validate_pattern


def test_text_rule_is_case_insensitive():
    assert Rule(1, "tesco", "groceries").matches("TESCO STORES 123")


def test_regex_rule():
    rule = Rule(1, r"^TFL\b", "transport", is_regex=True)
    assert rule.matches("tfl travel ch")
    assert not rule.matches("NOT TFL")


def test_priority_then_age_decides():
    categorize = make_categorizer(
        [
            Rule(1, "AMAZON", "shopping"),
            Rule(2, "AMAZON PRIME", "subscriptions", priority=5),
            Rule(3, "AMAZON", "other"),
        ]
    )
    assert categorize("AMAZON PRIME UK") == "subscriptions"
    assert categorize("AMAZON MARKETPLACE") == "shopping"  # rule 1 is older than rule 3
    assert categorize("BAKERY") is None


def test_normalize_category():
    assert normalize_category("  Eating   OUT ") == "eating out"
    with pytest.raises(ValueError):
        normalize_category("   ")


def test_validate_pattern_keeps_spaces_and_checks_regex():
    assert validate_pattern(" DD", is_regex=False) == " DD"
    with pytest.raises(ValueError):
        validate_pattern("  ", is_regex=False)
    with pytest.raises(ValueError, match="invalid regular expression"):
        validate_pattern("(unclosed", is_regex=True)
