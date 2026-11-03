#!/usr/bin/env bash
# Try Tally on made-up sample data without touching your real database.
#   bash examples/demo.sh
set -euo pipefail

cd "$(dirname "$0")"
export TALLY_DB="$(mktemp -d)/demo.db"

tally import sample-statement.csv

tally rules add "TESCO" groceries --no-apply
tally rules add "SAINSBURY" groceries --no-apply
tally rules add "LIDL" groceries --no-apply
tally rules add "ALDI" groceries --no-apply
tally rules add "PRET|COSTA|DELIVEROO|NANDOS" "eating out" --regex --no-apply
tally rules add "TFL" transport --no-apply
tally rules add "RENT" rent --no-apply
tally rules add " DD" bills --no-apply
tally rules add "SPOTIFY" subscriptions --priority 1 --no-apply
tally rules add "PUREGYM" subscriptions --no-apply
tally rules add "AMAZON|ARGOS|UNIQLO" shopping --regex --no-apply
tally rules add "SALARY" salary --no-apply
tally rules add "SAVINGS TRANSFER" savings --no-apply
tally rules apply

tally budget set groceries 250
tally budget set "eating out" 90
tally budget set transport 60

echo
tally report --month 2026-10
echo
tally trend --months 3
echo
tally list --uncategorised
