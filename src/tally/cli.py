"""The `tally` command.

Each sub-command (import, list, rules, budget, report, trend, ...) has a
small handler function named cmd_<name>. They all receive the parsed
arguments plus an open Store, print their output, and return an exit code.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from tally import __version__
from tally.db import Store, default_db_path
from tally.importer import CSVFormatError, fingerprints, parse_csv
from tally.money import format_money, parse_amount
from tally.reports import (
    Style,
    render_month,
    render_trend,
    summarize_month,
    trend,
    validate_month,
)
from tally.rules import make_categorizer, normalize_category, ordered, validate_pattern

DEFAULT_CURRENCY = "£"


def _symbol(store: Store) -> str:
    return store.get_setting("currency", DEFAULT_CURRENCY)


def _latest_month(store: Store) -> str | None:
    months = store.months()
    return months[-1] if months else None


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


NO_DATA = "No transactions yet. Import a bank statement first:\n  tally import statement.csv"


# -- handlers ---------------------------------------------------------------


def cmd_import(args, store: Store) -> int:
    overrides = {
        "date": args.date_col,
        "description": args.desc_col,
        "amount": args.amount_col,
        "debit": args.debit_col,
        "credit": args.credit_col,
    }
    result = parse_csv(args.file, overrides, args.date_format, args.invert)
    cols = result.columns
    amount_desc = (
        f"amount={cols.amount!r}" if cols.amount else f"money out={cols.debit!r}, money in={cols.credit!r}"
    )
    print(f"Read {len(result.transactions)} transactions from {Path(args.file).name}")
    print(f"  columns: date={cols.date!r}, description={cols.description!r}, {amount_desc}")
    print(f"  date format: {result.date_format}")

    for line_no, reason in result.skipped[:10]:
        print(f"  skipped line {line_no}: {reason}", file=sys.stderr)
    if len(result.skipped) > 10:
        print(f"  ...and {len(result.skipped) - 10} more skipped lines", file=sys.stderr)

    if args.dry_run:
        symbol = _symbol(store)
        for t in result.transactions[:10]:
            print(f"  {t.date}  {format_money(t.amount, symbol):>12}  {t.description}")
        print("Dry run: nothing was saved.")
        return 0

    categorize = make_categorizer(store.rules())
    added, dupes = store.add_transactions(
        result.transactions, fingerprints(result.transactions), Path(args.file).name, categorize
    )
    print(f"Added {added} new transaction{'s' if added != 1 else ''}", end="")
    print(f" ({dupes} already imported)" if dupes else "")
    return 0


def cmd_list(args, store: Store) -> int:
    month = validate_month(args.month) if args.month else None
    category = normalize_category(args.category) if args.category else None
    rows = store.transactions(
        month=month, category=category, search=args.search,
        uncategorised=args.uncategorised, limit=args.limit,
    )
    if not rows:
        print("No matching transactions." if store.months() else NO_DATA)
        return 0

    symbol = _symbol(store)
    style = Style.for_stream(sys.stdout)
    amounts = [format_money(r["amount"], symbol) for r in rows]
    id_w = max(len(str(r["id"])) for r in rows)
    amt_w = max(len(a) for a in amounts)
    cat_w = min(18, max(len(r["category"] or "-") for r in rows))
    for row, amount in zip(rows, amounts):
        amount_cell = f"{amount:>{amt_w}}"
        if row["amount"] > 0:
            amount_cell = style.green(amount_cell)
        category = _truncate(row["category"] or "-", cat_w)
        marker = "*" if row["category_manual"] else " "
        print(
            f"{row['id']:>{id_w}}  {row['date']}  {amount_cell}  "
            f"{category:<{cat_w}}{marker} {_truncate(row['description'], 48)}"
        )
    print(style.dim(f"{len(rows)} transaction{'s' if len(rows) != 1 else ''}  (* = category set by hand)"))
    return 0


def cmd_categorize(args, store: Store) -> int:
    category = None if args.category == "-" else normalize_category(args.category)
    if not store.set_category(args.id, category):
        raise ValueError(f"no transaction with id {args.id}")
    if category:
        print(f"Transaction {args.id} → {category} (rules won't change it now)")
    else:
        store.recategorize(make_categorizer(store.rules()))
        print(f"Transaction {args.id} is back under rule control")
    return 0


def cmd_rules_add(args, store: Store) -> int:
    pattern = validate_pattern(args.pattern, args.regex)
    category = normalize_category(args.category)
    rule_id = store.add_rule(pattern, category, args.regex, args.priority)
    print(f"Added rule {rule_id}: {'regex ' if args.regex else ''}{pattern!r} → {category}")
    if not args.no_apply:
        changed = store.recategorize(make_categorizer(store.rules()))
        print(f"Re-categorised {changed} transaction{'s' if changed != 1 else ''}")
    return 0


def cmd_rules_list(args, store: Store) -> int:
    rules = ordered(store.rules())
    if not rules:
        print('No rules yet. Add one with: tally rules add "TESCO" groceries')
        return 0
    id_w = max(len(str(r.id)) for r in rules)
    pat_w = min(32, max(len(r.pattern) for r in rules))
    print(f"{'id':>{id_w}}  {'pattern':<{pat_w}}  {'category':<16}  type   priority")
    for r in rules:
        kind = "regex" if r.is_regex else "text"
        print(f"{r.id:>{id_w}}  {_truncate(r.pattern, pat_w):<{pat_w}}  {r.category:<16}  {kind:<5}  {r.priority}")
    return 0


def cmd_rules_remove(args, store: Store) -> int:
    if not store.remove_rule(args.id):
        raise ValueError(f"no rule with id {args.id}")
    changed = store.recategorize(make_categorizer(store.rules()))
    print(f"Removed rule {args.id}. Re-categorised {changed} transaction{'s' if changed != 1 else ''}")
    return 0


def cmd_rules_apply(args, store: Store) -> int:
    changed = store.recategorize(make_categorizer(store.rules()))
    print(f"Re-categorised {changed} transaction{'s' if changed != 1 else ''}")
    return 0


def cmd_budget_set(args, store: Store) -> int:
    category = normalize_category(args.category)
    limit = parse_amount(args.amount)
    if limit <= 0:
        raise ValueError("budget must be more than zero")
    store.set_budget(category, limit)
    print(f"Budget for {category}: {format_money(limit, _symbol(store))} a month")
    return 0


def cmd_budget_list(args, store: Store) -> int:
    budgets = store.budgets()
    if not budgets:
        print("No budgets yet. Add one with: tally budget set groceries 300")
        return 0
    symbol = _symbol(store)
    width = max(len(c) for c in budgets)
    for category, limit in budgets.items():
        print(f"{category:<{width}}  {format_money(limit, symbol)}")
    return 0


def cmd_budget_remove(args, store: Store) -> int:
    category = normalize_category(args.category)
    if not store.remove_budget(category):
        raise ValueError(f"no budget for {category!r}")
    print(f"Removed budget for {category}")
    return 0


def cmd_report(args, store: Store) -> int:
    month = validate_month(args.month) if args.month else _latest_month(store)
    if month is None:
        print(NO_DATA)
        return 0
    summary = summarize_month(store, month)
    style = Style.for_stream(sys.stdout)
    if summary.transaction_count == 0 and not summary.spending:
        print(f"No transactions in {month}.")
        return 0
    print(render_month(summary, _symbol(store), style))
    return 0


def cmd_trend(args, store: Store) -> int:
    if args.months < 1:
        raise ValueError("--months must be at least 1")
    end = validate_month(args.end) if args.end else _latest_month(store)
    if end is None:
        print(NO_DATA)
        return 0
    summaries = trend(store, end, args.months)
    print(render_trend(summaries, _symbol(store), Style.for_stream(sys.stdout)))
    return 0


def cmd_config(args, store: Store) -> int:
    if args.currency is not None:
        if not args.currency.strip() or len(args.currency) > 4:
            raise ValueError("currency symbol should be 1–4 characters, e.g. £ $ € or 'EUR '")
        store.set_setting("currency", args.currency)
    print(f"currency: {_symbol(store)}")
    print(f"database: {args.db}")
    return 0


# -- argument parsing -------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tally",
        description="A personal budget tracker for your terminal. Your data stays on your computer.",
    )
    parser.add_argument("--version", action="version", version=f"tally {__version__}")
    parser.add_argument(
        "--db", type=Path, default=None,
        help="database file (default: $TALLY_DB or ~/.tally/tally.db)",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("import", help="import a bank statement CSV")
    p.add_argument("file", help="path to the CSV file")
    p.add_argument("--date-col", help="name of the date column, if not detected")
    p.add_argument("--desc-col", help="name of the description column")
    p.add_argument("--amount-col", help="name of a single signed amount column")
    p.add_argument("--debit-col", help="name of the money-out column")
    p.add_argument("--credit-col", help="name of the money-in column")
    p.add_argument("--date-format", help="strftime format, e.g. '%%d/%%m/%%Y'")
    p.add_argument("--invert", action="store_true", help="flip signs (for cards that show spending as positive)")
    p.add_argument("--dry-run", action="store_true", help="show what would be imported without saving")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("list", help="list transactions")
    p.add_argument("--month", help="only this month, e.g. 2026-10")
    p.add_argument("--category", help="only this category")
    p.add_argument("--search", help="description contains this text")
    p.add_argument("--uncategorised", "--uncategorized", action="store_true", help="only uncategorised")
    p.add_argument("--limit", type=int, default=None, help="show at most this many")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("categorize", aliases=["categorise"], help="set one transaction's category by hand")
    p.add_argument("id", type=int, help="transaction id (see `tally list`)")
    p.add_argument("category", help="category name, or - to hand it back to the rules")
    p.set_defaults(func=cmd_categorize)

    rules = sub.add_parser("rules", help="manage categorisation rules")
    rules_sub = rules.add_subparsers(dest="rules_command", metavar="<action>", required=True)
    p = rules_sub.add_parser("add", help="add a rule")
    p.add_argument("pattern", help="text to look for in descriptions (case-insensitive)")
    p.add_argument("category")
    p.add_argument("--regex", action="store_true", help="treat pattern as a regular expression")
    p.add_argument("--priority", type=int, default=0, help="higher wins when several rules match")
    p.add_argument("--no-apply", action="store_true", help="don't re-categorise existing transactions")
    p.set_defaults(func=cmd_rules_add)
    p = rules_sub.add_parser("list", help="show rules in the order they're tried")
    p.set_defaults(func=cmd_rules_list)
    p = rules_sub.add_parser("remove", help="delete a rule")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_rules_remove)
    p = rules_sub.add_parser("apply", help="re-run all rules over existing transactions")
    p.set_defaults(func=cmd_rules_apply)

    budget = sub.add_parser("budget", help="manage monthly budgets")
    budget_sub = budget.add_subparsers(dest="budget_command", metavar="<action>", required=True)
    p = budget_sub.add_parser("set", help="set a monthly budget for a category")
    p.add_argument("category")
    p.add_argument("amount", help="e.g. 300 or 299.99")
    p.set_defaults(func=cmd_budget_set)
    p = budget_sub.add_parser("list", help="show budgets")
    p.set_defaults(func=cmd_budget_list)
    p = budget_sub.add_parser("remove", help="delete a budget")
    p.add_argument("category")
    p.set_defaults(func=cmd_budget_remove)

    p = sub.add_parser("report", help="monthly summary with spending by category")
    p.add_argument("--month", help="e.g. 2026-10 (default: latest month with data)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("trend", help="money in and out over recent months")
    p.add_argument("--months", type=int, default=6, help="how many months (default 6)")
    p.add_argument("--end", help="last month to show (default: latest with data)")
    p.set_defaults(func=cmd_trend)

    p = sub.add_parser("config", help="show or change settings")
    p.add_argument("--currency", help="currency symbol to display, e.g. £ $ €")
    p.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    args.db = (args.db or default_db_path()).expanduser()
    try:
        with Store(args.db) as store:
            return args.func(args, store)
    except (ValueError, CSVFormatError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
