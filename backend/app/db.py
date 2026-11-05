"""Database engine, session factory and settings."""
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "mysql+pymysql://sales:sales@localhost:3306/sales_portal?charset=utf8mb4"
)
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret")
JWT_HOURS = int(os.getenv("JWT_HOURS", "8"))
APP_TZ = os.getenv("APP_TZ", "Asia/Kolkata")   # local time for attendance, shifts and document dates
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

_engine_args = {"pool_pre_ping": True, "future": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_args["connect_args"] = {"check_same_thread": False}
else:
    _engine_args["pool_recycle"] = 1800

engine = create_engine(DATABASE_URL, **_engine_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns() -> list[str]:
    """create_all makes new tables but never changes existing ones, so columns added in a later version
    are added here: nullable, no data touched. Returns what was added."""
    added = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as con:
        for t in Base.metadata.sorted_tables:
            if t.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(t.name)}
            for col in t.columns:
                if col.name in have:
                    continue
                typ = col.type.compile(dialect=engine.dialect)
                con.execute(text(f"ALTER TABLE {t.name} ADD COLUMN {col.name} {typ} NULL"))
                added.append(f"{t.name}.{col.name}")
    return added
