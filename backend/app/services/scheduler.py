"""Automatic download of the masters from Dynamics, every dynamics.auto_pull_minutes (0 = off).

Runs in each API worker; a database lock (MySQL GET_LOCK) and the time of the last run make sure only one of them
downloads at a time and not more often than set. Writes one line in the sync log only when the outcome changes
(a failure, or back to normal after one), so the log does not fill up every 5 minutes."""
import logging
import os
import sys
import threading
import time
from datetime import timedelta

from sqlalchemy import text

from ..db import SessionLocal, engine
from .common import get_settings, iso_utc, log, now_utc, put_settings

LOG = logging.getLogger("sales-portal.scheduler")
_local = threading.Lock()
TICK = 30


def _due(s: dict) -> bool:
    d = s["dynamics"]
    mins = int(d.get("auto_pull_minutes") or 0)
    if mins <= 0 or not any(d["ep"].get(k) for k in ("customers", "materials", "prices", "hsn", "charges", "attributes", "stock")):
        return False
    if not (d.get("token") or (d.get("tenant_id") and d.get("client_id") and d.get("client_secret"))):
        return False
    last = (s.get("auto_pull") or {}).get("at") or ""
    return last < iso_utc(now_utc() - timedelta(minutes=mins) + timedelta(seconds=TICK / 2))


def run_once(force: bool = False) -> dict | None:
    """One automatic download if it is due (or force). Returns its summary, None when not run."""
    from ..routers.integration import run_pull_all
    if not _local.acquire(blocking=False):
        return None
    try:
        mysql = engine.dialect.name == "mysql"
        # a MySQL lock belongs to one connection: held on its own connection for the whole run
        with engine.connect() as lock, SessionLocal() as db:
            if mysql and not lock.execute(text("SELECT GET_LOCK('sp_auto_pull', 0)")).scalar():
                return None                                  # the other worker is downloading
            try:
                s = get_settings(db)
                if not force and not _due(s):
                    return None
                put_settings(db, {"auto_pull": {**(s.get("auto_pull") or {}), "at": iso_utc(now_utc()), "running": True}})
                db.commit()
                try:
                    out = run_pull_all(db, None, quiet=True)
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    out = [{"entity": "all", "label": "Download", "status": "error", "message": str(getattr(e, "detail", e))}]
                errors = [[x["label"], x["message"]] for x in out if x["status"] == "error"]   # a list: settings merge dicts
                done = [x for x in out if x["status"] in ("ok", "warning")]
                s = get_settings(db)
                before = (s.get("auto_pull") or {}).get("errors") or []
                msg = (f"Automatic download: {len(done)} downloaded"
                       + (f"; failed: " + "; ".join(f"{k}: {v}" for k, v in errors) if errors else ""))
                if errors != before:                         # a new problem, or fixed
                    log(db, "in", "Masters (automatic)", sum(x.get("added", 0) + x.get("updated", 0) for x in done),
                        "error" if errors else "ok", msg[:2000], None)
                summary = {"at": iso_utc(now_utc()), "running": False, "errors": errors, "ok": len(done),
                           "added": sum(x.get("added", 0) for x in done)}
                put_settings(db, {"auto_pull": summary})
                db.commit()
                return summary
            finally:
                if mysql:
                    lock.execute(text("SELECT RELEASE_LOCK('sp_auto_pull')"))
    finally:
        _local.release()


def _loop():
    time.sleep(20)                                           # let the app start first
    while True:
        try:
            run_once()
        except Exception:  # noqa: BLE001
            LOG.exception("automatic download failed")
        time.sleep(TICK)


def start() -> None:
    if os.environ.get("SP_SCHEDULER", "1") == "0" or "pytest" in sys.modules:
        return
    threading.Thread(target=_loop, name="auto-pull", daemon=True).start()
