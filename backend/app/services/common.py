"""Settings, local time, document numbers, sync log and small helpers."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import APP_TZ
from ..models import AppSetting, DocSequence, SyncLog, User

TZ = ZoneInfo(APP_TZ)

DEFAULT_SETTINGS = {
    "company": {"name": "Samurai Foods", "gstin": "", "state": "09", "address": ""},
    "prefixes": {"order": "SO", "quote": "QT", "payment": "RC", "expense": "EX"},
    "quote_days": 15, "need_approval": True, "credit_check": "warn", "price_override": False, "round_off": True,
    "shift_start": "09:30", "grace_min": 15, "full_day_hrs": 8, "half_day_hrs": 4, "punch_needs_location": True,
    "maps_key": "", "geofence_m": 300,
    "dynamics": {"product": "bc", "base_url": "", "token": "", "tenant_id": "", "client_id": "", "client_secret": "",
                 "scope": "https://api.businesscentral.dynamics.com/.default", "payments_negative": True,
                 "ep": {"customers": "customers", "materials": "items", "prices": "", "hsn": "", "charges": "",
                        "quotes": "salesQuotes", "orders": "salesOrders", "payments": "", "expenses": ""}},
}
SECRET_KEYS = ("token", "client_secret")

STATES = {"01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
          "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
          "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
          "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
          "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
          "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
          "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory"}


def merge(base: dict, over: dict) -> dict:
    out = deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def get_settings(db: Session) -> dict:
    row = db.get(AppSetting, "settings")
    return merge(DEFAULT_SETTINGS, row.value if row else {})


def put_settings(db: Session, value: dict) -> dict:
    row = db.get(AppSetting, "settings")
    new = merge(get_settings(db), value)
    if row:
        row.value = new
    else:
        db.add(AppSetting(key="settings", value=new))
    return new


def public_settings(s: dict, admin: bool) -> dict:
    s = deepcopy(s)
    for k in SECRET_KEYS:
        if s["dynamics"].get(k):
            s["dynamics"][k] = "••••••" if admin else ""
    if not admin:
        s["dynamics"] = {"product": s["dynamics"]["product"]}
    return s


# ---------------- local time
def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ) if dt else None


def local_today() -> date:
    return datetime.now(TZ).date()


def local_at(d: date, hhmm: str) -> datetime:
    """UTC datetime for a local date and HH:MM."""
    h, m = (int(x) for x in (hhmm or "00:00").split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)


def iso_utc(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def fy_of(d: date) -> str:
    s = d.year if d.month >= 4 else d.year - 1
    return f"{str(s)[2:]}{str(s + 1)[2:]}"


def next_no(db: Session, kind: str, d: date) -> str:
    """Next document number for the financial year, e.g. SO2627-00001. The row lock keeps numbers unique."""
    fy = fy_of(d)
    seq = db.scalar(select(DocSequence).where(DocSequence.kind == kind, DocSequence.fy == fy).with_for_update())
    if not seq:
        seq = DocSequence(kind=kind, fy=fy, last=0)
        db.add(seq)
        db.flush()
    seq.last += 1
    prefix = get_settings(db)["prefixes"].get(kind, kind.upper()[:2])
    return f"{prefix}{fy}-{seq.last:05d}"


def log(db: Session, direction: str, entity: str, count: int, status: str, message: str, user: User | None):
    db.add(SyncLog(direction=direction, entity=entity, count=count, status=status, message=message[:2000],
                   user_name=user.name if user else ""))


def f(v) -> float | None:
    return None if v is None else float(v)


def r2(x) -> float:
    return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP"))


def parse_date(v, field="date") -> date | None:
    if v in (None, ""):
        return None
    try:
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(422, f"{field} is not a valid date.")


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def get_or_404(db: Session, model, id_, what: str):
    obj = db.get(model, id_)
    if not obj:
        raise HTTPException(404, f"That {what} does not exist. Reload the page.")
    return obj
