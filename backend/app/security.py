"""Passwords, sign-in tokens, roles and who may see whose data."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import JWT_HOURS, JWT_SECRET, get_db
from .models import Customer, User

bearer = HTTPBearer(auto_error=False)
ROLES = {"admin": "Administrator", "manager": "Sales manager", "rep": "Sales representative"}


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def make_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_HOURS)
    return jwt.encode({"sub": str(user.id), "exp": exp}, JWT_SECRET, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Sign in to continue.")
    try:
        data = jwt.decode(cred.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session has expired. Sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(401, "Sign in to continue.")
    user = db.get(User, int(data["sub"]))
    if not user or not user.active:
        raise HTTPException(401, "This account is not active.")
    return user


def require(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if roles and user.role not in roles:
            raise HTTPException(403, "Your role does not allow this.")
        return user
    return dep


def deny(msg="Your role does not allow this."):
    raise HTTPException(403, msg)


def visible_user_ids(db: Session, me: User) -> list[int]:
    """Admin: everyone. Manager: self and team (everyone if no one reports to them). Rep: self."""
    if me.role == "admin":
        return list(db.scalars(select(User.id)))
    if me.role == "manager":
        team = list(db.scalars(select(User.id).where(User.manager_id == me.id)))
        return [me.id, *team] if team else list(db.scalars(select(User.id)))
    return [me.id]


def customers_for(db: Session, user: User) -> list[Customer]:
    q = select(Customer).where(Customer.blocked.is_(False)).order_by(Customer.name)
    if user.role == "rep" and user.customers:
        q = q.where(Customer.id.in_([c.customer_id for c in user.customers]))
    return list(db.scalars(q))


def may_use_customer(db: Session, user: User, cust: Customer) -> bool:
    if user.role != "rep" or not user.customers:
        return True
    return any(c.customer_id == cust.id for c in user.customers)


def is_only_active_admin(db: Session, user: User) -> bool:
    return user.role == "admin" and db.query(User).filter(User.role == "admin", User.active.is_(True)).count() == 1


def can_approve_for(db: Session, me: User, owner_id: int) -> bool:
    """Managers approve their team; administrators everyone. Nobody approves their own, except the only administrator."""
    if me.role not in ("admin", "manager"):
        return False
    if owner_id == me.id:
        return is_only_active_admin(db, me)
    return owner_id in visible_user_ids(db, me)
