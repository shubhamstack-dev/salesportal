"""Quotations, sales orders and payments. Prices and taxes are always worked out here, never trusted from the device."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Customer, Payment, PaymentAllocation, SalesDoc, SalesDocLine, User
from ..security import current_user, may_use_customer, visible_user_ids
from ..services.calc import build_lines, compute_totals, haversine_m, order_paid, outstanding
from ..services.common import (STATES, add_days, f, get_or_404, get_settings, iso_utc, local_today, next_no, now_utc,
                               parse_date, r2)
from ..services.xl import workbook, xlsx_response

router = APIRouter(prefix="/api", tags=["sales"])
SYNC_LABEL = {"na": "—", "pending": "To send", "exported": "Sent by file", "synced": "In Dynamics", "error": "Sync error"}
MODES = {"cash": "Cash", "cheque": "Cheque", "upi": "UPI", "neft": "NEFT / RTGS", "card": "Card"}


class LineIn(BaseModel):
    material: str
    qty: float = 0
    disc: float = 0
    price: float | None = None


class DocIn(BaseModel):
    kind: str
    customer_id: int
    date: str
    delivery: str | None = None
    valid_to: str | None = None
    po_ref: str = ""
    remarks: str = ""
    charges: list[str] = Field(default_factory=list)
    lines: list[LineIn] = Field(default_factory=list)
    submit: bool = True
    quote_id: int | None = None
    lat: float | None = None
    lng: float | None = None


def _customer(db: Session, me: User, cid: int) -> Customer:
    c = get_or_404(db, Customer, cid, "customer")
    if not may_use_customer(db, me, c):
        raise HTTPException(403, "This customer is not assigned to you.")
    return c


def _price(db: Session, body: DocIn, me: User):
    s = get_settings(db)
    c = _customer(db, me, body.customer_id)
    on = parse_date(body.date, "Date") or local_today()
    lines, problems = build_lines(db, c, on, [l.model_dump() for l in body.lines], s["price_override"])
    totals = compute_totals(db, c, lines, body.charges)
    return c, on, lines, problems, totals, s


def _credit(db: Session, c: Customer, total: float, replacing: float = 0) -> dict:
    out = outstanding(db, c)
    after = r2(out + total - replacing)
    limit = float(c.credit_limit or 0)
    return {"outstanding": out, "limit": limit, "after": after, "over": bool(limit and after > limit)}


@router.post("/docs/preview")
def preview(body: DocIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c, on, lines, problems, totals, s = _price(db, body, me)
    return {"lines": lines, "totals": totals, "problems": problems,
            "credit": _credit(db, c, totals["total"]) if body.kind == "order" else None,
            "customer": {"id": c.id, "code": c.code, "name": c.name, "gstin": c.gstin, "state": STATES.get(c.state, ""),
                         "price_group": c.price_group, "intra": totals["intra"]}}


def doc_out(db: Session, d: SalesDoc, full=False) -> dict:
    c = db.get(Customer, d.customer_id)
    rep = db.get(User, d.rep_id)
    expired = d.kind == "quote" and d.status == "open" and d.valid_to and d.valid_to < local_today()
    out = {"id": d.id, "kind": d.kind, "no": d.no, "date": d.doc_date.isoformat(), "customer_id": d.customer_id, "customer": c.name,
           "customer_code": c.code, "rep_id": d.rep_id, "rep": rep.name if rep else "", "status": "expired" if expired else d.status,
           "total": f(d.total), "lines_count": len(d.lines), "sync": {"status": d.sync_status, "label": SYNC_LABEL[d.sync_status],
           "no": d.sync_no, "error": d.sync_error}, "valid_to": d.valid_to.isoformat() if d.valid_to else None}
    if full:
        q = db.get(SalesDoc, d.quote_id) if d.quote_id else None
        conv = db.scalar(select(SalesDoc).where(SalesDoc.quote_id == d.id, SalesDoc.status != "cancelled")) if d.kind == "quote" else None
        dist = round(haversine_m((d.lat, d.lng), (c.lat, c.lng))) if d.lat is not None and c.lat is not None else None
        out.update(delivery=d.delivery_date.isoformat() if d.delivery_date else None, po_ref=d.po_ref, remarks=d.remarks,
                   charges=d.chosen_charges, totals=d.totals, raw_status=d.status, quote_no=q.no if q else None, quote_id=d.quote_id,
                   order_no=conv.no if conv else None, loc={"lat": f(d.lat), "lng": f(d.lng)} if d.lat is not None else None,
                   distance_m=dist, created_at=iso_utc(d.created_at), paid=order_paid(db, d.id) if d.kind == "order" else None,
                   customer_detail={"code": c.code, "name": c.name, "gstin": c.gstin, "state": STATES.get(c.state, ""),
                                    "address": ", ".join(x for x in [c.address, c.city, c.pin] if x)},
                   lines=[{"material": l.material_code, "name": l.name, "uom": l.uom, "hsn": l.hsn, "qty": f(l.qty), "price": f(l.price),
                           "disc": f(l.disc), "gst_rate": f(l.gst_rate), "taxable": f(l.taxable), "gst": f(l.gst), "price_source": l.price_source}
                          for l in d.lines])
    return out


def _editable(db: Session, d: SalesDoc, me: User) -> bool:
    if d.rep_id != me.id and (me.role == "rep" or d.rep_id not in visible_user_ids(db, me)):
        return False
    if d.kind == "order":
        return d.status in ("draft", "submitted")
    return d.status in ("draft", "open") and d.sync_status not in ("exported", "synced")


def _save(db: Session, d: SalesDoc | None, body: DocIn, me: User) -> SalesDoc:
    if body.kind not in ("quote", "order"):
        raise HTTPException(422, "Unknown document type.")
    c, on, lines, problems, totals, s = _price(db, body, me)
    if c.blocked:
        raise HTTPException(422, f"{c.name} is blocked in Dynamics.")
    if not lines:
        raise HTTPException(422, "Add at least one material.")
    if body.submit and problems:
        raise HTTPException(422, problems[0])
    valid_to = parse_date(body.valid_to, "Valid until") if body.kind == "quote" else None
    if body.kind == "quote":
        valid_to = valid_to or add_days(on, int(s["quote_days"]))
        if valid_to < on:
            raise HTTPException(422, "Valid until is before the quotation date.")
    if body.kind == "order" and body.submit and s["credit_check"] == "block":
        cr = _credit(db, c, totals["total"], float(d.total) if d else 0)
        if cr["over"]:
            raise HTTPException(409, f"This order takes {c.name} to ₹{cr['after']:,.0f}, over the credit limit of ₹{cr['limit']:,.0f}.")
    quote = None
    if body.kind == "order" and body.quote_id:
        quote = get_or_404(db, SalesDoc, body.quote_id, "quotation")
        if quote.kind != "quote" or quote.status not in ("open",) or quote.customer_id != c.id:
            raise HTTPException(409, "That quotation cannot be converted (it is not open, or is for another customer).")
    if body.kind == "quote":
        status = "open" if body.submit else "draft"
    else:
        status = "draft" if not body.submit else ("submitted" if s["need_approval"] and me.role == "rep" else "approved")
    if not d:
        d = SalesDoc(kind=body.kind, no=next_no(db, body.kind, on), rep_id=me.id, sync_status="na")
        db.add(d)
    d.customer_id, d.doc_date, d.valid_to = c.id, on, valid_to
    d.delivery_date = parse_date(body.delivery, "Deliver by") if body.kind == "order" else None
    d.po_ref, d.remarks, d.chosen_charges = body.po_ref.strip()[:60], body.remarks.strip()[:500], [x for x in body.charges]
    d.totals, d.total, d.status, d.updated_at = totals, totals["total"], status, now_utc()
    if body.lat is not None and body.lng is not None:
        d.lat, d.lng = body.lat, body.lng
    d.lines = [SalesDocLine(line_no=i + 1, material_code=l["material"], name=l["name"], uom=l["uom"], hsn=l["hsn"], qty=l["qty"],
                            price=l["price"], disc=l["disc"], gst_rate=l["gst_rate"], cess_rate=l["cess_rate"], taxable=l["taxable"],
                            gst=l["gst"], price_source=l["price_source"]) for i, l in enumerate(lines)]
    if (d.kind == "quote" and status == "open") or (d.kind == "order" and status == "approved"):
        d.sync_status, d.sync_error = "pending", None
        if status == "approved":
            d.approved_by, d.approved_at = me.id, now_utc()
    if quote:
        d.quote_id = quote.id
        if body.submit:
            quote.status = "converted"
    db.commit()
    return d


@router.post("/docs")
def create_doc(body: DocIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    return doc_out(db, _save(db, None, body, me), True)


@router.put("/docs/{doc_id}")
def update_doc(doc_id: int, body: DocIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = get_or_404(db, SalesDoc, doc_id, "document")
    if d.kind != body.kind or not _editable(db, d, me):
        raise HTTPException(409, "This document can no longer be changed.")
    return doc_out(db, _save(db, d, body, me), True)


@router.get("/docs")
def list_docs(kind: str, status: str = "", sync: str = "", date_from: str = "", date_to: str = "",
              db: Session = Depends(get_db), me: User = Depends(current_user)):
    q = select(SalesDoc).where(SalesDoc.kind == kind, SalesDoc.rep_id.in_(visible_user_ids(db, me)))
    if status and status != "expired":
        q = q.where(SalesDoc.status == status)
    if status == "expired":
        q = q.where(SalesDoc.status == "open", SalesDoc.valid_to < local_today())
    if sync:
        q = q.where(SalesDoc.sync_status == sync)
    if date_from:
        q = q.where(SalesDoc.doc_date >= parse_date(date_from))
    if date_to:
        q = q.where(SalesDoc.doc_date <= parse_date(date_to))
    return [doc_out(db, d) for d in db.scalars(q.order_by(SalesDoc.id.desc()).limit(500))]


@router.get("/docs/{doc_id}")
def get_doc(doc_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = get_or_404(db, SalesDoc, doc_id, "document")
    if d.rep_id not in visible_user_ids(db, me):
        raise HTTPException(403, "You cannot see this document.")
    out = doc_out(db, d, True)
    out["editable"] = _editable(db, d, me)
    out["can_approve"] = d.kind == "order" and d.status == "submitted" and me.role in ("admin", "manager")
    out["can_cancel"] = d.status not in ("cancelled", "converted") and d.sync_status != "synced" and (d.rep_id == me.id or me.role != "rep")
    return out


@router.post("/docs/{doc_id}/approve")
def approve(doc_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = get_or_404(db, SalesDoc, doc_id, "document")
    if me.role not in ("admin", "manager") or d.rep_id not in visible_user_ids(db, me):
        raise HTTPException(403, "Only a manager or administrator can approve orders.")
    if d.kind != "order" or d.status != "submitted":
        raise HTTPException(409, "Only orders waiting for approval can be approved.")
    d.status, d.approved_by, d.approved_at, d.sync_status = "approved", me.id, now_utc(), "pending"
    db.commit()
    return doc_out(db, d, True)


@router.post("/docs/{doc_id}/cancel")
def cancel(doc_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = get_or_404(db, SalesDoc, doc_id, "document")
    if d.rep_id not in visible_user_ids(db, me) or (me.role == "rep" and d.rep_id != me.id):
        raise HTTPException(403, "You cannot cancel this document.")
    if d.status in ("cancelled", "converted") or d.sync_status == "synced":
        raise HTTPException(409, "This document can no longer be cancelled here; cancel it in Dynamics.")
    if d.kind == "order" and order_paid(db, d.id) > 0:
        raise HTTPException(409, "Payments are allocated to this order. Cancel those receipts first.")
    d.status = "cancelled"
    if d.sync_status != "exported":
        d.sync_status = "na"
    if d.quote_id:
        q = db.get(SalesDoc, d.quote_id)
        if q and q.status == "converted":
            q.status = "open"
    db.commit()
    return doc_out(db, d, True)


@router.get("/docs-export")
def export_docs(kind: str, db: Session = Depends(get_db), me: User = Depends(current_user)):
    docs = list(db.scalars(select(SalesDoc).where(SalesDoc.kind == kind, SalesDoc.rep_id.in_(visible_user_ids(db, me))).order_by(SalesDoc.id)))
    head, lines = [], []
    for d in docs:
        o = doc_out(db, d, True)
        t = d.totals
        head.append({"No": d.no, "Date": o["date"], "Customer code": o["customer_code"], "Customer": o["customer"], "Sales staff": o["rep"],
                     "Taxable": t.get("taxable"), "CGST": t.get("cgst"), "SGST": t.get("sgst"), "IGST": t.get("igst"), "Total": f(d.total),
                     "Status": d.status, "Dynamics": d.sync_no or "", "Sync": SYNC_LABEL[d.sync_status]})
        lines += [{"No": d.no, "Material": l["material"], "Description": l["name"], "HSN": l["hsn"], "UOM": l["uom"], "Qty": l["qty"],
                   "Price": l["price"], "Disc %": l["disc"], "Taxable": l["taxable"], "GST %": l["gst_rate"]} for l in o["lines"]]
    name = "Quotations" if kind == "quote" else "Sales_orders"
    return xlsx_response(workbook({name.replace("_", " "): head, "Lines": lines}), f"{name}.xlsx")


# ------------------------------------------------------------------ payments
class AllocIn(BaseModel):
    order_id: int
    amount: float


class PaymentIn(BaseModel):
    customer_id: int
    date: str
    amount: float
    mode: str
    ref: str = ""
    bank: str = ""
    cheque_date: str | None = None
    remarks: str = ""
    allocations: list[AllocIn] = Field(default_factory=list)
    lat: float | None = None
    lng: float | None = None


def pay_out(db: Session, p: Payment, full=False) -> dict:
    c = db.get(Customer, p.customer_id)
    rep = db.get(User, p.rep_id)
    out = {"id": p.id, "no": p.no, "date": p.pay_date.isoformat(), "customer_id": c.id, "customer": c.name, "customer_code": c.code,
           "rep": rep.name if rep else "", "rep_id": p.rep_id, "amount": f(p.amount), "mode": p.mode, "mode_label": MODES[p.mode], "ref": p.ref,
           "cancelled": p.cancelled, "sync": {"status": p.sync_status, "label": SYNC_LABEL[p.sync_status], "no": p.sync_no, "error": p.sync_error}}
    if full:
        out.update(bank=p.bank, cheque_date=p.cheque_date.isoformat() if p.cheque_date else None, remarks=p.remarks,
                   loc={"lat": f(p.lat), "lng": f(p.lng)} if p.lat is not None else None,
                   allocations=[{"order_id": a.order_id, "order_no": db.get(SalesDoc, a.order_id).no, "amount": f(a.amount)} for a in p.allocations])
    return out


@router.post("/payments")
def create_payment(body: PaymentIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = _customer(db, me, body.customer_id)
    on = parse_date(body.date, "Date") or local_today()
    amount = r2(body.amount)
    if on > local_today():
        raise HTTPException(422, "The payment date cannot be in the future.")
    if amount <= 0:
        raise HTTPException(422, "Enter the amount received.")
    if body.mode not in MODES:
        raise HTTPException(422, "Choose a payment mode.")
    if body.mode == "cheque" and not body.ref.strip():
        raise HTTPException(422, "Enter the cheque number.")
    if body.mode in ("upi", "neft", "card") and not body.ref.strip():
        raise HTTPException(422, "Enter the transaction reference.")
    allocs = [a for a in body.allocations if a.amount > 0]
    if r2(sum(a.amount for a in allocs)) > amount + 0.001:
        raise HTTPException(422, "Allocations add up to more than the amount received.")
    for a in allocs:
        o = db.get(SalesDoc, a.order_id)
        if not o or o.kind != "order" or o.customer_id != c.id or o.status not in ("submitted", "approved"):
            raise HTTPException(422, "An allocation is to an order that is not open for this customer.")
        due = r2(float(o.total) - order_paid(db, o.id))
        if a.amount > due + 0.001:
            raise HTTPException(422, f"{o.no} has only ₹{due:,.2f} due.")
    p = Payment(no=next_no(db, "payment", on), customer_id=c.id, rep_id=me.id, pay_date=on, amount=amount, mode=body.mode,
                ref=body.ref.strip()[:60], bank=body.bank.strip()[:80], cheque_date=parse_date(body.cheque_date, "Cheque date"),
                remarks=body.remarks.strip()[:300], lat=body.lat, lng=body.lng, sync_status="pending",
                allocations=[PaymentAllocation(order_id=a.order_id, amount=r2(a.amount)) for a in allocs])
    db.add(p)
    db.commit()
    return pay_out(db, p, True)


@router.get("/payments")
def list_payments(date_from: str = "", date_to: str = "", db: Session = Depends(get_db), me: User = Depends(current_user)):
    q = select(Payment).where(Payment.rep_id.in_(visible_user_ids(db, me)))
    if date_from:
        q = q.where(Payment.pay_date >= parse_date(date_from))
    if date_to:
        q = q.where(Payment.pay_date <= parse_date(date_to))
    return [pay_out(db, p) for p in db.scalars(q.order_by(Payment.id.desc()).limit(500))]


@router.get("/payments/{pid}")
def get_payment(pid: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    p = get_or_404(db, Payment, pid, "payment")
    if p.rep_id not in visible_user_ids(db, me):
        raise HTTPException(403, "You cannot see this payment.")
    out = pay_out(db, p, True)
    out["can_cancel"] = not p.cancelled and p.sync_status != "synced" and (p.rep_id == me.id or me.role != "rep")
    return out


@router.post("/payments/{pid}/cancel")
def cancel_payment(pid: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    p = get_or_404(db, Payment, pid, "payment")
    if p.rep_id not in visible_user_ids(db, me) or (me.role == "rep" and p.rep_id != me.id):
        raise HTTPException(403, "You cannot cancel this receipt.")
    if p.cancelled or p.sync_status == "synced":
        raise HTTPException(409, "This receipt can no longer be cancelled here; reverse it in Dynamics.")
    p.cancelled = True
    if p.sync_status != "exported":
        p.sync_status = "na"
    db.commit()
    return pay_out(db, p, True)


@router.get("/payments-export")
def export_payments(db: Session = Depends(get_db), me: User = Depends(current_user)):
    rows = [pay_out(db, p, True) for p in db.scalars(select(Payment).where(Payment.rep_id.in_(visible_user_ids(db, me))).order_by(Payment.id))]
    return xlsx_response(workbook({"Payments": [{"Receipt": p["no"], "Date": p["date"], "Customer code": p["customer_code"], "Customer": p["customer"],
        "Mode": p["mode_label"], "Reference": p["ref"], "Bank": p["bank"], "Amount": p["amount"], "Received by": p["rep"],
        "Allocated to": "; ".join(f"{a['order_no']} {a['amount']}" for a in p["allocations"]), "Status": "Cancelled" if p["cancelled"] else p["sync"]["label"],
        "Dynamics": p["sync"]["no"] or ""} for p in rows]}), "Payments.xlsx")
