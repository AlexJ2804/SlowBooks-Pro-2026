"""FX rate lookup endpoint backed by Bank of Canada Valet."""

from fastapi import APIRouter, Query

from app.services.fx_service import get_rate


router = APIRouter(prefix="/api/fx", tags=["fx"])


@router.get("/rate")
def fx_rate(
    from_: str = Query(..., alias="from", min_length=3, max_length=3),
    to: str = Query(..., min_length=3, max_length=3),
):
    """Return an FX rate from `from` to `to`.

    Always returns 200; check the `rate` field for null on failure so the
    client can fall back to a manually-entered rate without exception
    handling. `source` indicates the path taken (direct/cross/identity).
    """
    result = get_rate(from_, to)
    return {
        "from": from_.upper(),
        "to": to.upper(),
        "rate": str(result["rate"]) if result["rate"] is not None else None,
        "observation_date": result["observation_date"],
        "source": result["source"],
        "error": result["error"],
    }
