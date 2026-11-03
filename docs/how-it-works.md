# How Tally works

A tour of the code, in the order data flows through it.

```
statement.csv ─► importer.py ─► db.py (SQLite) ─► reports.py ─► your terminal
                                    ▲
                    rules.py ───────┘  (decides each transaction's category)
cli.py wires it all together as the `tally` command.
```

## `money.py`: amounts as whole pence

Computers store decimals like `0.1` slightly inaccurately, so adding up money as
floats slowly drifts. Tally stores every amount as an **integer number of
pence** (`£12.30` → `1230`). Negative means money out.

`parse_amount` copes with the messy ways banks write numbers: `-£1,234.56`,
`(45.00)`, `12.30 DR`. `format_money` turns pence back into `£1,234.56`.

## `importer.py`: reading any bank's CSV

Banks all export differently. The importer:

1. **Finds the header row.** It looks in the first 20 lines for a row that
   contains something like "Date", which skips account-detail lines at the top.
2. **Works out the columns** by matching header names against lists of known
   names (`COLUMN_ALIASES`). Users can override any of them.
3. **Detects the date format** by trying each known format and picking the
   first one that works for *every* date in the file. A single `31/10/2026` is
   enough to prove a file is day-first.
4. **Parses each row.** Bad rows are collected with their line number and a
   reason instead of crashing the whole import.

`fingerprints()` gives each transaction a stable ID made from its date,
description and amount. Importing the same file twice therefore adds nothing.
Two identical coffees on the same day get different IDs because repeats are
numbered.

## `rules.py`: categorising

A rule is "description contains X → category Y". Text rules ignore case;
`--regex` rules allow patterns like `PRET|COSTA`. If several rules match, the
highest `priority` wins, and ties go to the oldest rule. `make_categorizer()`
sorts the rules once and returns a function that categorises descriptions.

## `db.py`: storage

One SQLite file with four tables: `transactions`, `rules`, `budgets` and
`settings`. Notable details:

- `fingerprint` is `UNIQUE`, so duplicates are rejected by the database itself.
- `category_manual = 1` marks categories you set by hand, and `recategorize()`
  never touches those.
- `PRAGMA user_version` records the schema version so future changes can
  migrate old databases safely.

## `reports.py`: summaries and drawing

`summarize()` is a pure function. It takes rows and returns a `MonthSummary`
without touching the database, which makes it easy to test. It nets each
category so refunds reduce spending. The rendering functions turn summaries
into text, using Unicode eighth-blocks (`▏▎▍▌▋▊▉█`) for smooth bars. Colour
is only used when writing to a real terminal and `NO_COLOR` isn't set.

## `cli.py`: the command

`build_parser()` defines every sub-command with `argparse`. Each one maps to a
`cmd_*` function. `main()` opens the database, runs the handler and turns
`ValueError`s into short `error: …` messages with exit code 1, so users never
see a Python traceback for a mistake like a bad month.

## Tests

`tests/` has one file per module, plus `test_cli.py`, which runs the real
command end to end against a temporary database and the sample statement.
GitHub Actions runs everything on Linux and macOS for Python 3.10–3.13 on
every push.
