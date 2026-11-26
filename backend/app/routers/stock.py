"""Stock by item and location, from Business Central (open Item Ledger Entries). Read by everyone; downloaded by
Dynamics sync (Download all, or Stock by location), by Refresh here, and on its own when older than stock_minutes."""
import threading
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import Material, StockEntry, User
from ..security import current_user, require
from ..services import dynamics as D
from ..services.common import get_settings, iso_utc, local_today, log, now_utc, put_settings

router = APIRouter(prefix="/api/stock", tags=["stock"])
_busy = threading.Lock()


def refresh(db: Session, me: User | None) -> dict:
    """Downloads the stock now, with the columns remembered for it; replaces what is here."""
    s = get_settings(db)
    if not s["dynamics"]["ep"].get("stock"):
        raise HTTPException(422, "No Stock endpoint is set. Under Dynamics sync, Dynamics connection, set Stock by location "
                                 "(for example odata:ItemLedgerEntries, the published Item Ledger Entries page).")
    token = D.access_token(s)
    rows = D.api_pull(s, "stock", token, {})
    headers = list({k: 1 for r in rows for k in r}.keys())
    m = D.api_map(s, "stock", headers)
    miss = D.missing_fields("stock", m)
    if not rows:
        raise HTTPException(422, "Dynamics returned no stock lines, so the stock here was kept as it was. Check the Stock endpoint.")
    if miss:
        raise HTTPException(422, f"Columns not found in the Stock endpoint ({', '.join(miss)}). Use Download via API for Stock by location once and choose them.")
    res = D.apply_rows(db, "stock", rows, m, dry=False)
    put_settings(db, {"sync_info": {**s.get("sync_info", {}), "stock": iso_utc(now_utc())}, "stock_locations": D.location_names(s, token)})
    log(db, "in", "Stock by location", res["added"], "ok", f"Dynamics API: {res['added']} stock lines, {res.get('items', 0)} items", me)
    db.commit()
    return res


def _auto_refresh():
    if not _busy.acquire(blocking=False):
        return
    try:
        db = SessionLocal()
        try:
            if not get_settings(db)["dynamics"]["ep"].get("stock"):
                return
            refresh(db, None)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            msg = e.detail if isinstance(e, HTTPException) else str(e)
            log(db, "in", "Stock by location", 0, "error", f"Automatic refresh: {msg}"[:500], None)
            put_settings(db, {"stock_error": {"at": iso_utc(now_utc()), "message": str(msg)[:300]}})
            db.commit()
        finally:
            db.close()
    finally:
        _busy.release()


def _stale(s: dict) -> bool:
    last, mins = s.get("sync_info", {}).get("stock"), int(s["dynamics"].get("stock_minutes") or 0)
    if not mins or not s["dynamics"]["ep"].get("stock"):
        return False
    err = (s.get("stock_error") or {}).get("at")
    since = max(x for x in (last, err, "") if x is not None)          # after an error, wait the same time before trying again
    return not since or since < iso_utc(now_utc() - timedelta(minutes=mins))


@router.get("")
def stock(bg: BackgroundTasks, location: str = "", q: str = "", zero: bool = False, db: Session = Depends(get_db), me: User = Depends(current_user)):
    s = get_settings(db)
    if _stale(s):
        bg.add_task(_auto_refresh)
    names = s.get("stock_locations") or {}
    mats = {m.code: m for m in db.scalars(select(Material))}
    entries = list(db.scalars(select(StockEntry)))
    loc_tot = {}
    for e in entries:
        loc_tot[e.location] = loc_tot.get(e.location, 0) + float(e.qty)
    loc = location.strip().upper()
    today, ql = local_today(), q.strip().lower()
    items = {}
    for e in entries:
        if loc and e.location != loc:
            continue
        it = items.setdefault(e.material_code, {"by_loc": {}, "lots": [], "total": 0.0})
        it["by_loc"][e.location] = round(it["by_loc"].get(e.location, 0) + float(e.qty), 4)
        it["total"] = round(it["total"] + float(e.qty), 4)
        if e.lot or e.expiry:
            it["lots"].append({"location": e.location, "lot": e.lot, "expiry": e.expiry.isoformat() if e.expiry else None,
                               "days": (e.expiry - today).days if e.expiry else None, "qty": float(e.qty)})
    if zero:
        for code in mats:
            items.setdefault(code, {"by_loc": {}, "lots": [], "total": 0.0})
    rows = []
    for code, it in items.items():
        mt = mats.get(code)
        name = mt.name if mt else ""
        if ql and ql not in code.lower() and ql not in name.lower():
            continue
        it["lots"].sort(key=lambda x: (x["expiry"] or "9999", x["location"], x["lot"]))
        soon = [x["days"] for x in it["lots"] if x["days"] is not None and x["qty"] > 0]
        rows.append({"code": code, "name": name, "uom": mt.uom if mt else "", "known": bool(mt), **it,
                     "next_expiry_days": min(soon) if soon else None})
    rows.sort(key=lambda x: (x["name"] or "~", x["code"]))
    return {"synced": s.get("sync_info", {}).get("stock"), "api": bool(s["dynamics"]["ep"].get("stock")),
            "minutes": int(s["dynamics"].get("stock_minutes") or 0), "refreshing": _busy.locked(),
            "error": s.get("stock_error") if (s.get("stock_error") or {}).get("at", "") > (s.get("sync_info", {}).get("stock") or "") else None,
            "locations": [{"code": c, "name": names.get(c, ""), "qty": round(t, 4)} for c, t in sorted(loc_tot.items())],
            "rows": rows}


@router.post("/refresh")
def refresh_now(db: Session = Depends(get_db), me: User = Depends(require("admin", "manager"))):
    with _busy:
        res = refresh(db, me)
    return {"lines": res["added"], "items": res.get("items", 0), "errors": res["errors"]}
