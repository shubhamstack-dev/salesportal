"""Business rules, worked on the server so every device gets the same answer.

Pricing:  the customer's own price, then its price group, then the price for all customers; within the
          valid dates; the highest minimum quantity not above the ordered quantity.
GST:      from each material's HSN code. Customer in the company's state: CGST + SGST, otherwise IGST.
Charges:  before GST (freight, trade discount) change the taxable value and take GST at the weighted
          rate of the lines; after GST (TCS) are worked on the invoice value.
Expenses: fixed daily allowance x days, variable rate x km, hotel defaulted at grade rate x nights.
Attendance: present / half day / short / absent / weekly off against the shift, and late Time In."""
import math
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (Attendance, Charge, Customer, ExpenseClaim, Grade, HsnCode, Material, Payment, PaymentAllocation,
                      Price, SalesDoc, User)
from .common import add_days, get_settings, local_at, local_today, r2, to_local


# ------------------------------------------------------------------ pricing
def price_for(db: Session, cust: Customer | None, material_code: str, qty: float, on: date) -> Price | None:
    rows = list(db.scalars(select(Price).where(Price.material_code == material_code)))
    rows = [p for p in rows if (not p.valid_from or p.valid_from <= on) and (not p.valid_to or p.valid_to >= on)
            and float(p.min_qty or 0) <= max(qty, 0)]

    def pick(kind, code=""):
        c = [p for p in rows if p.type == kind and (kind == "all" or p.code.lower() == (code or "").lower())]
        return max(c, key=lambda p: float(p.min_qty or 0)) if c else None

    return (cust and pick("customer", cust.code)) or (cust and cust.price_group and pick("group", cust.price_group)) or pick("all")


def price_label(p: Price) -> str:
    return "customer price" if p.type == "customer" else f"{p.code} price" if p.type == "group" else "base price"


def gst_of(db: Session, material: Material) -> tuple[float, float]:
    h = db.get(HsnCode, material.hsn) if material.hsn else None
    return (float(h.rate), float(h.cess)) if h else (0.0, 0.0)


def build_lines(db: Session, cust: Customer | None, on: date, lines_in: list[dict], allow_override: bool) -> tuple[list[dict], list[str]]:
    """Prices and taxes each line from the masters. Returns (lines, problems)."""
    out, problems = [], []
    for i, l in enumerate(lines_in):
        code = str(l.get("material") or "").strip()
        if not code:
            continue
        m = db.scalar(select(Material).where(Material.code == code))
        if not m:
            problems.append(f"Line {i + 1}: material {code} is not in the masters.")
            continue
        if m.blocked:
            problems.append(f"Line {i + 1}: {m.code} is blocked in Dynamics.")
        qty = float(l.get("qty") or 0)
        disc = float(l.get("disc") or 0)
        p = price_for(db, cust, m.code, qty or 1, on)
        price, source = (float(p.price), price_label(p)) if p else (0.0, "")
        if allow_override and l.get("price") not in (None, "") and float(l["price"]) > 0:
            if not p or abs(float(l["price"]) - price) > 0.0001:
                price, source = float(l["price"]), "entered"
        gst, cess = gst_of(db, m)
        taxable = r2(qty * price * (1 - disc / 100))
        if qty <= 0:
            problems.append(f"{m.code}: enter a quantity above zero.")
        if price <= 0:
            problems.append(f"{m.code}: no price in Dynamics for this customer.")
        if disc < 0 or disc >= 100:
            problems.append(f"{m.code}: discount must be from 0 to below 100%.")
        out.append({"material": m.code, "name": m.name, "uom": (p.uom if p and p.uom else m.uom), "hsn": m.hsn, "qty": qty,
                    "price": price, "disc": disc, "gst_rate": gst, "cess_rate": cess, "taxable": taxable,
                    "gst": r2(taxable * gst / 100), "cess": r2(taxable * cess / 100), "price_source": source})
    return out, problems


def compute_totals(db: Session, cust: Customer | None, lines: list[dict], chosen: list[str]) -> dict:
    s = get_settings(db)
    company_state = s["company"]["state"]
    intra = not cust or not cust.state or not company_state or cust.state == company_state
    sub = r2(sum(l["taxable"] for l in lines))
    line_gst = sum(l["gst"] for l in lines)
    avg = (line_gst / sub * 100) if sub else 0
    charges = [c for c in db.scalars(select(Charge).where(Charge.active.is_(True)).order_by(Charge.id)) if c.auto or c.code in (chosen or [])]
    pre = []
    for c in charges:
        if c.stage == "post":
            continue
        amt = r2((float(c.value) if c.calc == "fixed" else sub * float(c.value) / 100) * (-1 if c.sign < 0 else 1))
        pre.append({"code": c.code, "name": c.name, "amount": amt, "gst": r2(amt * avg / 100)})
    taxable = r2(sub + sum(c["amount"] for c in pre))
    gst = r2(line_gst + sum(c["gst"] for c in pre))
    cess = r2(sum(l["cess"] for l in lines))
    invoice = r2(taxable + gst + cess)
    post = [{"code": c.code, "name": c.name, "gst": 0,
             "amount": r2((float(c.value) if c.calc == "fixed" else invoice * float(c.value) / 100) * (-1 if c.sign < 0 else 1))}
            for c in charges if c.stage == "post"]
    before = r2(invoice + sum(c["amount"] for c in post))
    total = float(round(Decimal(str(before)))) if s["round_off"] else before
    half = r2(gst / 2)
    return {"intra": intra, "sub": sub, "pre": pre, "post": post, "taxable": taxable, "gst": gst, "cess": cess,
            "cgst": half if intra else 0, "sgst": r2(gst - half) if intra else 0, "igst": 0 if intra else gst,
            "invoice": invoice, "round_off": r2(total - before), "total": total}


def order_paid(db: Session, order_id: int) -> float:
    v = db.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).join(Payment, Payment.id == PaymentAllocation.payment_id)
                  .where(PaymentAllocation.order_id == order_id, Payment.cancelled.is_(False)))
    return r2(v)


def outstanding(db: Session, cust: Customer) -> float:
    """Dynamics balance at the last download, plus orders placed here since, less payments received since."""
    orders = db.scalar(select(func.coalesce(func.sum(SalesDoc.total), 0)).where(
        SalesDoc.customer_id == cust.id, SalesDoc.kind == "order", SalesDoc.status.in_(["submitted", "approved"]),
        SalesDoc.created_at > cust.balance_at))
    pays = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.customer_id == cust.id, Payment.cancelled.is_(False), Payment.created_at > cust.balance_at))
    return r2(float(cust.balance or 0) + float(orders) - float(pays))


# ------------------------------------------------------------------ expenses
def grade_rates(g: Grade, kind: str) -> dict:
    out = kind == "out"
    return {"da": float(g.da_out if out else g.da_in), "km": float(g.km_out if out else g.km_in), "hotel": float(g.hotel_out if out else g.hotel_in)}


def compute_claim(rates: dict, d_from: date, d_to: date, km: float, nights: int, hotel: float, others: list[dict]) -> dict:
    days = (d_to - d_from).days + 1 if d_from and d_to and d_to >= d_from else 0
    fixed = r2(days * rates["da"])
    variable = r2((km or 0) * rates["km"])
    hotel_policy = r2((nights or 0) * rates["hotel"])
    hotel = r2(hotel or 0)
    other = r2(sum(float(o.get("amount") or 0) for o in others))
    return {"days": days, "fixed": fixed, "variable": variable, "hotel": hotel, "hotel_policy": hotel_policy,
            "hotel_over": r2(hotel - hotel_policy) if hotel > hotel_policy + 0.005 else 0, "other": other,
            "total": r2(fixed + variable + hotel + other)}


def haversine_m(a, b) -> float:
    if None in (a[0], a[1], b[0], b[1]):
        return 0
    R, rad = 6371000, math.pi / 180
    la1, lo1, la2, lo2 = (float(x) * rad for x in (*a, *b))
    x = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def day_points(db: Session, user_id: int, d: date) -> list[tuple]:
    """(utc time, lat, lng, what) for a user's recorded locations on a local date."""
    pts = []
    for a in db.scalars(select(Attendance).where(Attendance.user_id == user_id, Attendance.work_date == d)):
        if a.in_lat is not None:
            pts.append((a.in_at, a.in_lat, a.in_lng, "Time In"))
        if a.out_at and a.out_lat is not None:
            pts.append((a.out_at, a.out_lat, a.out_lng, "Time Out"))
    for doc in db.scalars(select(SalesDoc).where(SalesDoc.rep_id == user_id, SalesDoc.doc_date == d, SalesDoc.lat.is_not(None))):
        pts.append((doc.created_at, doc.lat, doc.lng, ("Quotation " if doc.kind == "quote" else "Order ") + doc.no))
    for p in db.scalars(select(Payment).where(Payment.rep_id == user_id, Payment.pay_date == d, Payment.lat.is_not(None))):
        pts.append((p.created_at, p.lat, p.lng, "Payment " + p.no))
    return sorted(pts, key=lambda x: x[0])


def gps_km(db: Session, user_id: int, d_from: date, d_to: date) -> float:
    m, d = 0.0, d_from
    while d and d_to and d <= d_to:
        pts = day_points(db, user_id, d)
        m += sum(haversine_m((pts[i - 1][1], pts[i - 1][2]), (pts[i][1], pts[i][2])) for i in range(1, len(pts)))
        d = add_days(d, 1)
    return round(m / 1000, 1)


# ------------------------------------------------------------------ attendance
DAY_LABEL = {"P": "Present", "H": "Half day", "S": "Short day", "A": "Absent", "WO": "Weekly off", "": "—"}


def hours_of(recs: list[Attendance], now: datetime) -> float:
    today = local_today()
    secs = 0.0
    for a in recs:
        end = a.out_at or (now if a.work_date == today else a.in_at)
        secs += max(0.0, (end - a.in_at).total_seconds())
    return secs / 3600


def day_status(db: Session, user: User, d: date, recs: list[Attendance], now: datetime) -> dict:
    s = get_settings(db)
    today = local_today()
    if not recs:
        code = "" if user.joined_on and d < user.joined_on else "WO" if d.weekday() == 6 else "A" if d < today else ""
        return {"code": code, "hours": 0.0, "late": 0, "open": False, "corrected": False}
    recs = sorted(recs, key=lambda a: a.in_at)
    hours = hours_of(recs, now)
    is_open = any(a.out_at is None for a in recs)
    late = max(0, round((recs[0].in_at - local_at(d, s["shift_start"])).total_seconds() / 60) - int(s["grace_min"] or 0))
    if (is_open and d == today) or hours >= float(s["full_day_hrs"] or 8):
        code = "P"
    elif hours >= float(s["half_day_hrs"] or 4):
        code = "H"
    else:
        code = "S"
    return {"code": code, "hours": round(hours, 2), "late": late, "open": is_open,
            "corrected": any(a.source == "correction" for a in recs)}


def session_out(a: Attendance) -> dict:
    return {"id": a.id, "user_id": a.user_id, "date": a.work_date.isoformat(), "in_at": a.in_at.isoformat() + "Z",
            "in_local": to_local(a.in_at).strftime("%H:%M"), "in": {"lat": float(a.in_lat) if a.in_lat is not None else None,
            "lng": float(a.in_lng) if a.in_lng is not None else None, "acc": a.in_acc, "addr": a.in_addr}, "in_note": a.in_note,
            "out_at": a.out_at.isoformat() + "Z" if a.out_at else None, "out_local": to_local(a.out_at).strftime("%H:%M") if a.out_at else None,
            "out": {"lat": float(a.out_lat) if a.out_lat is not None else None, "lng": float(a.out_lng) if a.out_lng is not None else None,
                    "acc": a.out_acc, "addr": a.out_addr} if a.out_at else None, "out_note": a.out_note, "source": a.source}
