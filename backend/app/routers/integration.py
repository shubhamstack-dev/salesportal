from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (Charge, Customer, ExpenseClaim, HsnCode, Material, MaterialAttribute, Payment, Price, SalesDoc, SyncLog, User)
from ..security import require
from ..services import dynamics as D
from ..services.common import get_settings, iso_utc, log, now_utc, put_settings
from ..services.xl import workbook, xlsx_response

router = APIRouter(prefix="/api/integration", tags=["integration"])
admin = require("admin")


def _preview(db: Session, ent: str, key: str, si: int | None, mapping: dict | None):
    data = D.unstash(key)
    sheets = data["sheets"]
    si = D.pick_sheet(ent, sheets) if si is None else max(0, min(si, len(sheets) - 1))
    sh = sheets[si]
    m = mapping or D.auto_map(ent, sh["headers"])
    res = D.apply_rows(db, ent, sh["rows"], m, dry=True)
    db.rollback()
    return {"import_id": key, "entity": ent, "label": D.ENT[ent]["label"], "source": data["source"], "sheet": si,
            "sheets": [{"name": s["name"], "rows": len(s["rows"])} for s in sheets], "headers": sh["headers"], "fields": list(D.ENT[ent]["fields"]),
            "map": m, "result": res}


def _ent(ent: str):
    if ent not in D.ENT:
        raise HTTPException(404, "Unknown master.")


@router.post("/import/{ent}/file")
async def import_file(ent: str, file: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(admin)):
    _ent(ent)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "The file is larger than 20 MB.")
    sheets = D.read_file(data, file.filename or "upload.xlsx")
    if not sheets:
        raise HTTPException(422, "The file has no rows.")
    return _preview(db, ent, D.stash(sheets, file.filename or "file"), None, None)


@router.post("/import/{ent}/api")
def import_api(ent: str, db: Session = Depends(get_db), _=Depends(admin)):
    _ent(ent)
    rows = D.api_pull(get_settings(db), ent)
    if not rows:
        raise HTTPException(422, "Dynamics returned no rows.")
    headers = list({k: 1 for r in rows for k in r}.keys())
    return _preview(db, ent, D.stash([{"name": "API", "headers": headers, "rows": rows}], f"Dynamics API: {get_settings(db)['dynamics']['ep'][ent]}"), None, None)


class MapIn(BaseModel):
    import_id: str
    sheet: int | None = None
    map: dict | None = None


@router.post("/import/{ent}/preview")
def remap(ent: str, body: MapIn, db: Session = Depends(get_db), _=Depends(admin)):
    _ent(ent)
    return _preview(db, ent, body.import_id, body.sheet, body.map)


@router.post("/import/{ent}/apply")
def apply(ent: str, body: MapIn, db: Session = Depends(get_db), me: User = Depends(admin)):
    _ent(ent)
    data = D.unstash(body.import_id)
    sheets = data["sheets"]
    si = D.pick_sheet(ent, sheets) if body.sheet is None else body.sheet
    sh = sheets[si]
    res = D.apply_rows(db, ent, sh["rows"], body.map or D.auto_map(ent, sh["headers"]), dry=False)
    s = get_settings(db)
    put_settings(db, {"sync_info": {**s.get("sync_info", {}), ent: iso_utc(now_utc())}})
    log(db, "in", D.ENT[ent]["label"], res["added"] + res["updated"], "warning" if res["skipped"] else "ok",
        f"{data['source']}: {res['added']} new, {res['updated']} updated, {res['skipped']} skipped", me)
    db.commit()
    return res


@router.get("/template/{ent}")
def template(ent: str, _=Depends(admin)):
    _ent(ent)
    return xlsx_response(workbook({D.ENT[ent]["label"]: [{a[0]: "" for a in D.ENT[ent]["fields"].values()}]}), f"Template_{ent}.xlsx")


@router.get("/summary")
def summary(db: Session = Depends(get_db), _=Depends(admin)):
    q = D.out_queues(db)
    s = get_settings(db)
    waiting_file = sum(db.query(M).filter(M.sync_status == "exported").count() for M in (SalesDoc, Payment, ExpenseClaim))
    errors = sum(db.query(M).filter(M.sync_status == "error").count() for M in (SalesDoc, Payment, ExpenseClaim))
    counts = {"customers": db.query(Customer).count(), "materials": db.query(Material).count(), "attributes": db.query(MaterialAttribute).count(),
              "prices": db.query(Price).count(), "hsn": db.query(HsnCode).count(), "charges": db.query(Charge).count()}
    return {"masters": [{"entity": k, "label": v["label"], "count": counts[k], "last": s.get("sync_info", {}).get(k),
                         "api": bool(s["dynamics"]["ep"].get(k))} for k, v in D.ENT.items()],
            "out": {"quotes": {"count": len(q["quotes"]), "value": sum(float(x.total) for x in q["quotes"])},
                    "orders": {"count": len(q["orders"]), "value": sum(float(x.total) for x in q["orders"])},
                    "payments": {"count": len(q["payments"]), "value": sum(float(x.amount) for x in q["payments"])},
                    "expenses": {"count": len(q["expenses"]), "value": sum(float(x.total) for x in q["expenses"])}},
            "waiting_file": waiting_file, "errors": errors,
            "log": [{"at": iso_utc(l.at), "direction": l.direction, "entity": l.entity, "count": l.count, "status": l.status, "message": l.message,
                     "user": l.user_name} for l in db.scalars(select(SyncLog).order_by(SyncLog.id.desc()).limit(50))]}


@router.post("/export")
def export(db: Session = Depends(get_db), me: User = Depends(admin)):
    q = D.out_queues(db)
    n = sum(len(v) for v in q.values())
    if not n:
        raise HTTPException(409, "Nothing is waiting to go to Dynamics.")
    neg = get_settings(db)["dynamics"]["payments_negative"]
    data = workbook({
        "Quote Header": [D.doc_header(db, d) for d in q["quotes"]], "Quote Lines": [l for d in q["quotes"] for l in D.doc_lines(d)],
        "Sales Header": [D.doc_header(db, d) for d in q["orders"]], "Sales Lines": [l for d in q["orders"] for l in D.doc_lines(d)],
        "Order Charges": [c for d in q["quotes"] + q["orders"] for c in D.doc_charges(d)],
        "Payments": [D.payment_row(db, p, neg) for p in q["payments"]],
        "Employee Expenses": [l for x in q["expenses"] for l in D.expense_lines(db, x)]})
    now = now_utc()
    for items in q.values():
        for x in items:
            x.sync_status, x.sync_at, x.sync_error = "exported", now, None
    log(db, "out", "Quotations, orders, payments, expenses", n, "ok", f"File: {len(q['quotes'])} quotations, {len(q['orders'])} orders, "
        f"{len(q['payments'])} payments, {len(q['expenses'])} expense claims", me)
    db.commit()
    return xlsx_response(data, f"To_Dynamics_{now:%Y-%m-%d}.xlsx")


@router.post("/ack")
async def ack(file: UploadFile = File(...), db: Session = Depends(get_db), me: User = Depends(admin)):
    """Imports Dynamics document numbers: columns External Document No. (portal number) and Document No. (Dynamics number)."""
    sheets = D.read_file(await file.read(), file.filename or "ack.xlsx")
    done = unknown = 0
    for sh in sheets:
        hs = sh["headers"]
        ext_h = next((h for h in hs if D.re.search(r"external\s*document|portal\s*(no|number)|receipt", h, D.re.I)), None)
        dyn_h = next((h for h in hs if D.re.fullmatch(r"(document\s*no\.?|no\.?|dynamics|number)", h.strip(), D.re.I)), None) \
            or next((h for h in hs if h != ext_h and D.re.search(r"document\s*no", h, D.re.I)), None)
        if not ext_h:
            continue
        for r in sh["rows"]:
            key = D._s(r.get(ext_h))
            if not key:
                continue
            rec = next((x for M in (SalesDoc, Payment, ExpenseClaim) for x in [db.scalar(select(M).where(M.no == key))] if x), None)
            if not rec:
                unknown += 1
                continue
            rec.sync_status, rec.sync_no, rec.sync_at, rec.sync_error = "synced", D._s(r.get(dyn_h))[:40] if dyn_h else "", now_utc(), None
            done += 1
    log(db, "in", "Dynamics document numbers", done, "warning" if unknown else "ok", f"{file.filename}: {done} matched, {unknown} not found", me)
    db.commit()
    return {"matched": done, "unknown": unknown}


@router.post("/push")
def push(db: Session = Depends(get_db), me: User = Depends(admin)):
    s = get_settings(db)
    ep = s["dynamics"]["ep"]
    q = D.out_queues(db)
    token = D.access_token(s)
    ok = bad = 0
    targets = [("quotes", ep.get("quotes")), ("orders", ep.get("orders")), ("payments", ep.get("payments")), ("expenses", ep.get("expenses"))]
    for kind, path in targets:
        if not path:
            continue
        for x in q[kind]:
            try:
                if kind in ("quotes", "orders"):
                    r = D.api_call(s, token, path, "POST", D.order_payload(db, x))
                    no = r.get("number") or r.get("No") or r.get("id") or ""
                elif kind == "payments":
                    c = db.get(Customer, x.customer_id)
                    r = D.api_call(s, token, path, "POST", {"customerNumber": c.code, "postingDate": x.pay_date.isoformat(), "documentNumber": x.no,
                                                           "externalDocumentNumber": x.ref or x.no, "amount": -float(x.amount) if s["dynamics"]["payments_negative"] else float(x.amount),
                                                           "description": f"{x.mode.upper()} {x.ref}".strip()})
                    no = r.get("documentNumber") or x.no
                else:
                    for line in D.expense_lines(db, x):
                        D.api_call(s, token, path, "POST", line)
                    no = x.no
                x.sync_status, x.sync_no, x.sync_at, x.sync_error = "synced", str(no)[:40], now_utc(), None
                ok += 1
            except HTTPException as e:
                x.sync_status, x.sync_error, x.sync_at = "error", str(e.detail)[:500], now_utc()
                bad += 1
    log(db, "out", "Quotations, orders, payments, expenses", ok, "error" if bad else "ok", f"API: {ok} sent, {bad} failed", me)
    db.commit()
    return {"sent": ok, "failed": bad}


@router.post("/test")
def test(db: Session = Depends(get_db), _=Depends(admin)):
    s = get_settings(db)
    ep = s["dynamics"]["ep"].get("customers") or ""
    b = D.api_call(s, D.access_token(s), ep + ("&" if "?" in ep else "?") + "$top=1")
    return {"ok": True, "rows": len(b.get("value", []))}
