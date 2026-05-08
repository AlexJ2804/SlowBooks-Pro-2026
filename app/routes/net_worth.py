"""Net worth dashboard — net worth phase 1, task 5.

Assembles the dashboard's full data structure server-side: per-account
latest balance, FX conversion to home currency, sign-adjustment for
liabilities, and totals (household + per-person slices).

Phase 1.5 changes (alembic j2a3b4c5d6e7):
  - Per-person slices come from the account_ownerships join table
    rather than the legacy alex_pct/alexa_pct/kids_pct columns.
  - Response now carries `slices_by_person` (list, ordered by
    person.display_order) for the upcoming dashboard hoist.
  - Legacy `totals.alex/alexa/kids` keys + per-account `ownership` and
    `contributions` dicts are still emitted by mapping person_id 1/2/3
    so the existing /#/net-worth page keeps working through the
    dual-write window.

FX strategy (per phase-1 spec):
- Lazy: only convert pairs we actually need this request, cached for
  the duration of the request.
- Use the existing fx_service.get_rate (Bank of Canada Valet, with
  cross-rate via CAD when needed).
- Fall back to a hardcoded USD/EUR = 1.08 constant if the service
  returns None — phase-1 prefers a degraded dashboard over a broken
  one. Surface "fx_warning" in the response so the UI can banner it.
- Other currency pairs we don't have a hardcoded fallback for fall
  back to identity (rate 1.0) with a louder warning. In practice the
  user's accounts are all USD or EUR for phase 1.

Liability sign convention:
- account_kind ∈ {credit_card, loan}: positive balance represents debt.
  Multiplied by -1 before summing into net-worth totals.
- All other kinds: positive balance is a positive contribution.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.accounts import Account
from app.models.balance_snapshots import BalanceSnapshot
from app.models.people import Person
from app.models.settings import Settings
from app.services.fx_service import get_rate as fx_get_rate

router = APIRouter(prefix="/api/net-worth", tags=["net-worth"])


_CENTS = Decimal("0.01")
# Fallback constant — only USD↔EUR is hardcoded here. Phase-1 accounts
# are USD or EUR; other pairs that come up later should either lean on
# the live rate or extend this map.
_HARDCODED_RATES = {
    ("USD", "EUR"): Decimal("0.926"),  # 1 USD ≈ 0.926 EUR (i.e. 1 EUR ≈ 1.08 USD)
    ("EUR", "USD"): Decimal("1.080"),
}
_LIABILITY_KINDS = {"credit_card", "loan"}

# Legacy slice keys for backwards-compat with /#/net-worth UI. Maps
# person_id → JSON key under `totals`. New code should iterate
# `slices_by_person` (list keyed by display_order) instead.
_LEGACY_SLICE_KEY_BY_PID = {1: "alex", 2: "alexa", 3: "kids"}


def _home_currency(db: Session) -> str:
    row = db.query(Settings).filter(Settings.key == "home_currency").first()
    if row and row.value:
        return row.value.strip().upper() or "USD"
    return "USD"


def _resolve_rate(from_ccy: str, to_ccy: str, cache: dict) -> dict:
    """Return {'rate': Decimal, 'source': str, 'fallback_used': bool}.
    Cached per (from, to) pair within a single dashboard render.
    Never raises — on total failure, returns rate=1.0 with a warning."""
    f = (from_ccy or "").upper()
    t = (to_ccy or "").upper()
    if f == t or not f or not t:
        return {"rate": Decimal("1"), "source": "identity", "fallback_used": False}

    key = (f, t)
    if key in cache:
        return cache[key]

    live = fx_get_rate(f, t)
    if live.get("rate") is not None:
        result = {
            "rate": live["rate"],
            "source": live.get("source") or "live",
            "fallback_used": False,
        }
    elif key in _HARDCODED_RATES:
        result = {
            "rate": _HARDCODED_RATES[key],
            "source": "hardcoded-fallback",
            "fallback_used": True,
        }
    else:
        # Last resort: identity. Loud warning lets the UI flag the
        # affected account row(s).
        result = {
            "rate": Decimal("1"),
            "source": "identity-fallback",
            "fallback_used": True,
        }
    cache[key] = result
    return result


def _q(d: Decimal) -> Decimal:
    return d.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _latest_snapshots(db: Session) -> dict:
    """{account_id: BalanceSnapshot} for the most recent snapshot per
    account. One round-trip via max-date subquery — same shape as the
    helper in app/routes/accounts.py but kept local to avoid
    cross-module coupling on the dashboard's hot path."""
    latest_dates = (
        db.query(
            BalanceSnapshot.account_id.label("aid"),
            func.max(BalanceSnapshot.as_of_date).label("max_date"),
        )
        .group_by(BalanceSnapshot.account_id)
        .subquery()
    )
    rows = (
        db.query(BalanceSnapshot)
        .join(latest_dates, and_(
            BalanceSnapshot.account_id == latest_dates.c.aid,
            BalanceSnapshot.as_of_date == latest_dates.c.max_date,
        ))
        .all()
    )
    return {r.account_id: r for r in rows}


@router.get("")
def net_worth_dashboard(db: Session = Depends(get_db)):
    home = _home_currency(db)
    accounts = (
        db.query(Account)
        .options(joinedload(Account.ownerships))
        .filter(Account.account_kind.isnot(None), Account.is_active == True)
        .order_by(Account.account_kind, Account.name)
        .all()
    )
    latest_by_id = _latest_snapshots(db)

    people = db.query(Person).order_by(Person.display_order, Person.id).all()
    # slice_bucket[person_id] tracks running totals per person. Built
    # from people-table rows, so a household with N members produces N
    # entries automatically — no hardcoding of Alex/Alexa/Theodore.
    slice_buckets: dict = {
        p.id: {
            "person_id": p.id,
            "name": p.name,
            "role": p.role,
            "display_order": p.display_order,
            "assets": Decimal("0"),
            "liabilities": Decimal("0"),
        }
        for p in people
    }

    fx_cache: dict = {}
    fx_warnings: list = []

    rendered_accounts = []
    # Legacy slice totals — keyed by alex/alexa/kids strings, populated
    # by mirroring person_id 1/2/3 contributions. Kept until the
    # dashboard JS migrates to slices_by_person in the Task 5 hoist.
    totals = {
        "household": {"assets": Decimal("0"), "liabilities": Decimal("0")},
        "alex":      {"assets": Decimal("0"), "liabilities": Decimal("0")},
        "alexa":     {"assets": Decimal("0"), "liabilities": Decimal("0")},
        "kids":      {"assets": Decimal("0"), "liabilities": Decimal("0")},
    }

    for a in accounts:
        snap = latest_by_id.get(a.id)
        native = snap.balance if snap is not None else None
        snap_currency = (snap.currency if snap else None) or a.currency or home
        as_of = snap.as_of_date.isoformat() if snap else None

        ownership_rows_json = [
            {"person_id": o.person_id, "share_pct": o.share_pct}
            for o in a.ownerships
        ]

        # Legacy ownership block: derive from the join rows so it stays
        # accurate even if the dual-write columns drift. Person IDs
        # outside {1, 2, 3} contribute to neither — they only show up
        # in ownership_rows_json.
        legacy_ownership = {"alex_pct": 0, "alexa_pct": 0, "kids_pct": 0}
        for o in a.ownerships:
            key = _LEGACY_SLICE_KEY_BY_PID.get(o.person_id)
            if key == "alex":
                legacy_ownership["alex_pct"] += o.share_pct
            elif key == "alexa":
                legacy_ownership["alexa_pct"] += o.share_pct
            elif key == "kids":
                legacy_ownership["kids_pct"] += o.share_pct

        # Even with no snapshot we render the account row so the user
        # can see "no balance entered yet" rather than the account
        # silently disappearing from the dashboard.
        if native is None:
            rendered_accounts.append({
                "id": a.id,
                "name": a.name,
                "kind": a.account_kind,
                "currency": snap_currency,
                "ownership": legacy_ownership,
                "ownership_rows": ownership_rows_json,
                "latest_balance_native": None,
                "latest_balance_as_of": None,
                "balance_in_home_currency": None,
                "is_liability": a.account_kind in _LIABILITY_KINDS,
                "signed_balance_home": None,
                "contributions": {"alex": None, "alexa": None, "kids": None},
                "contributions_by_person": {},
                "fx_rate": None,
                "fx_source": None,
            })
            continue

        rate_info = _resolve_rate(snap_currency, home, fx_cache)
        rate = Decimal(rate_info["rate"])
        if rate_info["fallback_used"] and rate_info["source"] == "identity-fallback":
            fx_warnings.append(
                f"FX rate unavailable for {snap_currency}->{home}; using identity. "
                f"Account '{a.name}' may be misvalued in totals."
            )

        balance_home = _q(Decimal(native) * rate)
        is_liability = a.account_kind in _LIABILITY_KINDS
        signed = -balance_home if is_liability else balance_home
        bucket = "liabilities" if is_liability else "assets"

        # Per-person contributions from the join table. No assumption
        # that person_id 1/2/3 are the only members.
        contributions_by_person: dict = {}
        legacy_contributions = {"alex": Decimal("0"), "alexa": Decimal("0"),
                                "kids": Decimal("0")}
        for o in a.ownerships:
            contrib = _q(signed * Decimal(o.share_pct) / Decimal(100))
            contributions_by_person[str(o.person_id)] = str(contrib)
            # Slice totals (asset/liability split, not signed)
            slice_share = _q(balance_home * Decimal(o.share_pct) / Decimal(100))
            if o.person_id in slice_buckets:
                slice_buckets[o.person_id][bucket] += slice_share
            # Legacy mirror
            legacy_key = _LEGACY_SLICE_KEY_BY_PID.get(o.person_id)
            if legacy_key is not None:
                legacy_contributions[legacy_key] += contrib
                totals[legacy_key][bucket] += slice_share

        # Household total ignores ownership — it's the sum of every
        # account's home-currency balance.
        totals["household"][bucket] += balance_home

        rendered_accounts.append({
            "id": a.id,
            "name": a.name,
            "kind": a.account_kind,
            "currency": snap_currency,
            "ownership": legacy_ownership,
            "ownership_rows": ownership_rows_json,
            "latest_balance_native": str(native),
            "latest_balance_as_of": as_of,
            "balance_in_home_currency": str(balance_home),
            "is_liability": is_liability,
            "signed_balance_home": str(signed),
            "contributions": {
                "alex":  str(legacy_contributions["alex"]),
                "alexa": str(legacy_contributions["alexa"]),
                "kids":  str(legacy_contributions["kids"]),
            },
            "contributions_by_person": contributions_by_person,
            "fx_rate": str(rate),
            "fx_source": rate_info["source"],
        })

    # Compute net per legacy slice, stringify for JSON.
    for slice_key in totals:
        slice_data = totals[slice_key]
        slice_data["net"] = _q(slice_data["assets"] - slice_data["liabilities"])
        slice_data["assets"]      = str(_q(slice_data["assets"]))
        slice_data["liabilities"] = str(_q(slice_data["liabilities"]))
        slice_data["net"]         = str(slice_data["net"])

    # Convert slice_buckets dict → ordered list of person slices.
    slices_by_person = []
    for p in people:
        s = slice_buckets[p.id]
        s["net"] = _q(s["assets"] - s["liabilities"])
        slices_by_person.append({
            "person_id":    s["person_id"],
            "name":         s["name"],
            "role":         s["role"],
            "display_order": s["display_order"],
            "assets":       str(_q(s["assets"])),
            "liabilities":  str(_q(s["liabilities"])),
            "net":          str(s["net"]),
        })

    # Aggregate fx_source flag for the response banner.
    sources = {a["fx_source"] for a in rendered_accounts if a["fx_source"]}
    if "hardcoded-fallback" in sources or "identity-fallback" in sources:
        if any(s in sources for s in ("bankofcanada-direct", "bankofcanada-cross")):
            fx_status = "mixed"
        else:
            fx_status = "fallback"
    elif sources:
        fx_status = "live"
    else:
        fx_status = "none"

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "home_currency": home,
        "fx_status": fx_status,
        "fx_warnings": fx_warnings,
        "totals": totals,
        "slices_by_person": slices_by_person,
        "accounts": rendered_accounts,
    }
