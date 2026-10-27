"""Expense claims against the employee's grade: fixed daily allowance, variable per km, hotel defaulted per night."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ExpenseClaim, ExpenseOther, Grade, User
from ..security import can_approve_for, current_user, visible_user_ids
from ..services.calc import compute_claim, gps_km, grade_rates
from ..services.common import f, get_or_404, local_today, next_no, now_utc, parse_date
from ..services.xl import workbook, xlsx_response

router = APIRouter(prefix="/api/expenses", tags=["expenses"])
STN = {"in": "In-station", "out": "Out-station"}
CATEGORIES = ["Food", "Local conveyance", "Phone and internet", "Toll and parking", "Courier and postage", "Other"]


class OtherIn(BaseModel):
    category: str
    amount: float
    note: str = ""


class ClaimIn(BaseModel):
    type: str = "in"
    date_from: str
    date_to: str
    purpose: str = ""
    places: str = ""
    km: float = 0
    nights: int | None = None       # None: default (out-station days - 1)
    hotel: float | None = None      # None: default (nights x grade hotel rate)
    hotel_name: str = ""
    hotel_bill: str = ""
    others: list[OtherIn] = Field(default_factory=list)
    submit: bool = True


def _grade(db: Session, u: User) -> Grade:
    g = db.scalar(select(Grade).where(Grade.code == u.grade_code)) if u.grade_code else None
    if not g:
        raise HTTPException(409, "You have no grade, so your allowances are not known. Ask the administrator to give you a grade.")
    return g


def _work(db: Session, body: ClaimIn, u: User) -> dict:
    if body.type not in STN:
        raise HTTPException(422, "Choose in-station or out-station.")
    g = _grade(db, u)
    d1, d2 = parse_date(body.date_from, "From"), parse_date(body.date_to, "To")
    rates = grade_rates(g, body.type)
    days = (d2 - d1).days + 1 if d1 and d2 and d2 >= d1 else 0
    nights = body.nights if body.nights is not None else (max(days - 1, 0) if body.type == "out" else 0)
    hotel = body.hotel if body.hotel is not None else round(nights * rates["hotel"], 2)
    others = [o.model_dump() for o in body.others if o.amount]
    calc = compute_claim(rates, d1, d2, body.km, nights, hotel, others)
    return {"grade": g, "d1": d1, "d2": d2, "rates": rates, "nights": nights, "hotel": hotel, "others": others, "calc": calc,
            "gps_km": gps_km(db, u.id, d1, d2) if d1 and d2 and d2 >= d1 and (d2 - d1).days < 62 else 0}


def claim_out(db: Session, x: ExpenseClaim, me: User | None = None) -> dict:
    u = db.get(User, x.user_id)
    out = {"id": x.id, "no": x.no, "user_id": x.user_id, "employee": u.name, "emp_code": u.emp_code, "grade": x.grade_code, "type": x.type,
           "type_label": STN[x.type], "date_from": x.date_from.isoformat(), "date_to": x.date_to.isoformat(), "purpose": x.purpose,
           "places": x.places, "km": f(x.km), "nights": x.nights, "hotel": f(x.hotel), "hotel_name": x.hotel_name, "hotel_bill": x.hotel_bill,
           "rates": x.rates, "calc": x.calc, "total": f(x.total), "gps_km": f(x.gps_km), "status": x.status, "reject_reason": x.reject_reason,
           "others": [{"category": o.category, "amount": f(o.amount), "note": o.note} for o in x.others],
           "approved_by": (db.get(User, x.approved_by).name if x.approved_by else None),
           "sync": {"status": x.sync_status, "no": x.sync_no, "error": x.sync_error}}
    if me:
        out["can_approve"] = x.status == "submitted" and can_approve_for(db, me, x.user_id)
        out["can_edit"] = x.user_id == me.id and x.status in ("draft", "rejected")
    return out


@router.get("/meta")
def meta(db: Session = Depends(get_db), me: User = Depends(current_user)):
    g = db.scalar(select(Grade).where(Grade.code == me.grade_code)) if me.grade_code else None
    return {"categories": CATEGORIES, "grade": {"code": g.code, "name": g.name, "in": grade_rates(g, "in"), "out": grade_rates(g, "out")} if g else None}


@router.post("/preview")
def preview(body: ClaimIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    w = _work(db, body, me)
    return {"rates": w["rates"], "nights": w["nights"], "hotel": w["hotel"], "calc": w["calc"], "gps_km": w["gps_km"]}


def _save(db: Session, x: ExpenseClaim | None, body: ClaimIn, me: User) -> ExpenseClaim:
    w = _work(db, body, me)
    d1, d2, c = w["d1"], w["d2"], w["calc"]
    if not d1 or not d2 or d2 < d1:
        raise HTTPException(422, "Check the dates: To must be on or after From.")
    if d2 > local_today():
        raise HTTPException(422, "Claims are for days already worked.")
    if body.submit and not body.purpose.strip():
        raise HTTPException(422, "Enter the purpose of the trip.")
    if body.km < 0 or w["hotel"] < 0 or any(o["amount"] < 0 for o in w["others"]) or w["nights"] < 0:
        raise HTTPException(422, "Amounts cannot be negative.")
    if any(o["amount"] > 0 and not o["note"].strip() for o in w["others"]):
        raise HTTPException(422, "Add a note for each other expense.")
    if any(o["category"] not in CATEGORIES for o in w["others"]):
        raise HTTPException(422, "Unknown expense category.")
    clash = db.scalar(select(ExpenseClaim).where(ExpenseClaim.user_id == me.id, ExpenseClaim.status != "rejected",
                                                 ExpenseClaim.date_from <= d2, ExpenseClaim.date_to >= d1,
                                                 ExpenseClaim.id != (x.id if x else 0)))
    if clash:
        raise HTTPException(409, f"These dates overlap claim {clash.no} ({clash.date_from:%d-%m-%Y} to {clash.date_to:%d-%m-%Y}). "
                                 "Daily allowance can be claimed once per day.")
    if body.submit and c["total"] <= 0:
        raise HTTPException(422, "The claim total is zero.")
    if not x:
        x = ExpenseClaim(no=next_no(db, "expense", d1), user_id=me.id, sync_status="na")
        db.add(x)
    x.type, x.date_from, x.date_to = body.type, d1, d2
    x.purpose, x.places = body.purpose.strip()[:200], body.places.strip()[:200]
    x.km, x.nights, x.hotel = body.km, w["nights"], w["hotel"]
    x.hotel_name, x.hotel_bill = body.hotel_name.strip()[:120], body.hotel_bill.strip()[:60]
    x.grade_code, x.rates, x.calc, x.total, x.gps_km = w["grade"].code, w["rates"], c, c["total"], w["gps_km"]
    x.others = [ExpenseOther(category=o["category"], amount=o["amount"], note=o["note"].strip()[:200]) for o in w["others"]]
    x.status, x.reject_reason = ("submitted" if body.submit else "draft"), ""
    db.commit()
    return x


@router.post("")
def create(body: ClaimIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    return claim_out(db, _save(db, None, body, me), me)


@router.put("/{cid}")
def update(cid: int, body: ClaimIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    x = get_or_404(db, ExpenseClaim, cid, "claim")
    if x.user_id != me.id or x.status not in ("draft", "rejected"):
        raise HTTPException(409, "Only your own draft or rejected claims can be changed.")
    return claim_out(db, _save(db, x, body, me), me)


@router.get("")
def list_claims(status: str = "", month: str = "", db: Session = Depends(get_db), me: User = Depends(current_user)):
    q = select(ExpenseClaim).where(ExpenseClaim.user_id.in_(visible_user_ids(db, me)))
    if status:
        q = q.where(ExpenseClaim.status == status)
    rows = [x for x in db.scalars(q.order_by(ExpenseClaim.id.desc()).limit(500))
            if not month or x.date_from.isoformat().startswith(month) or x.date_to.isoformat().startswith(month)]
    return [claim_out(db, x, me) for x in rows]


@router.get("/{cid}")
def get_claim(cid: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    x = get_or_404(db, ExpenseClaim, cid, "claim")
    if x.user_id not in visible_user_ids(db, me):
        raise HTTPException(403, "You cannot see this claim.")
    return claim_out(db, x, me)


class DecideIn(BaseModel):
    approve: bool
    reason: str = ""


@router.post("/{cid}/decide")
def decide(cid: int, body: DecideIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    x = get_or_404(db, ExpenseClaim, cid, "claim")
    if x.status != "submitted" or not can_approve_for(db, me, x.user_id):
        raise HTTPException(403, "You cannot approve or reject this claim.")
    if body.approve:
        x.status, x.approved_by, x.approved_at, x.sync_status = "approved", me.id, now_utc(), "pending"
    else:
        if len(body.reason.strip()) < 3:
            raise HTTPException(422, "Give a reason for rejecting.")
        x.status, x.reject_reason = "rejected", body.reason.strip()[:300]
    db.commit()
    return claim_out(db, x, me)


@router.delete("/{cid}")
def delete(cid: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    x = get_or_404(db, ExpenseClaim, cid, "claim")
    if x.user_id != me.id or x.status not in ("draft", "rejected"):
        raise HTTPException(409, "Only your own draft or rejected claims can be deleted.")
    db.delete(x)
    db.commit()
    return {"ok": True}


@router.get("-export/all")
def export(db: Session = Depends(get_db), me: User = Depends(current_user)):
    rows = []
    for x in db.scalars(select(ExpenseClaim).where(ExpenseClaim.user_id.in_(visible_user_ids(db, me))).order_by(ExpenseClaim.id)):
        o = claim_out(db, x)
        c = o["calc"]
        rows.append({"Claim": o["no"], "Employee code": o["emp_code"], "Employee": o["employee"], "Grade": o["grade"], "From": o["date_from"],
                     "To": o["date_to"], "Days": c["days"], "Type": o["type_label"], "Purpose": o["purpose"], "DA per day": o["rates"]["da"],
                     "Fixed (DA)": c["fixed"], "Km": o["km"], "Rate per km": o["rates"]["km"], "Variable (travel)": c["variable"],
                     "Nights": o["nights"], "Hotel policy": c["hotel_policy"], "Hotel paid": c["hotel"], "Hotel above policy": c["hotel_over"],
                     "Other": c["other"], "Total": c["total"], "Status": o["status"], "Approved by": o["approved_by"] or "", "Dynamics": o["sync"]["no"] or ""})
    return xlsx_response(workbook({"Claims": rows}), "Expense_claims.xlsx")
