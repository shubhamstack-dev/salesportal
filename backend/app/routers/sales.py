"""Quotations, sales orders and payments. Prices and taxes are always worked out here, never trusted from the device."""
import re
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Customer, Material, Payment, PaymentAllocation, SalesDoc, SalesDocLine, User
from ..security import current_user, may_use_customer, visible_user_ids
from ..services.dynamics import STATE_ABBR, auto_send, post_invoice
from ..services.calc import (build_lines, compute_totals, doc_due, haversine_m, invoiced_qty, invoices_of, order_paid, outstanding,
                             pay_status)
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
    if c.status == "pending":
        raise HTTPException(422, f"{c.name} is a new customer waiting for a manager's approval.")
    if c.status == "rejected":
        raise HTTPException(422, f"{c.name} was not approved: {c.reject_reason}")
    if c.created_by is not None and c.sync_status != "synced":
        raise HTTPException(422, f"{c.name} is not in Dynamics yet, so it has no customer number there. "
                                 + (f"Sending it failed: {c.sync_error}" if c.sync_status == "error" else "It is being sent; try again in a minute."))
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


def _print_extra(db: Session, code: str) -> dict:
    """MRP and pack size of the material, for the Pkts. and MRP columns of the printed document."""
    m = db.scalar(select(Material).where(Material.code == code))
    return {"mrp": f(m.mrp) if m and m.mrp else 0, "pack_qty": f(m.pack_qty) if m and m.pack_qty else 0}


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
                   distance_m=dist, created_at=iso_utc(d.created_at), paid=order_paid(db, d.id) if d.kind in ("order", "inv") else None,
                   customer_detail={"code": c.code, "name": c.name, "gstin": c.gstin, "state": STATES.get(c.state, ""), "state_code": c.state,
                                    "address": ", ".join(x for x in [c.address, c.city, c.pin] if x), "street": c.address, "city": c.city,
                                    "pin": c.pin, "phone": c.phone, "email": c.email, "terms": c.terms, "price_group": c.price_group,
                                    "state_abbr": next((k for k, v in STATE_ABBR.items() if v == c.state), c.state)},
                   rep_code=rep.emp_code if rep else "", delivery_text=d.delivery_date.isoformat() if d.delivery_date else None,
                   lines=[{"material": l.material_code, "name": l.name, "uom": l.uom, "hsn": l.hsn, "qty": f(l.qty), "price": f(l.price),
                           "disc": f(l.disc), "gst_rate": f(l.gst_rate), "taxable": f(l.taxable), "gst": f(l.gst), "price_source": l.price_source,
                           "price_incl": bool(l.price_incl), "line_id": l.id, **_print_extra(db, l.material_code)} for l in d.lines])
        if d.kind == "order":
            done = invoiced_qty(db, d)
            for l, o in zip(d.lines, out["lines"]):
                o["invoiced"] = done.get(l.id, 0)
                o["to_invoice"] = round(max(0.0, float(l.qty) - done.get(l.id, 0)), 4)
            out["invoices"] = [{"id": i.id, "no": i.no, "date": i.doc_date.isoformat(), "total": f(i.total), "pay": pay_status(db, i), "dyn": i.sync_no}
                               for i in invoices_of(db, d.id)]
        if d.kind == "inv":
            o = db.get(SalesDoc, d.order_id) if d.order_id else None
            out.update(order_no=o.no if o else None, order_id=d.order_id, due_date=d.valid_to.isoformat() if d.valid_to else None,
                       quote_no=(db.get(SalesDoc, o.quote_id).no if o and o.quote_id else None),
                       payments=[{"id": p.id, "no": p.no, "date": p.pay_date.isoformat(), "mode": MODES[p.mode], "amount": f(a.amount)}
                                 for a, p in db.execute(select(PaymentAllocation, Payment).join(Payment, Payment.id == PaymentAllocation.payment_id)
                                                        .where(PaymentAllocation.order_id == d.id, Payment.cancelled.is_(False)))])
    if d.kind == "inv" and full and d.status == "open":
        out["on_account"] = r2(sum(unallocated(p) for p in on_account(db, d.customer_id)))
    if d.kind == "inv":
        if "order_no" not in out:
            o = db.get(SalesDoc, d.order_id) if d.order_id else None
            out["order_no"] = o.no if o else None
        out.update(due=doc_due(db, d) if d.status != "cancelled" else 0, pay=pay_status(db, d),
                   due_date=d.valid_to.isoformat() if d.valid_to else None, paid=order_paid(db, d.id))
    if d.kind == "order" and d.status == "approved":
        billed = invoices_of(db, d.id)
        left = any(float(l.qty) - invoiced_qty(db, d).get(l.id, 0) > 0.0001 for l in d.lines) if billed else True
        out["invoiced"] = "" if not billed else ("partial" if left else "full")
    return out


def _editable(db: Session, d: SalesDoc, me: User) -> bool:
    if d.kind == "inv":
        return False
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
                            gst=l["gst"], price_source=l["price_source"], price_incl=l["price_incl"]) for i, l in enumerate(lines)]
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


def _queue_send(db: Session, d: SalesDoc, tasks: BackgroundTasks) -> None:
    """With automatic sending on, a saved quotation or approved order goes to Dynamics right after the reply."""
    dyn = get_settings(db)["dynamics"]
    if d.sync_status == "pending" and dyn.get("auto_push") and dyn["ep"].get("quotes" if d.kind == "quote" else "orders"):
        tasks.add_task(auto_send, d.id)


@router.post("/docs")
def create_doc(body: DocIn, tasks: BackgroundTasks, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = _save(db, None, body, me)
    _queue_send(db, d, tasks)
    return doc_out(db, d, True)


@router.put("/docs/{doc_id}")
def update_doc(doc_id: int, body: DocIn, tasks: BackgroundTasks, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = get_or_404(db, SalesDoc, doc_id, "document")
    if d.kind != body.kind or not _editable(db, d, me):
        raise HTTPException(409, "This document can no longer be changed.")
    d = _save(db, d, body, me)
    _queue_send(db, d, tasks)
    return doc_out(db, d, True)


@router.get("/docs")
def list_docs(kind: str, status: str = "", sync: str = "", date_from: str = "", date_to: str = "", pay: str = "",
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
    rows = [doc_out(db, d) for d in db.scalars(q.order_by(SalesDoc.id.desc()).limit(500))]
    if kind == "inv" and pay:
        rows = [r for r in rows if r["pay"] == pay or (pay == "due" and r["pay"] in ("unpaid", "partly", "overdue"))]
    return rows


@router.get("/docs/{doc_id}")
def get_doc(doc_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = get_or_404(db, SalesDoc, doc_id, "document")
    if d.rep_id not in visible_user_ids(db, me):
        raise HTTPException(403, "You cannot see this document.")
    out = doc_out(db, d, True)
    out["editable"] = _editable(db, d, me)
    out["can_approve"] = d.kind == "order" and d.status == "submitted" and me.role in ("admin", "manager")
    out["can_cancel"] = d.status not in ("cancelled", "converted") and d.sync_status != "synced" and (d.rep_id == me.id or me.role != "rep")
    if d.kind == "inv":
        out["can_cancel"] = d.status == "open" and me.role in ("admin", "manager") and order_paid(db, d.id) == 0 and d.sync_status != "synced"
        out["can_post"] = d.status == "open" and me.role in ("admin", "manager") and d.sync_status in ("na", "error")
    if d.kind == "order":
        out["can_cancel"] = out["can_cancel"] and not invoices_of(db, d.id)
        out["can_invoice"] = d.status == "approved" and me.role in ("admin", "manager") and any(l["to_invoice"] > 0 for l in out["lines"])
    return out


@router.post("/docs/{doc_id}/approve")
def approve(doc_id: int, tasks: BackgroundTasks, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = get_or_404(db, SalesDoc, doc_id, "document")
    if me.role not in ("admin", "manager") or d.rep_id not in visible_user_ids(db, me):
        raise HTTPException(403, "Only a manager or administrator can approve orders.")
    if d.kind != "order" or d.status != "submitted":
        raise HTTPException(409, "Only orders waiting for approval can be approved.")
    d.status, d.approved_by, d.approved_at, d.sync_status = "approved", me.id, now_utc(), "pending"
    db.commit()
    _queue_send(db, d, tasks)
    return doc_out(db, d, True)


class InvLineIn(BaseModel):
    line_id: int
    qty: float


class InvoiceIn(BaseModel):
    date: str | None = None
    due_date: str | None = None
    remarks: str = ""
    lines: list[InvLineIn] | None = None        # None: everything not yet invoiced


def _terms_days(terms: str) -> int:
    """Credit days from a payment terms code such as 30D, NET 15 or 45 DAYS; 0 for cash or none."""
    m = re.search(r"(\d{1,3})", terms or "")
    return int(m[1]) if m else 0


@router.post("/docs/{doc_id}/invoice")
def make_invoice(doc_id: int, body: InvoiceIn, tasks: BackgroundTasks, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Bills an approved sales order, wholly or in part. Prices, discounts and GST are the order's; each line can be
    invoiced in more than one go until its quantity is used. Advances received on the order move to the invoice."""
    o = get_or_404(db, SalesDoc, doc_id, "order")
    if me.role not in ("admin", "manager") or o.rep_id not in visible_user_ids(db, me):
        raise HTTPException(403, "Only a manager or administrator can make invoices.")
    if o.kind != "order" or o.status != "approved":
        raise HTTPException(409, "Only approved sales orders can be invoiced.")
    c = db.get(Customer, o.customer_id)
    on = parse_date(body.date, "Invoice date") or local_today()
    if on > local_today():
        raise HTTPException(422, "The invoice date cannot be in the future.")
    if on < o.doc_date:
        raise HTTPException(422, "The invoice date is before the order date.")
    done = invoiced_qty(db, o)
    want = {x.line_id: x.qty for x in body.lines} if body.lines is not None else None
    if want and not set(want) <= {l.id for l in o.lines}:
        raise HTTPException(422, "A line is not on this order.")
    lines = []
    for l in o.lines:
        left = round(float(l.qty) - done.get(l.id, 0), 4)
        q = round(float(want.get(l.id, 0) if want is not None else left), 4)
        if q <= 0:
            continue
        if q > left + 0.0001:
            raise HTTPException(422, f"{l.material_code}: only {left:g} {l.uom} is left to invoice.")
        if abs(q - left) < 0.0001:      # last part of the line: what is left of the order's amount, so the parts add up exactly
            billed = sum(float(x.taxable) for i in invoices_of(db, o.id) for x in i.lines if x.src_line_id == l.id)
            taxable = r2(float(l.taxable) - billed)
        else:
            taxable = r2(float(l.taxable) * q / float(l.qty))
        lines.append({"src": l, "qty": q, "taxable": taxable, "gst": r2(taxable * float(l.gst_rate) / 100),
                      "cess": r2(taxable * float(l.cess_rate or 0) / 100)})
    if not lines:
        raise HTTPException(422, "Nothing is left to invoice on this order." if want is None else "Enter a quantity to invoice.")
    totals = compute_totals(db, c, lines, o.chosen_charges)
    due = parse_date(body.due_date, "Due date") or add_days(on, _terms_days(c.terms))
    if due < on:
        raise HTTPException(422, "The due date is before the invoice date.")
    inv = SalesDoc(kind="inv", no=next_no(db, "invoice", on), customer_id=o.customer_id, rep_id=o.rep_id, doc_date=on, valid_to=due,
                   delivery_date=o.delivery_date, po_ref=o.po_ref, remarks=(body.remarks.strip() or o.remarks)[:500], status="open",
                   chosen_charges=list(o.chosen_charges or []), totals=totals, total=totals["total"], order_id=o.id, quote_id=None,
                   approved_by=me.id, approved_at=now_utc(), sync_status="na", updated_at=now_utc(),
                   lines=[SalesDocLine(line_no=i + 1, material_code=x["src"].material_code, name=x["src"].name, uom=x["src"].uom, hsn=x["src"].hsn,
                                       qty=x["qty"], price=x["src"].price, disc=x["src"].disc, gst_rate=x["src"].gst_rate, cess_rate=x["src"].cess_rate,
                                       taxable=x["taxable"], gst=x["gst"], price_source=x["src"].price_source, price_incl=x["src"].price_incl,
                                       src_line_id=x["src"].id) for i, x in enumerate(lines)])
    db.add(inv)
    db.flush()
    # advances received on the order now pay this invoice, oldest first
    room = float(inv.total)
    for a, p in db.execute(select(PaymentAllocation, Payment).join(Payment, Payment.id == PaymentAllocation.payment_id)
                           .where(PaymentAllocation.order_id == o.id, Payment.cancelled.is_(False)).order_by(Payment.pay_date, Payment.id)).all():
        if room <= 0.004:
            break
        take = r2(min(float(a.amount), room))
        if take >= float(a.amount) - 0.004:
            a.order_id = inv.id
        else:
            a.amount = r2(float(a.amount) - take)
            db.add(PaymentAllocation(payment_id=p.id, order_id=inv.id, amount=take))
        room = r2(room - take)
    if get_settings(db)["dynamics"].get("post_invoices"):     # post the order in Business Central right after the reply
        inv.sync_status = "pending"
        tasks.add_task(post_invoice, inv.id)
    db.commit()
    return doc_out(db, inv, True)


@router.post("/docs/{doc_id}/post-dynamics")
def post_in_dynamics(doc_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Posts (again) the invoice's sales order in Business Central, for an invoice that failed or was made before
    posting was turned on. Runs now, so the answer shows the result."""
    inv = get_or_404(db, SalesDoc, doc_id, "invoice")
    if me.role not in ("admin", "manager"):
        raise HTTPException(403, "Only a manager or administrator can post invoices.")
    if inv.kind != "inv" or inv.status != "open":
        raise HTTPException(409, "Only open invoices can be posted.")
    if inv.sync_status == "synced":
        raise HTTPException(409, f"Already posted in Dynamics as {inv.sync_no}.")
    inv.sync_status, inv.sync_error = "pending", None
    db.commit()
    post_invoice(inv.id)
    db.expire_all()
    return doc_out(db, db.get(SalesDoc, doc_id), True)


@router.post("/docs/{doc_id}/cancel")
def cancel(doc_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = get_or_404(db, SalesDoc, doc_id, "document")
    if d.rep_id not in visible_user_ids(db, me) or (me.role == "rep" and d.rep_id != me.id):
        raise HTTPException(403, "You cannot cancel this document.")
    if d.status in ("cancelled", "converted") or d.sync_status == "synced":
        raise HTTPException(409, "This invoice is posted in Dynamics; cancel it there with a sales credit memo." if d.kind == "inv"
                            else "This document can no longer be cancelled here; cancel it in Dynamics.")
    if d.kind == "order" and invoices_of(db, d.id):
        raise HTTPException(409, "This order has invoices. Cancel the invoices first.")
    if d.kind in ("order", "inv") and order_paid(db, d.id) > 0:
        raise HTTPException(409, f"Payments are allocated to this {'invoice' if d.kind == 'inv' else 'order'}. Cancel those receipts first.")
    if d.kind == "inv" and me.role not in ("admin", "manager"):
        raise HTTPException(403, "Only a manager or administrator can cancel invoices.")
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
           "cancelled": p.cancelled, "unallocated": unallocated(p),
           "sync": {"status": p.sync_status, "label": SYNC_LABEL[p.sync_status], "no": p.sync_no, "error": p.sync_error}}
    if full:
        out.update(bank=p.bank, cheque_date=p.cheque_date.isoformat() if p.cheque_date else None, remarks=p.remarks,
                   loc={"lat": f(p.lat), "lng": f(p.lng)} if p.lat is not None else None,
                   allocations=[{"order_id": a.order_id, "order_no": db.get(SalesDoc, a.order_id).no, "amount": f(a.amount),
                                 "kind": db.get(SalesDoc, a.order_id).kind} for a in p.allocations])
    return out


def _check_allocs(db: Session, c: Customer, given: list, room: float) -> list:
    allocs = [a for a in given if a.amount > 0]
    if r2(sum(a.amount for a in allocs)) > room + 0.001:
        raise HTTPException(422, "Allocations add up to more than the amount received." if room > 0 else "Nothing of this receipt is left to allocate.")
    for a in allocs:
        o = db.get(SalesDoc, a.order_id)
        ok = o and o.customer_id == c.id and ((o.kind == "inv" and o.status == "open") or (o.kind == "order" and o.status in ("submitted", "approved")))
        if not ok:
            raise HTTPException(422, "An allocation is to an invoice or order that is not open for this customer.")
        due = doc_due(db, o)
        if a.amount > due + 0.001:
            raise HTTPException(422, f"{o.no} has only ₹{max(due, 0):,.2f} due.")
    return allocs


def unallocated(p: Payment) -> float:
    return 0.0 if p.cancelled else r2(float(p.amount) - sum(float(a.amount) for a in p.allocations))


def on_account(db: Session, customer_id: int) -> list[Payment]:
    """The customer's receipts with money not allocated to any invoice or order, oldest first."""
    rows = db.scalars(select(Payment).where(Payment.customer_id == customer_id, Payment.cancelled.is_(False)).order_by(Payment.pay_date, Payment.id))
    return [p for p in rows if unallocated(p) > 0.004]


class AllocateIn(BaseModel):
    allocations: list[AllocIn]


@router.post("/payments/{pid}/allocate")
def allocate_payment(pid: int, body: AllocateIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Allocates the part of a receipt that is still on account (for example to an invoice made later)."""
    p = get_or_404(db, Payment, pid, "payment")
    if p.rep_id not in visible_user_ids(db, me) or (me.role == "rep" and p.rep_id != me.id):
        raise HTTPException(403, "You cannot change this receipt.")
    if p.cancelled:
        raise HTTPException(409, "This receipt is cancelled.")
    allocs = _check_allocs(db, db.get(Customer, p.customer_id), body.allocations, unallocated(p))
    for a in allocs:
        hit = next((x for x in p.allocations if x.order_id == a.order_id), None)
        if hit:
            hit.amount = r2(float(hit.amount) + a.amount)
        else:
            p.allocations.append(PaymentAllocation(order_id=a.order_id, amount=r2(a.amount)))
    db.commit()
    return pay_out(db, p, True)


@router.post("/docs/{doc_id}/apply-on-account")
def apply_on_account(doc_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Pays an invoice from the customer's money on account (receipts not allocated in full), oldest first."""
    d = get_or_404(db, SalesDoc, doc_id, "invoice")
    if d.rep_id not in visible_user_ids(db, me):
        raise HTTPException(403, "You cannot change this invoice.")
    if d.kind != "inv" or d.status != "open":
        raise HTTPException(409, "Only open invoices can be paid.")
    room = doc_due(db, d)
    used = []
    for p in on_account(db, d.customer_id):
        if room <= 0.004:
            break
        take = r2(min(unallocated(p), room))
        hit = next((x for x in p.allocations if x.order_id == d.id), None)
        if hit:
            hit.amount = r2(float(hit.amount) + take)
        else:
            p.allocations.append(PaymentAllocation(order_id=d.id, amount=take))
        room = r2(room - take)
        used.append(p.no)
    if not used:
        raise HTTPException(422, "This customer has no money on account." if room > 0.004 else "Nothing is due on this invoice.")
    db.commit()
    return doc_out(db, d, True)


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
    allocs = _check_allocs(db, c, body.allocations, amount)
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
