"""Employees (the portal's users), expense grades and settings."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Customer, Grade, User, UserCustomer
from ..security import ROLES, current_user, hash_password, require, visible_user_ids
from ..services.common import f, get_or_404, get_settings, local_today, public_settings, put_settings, SECRET_KEYS

router = APIRouter(prefix="/api", tags=["organisation"])
admin = require("admin")


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "username": u.username, "role": u.role, "role_label": ROLES[u.role], "emp_code": u.emp_code,
            "phone": u.phone, "email": u.email, "manager_id": u.manager_id, "territory": u.territory, "grade": u.grade_code,
            "active": u.active, "joined_on": u.joined_on.isoformat(), "customer_ids": [c.customer_id for c in u.customers]}


class UserIn(BaseModel):
    name: str
    username: str
    password: str | None = None
    role: str = "rep"
    emp_code: str = ""
    phone: str = ""
    email: str = ""
    manager_id: int | None = None
    territory: str = ""
    grade: str | None = None
    active: bool = True
    customer_ids: list[int] = []


@router.get("/users")
def list_users(db: Session = Depends(get_db), me: User = Depends(current_user)):
    """Admins get every employee in full; others get the people they may see, for filters and names."""
    ids = visible_user_ids(db, me)
    users = db.scalars(select(User).order_by(User.name))
    if me.role == "admin":
        return [user_out(u) for u in users]
    return [{"id": u.id, "name": u.name, "emp_code": u.emp_code, "role": u.role, "phone": u.phone, "active": u.active}
            for u in users if u.id in ids]


def _check(db: Session, body: UserIn, existing: User | None, me: User):
    username = body.username.strip().lower()
    if not body.name.strip() or not username:
        raise HTTPException(422, "Enter a name and a username.")
    if not re.fullmatch(r"[a-z0-9._@-]+", username):
        raise HTTPException(422, "Usernames can use letters, numbers and . _ @ - only.")
    clash = db.scalar(select(User).where(User.username == username))
    if clash and clash is not existing:
        raise HTTPException(409, "That username is taken.")
    if body.role not in ROLES:
        raise HTTPException(422, "Unknown role.")
    if (not existing or body.password) and len(body.password or "") < 8:
        raise HTTPException(422, "Use a password of at least 8 characters.")
    if body.grade and not db.scalar(select(Grade).where(Grade.code == body.grade)):
        raise HTTPException(422, "Unknown grade.")
    if existing and existing.id == me.id and (body.role != "admin" or not body.active):
        others = db.query(User).filter(User.role == "admin", User.active.is_(True), User.id != me.id).count()
        if not others:
            raise HTTPException(409, "Keep at least one active administrator.")
    return username


def _apply(db: Session, u: User, body: UserIn, username: str):
    u.name, u.username, u.role, u.emp_code = body.name.strip(), username, body.role, body.emp_code.strip()
    u.phone, u.email, u.territory, u.active = body.phone.strip(), body.email.strip(), body.territory.strip(), body.active
    u.manager_id = body.manager_id if body.manager_id and body.manager_id != u.id else None
    u.grade_code = body.grade or None
    valid = set(db.scalars(select(Customer.id).where(Customer.id.in_(body.customer_ids or [0]))))
    u.customers = [UserCustomer(customer_id=cid) for cid in body.customer_ids if cid in valid]
    if body.password:
        u.password_hash = hash_password(body.password)


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), me: User = Depends(admin)):
    username = _check(db, body, None, me)
    u = User(password_hash="", joined_on=local_today())
    _apply(db, u, body, username)
    db.add(u)
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserIn, db: Session = Depends(get_db), me: User = Depends(admin)):
    u = get_or_404(db, User, user_id, "employee")
    username = _check(db, body, u, me)
    _apply(db, u, body, username)
    db.commit()
    return user_out(u)


# ---------------- grades (expense policy)
GRADE_FIELDS = ["da_in", "km_in", "hotel_in", "da_out", "km_out", "hotel_out"]


class GradeIn(BaseModel):
    code: str
    name: str
    da_in: float = 0
    km_in: float = 0
    hotel_in: float = 0
    da_out: float = 0
    km_out: float = 0
    hotel_out: float = 0


def grade_out(db: Session, g: Grade) -> dict:
    return {"code": g.code, "name": g.name, **{k: f(getattr(g, k)) for k in GRADE_FIELDS},
            "employees": db.query(User).filter(User.grade_code == g.code).count()}


@router.get("/grades")
def list_grades(db: Session = Depends(get_db), _=Depends(current_user)):
    return [grade_out(db, g) for g in db.scalars(select(Grade).order_by(Grade.code))]


@router.put("/grades/{code}")
def save_grade(code: str, body: GradeIn, db: Session = Depends(get_db), _=Depends(admin)):
    code = code.strip().upper()
    if not code or not body.name.strip():
        raise HTTPException(422, "Enter a grade code and name.")
    if any(getattr(body, k) < 0 for k in GRADE_FIELDS):
        raise HTTPException(422, "Rates cannot be negative.")
    g = db.scalar(select(Grade).where(Grade.code == code)) or Grade(code=code)
    g.name = body.name.strip()
    for k in GRADE_FIELDS:
        setattr(g, k, getattr(body, k))
    db.add(g)
    db.commit()
    return grade_out(db, g)


@router.delete("/grades/{code}")
def delete_grade(code: str, db: Session = Depends(get_db), _=Depends(admin)):
    g = db.scalar(select(Grade).where(Grade.code == code))
    if not g:
        raise HTTPException(404, "That grade does not exist.")
    n = db.query(User).filter(User.grade_code == code).count()
    if n:
        raise HTTPException(409, f"{n} employee(s) have this grade. Give them another grade first.")
    db.delete(g)
    db.commit()
    return {"ok": True}


# ---------------- settings
@router.get("/settings")
def read_settings(db: Session = Depends(get_db), me: User = Depends(current_user)):
    return public_settings(get_settings(db), me.role == "admin")


@router.put("/settings")
def write_settings(body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    dyn = body.get("dynamics") or {}
    for k in SECRET_KEYS:          # a masked or empty secret keeps the stored one
        if dyn.get(k) in ("••••••", None):
            dyn.pop(k, None)
    s = body.get("company", {})
    if s.get("gstin") and not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]", s["gstin"].upper()):
        raise HTTPException(422, "The company GSTIN does not look valid.")
    if "full_day_hrs" in body and "half_day_hrs" in body and float(body["half_day_hrs"]) > float(body["full_day_hrs"]):
        raise HTTPException(422, "Half-day hours cannot be more than full-day hours.")
    new = put_settings(db, body)
    db.commit()
    return public_settings(new, True)
