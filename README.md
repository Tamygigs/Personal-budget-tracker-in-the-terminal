# Tally: a personal budget tracker for the terminal

[![tests](https://github.com/Tamygigs/Personal-budget-tracker-in-the-terminal/actions/workflows/tests.yml/badge.svg)](https://github.com/Tamygigs/Personal-budget-tracker-in-the-terminal/actions/workflows/tests.yml)

Download a CSV statement from your bank, give it to `tally`, and see where your
money went. You set simple rules ("anything with TESCO is groceries"), set
monthly budgets, and get clear reports right in your terminal.

**Private by design.** Your data lives in one file on your own computer
(`~/.tally/tally.db`). Tally makes no network calls and needs no account.
It has no dependencies beyond Python itself.

```
October 2026
────────────────────────────────────────────
Money in   £2,450.00
Money out  £1,926.25
Net         +£523.75

Spending by category
  rent           £950.00  ████████████████████████
  bills          £247.40  ██████▎
  savings        £200.00  █████
  groceries      £183.14  ████▋                      73% of £250.00
  shopping       £158.38  ████
  eating out      £87.75  ██▎                        98% of £90.00
  transport       £47.60  █▎                         79% of £60.00
  subscriptions   £36.98  ▉
  uncategorised   £15.00  ▍
```

## Install

You need Python 3.10 or newer. On a Mac: `brew install python` if you don't have it.

```bash
git clone https://github.com/Tamygigs/Personal-budget-tracker-in-the-terminal.git
cd Personal-budget-tracker-in-the-terminal
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
tally --help
```

Try it on made-up data first (it won't touch your real database):

```bash
bash examples/demo.sh
```

## Use

```bash
# 1. Import a statement. Columns and date format are detected automatically.
tally import ~/Downloads/statement.csv
tally import card.csv --invert          # card exports that show spending as positive
tally import odd.csv --dry-run          # preview without saving

# 2. Teach it your categories. Rules re-apply to past transactions too.
tally rules add "TESCO" groceries
tally rules add "PRET|COSTA|DELIVEROO" "eating out" --regex
tally rules add "AMAZON PRIME" subscriptions --priority 5   # beats a plain AMAZON rule
tally rules list

# 3. Fix one-offs by hand (rules won't overwrite these)
tally list --uncategorised
tally categorize 95 groceries

# 4. Budgets and reports
tally budget set groceries 250
tally report                      # latest month
tally report --month 2026-09
tally trend --months 6

# Settings
tally config --currency '$'
```

Run `tally <command> --help` for every option.

### Supported CSV layouts

* A single signed amount column (`Amount`, `Value`, …), **or** separate
  money-out / money-in columns (`Debit`/`Credit`, `Paid out`/`Paid in`, …)
* Day-first (UK), month-first (US) and ISO dates, detected from the whole file
* Comma, semicolon or tab separated, with or without Excel's BOM
* Account-detail lines above the header row
* Anything else: name the columns yourself with `--date-col`, `--desc-col`,
  `--amount-col`, `--debit-col`, `--credit-col` and `--date-format`

Re-importing the same or overlapping statements is safe: duplicates are skipped.

## How money in and out is counted

Transactions are netted per category, so a £20 refund in `shopping` lowers
shopping spend instead of counting as income. A category with a negative net
is spending; a positive one is income. Uncategorised items are split by sign.

## Develop

```bash
python -m pytest -q       # run the tests
```

The code is small and commented. [docs/how-it-works.md](docs/how-it-works.md)
walks through it file by file.

## Roadmap

Ideas for what comes next:

- [ ] `tally export` to CSV for a month or category
- [ ] Detect recurring payments and subscriptions automatically
- [ ] Multiple accounts (current account, credit card, savings) with transfers between them ignored
- [ ] OFX/QIF import
- [ ] Interactive categorising: step through uncategorised items and create rules on the spot
- [ ] Budget rollover (unspent budget carries to next month)
- [ ] Rules import/export so they can be backed up
- [ ] Category spending over time (`tally trend --category groceries`)

## How this was built

Built with the help of an AI coding assistant, with design decisions, review and
testing by me.

## Licence

[MIT](LICENSE)
