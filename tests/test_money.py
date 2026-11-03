import pytest

from tally.money import format_money, parse_amount


@pytest.mark.parametrize(
    "text, expected",
    [
        ("12.30", 1230),
        ("-12.30", -1230),
        ("£1,234.56", 123456),
        ("-£1,234.56", -123456),
        ("(45.00)", -4500),
        ("+5", 500),
        ("12.30 CR", 1230),
        ("12.30 DR", -1230),
        ("  7.5 ", 750),
        ("0.005", 1),  # rounds half up
        ("USD 10.00", 1000),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "   ", None, "abc", "NaN", "Infinity", "1.2.3"])
def test_parse_amount_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_no_float_rounding_errors():
    assert parse_amount("0.10") + parse_amount("0.20") == parse_amount("0.30")


@pytest.mark.parametrize(
    "minor, signed, expected",
    [
        (0, False, "£0.00"),
        (5, False, "£0.05"),
        (123456, False, "£1,234.56"),
        (-123456, False, "-£1,234.56"),
        (100, True, "+£1.00"),
        (0, True, "£0.00"),
    ],
)
def test_format_money(minor, signed, expected):
    assert format_money(minor, "£", signed) == expected


def test_format_money_other_symbol():
    assert format_money(-999, "$") == "-$9.99"
