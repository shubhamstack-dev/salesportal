import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Grade, User
from ..security import ROLES, current_user, hash_password, make_token, verify_password
from ..services.common import (MAX_PENDING_SIGNUPS, STATES, get_settings, local_today, pending_signups, public_settings,
                               put_settings, save_pending_signups)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupIn(BaseModel):
    name: str
    username: str
    password: str
    company: str = "Samurai Foods"


class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    name: str
    username: str
    phone: str = ""
    email: str = ""
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


def me_out(db: Session, u: User) -> dict:
    g = db.scalar(select(Grade).where(Grade.code == u.grade_code)) if u.grade_code else None
    return {"user": {"id": u.id, "name": u.name, "username": u.username, "role": u.role, "role_label": ROLES[u.role],
                     "emp_code": u.emp_code, "grade": u.grade_code, "grade_name": g.name if g else None},
            "settings": public_settings(get_settings(db), u.role == "admin"), "states": STATES, "roles": ROLES}


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {"needs_setup": not db.scalar(select(func.count(User.id))), "company": get_settings(db)["company"]["name"]}


@router.post("/setup")
def setup(body: SetupIn, db: Session = Depends(get_db)):
    if db.scalar(select(func.count(User.id))):
        raise HTTPException(409, "The administrator already exists. Sign in instead.")
    if not body.name.strip() or not body.username.strip():
        raise HTTPException(422, "Enter your name and a username.")
    if len(body.password) < 8:
        raise HTTPException(422, "Use a password of at least 8 characters.")
    u = User(name=body.name.strip(), username=body.username.strip().lower(), password_hash=hash_password(body.password),
             role="admin", joined_on=local_today())
    db.add(u)
    put_settings(db, {"company": {"name": body.company.strip() or "Samurai Foods"}})
    db.commit()
    return {"token": make_token(u), **me_out(db, u)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Username or password is incorrect.")
    if not u.active:
        if u.id in pending_signups(db):
            raise HTTPException(403, "Your registration is waiting for administrator approval.")
        raise HTTPException(403, "This account is inactive. Ask your administrator.")
    return {"token": make_token(u), **me_out(db, u)}


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Anyone can ask for an account. It starts inactive, as a sales representative,
    and an administrator approves it under Employees before it can sign in."""
    if not db.scalar(select(func.count(User.id))):
        raise HTTPException(409, "The portal is not set up yet. Create the administrator first.")
    name, username = body.name.strip(), body.username.strip().lower()
    if not name or not username:
        raise HTTPException(422, "Enter your name and a username.")
    if not re.fullmatch(r"[a-z0-9._@-]+", username):
        raise HTTPException(422, "Usernames can use letters, numbers and . _ @ - only.")
    if len(body.password) < 8:
        raise HTTPException(422, "Use a password of at least 8 characters.")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, "That username is taken.")
    pending = pending_signups(db)
    if len(pending) >= MAX_PENDING_SIGNUPS:
        raise HTTPException(429, "Too many registrations are waiting. Try again later or ask your administrator.")
    email = body.email.strip() or (username if "@" in username else "")
    u = User(name=name, username=username, password_hash=hash_password(body.password), role="rep", active=False,
             phone=body.phone.strip(), email=email, joined_on=local_today())
    db.add(u)
    db.flush()
    save_pending_signups(db, pending | {u.id})
    db.commit()
    return {"ok": True, "message": "Registration sent. You can sign in once an administrator approves it."}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_out(db, user)


@router.post("/password")
def password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(422, "Your current password is not correct.")
    if len(body.new_password) < 8:
        raise HTTPException(422, "Use a password of at least 8 characters.")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}
