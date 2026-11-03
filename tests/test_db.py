from datetime import date

import pytest

from tally.db import Store
from tally.importer import ParsedTransaction, fingerprints
from tally.rules import make_categorizer


@pytest.fixture
def store():
    with Store(":memory:") as s:
        yield s


def add(store, txns, rules=None):
    categorize = make_categorizer(rules or store.rules())
    return store.add_transactions(txns, fingerprints(txns), "test.csv", categorize)


TXNS = [
    ParsedTransaction(date(2026, 9, 30), "TESCO", -1000),
    ParsedTransaction(date(2026, 10, 1), "TESCO", -2000),
    ParsedTransaction(date(2026, 10, 2), "SALARY", 100000),
]


def test_reimport_adds_nothing(store):
    assert add(store, TXNS) == (3, 0)
    assert add(store, TXNS) == (0, 3)


def test_filters(store):
    add(store, TXNS)
    assert len(store.transactions(month="2026-10")) == 2
    assert len(store.transactions(search="sal")) == 1
    assert len(store.transactions(limit=1)) == 1
    assert store.months() == ["2026-09", "2026-10"]


def test_rules_categorize_on_import_and_reapply(store):
    store.add_rule("TESCO", "groceries")
    add(store, TXNS)
    assert len(store.transactions(category="groceries")) == 2
    assert len(store.transactions(uncategorised=True)) == 1

    store.add_rule("SALARY", "salary")
    assert store.recategorize(make_categorizer(store.rules())) == 1
    assert store.transactions(uncategorised=True) == []


def test_manual_category_survives_rules(store):
    store.add_rule("TESCO", "groceries")
    add(store, TXNS)
    target = store.transactions(month="2026-09")[0]["id"]
    assert store.set_category(target, "party")
    store.recategorize(make_categorizer(store.rules()))
    assert store.transactions(month="2026-09")[0]["category"] == "party"

    store.set_category(target, None)  # hand back to rules
    store.recategorize(make_categorizer(store.rules()))
    assert store.transactions(month="2026-09")[0]["category"] == "groceries"


def test_set_category_unknown_id(store):
    assert store.set_category(999, "x") is False


def test_duplicate_rule_rejected(store):
    store.add_rule("TESCO", "groceries")
    with pytest.raises(ValueError, match="already exists"):
        store.add_rule("TESCO", "food")


def test_remove_rule(store):
    rule_id = store.add_rule("TESCO", "groceries")
    assert store.remove_rule(rule_id)
    assert not store.remove_rule(rule_id)


def test_budgets_and_settings(store):
    store.set_budget("groceries", 30000)
    store.set_budget("groceries", 25000)
    assert store.budgets() == {"groceries": 25000}
    assert store.remove_budget("groceries")
    assert store.budgets() == {}

    assert store.get_setting("currency", "£") == "£"
    store.set_setting("currency", "$")
    assert store.get_setting("currency", "£") == "$"


def test_creates_parent_folder(tmp_path):
    path = tmp_path / "nested" / "dir" / "tally.db"
    with Store(path):
        pass
    assert path.exists()
