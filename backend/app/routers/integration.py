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


def _rates(db: Session, given: dict | None) -> dict:
    return {**(get_settings(db)["dynamics"].get("gst_rates") or {}), **{str(k).strip(): v for k, v in (given or {}).items() if str(k).strip()}}


def _preview(db: Session, ent: str, key: str, si: int | None, mapping: dict | None, gst_rates: dict | None = None):
    data = D.unstash(key)
    sheets = data["sheets"]
    si = D.pick_sheet(ent, sheets) if si is None else max(0, min(si, len(sheets) - 1))
    sh = sheets[si]
    from_api = data["source"].startswith("Dynamics API")
    m = mapping or (D.api_map(get_settings(db), ent, sh["headers"]) if from_api else D.auto_map(ent, sh["headers"]))
    rates = _rates(db, gst_rates)
    res = D.apply_rows(db, ent, sh["rows"], m, dry=True, gst_rates=rates)
    db.rollback()
    return {"import_id": key, "gst_groups": D.gst_groups(sh["rows"], m, rates) if ent == "hsn" else [], "entity": ent, "label": D.ENT[ent]["label"], "source": data["source"], "sheet": si,
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
        raise HTTPException(422, f"Dynamics returned no rows for {D.ENT[ent]['label'].lower()}.")
    headers = list({k: 1 for r in rows for k in r}.keys())
    return _preview(db, ent, D.stash([{"name": "API", "headers": headers, "rows": rows}], f"Dynamics API: {get_settings(db)['dynamics']['ep'][ent]}"), None, None)


class MapIn(BaseModel):
    import_id: str
    sheet: int | None = None
    map: dict | None = None
    gst_rates: dict | None = None


@router.post("/import/{ent}/preview")
def remap(ent: str, body: MapIn, db: Session = Depends(get_db), _=Depends(admin)):
    _ent(ent)
    return _preview(db, ent, body.import_id, body.sheet, body.map, body.gst_rates)


@router.post("/import/{ent}/apply")
def apply(ent: str, body: MapIn, db: Session = Depends(get_db), me: User = Depends(admin)):
    _ent(ent)
    data = D.unstash(body.import_id)
    sheets = data["sheets"]
    si = D.pick_sheet(ent, sheets) if body.sheet is None else body.sheet
    sh = sheets[si]
    from_api = data["source"].startswith("Dynamics API")
    s = get_settings(db)
    m = body.map or (D.api_map(s, ent, sh["headers"]) if from_api else D.auto_map(ent, sh["headers"]))
    rates = _rates(db, body.gst_rates)
    res = D.apply_rows(db, ent, sh["rows"], m, dry=False, gst_rates=rates)
    if ent == "materials" and from_api:
        try:
            db.flush()
            res["packs"] = D.apply_packs(db, s)["items"]
        except HTTPException as e:
            res["errors"] = [*res["errors"], f"Packets (Item Units of Measure): {e.detail}"]
    patch = {"sync_info": {**s.get("sync_info", {}), ent: iso_utc(now_utc())}, "dynamics": {}}
    if from_api:      # remember the columns, so "Download all" and the next download use them
        patch["dynamics"]["api_map"] = {**(s["dynamics"].get("api_map") or {}), ent: m}
    if ent == "hsn" and body.gst_rates:   # and the GST rate of each GST group
        patch["dynamics"]["gst_rates"] = rates
    if not patch["dynamics"]:
        del patch["dynamics"]
    put_settings(db, patch)
    log(db, "in", D.ENT[ent]["label"], res["added"] + res["updated"], "warning" if res["skipped"] else "ok",
        f"{data['source']}: {res['added']} new, {res['updated']} updated, {res['skipped']} skipped", me)
    db.commit()
    return res


@router.post("/pull-all")
def pull_all(db: Session = Depends(get_db), me: User = Depends(admin)):
    """Downloads every master that has an API endpoint, in dependency order, with the remembered columns."""
    s = get_settings(db)
    token, cache, out, items = None, {}, [], None
    for ent in D.PULL_ORDER:
        label = D.ENT[ent]["label"]
        if not s["dynamics"]["ep"].get(ent):
            out.append({"entity": ent, "label": label, "status": "skipped", "message": "No API endpoint; use a file"})
            continue
        try:
            token = token or D.access_token(s)
            rows = D.api_pull(s, ent, token, cache)
        except HTTPException as e:
            out.append({"entity": ent, "label": label, "status": "error", "message": str(e.detail)})
            log(db, "in", label, 0, "error", f"Dynamics API: {e.detail}", me)
            db.commit()
            continue
        headers = list({k: 1 for r in rows for k in r}.keys())
        m = D.api_map(s, ent, headers)
        miss = D.missing_fields(ent, m)
        if not rows or miss:
            msg = "Dynamics returned no rows" if not rows else \
                f"Columns not found ({', '.join(miss)}). Use Download via API once and choose them."
            out.append({"entity": ent, "label": label, "status": "error", "message": msg})
            continue
        rates = s["dynamics"].get("gst_rates") or {}
        dry = D.apply_rows(db, ent, rows, m, dry=True, gst_rates=rates)
        db.rollback()
        if ent in ("prices", "charges") and not dry["added"]:     # these replace everything; never wipe them with nothing
            out.append({"entity": ent, "label": label, "status": "error", "message": f"No usable rows ({dry['skipped']} skipped); nothing replaced",
                        "errors": dry["errors"][:5]})
            continue
        res = D.apply_rows(db, ent, rows, m, dry=False, gst_rates=rates)
        if ent == "materials":
            items = (rows, m)
            try:
                res["packs"] = D.apply_packs(db, s, token, cache)["items"]
            except HTTPException as e:
                res["errors"] = [*res["errors"], f"Packets (Item Units of Measure): {e.detail}"]
        if ent == "prices" and items:
            db.flush()
            res["item_prices"] = D.item_price_fallback(db, *items)
        s = get_settings(db)
        put_settings(db, {"sync_info": {**s.get("sync_info", {}), ent: iso_utc(now_utc())}})
        log(db, "in", label, res["added"] + res["updated"], "warning" if res["skipped"] else "ok",
            f"Dynamics API: {res['added']} new, {res['updated']} updated, {res['skipped']} skipped", me)
        db.commit()
        s = get_settings(db)
        out.append({"entity": ent, "label": label, "status": "warning" if res["skipped"] else "ok", "added": res["added"], "updated": res["updated"],
                    "skipped": res["skipped"], "errors": res["errors"][:5], "item_prices": res.get("item_prices", 0)})
    return {"results": out}


@router.post("/company")
def company(db: Session = Depends(get_db), me: User = Depends(admin)):
    """Fills the printed company and bank details from Business Central's Company Information. Empty fields keep their value."""
    got = D.company_from_dynamics(get_settings(db))
    if not got["company"] and not got["print"]:
        raise HTTPException(422, "Dynamics returned no company details.")
    put_settings(db, {"company": got["company"], "print": got["print"]})
    log(db, "in", "Company details", 1, "ok", f"Dynamics: {', '.join(list(got['company']) + list(got['print']))}", me)
    db.commit()
    return got


@router.get("/services")
def services(db: Session = Depends(get_db), _=Depends(admin)):
    """What is published under Web Services in Business Central, to fill in odata: endpoints."""
    return {"services": D.odata_services(get_settings(db))}


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
    cache = {}
    targets = [("quotes", ep.get("quotes")), ("orders", ep.get("orders")), ("payments", ep.get("payments")), ("expenses", ep.get("expenses"))]
    for kind, path in targets:
        if not path:
            continue
        path = D.endpoint_url(s, token, path, cache)
        for x in q[kind]:
            try:
                if kind in ("quotes", "orders"):
                    D.send_doc(db, s, token, x, path)
                    ok += 1
                    continue
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
    token = D.access_token(s)
    company = D.api_call(s, token, "")
    ep = D.endpoint_url(s, token, s["dynamics"]["ep"].get("customers") or "customers")
    b = D.api_call(s, token, ep + ("&" if "?" in ep else "?") + "$top=1")
    return {"ok": True, "rows": len(b.get("value", [])), "company": company.get("name") or company.get("displayName") or ""}
