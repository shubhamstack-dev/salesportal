"""Time In / Time Out, day status, corrections for missed punches, and the monthly muster."""
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Attendance, AttendanceCorrection, Payment, SalesDoc, User
from ..security import can_approve_for, current_user, visible_user_ids
from ..services.calc import DAY_LABEL, day_points, day_status, hours_of, session_out
from ..services.common import add_days, f, get_or_404, get_settings, local_at, local_today, now_utc, parse_date, to_local
from ..services.xl import workbook, xlsx_response

router = APIRouter(prefix="/api", tags=["attendance"])
CTYPE = {"out": "Missed Time Out", "in": "Missed Time In", "day": "Whole day missed"}


def recs_on(db: Session, uid: int, d: date) -> list[Attendance]:
    return list(db.scalars(select(Attendance).where(Attendance.user_id == uid, Attendance.work_date == d).order_by(Attendance.in_at)))


def corr_out(db: Session, c: AttendanceCorrection) -> dict:
    u = db.get(User, c.user_id)
    return {"id": c.id, "user_id": c.user_id, "employee": u.name, "emp_code": u.emp_code, "date": c.work_date.isoformat(), "type": c.type,
            "type_label": CTYPE[c.type], "in_time": c.in_time, "out_time": c.out_time, "reason": c.reason, "status": c.status,
            "recorded": [session_out(a) for a in recs_on(db, c.user_id, c.work_date)]}


class PunchIn(BaseModel):
    kind: str                      # in | out
    lat: float | None = None
    lng: float | None = None
    acc: int | None = None
    note: str = ""


@router.post("/timeclock/punch")
def punch(body: PunchIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    s = get_settings(db)
    has_loc = body.lat is not None and body.lng is not None
    if s["punch_needs_location"] and not has_loc:
        raise HTTPException(422, "Time In and Time Out need your location. Allow location for this site and try again.")
    today, now = local_today(), now_utc()
    recs = recs_on(db, me.id, today)
    open_ = next((a for a in recs if a.out_at is None), None)
    note = body.note.strip()[:80]
    if body.kind == "in":
        if open_:
            raise HTTPException(409, "You are already timed in.")
        a = Attendance(user_id=me.id, work_date=today, in_at=now, in_lat=body.lat, in_lng=body.lng, in_acc=body.acc, in_note=note, source="app")
        db.add(a)
        late = 0 if recs else max(0, round((now - local_at(today, s["shift_start"])).total_seconds() / 60) - int(s["grace_min"]))
    elif body.kind == "out":
        if not open_:
            raise HTTPException(409, "You are not timed in.")
        a = open_
        a.out_at, a.out_lat, a.out_lng, a.out_acc, a.out_note = now, body.lat, body.lng, body.acc, note
        late = 0
    else:
        raise HTTPException(422, "Unknown punch.")
    db.commit()
    return {"session": session_out(a), "late": late, "hours_today": round(hours_of(recs_on(db, me.id, today), now_utc()), 2)}


class AddrIn(BaseModel):
    side: str
    addr: str


@router.patch("/attendance/{aid}/address")
def set_address(aid: int, body: AddrIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Street address looked up by the browser through Google Maps after a punch."""
    a = get_or_404(db, Attendance, aid, "punch")
    if a.user_id != me.id:
        raise HTTPException(403, "Not your punch.")
    if body.side == "in":
        a.in_addr = body.addr[:250]
    elif body.side == "out" and a.out_at:
        a.out_addr = body.addr[:250]
    db.commit()
    return {"ok": True}


@router.get("/timeclock")
def timeclock(db: Session = Depends(get_db), me: User = Depends(current_user)):
    today, now = local_today(), now_utc()
    recs = recs_on(db, me.id, today)
    stale = db.scalar(select(Attendance).where(Attendance.user_id == me.id, Attendance.out_at.is_(None), Attendance.work_date < today)
                      .order_by(Attendance.in_at.desc()))
    history = []
    for i in range(14):
        d = add_days(today, -i)
        r = recs_on(db, me.id, d)
        st = day_status(db, me, d, r, now)
        pending = db.scalar(select(AttendanceCorrection).where(AttendanceCorrection.user_id == me.id, AttendanceCorrection.work_date == d,
                                                                AttendanceCorrection.status == "pending"))
        history.append({"date": d.isoformat(), "weekday": d.strftime("%a"), **st, "label": DAY_LABEL[st["code"]],
                        "first_in": to_local(r[0].in_at).strftime("%H:%M") if r else None,
                        "last_out": (to_local(r[-1].out_at).strftime("%H:%M") if r and r[-1].out_at else None),
                        "open_last": bool(r and not r[-1].out_at), "correction_pending": bool(pending)})
    st = day_status(db, me, today, recs, now)
    mine = db.scalars(select(AttendanceCorrection).where(AttendanceCorrection.user_id == me.id).order_by(AttendanceCorrection.id.desc()).limit(6))
    return {"today": today.isoformat(), "sessions": [session_out(a) for a in recs], "status": st, "on_duty": bool(recs and recs[-1].out_at is None),
            "stale": session_out(stale) if stale else None, "history": history, "corrections": [corr_out(db, c) for c in mine]}


class CorrIn(BaseModel):
    date: str
    type: str
    in_time: str = ""
    out_time: str = ""
    reason: str


@router.post("/corrections")
def request_correction(body: CorrIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    d = parse_date(body.date, "Date")
    if not d or d > local_today():
        raise HTTPException(422, "Choose a date up to today.")
    if body.type not in CTYPE:
        raise HTTPException(422, "Choose what happened.")
    if len(body.reason.strip()) < 5:
        raise HTTPException(422, "Give a reason for the correction.")
    need_in, need_out = body.type != "out", body.type != "in"
    if (need_in and not body.in_time) or (need_out and not body.out_time):
        raise HTTPException(422, "Enter the times.")
    recs = recs_on(db, me.id, d)
    if body.type == "out":
        o = next((a for a in recs if a.out_at is None), None)
        if not o:
            raise HTTPException(422, "There is no open Time In on that day to close.")
        if local_at(d, body.out_time) <= o.in_at:
            raise HTTPException(422, f"Time Out must be after the Time In at {to_local(o.in_at):%H:%M}.")
    if body.type == "in":
        if not recs:
            raise HTTPException(422, "Nothing was recorded that day; choose Whole day missed.")
        if local_at(d, body.in_time) >= recs[0].in_at:
            raise HTTPException(422, f"Time In must be before the first punch at {to_local(recs[0].in_at):%H:%M}.")
    if body.type == "day":
        if recs:
            raise HTTPException(422, "Punches exist on that day; choose Missed Time In or Missed Time Out.")
        if body.out_time <= body.in_time:
            raise HTTPException(422, "Time Out must be after Time In.")
    if need_out and d == local_today() and local_at(d, body.out_time) > now_utc():
        raise HTTPException(422, "Time Out cannot be in the future.")
    if db.scalar(select(AttendanceCorrection).where(AttendanceCorrection.user_id == me.id, AttendanceCorrection.work_date == d,
                                                    AttendanceCorrection.status == "pending")):
        raise HTTPException(409, "A request for that day is already waiting for approval.")
    c = AttendanceCorrection(user_id=me.id, work_date=d, type=body.type, in_time=body.in_time if need_in else "",
                             out_time=body.out_time if need_out else "", reason=body.reason.strip()[:300])
    db.add(c)
    db.commit()
    return corr_out(db, c)


@router.get("/corrections")
def pending_corrections(db: Session = Depends(get_db), me: User = Depends(current_user)):
    rows = db.scalars(select(AttendanceCorrection).where(AttendanceCorrection.status == "pending").order_by(AttendanceCorrection.id))
    return [corr_out(db, c) for c in rows if can_approve_for(db, me, c.user_id)]


class DecideIn(BaseModel):
    approve: bool


@router.post("/corrections/{cid}/decide")
def decide(cid: int, body: DecideIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = get_or_404(db, AttendanceCorrection, cid, "request")
    if c.status != "pending" or not can_approve_for(db, me, c.user_id):
        raise HTTPException(403, "You cannot decide this request.")
    if body.approve:
        recs = recs_on(db, c.user_id, c.work_date)
        if c.type == "out":
            o = next((a for a in recs if a.out_at is None), None)
            if not o:
                raise HTTPException(409, "The open Time In no longer exists. Reject the request instead.")
            o.out_at, o.out_addr, o.source = local_at(c.work_date, c.out_time), "Corrected", "correction"
        elif c.type == "in":
            if not recs:
                raise HTTPException(409, "The punches for that day no longer exist. Reject the request instead.")
            recs[0].in_at, recs[0].source = local_at(c.work_date, c.in_time), "correction"
        else:
            if recs:
                raise HTTPException(409, "Punches now exist on that day. Reject the request instead.")
            db.add(Attendance(user_id=c.user_id, work_date=c.work_date, in_at=local_at(c.work_date, c.in_time), in_addr="Corrected",
                              out_at=local_at(c.work_date, c.out_time), out_addr="Corrected", source="correction"))
    c.status, c.decided_by, c.decided_at = ("approved" if body.approve else "rejected"), me.id, now_utc()
    db.commit()
    return {"ok": True, "status": c.status}


def _people(db: Session, me: User) -> list[User]:
    ids = visible_user_ids(db, me)
    return [u for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)) if u.id in ids and (me.role != "rep" or u.id == me.id)]


def _muster(db: Session, me: User, month: str):
    try:
        y, m = (int(x) for x in month.split("-"))
        days = monthrange(y, m)[1]
    except (ValueError, TypeError):
        raise HTTPException(422, "Month must look like 2026-10.")
    now = now_utc()
    first, last = date(y, m, 1), date(y, m, days)
    out = []
    for u in _people(db, me):
        recs = list(db.scalars(select(Attendance).where(Attendance.user_id == u.id, Attendance.work_date >= first, Attendance.work_date <= last)))
        by_day = {}
        for a in recs:
            by_day.setdefault(a.work_date, []).append(a)
        cells, present, hours, late_days = [], 0.0, 0.0, 0
        for i in range(days):
            d = date(y, m, i + 1)
            st = day_status(db, u, d, by_day.get(d, []), now)
            hours += st["hours"]
            present += 1 if st["code"] == "P" else 0.5 if st["code"] == "H" else 0
            late_days += 1 if st["late"] else 0
            cells.append({"date": d.isoformat(), **st})
        out.append({"user_id": u.id, "name": u.name, "emp_code": u.emp_code, "present": present, "hours": round(hours, 2), "late_days": late_days, "cells": cells})
    return days, out


@router.get("/attendance/muster")
def muster(month: str, db: Session = Depends(get_db), me: User = Depends(current_user)):
    days, rows = _muster(db, me, month)
    return {"month": month, "days": days, "rows": rows, "labels": DAY_LABEL}


@router.get("/attendance/muster.xlsx")
def muster_xlsx(month: str, db: Session = Depends(get_db), me: User = Depends(current_user)):
    if me.role == "rep":
        raise HTTPException(403, "Only managers download the muster.")
    days, rows = _muster(db, me, month)
    sheet = []
    for r in rows:
        row = {"Employee code": r["emp_code"], "Name": r["name"]}
        for c in r["cells"]:
            row[c["date"][8:]] = (f"{c['code']} {c['hours']:.1f}h" + (" L" if c["late"] else "")) if c["hours"] else c["code"]
        row.update({"Days present": r["present"], "Hours": r["hours"], "Late days": r["late_days"]})
        sheet.append(row)
    y, m = (int(x) for x in month.split("-"))
    ids = [r["user_id"] for r in rows]
    punches = []
    for a in db.scalars(select(Attendance).where(Attendance.user_id.in_(ids or [0]), Attendance.work_date >= date(y, m, 1),
                                                 Attendance.work_date <= date(y, m, days)).order_by(Attendance.work_date, Attendance.in_at)):
        u = db.get(User, a.user_id)
        punches.append({"Employee code": u.emp_code, "Employee": u.name, "Date": a.work_date.isoformat(), "Time In": to_local(a.in_at).strftime("%H:%M"),
                        "In note": a.in_note, "In latitude": f(a.in_lat), "In longitude": f(a.in_lng), "In address": a.in_addr,
                        "Time Out": to_local(a.out_at).strftime("%H:%M") if a.out_at else "", "Out note": a.out_note, "Out latitude": f(a.out_lat),
                        "Out longitude": f(a.out_lng), "Out address": a.out_addr, "Hours": round(hours_of([a], now_utc()), 2),
                        "Corrected": "Yes" if a.source == "correction" else ""})
    return xlsx_response(workbook({"Muster": sheet, "Punches": punches}), f"Attendance_{month}.xlsx")


@router.get("/attendance/day")
def day_detail(user_id: int, date_: str = "", db: Session = Depends(get_db), me: User = Depends(current_user)):
    if user_id not in visible_user_ids(db, me) or (me.role == "rep" and user_id != me.id):
        raise HTTPException(403, "You cannot see this employee.")
    u = get_or_404(db, User, user_id, "employee")
    d = parse_date(date_, "Date") or local_today()
    recs = recs_on(db, user_id, d)
    st = day_status(db, u, d, recs, now_utc())
    docs = list(db.scalars(select(SalesDoc).where(SalesDoc.rep_id == user_id, SalesDoc.doc_date == d, SalesDoc.status != "cancelled")))
    pays = list(db.scalars(select(Payment).where(Payment.rep_id == user_id, Payment.pay_date == d, Payment.cancelled.is_(False))))
    return {"employee": u.name, "date": d.isoformat(), "status": {**st, "label": DAY_LABEL[st["code"]]}, "sessions": [session_out(a) for a in recs],
            "orders": len([x for x in docs if x.kind == "order"]), "orders_total": round(sum(float(x.total) for x in docs if x.kind == "order"), 2),
            "payments": len(pays), "payments_total": round(sum(float(p.amount) for p in pays), 2),
            "points": [{"at": t.isoformat() + "Z", "lat": f(la), "lng": f(lo), "what": w} for t, la, lo, w in day_points(db, user_id, d)]}
