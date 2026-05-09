# Changelog

All notable household-finance changes to this project. The bookkeeping
side of Slowbooks Pro 2026 (invoicing, AR/AP, payroll, etc.) is older
and predates this file — see git history for those changes.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project does not use SemVer; releases are grouped by phase.

## [Unreleased]

## Phase 1.5 — Household ownership refactor + miles, scores, dashboard

### Added
- **Airline miles tracker** for the household's loyalty programmes.
  Three new tables — `airline_programs`, `airline_program_memberships`,
  `airline_miles_snapshots` — modelling programmes (AAdvantage,
  SkyMiles, MileagePlus, AerClub, Aeroplan), per-person memberships,
  and a points history. New page at `/#/miles` renders one card per
  programme with brand colour, logo, a per-person split bar, and an
  inline "Update balance" form. Snapshot upsert mirrors
  `balance_snapshots`: re-entering today's value overwrites by
  `(membership_id, as_of_date)` instead of failing.
- **Credit scores tracker** with a `credit_scores` table keyed by
  `(person_id, bureau, score_model, as_of_date)`. New page at
  `/#/credit-scores` shows a latest-scores grid (rows = parents,
  cols = bureaus), a per-parent history line chart (hand-rolled
  inline SVG; no charting library was added), and a full history
  table. Adult-parents-only enforced at the route layer with a
  specific 422 message; Theodore is filtered out of the person
  dropdown client-side.
- **Household dashboard hoist.** `/#/dashboard` now leads with a
  household section: net-worth headline + per-person slice cards,
  airline-miles roll-up, credit-score grid, and a recent-activity
  feed of the last five balance snapshots. The legacy QuickBooks
  Company Snapshot still lives below, retitled "Bookkeeping" so
  the personal/business split is self-evident.
- **People + ownership join.** New `people` table plus
  `account_ownerships` join table replaces the legacy
  `alex_pct / alexa_pct / kids_pct` three-column shape on
  `accounts`. Per-person net-worth slices, miles memberships, and
  credit scores all FK to the new `people` table. Sum-to-100 is
  enforced via a deferrable Postgres trigger plus app-level
  validation for the SQLite test database.

### Changed
- `/#/dashboard` route still resolves to the home page; the
  underlying renderer was rewritten to compose four household
  endpoints in parallel (`Promise.all`) before stitching in the
  legacy snapshot. No new aggregation endpoint was added.
- The dashboard's legacy "Company Snapshot" header is now
  "Bookkeeping".

### Backwards compatibility
- The legacy `accounts.alex_pct / alexa_pct / kids_pct` columns
  are still dual-written for the duration of phase 1.5; a
  follow-up migration drops them after a stable window.
- `/api/net-worth` still emits the legacy `totals.alex / alexa /
  kids` keys plus per-account `ownership` and `contributions`
  dicts so the existing `/#/net-worth` page keeps rendering
  through the dual-write window. New callers should iterate
  `slices_by_person` instead.

## Phase 1 — Personal net-worth tracker

### Added
- **Personal accounts** alongside the chart of accounts. New
  `account_kind` column on `accounts` (`bank` / `credit_card` /
  `brokerage` / `retirement` / `property` / `loan`) plus an
  `update_strategy` (`transactional` / `balance_only`) so accounts
  whose balance is published periodically (brokerage statements,
  property valuations, mortgage payoff figures) can be tracked
  without inventing transactions.
- **Manual balance snapshots** — `balance_snapshots` table holds
  one row per `(account_id, as_of_date)` reading. POST is upsert
  on the unique tuple so re-entering for the same date overwrites
  rather than failing.
- **Loan amortization** — `loans` table with a generated
  amortization schedule for mortgage / instalment-loan accounts.
- **Net-worth dashboard** at `/#/net-worth`: every personal
  account with its latest balance, FX-converted to the home
  currency, sign-adjusted for liabilities, summed into household
  totals and per-person slices.
- **FX service** — Bank of Canada Valet for live rates with a
  hardcoded USD/EUR fallback so the dashboard degrades gracefully
  rather than breaking when the upstream is unavailable.
