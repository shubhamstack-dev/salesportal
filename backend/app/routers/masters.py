"""Masters, read-only. They are written only by the Dynamics download (see integration)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Charge, Customer, HsnCode, Material, Payment, Price, SalesDoc, User
from ..security import current_user, customers_for, may_use_customer, require
from ..services.calc import gst_of, order_paid, outstanding, price_for
from ..services.common import STATES, f, get_or_404, iso_utc, local_today, now_utc

router = APIRouter(prefix="/api", tags=["masters"])


def cust_out(db: Session, c: Customer, full=False) -> dict:
    out = {"id": c.id, "code": c.code, "name": c.name, "gstin": c.gstin, "state": c.state, "state_name": STATES.get(c.state, ""),
           "city": c.city, "price_group": c.price_group, "credit_limit": f(c.credit_limit), "blocked": c.blocked,
           "lat": f(c.lat), "lng": f(c.lng), "outstanding": outstanding(db, c)}
    if full:
        out.update(address=c.address, pin=c.pin, phone=c.phone, email=c.email, terms=c.terms, balance=f(c.balance),
                   balance_at=iso_utc(c.balance_at), synced_at=iso_utc(c.synced_at))
    return out


@router.get("/customers")
def customers(q: str = "", db: Session = Depends(get_db), me: User = Depends(current_user)):
    rows = customers_for(db, me) if me.role == "rep" else list(db.scalars(select(Customer).order_by(Customer.name)))
    q = q.lower().strip()
    if q:
        rows = [c for c in rows if q in f"{c.code} {c.name} {c.city} {c.gstin}".lower()]
    return [cust_out(db, c) for c in rows[:1000]]


@router.get("/customers/{cid}")
def customer(cid: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = get_or_404(db, Customer, cid, "customer")
    if not may_use_customer(db, me, c):
        raise HTTPException(403, "This customer is not assigned to you.")
    docs = db.scalars(select(SalesDoc).where(SalesDoc.customer_id == c.id).order_by(SalesDoc.id.desc()).limit(10))
    pays = db.scalars(select(Payment).where(Payment.customer_id == c.id).order_by(Payment.id.desc()).limit(6))
    reps = [u.name for u in db.scalars(select(User).where(User.role == "rep")) if any(x.customer_id == c.id for x in u.customers)]
    return {**cust_out(db, c, True), "reps": reps,
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
    c = get_or_404(db, Customer, cid, "customer")
    rows = db.scalars(select(SalesDoc).where(SalesDoc.customer_id == c.id, SalesDoc.kind == "order",
                                             SalesDoc.status.in_(["submitted", "approved"])).order_by(SalesDoc.doc_date, SalesDoc.id))
    out = []
    for o in rows:
        due = round(float(o.total) - order_paid(db, o.id), 2)
        if due > 0:
            out.append({"id": o.id, "no": o.no, "date": o.doc_date.isoformat(), "total": f(o.total), "due": due})
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
