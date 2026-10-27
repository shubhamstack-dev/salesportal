from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Attendance, AttendanceCorrection, ExpenseClaim, Payment, SalesDoc, User
from ..security import can_approve_for, current_user, visible_user_ids
from ..services.calc import day_points
from ..services.common import f, local_today, pending_signups, to_local
from ..services.dynamics import out_queues

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), me: User = Depends(current_user)):
    today = local_today()
    ids = visible_user_ids(db, me)
    staff = [u for u in db.scalars(select(User).where(User.active.is_(True), User.role != "admin").order_by(User.name)) if u.id in ids]
    orders = [d for d in db.scalars(select(SalesDoc).where(SalesDoc.kind == "order", SalesDoc.doc_date == today,
                                                         SalesDoc.status.in_(["submitted", "approved"]))) if d.rep_id in ids]
    quotes = [d for d in db.scalars(select(SalesDoc).where(SalesDoc.kind == "quote", SalesDoc.doc_date == today,
                                                         SalesDoc.status.in_(["open", "converted"]))) if d.rep_id in ids]
    pays = [p for p in db.scalars(select(Payment).where(Payment.pay_date == today, Payment.cancelled.is_(False))) if p.rep_id in ids]
    team = []
    for u in staff:
        recs = list(db.scalars(select(Attendance).where(Attendance.user_id == u.id, Attendance.work_date == today).order_by(Attendance.in_at)))
        pts = day_points(db, u.id, today)
        last = pts[-1] if pts else None
        on = bool(recs and recs[-1].out_at is None)
        team.append({"id": u.id, "name": u.name, "emp_code": u.emp_code, "phone": u.phone, "status": "on" if on else "off" if recs else "none",
                     "since": to_local(recs[-1].in_at if on else recs[-1].out_at).strftime("%H:%M") if recs else None,
                     "last": {"lat": f(last[1]), "lng": f(last[2]), "what": last[3], "at": to_local(last[0]).strftime("%H:%M")} if last else None,
                     "orders": len([o for o in orders if o.rep_id == u.id]), "orders_value": sum(float(o.total) for o in orders if o.rep_id == u.id),
                     "collected": sum(float(p.amount) for p in pays if p.rep_id == u.id)})
    approvals = 0
    if me.role in ("admin", "manager"):
        approvals += len([o for o in db.scalars(select(SalesDoc).where(SalesDoc.kind == "order", SalesDoc.status == "submitted")) if o.rep_id in ids])
        approvals += len([x for x in db.scalars(select(ExpenseClaim).where(ExpenseClaim.status == "submitted")) if can_approve_for(db, me, x.user_id)])
        approvals += len([c for c in db.scalars(select(AttendanceCorrection).where(AttendanceCorrection.status == "pending")) if can_approve_for(db, me, c.user_id)])
    q = out_queues(db) if me.role == "admin" else None
    return {"on_duty": sum(1 for t in team if t["status"] == "on"), "staff": len(team),
            "orders": {"count": len(orders), "value": sum(float(o.total) for o in orders)},
            "quotes": {"count": len(quotes), "value": sum(float(o.total) for o in quotes)},
            "collected": {"count": len(pays), "value": sum(float(p.amount) for p in pays)},
            "approvals": approvals, "to_dynamics": sum(len(v) for v in q.values()) if q else None, "team": team}


@router.get("/counts")
def counts(db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Numbers for the menu badges."""
    if me.role == "rep":
        return {}
    ids = visible_user_ids(db, me)
    out = {"orders": len([o for o in db.scalars(select(SalesDoc).where(SalesDoc.kind == "order", SalesDoc.status == "submitted")) if o.rep_id in ids]),
           "expenses": len([x for x in db.scalars(select(ExpenseClaim).where(ExpenseClaim.status == "submitted")) if can_approve_for(db, me, x.user_id)]),
           "attendance": len([c for c in db.scalars(select(AttendanceCorrection).where(AttendanceCorrection.status == "pending")) if can_approve_for(db, me, c.user_id)])}
    if me.role == "admin":
        out["integration"] = sum(len(v) for v in out_queues(db).values())
        out["employees"] = len(pending_signups(db))
    return out
