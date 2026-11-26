"""Masters. Downloaded from Dynamics (see integration) and read-only here, except new customers and prospects:
added here, approved by a manager when a sales rep adds them, then created in Business Central (its number replaces
the temporary NEW- code)."""
import re
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Charge, Customer, HsnCode, Material, Payment, Price, SalesDoc, User, UserCustomer
from ..security import can_approve_for, current_user, customers_for, may_use_customer, require
from ..services import dynamics as D
from ..services.calc import doc_due, gst_of, order_paid, outstanding, pay_status, price_for
from ..services.common import STATES, f, get_or_404, get_settings, iso_utc, local_today, log, now_utc

router = APIRouter(prefix="/api", tags=["masters"])


def cust_out(db: Session, c: Customer, full=False) -> dict:
    out = {"id": c.id, "code": c.code, "name": c.name, "gstin": c.gstin, "state": c.state, "state_name": STATES.get(c.state, ""),
           "city": c.city, "price_group": c.price_group, "credit_limit": f(c.credit_limit), "blocked": c.blocked,
           "lat": f(c.lat), "lng": f(c.lng), "outstanding": outstanding(db, c),
           "kind": c.kind or "customer", "status": c.status or "active", "added": c.created_by is not None,
           "sync": {"status": c.sync_status, "error": c.sync_error, "at": iso_utc(c.sync_at)} if c.created_by is not None else None}
    if full:
        by = db.get(User, c.created_by) if c.created_by else None
        out.update(address=c.address, pin=c.pin, phone=c.phone, email=c.email, terms=c.terms, balance=f(c.balance), contact=c.contact or "",
                   balance_at=iso_utc(c.balance_at), synced_at=iso_utc(c.synced_at), created_by=by.name if by else "",
                   created_at=iso_utc(c.created_at), reject_reason=c.reject_reason or "")
    return out


def can_decide(db: Session, me: User, c: Customer) -> bool:
    return c.status == "pending" and can_approve_for(db, me, c.created_by or me.id)


def in_dynamics_yet(c: Customer) -> bool:
    return c.created_by is None or c.sync_status == "synced"


@router.get("/customers")
def customers(q: str = "", view: str = "", db: Session = Depends(get_db), me: User = Depends(current_user)):
    """view: "" every usable customer (for quotations, orders and payments: approved and in Dynamics), "all" the list
    for the Customers page (also prospects and new ones waiting), "pending" the ones waiting for my approval."""
    rows = customers_for(db, me) if me.role == "rep" else list(db.scalars(select(Customer).order_by(Customer.name)))
    if me.role == "rep":     # a rep's own new customers, also when the rep has assigned customers
        mine = {c.id for c in rows}
        rows += [c for c in db.scalars(select(Customer).where(Customer.created_by == me.id).order_by(Customer.name)) if c.id not in mine]
    if view == "pending":
        rows = [c for c in rows if can_decide(db, me, c)]
    elif view != "all":
        rows = [c for c in rows if (c.status or "active") == "active" and in_dynamics_yet(c)]
    else:
        rows = [c for c in rows if c.status != "rejected" or c.created_by == me.id or me.role != "rep"]
    q = q.lower().strip()
    if q:
        rows = [c for c in rows if q in f"{c.code} {c.name} {c.city} {c.gstin} {c.phone}".lower()]
    return [cust_out(db, c) for c in rows[:1000]]


class CustIn(BaseModel):
    kind: str = "customer"
    name: str
    contact: str = ""
    address: str = ""
    city: str = ""
    pin: str = ""
    state: str = ""
    gstin: str = ""
    phone: str = ""
    email: str = ""
    price_group: str = ""
    terms: str = ""


GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def _fill(db: Session, c: Customer, b: CustIn) -> None:
    name, gstin = b.name.strip(), re.sub(r"\s", "", b.gstin).upper()
    if b.kind not in ("customer", "prospect"):
        raise HTTPException(422, "Choose customer or prospect.")
    if len(name) < 3:
        raise HTTPException(422, "Enter the customer's name.")
    if gstin and not GSTIN_RE.match(gstin):
        raise HTTPException(422, "That GSTIN is not valid (15 characters, like 09AAACL1234F1Z5).")
    state = gstin[:2] if gstin else b.state.strip()
    if state not in STATES:
        raise HTTPException(422, "Choose the state.")
    phone = re.sub(r"[^\d+]", "", b.phone)
    if b.phone.strip() and len(re.sub(r"\D", "", phone)) < 10:
        raise HTTPException(422, "Enter a 10-digit phone number.")
    if not phone and not gstin:
        raise HTTPException(422, "Enter a phone number or the GSTIN.")
    if b.email.strip() and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", b.email.strip()):
        raise HTTPException(422, "That e-mail address is not valid.")
    if b.pin.strip() and not re.fullmatch(r"\d{6}", b.pin.strip()):
        raise HTTPException(422, "The PIN code has 6 digits.")
    dupe = [x for x in db.scalars(select(Customer).where(Customer.id != (c.id or 0), or_(Customer.status.is_(None), Customer.status != "rejected")))
            if (gstin and x.gstin == gstin) or (phone and x.phone and re.sub(r"\D", "", x.phone)[-10:] == re.sub(r"\D", "", phone)[-10:])]
    if dupe:
        x = dupe[0]
        raise HTTPException(409, f"{x.name} ({x.code}) already has this {'GSTIN' if gstin and x.gstin == gstin else 'phone number'}.")
    c.kind, c.name, c.contact, c.gstin, c.state = b.kind, name[:160], b.contact.strip()[:80], gstin, state
    c.address, c.city, c.pin, c.phone, c.email = b.address.strip()[:250], b.city.strip()[:80], b.pin.strip(), phone[:40], b.email.strip()[:120]
    c.price_group, c.terms = b.price_group.strip()[:40], b.terms.strip()[:40]


def _go(db: Session, bg: BackgroundTasks, c: Customer, me: User) -> None:
    """Approved: into the Dynamics queue, and sent now when automatic sending is on."""
    c.status, c.decided_by, c.reject_reason, c.sync_status, c.sync_error = "active", me.id, None, "pending", None
    db.commit()
    bg.add_task(D.auto_send_customer, c.id)


@router.post("/customers")
def add_customer(b: CustIn, bg: BackgroundTasks, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = Customer(code=f"NEW-{now_utc().strftime('%y%m%d%H%M%S%f')}", created_by=me.id, created_at=now_utc(), synced_at=now_utc(), balance_at=now_utc())
    _fill(db, c, b)
    c.status = "pending"
    db.add(c)
    db.flush()
    c.code = f"NEW-{c.id:05d}"
    if me.role == "rep" and me.customers:            # so the rep, who sees only assigned customers, sees this one
        db.add(UserCustomer(user_id=me.id, customer_id=c.id))
    if can_approve_for(db, me, me.id) or me.role in ("admin", "manager"):
        _go(db, bg, c, me)
    else:
        db.commit()
    return cust_out(db, c, True)


def _mine(db: Session, me: User, cid: int) -> Customer:
    c = get_or_404(db, Customer, cid, "customer")
    if c.created_by is None:
        raise HTTPException(422, "Customers from Dynamics are changed in Dynamics.")
    if c.sync_status == "synced":
        raise HTTPException(422, "This customer is in Dynamics now; change it there.")
    if c.created_by != me.id and me.role not in ("admin", "manager"):
        raise HTTPException(403, "Only who added this customer, or a manager, can change it.")
    return c


@router.put("/customers/{cid}")
def edit_customer(cid: int, b: CustIn, bg: BackgroundTasks, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = _mine(db, me, cid)
    _fill(db, c, b)
    if c.status == "rejected":                       # changed after a rejection: asks again
        c.status, c.reject_reason = "pending", None
    if c.status == "active":
        _go(db, bg, c, me)
    else:
        db.commit()
    return cust_out(db, c, True)


@router.post("/customers/{cid}/approve")
def approve_customer(cid: int, bg: BackgroundTasks, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = get_or_404(db, Customer, cid, "customer")
    if not can_decide(db, me, c):
        raise HTTPException(403, "You cannot approve this customer.")
    _go(db, bg, c, me)
    return cust_out(db, c, True)


class RejectIn(BaseModel):
    reason: str


@router.post("/customers/{cid}/reject")
def reject_customer(cid: int, b: RejectIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = get_or_404(db, Customer, cid, "customer")
    if not can_decide(db, me, c):
        raise HTTPException(403, "You cannot reject this customer.")
    if not b.reason.strip():
        raise HTTPException(422, "Give the reason, for who added it.")
    c.status, c.decided_by, c.reject_reason = "rejected", me.id, b.reason.strip()[:200]
    db.commit()
    return cust_out(db, c, True)


@router.post("/customers/{cid}/send")
def send_customer(cid: int, db: Session = Depends(get_db), me: User = Depends(require("admin", "manager"))):
    """Creates the approved customer in Business Central now (again after an error)."""
    c = get_or_404(db, Customer, cid, "customer")
    if c.status != "active" or c.sync_status not in ("pending", "error"):
        raise HTTPException(422, "Only an approved customer that is not in Dynamics yet can be sent.")
    s = get_settings(db)
    try:
        no = D.push_customer(db, s, D.access_token(s), c)
        log(db, "out", "Customer", 1, "ok", f"{c.name}: created in Dynamics as {no}", me)
    except HTTPException as e:
        log(db, "out", "Customer", 0, "error", f"{c.name}: {e.detail}", me)
        db.commit()
        raise
    db.commit()
    return cust_out(db, c, True)


@router.post("/customers/{cid}/convert")
def prospect_to_customer(cid: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """A prospect that has started buying is a customer (here only; in Dynamics it is a customer already)."""
    c = get_or_404(db, Customer, cid, "customer")
    if not may_use_customer(db, me, c) and c.created_by != me.id:
        raise HTTPException(403, "This customer is not assigned to you.")
    c.kind = "customer"
    db.commit()
    return cust_out(db, c, True)


@router.get("/customers/{cid}")
def customer(cid: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = get_or_404(db, Customer, cid, "customer")
    if not may_use_customer(db, me, c) and c.created_by != me.id:
        raise HTTPException(403, "This customer is not assigned to you.")
    docs = db.scalars(select(SalesDoc).where(SalesDoc.customer_id == c.id).order_by(SalesDoc.id.desc()).limit(10))
    pays = db.scalars(select(Payment).where(Payment.customer_id == c.id).order_by(Payment.id.desc()).limit(6))
    reps = [u.name for u in db.scalars(select(User).where(User.role == "rep")) if any(x.customer_id == c.id for x in u.customers)]
    return {**cust_out(db, c, True), "reps": reps, "can_decide": can_decide(db, me, c),
            "can_edit": c.created_by is not None and c.sync_status != "synced" and (c.created_by == me.id or me.role in ("admin", "manager")),
            "can_send": me.role in ("admin", "manager") and c.status == "active" and c.sync_status in ("pending", "error"),
            "usable": (c.status or "active") == "active" and in_dynamics_yet(c),
            "docs": [{"id": d.id, "kind": d.kind, "no": d.no, "date": d.doc_date.isoformat(), "status": d.status, "total": f(d.total)} for d in docs],
            "payments": [{"id": p.id, "no": p.no, "date": p.pay_date.isoformat(), "mode": p.mode, "amount": f(p.amount), "cancelled": p.cancelled} for p in pays]}


class TagIn(BaseModel):
    lat: float
    lng: float


@router.post("/customers/{cid}/tag")
def tag(cid: int, body: TagIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Saves the visit location (portal only; the customer in Dynamics is not changed)."""
    c = get_or_404(db, Customer, cid, "customer")
    if not may_use_customer(db, me, c):
        raise HTTPException(403, "This customer is not assigned to you.")
    if not (-90 <= body.lat <= 90 and -180 <= body.lng <= 180):
        raise HTTPException(422, "That is not a valid location.")
    c.lat, c.lng, c.tagged_by, c.tagged_at = body.lat, body.lng, me.id, now_utc()
    db.commit()
    return cust_out(db, c)


@router.get("/customers/{cid}/open-orders")
def open_orders(cid: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """What a payment can be allocated to: unpaid invoices first (oldest first), then orders not yet invoiced (advances)."""
    c = get_or_404(db, Customer, cid, "customer")
    rows = db.scalars(select(SalesDoc).where(SalesDoc.customer_id == c.id, or_(and_(SalesDoc.kind == "inv", SalesDoc.status == "open"),
                                             and_(SalesDoc.kind == "order", SalesDoc.status.in_(["submitted", "approved"]))))
                      .order_by(SalesDoc.doc_date, SalesDoc.id))
    out = []
    for o in rows:
        due = doc_due(db, o)
        if due > 0.004:
            out.append({"id": o.id, "no": o.no, "kind": o.kind, "date": o.doc_date.isoformat(), "total": f(o.total), "due": due,
                        "due_date": o.valid_to.isoformat() if o.kind == "inv" and o.valid_to else None,
                        "pay": pay_status(db, o) if o.kind == "inv" else None})
    out.sort(key=lambda x: (x["kind"] != "inv", x["date"]))
    return {"customer": cust_out(db, c), "orders": out}


@router.get("/materials")
def materials(q: str = "", db: Session = Depends(get_db), _=Depends(current_user)):
    rows = db.scalars(select(Material).order_by(Material.code))
    q = q.lower().strip()
    out = []
    for m in rows:
        attrs = {a.name: a.value for a in m.attributes}
        if q and q not in f"{m.code} {m.name} {m.hsn} {' '.join(attrs.values())}".lower():
            continue
        gst, cess = gst_of(db, m)
        base = price_for(db, None, m.code, 1, local_today())
        out.append({"id": m.id, "code": m.code, "name": m.name, "uom": m.uom, "hsn": m.hsn, "blocked": m.blocked, "attrs": attrs,
                    "gst": gst, "cess": cess, "hsn_known": bool(m.hsn and db.get(HsnCode, m.hsn)), "base_price": f(base.price) if base else None})
    return out


@router.get("/prices")
def prices(group: str = "", db: Session = Depends(get_db), _=Depends(require("admin", "manager"))):
    q = select(Price).order_by(Price.type, Price.code, Price.material_code)
    if group == "*all":
        q = q.where(Price.type == "all")
    elif group:
        q = q.where(Price.code == group)
    names = {m.code: m.name for m in db.scalars(select(Material))}
    return [{"id": p.id, "type": p.type, "code": p.code, "material": p.material_code, "name": names.get(p.material_code, ""), "uom": p.uom,
             "price": f(p.price), "min_qty": f(p.min_qty), "from": p.valid_from.isoformat() if p.valid_from else None,
             "to": p.valid_to.isoformat() if p.valid_to else None} for p in db.scalars(q.limit(2000))]


@router.get("/price-groups")
def price_groups(db: Session = Depends(get_db), _=Depends(current_user)):
    g = set(db.scalars(select(Customer.price_group))) | set(db.scalars(select(Price.code).where(Price.type == "group")))
    return sorted(x for x in g if x)


@router.get("/hsn")
def hsn(db: Session = Depends(get_db), _=Depends(current_user)):
    used = {}
    for m in db.scalars(select(Material)):
        used[m.hsn] = used.get(m.hsn, 0) + 1
    rows = list(db.scalars(select(HsnCode).order_by(HsnCode.code)))
    known = {h.code for h in rows}
    return {"codes": [{"code": h.code, "description": h.description, "rate": f(h.rate), "cess": f(h.cess), "materials": used.get(h.code, 0)} for h in rows],
            "materials_without_hsn": sum(n for k, n in used.items() if k not in known)}


@router.get("/charges")
def charges(db: Session = Depends(get_db), _=Depends(current_user)):
    return [{"code": c.code, "name": c.name, "calc": c.calc, "value": f(c.value), "sign": c.sign, "stage": c.stage, "auto": c.auto, "active": c.active}
            for c in db.scalars(select(Charge).order_by(Charge.id))]
