"""Database tables.

Masters (customers, materials, attributes, prices, HSN codes, charges) are written only by the
Dynamics download; no API endpoint creates or edits them. Transactions (quotations, sales orders,
payments, expense claims) carry a sync status and the Dynamics document number once they are there.
Times are stored in UTC; the local date of attendance is stored with it (APP_TZ)."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


Money = Numeric(15, 2)
Qty = Numeric(15, 3)


class SyncMixin:
    sync_status: Mapped[str] = mapped_column(String(10), default="na")   # na | pending | exported | synced | error
    sync_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ------------------------------------------------------------------ organisation
class Grade(Base):
    __tablename__ = "grades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    da_in: Mapped[Decimal] = mapped_column(Money, default=0)
    km_in: Mapped[Decimal] = mapped_column(Money, default=0)
    hotel_in: Mapped[Decimal] = mapped_column(Money, default=0)
    da_out: Mapped[Decimal] = mapped_column(Money, default=0)
    km_out: Mapped[Decimal] = mapped_column(Money, default=0)
    hotel_out: Mapped[Decimal] = mapped_column(Money, default=0)


class User(Base):
    """An employee. Every employee signs in; the role decides what they see."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default="rep")          # admin | manager | rep
    emp_code: Mapped[str] = mapped_column(String(40), default="")         # employee / salesperson no. in Dynamics
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    territory: Mapped[str] = mapped_column(String(80), default="")
    grade_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    customers: Mapped[list["UserCustomer"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class UserCustomer(Base):
    """Customers assigned to a sales representative. None assigned = every customer."""
    __tablename__ = "user_customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class DocSequence(Base):
    __tablename__ = "doc_sequences"
    __table_args__ = (UniqueConstraint("kind", "fy", name="uq_seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    fy: Mapped[str] = mapped_column(String(4))
    last: Mapped[int] = mapped_column(Integer, default=0)


# ------------------------------------------------------------------ masters (from Dynamics only)
class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    gstin: Mapped[str] = mapped_column(String(15), default="")
    state: Mapped[str] = mapped_column(String(2), default="")
    address: Mapped[str] = mapped_column(String(250), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    pin: Mapped[str] = mapped_column(String(10), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    price_group: Mapped[str] = mapped_column(String(40), default="")
    terms: Mapped[str] = mapped_column(String(40), default="")
    credit_limit: Mapped[Decimal] = mapped_column(Money, default=0)
    balance: Mapped[Decimal] = mapped_column(Money, default=0)            # Dynamics balance at download
    balance_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Visit location: kept in the portal only, never sent to Dynamics
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    tagged_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tagged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    uom: Mapped[str] = mapped_column(String(10), default="NOS")
    hsn: Mapped[str] = mapped_column(String(8), default="")
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    attributes: Mapped[list["MaterialAttribute"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                                 order_by="MaterialAttribute.id")


class MaterialAttribute(Base):
    __tablename__ = "material_attributes"
    __table_args__ = (UniqueConstraint("material_id", "name", name="uq_mat_attr"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(String(120), default="")


class Price(Base):
    __tablename__ = "prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(10))                      # all | group | customer
    code: Mapped[str] = mapped_column(String(40), default="")         # price group or customer code
    material_code: Mapped[str] = mapped_column(String(40), index=True)
    uom: Mapped[str] = mapped_column(String(10), default="")
    price: Mapped[Decimal] = mapped_column(Money)
    min_qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class HsnCode(Base):
    __tablename__ = "hsn_codes"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    cess: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)


class Charge(Base):
    __tablename__ = "charges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    calc: Mapped[str] = mapped_column(String(10), default="percent")  # percent | fixed
    value: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    sign: Mapped[int] = mapped_column(Integer, default=1)             # 1 add, -1 deduct
    stage: Mapped[str] = mapped_column(String(5), default="pre")      # pre: before GST | post: after GST
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ------------------------------------------------------------------ quotations and sales orders
class SalesDoc(SyncMixin, Base):
    __tablename__ = "sales_docs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(5), index=True)           # quote | order
    no: Mapped[str] = mapped_column(String(30), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    rep_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doc_date: Mapped[date] = mapped_column(Date, index=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    po_ref: Mapped[str] = mapped_column(String(60), default="")
    remarks: Mapped[str] = mapped_column(String(500), default="")
    # quote: draft | open | converted | cancelled ; order: draft | submitted | approved | cancelled
    status: Mapped[str] = mapped_column(String(10), index=True)
    chosen_charges: Mapped[list] = mapped_column(JSON, default=list)
    totals: Mapped[dict] = mapped_column(JSON, default=dict)
    total: Mapped[Decimal] = mapped_column(Money, default=0)
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("sales_docs.id", ondelete="SET NULL"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    lines: Mapped[list["SalesDocLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                       order_by="SalesDocLine.line_no")


class SalesDocLine(Base):
    __tablename__ = "sales_doc_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("sales_docs.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    material_code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    uom: Mapped[str] = mapped_column(String(10))
    hsn: Mapped[str] = mapped_column(String(8), default="")
    qty: Mapped[Decimal] = mapped_column(Qty)
    price: Mapped[Decimal] = mapped_column(Money)
    disc: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    taxable: Mapped[Decimal] = mapped_column(Money)
    gst: Mapped[Decimal] = mapped_column(Money)
    price_source: Mapped[str] = mapped_column(String(40), default="")


# ------------------------------------------------------------------ payments
class Payment(SyncMixin, Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no: Mapped[str] = mapped_column(String(30), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    rep_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    pay_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    mode: Mapped[str] = mapped_column(String(10))                      # cash | cheque | upi | neft | card
    ref: Mapped[str] = mapped_column(String(60), default="")
    bank: Mapped[str] = mapped_column(String(80), default="")
    cheque_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remarks: Mapped[str] = mapped_column(String(300), default="")
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    allocations: Mapped[list["PaymentAllocation"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_docs.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)


# ------------------------------------------------------------------ expenses
class ExpenseClaim(SyncMixin, Base):
    __tablename__ = "expense_claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no: Mapped[str] = mapped_column(String(30), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(3))                       # in | out
    date_from: Mapped[date] = mapped_column(Date, index=True)
    date_to: Mapped[date] = mapped_column(Date)
    purpose: Mapped[str] = mapped_column(String(200), default="")
    places: Mapped[str] = mapped_column(String(200), default="")
    km: Mapped[Decimal] = mapped_column(Numeric(10, 1), default=0)
    nights: Mapped[int] = mapped_column(Integer, default=0)
    hotel: Mapped[Decimal] = mapped_column(Money, default=0)
    hotel_name: Mapped[str] = mapped_column(String(120), default="")
    hotel_bill: Mapped[str] = mapped_column(String(60), default="")
    grade_code: Mapped[str] = mapped_column(String(20))
    rates: Mapped[dict] = mapped_column(JSON)                          # da, km, hotel at the time of the claim
    calc: Mapped[dict] = mapped_column(JSON)                           # days, fixed, variable, hotel, hotel_policy ...
    total: Mapped[Decimal] = mapped_column(Money, default=0)
    gps_km: Mapped[Decimal] = mapped_column(Numeric(10, 1), default=0)
    status: Mapped[str] = mapped_column(String(10), default="draft")   # draft | submitted | approved | rejected
    reject_reason: Mapped[str] = mapped_column(String(300), default="")
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    others: Mapped[list["ExpenseOther"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ExpenseOther(Base):
    __tablename__ = "expense_other"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("expense_claims.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Money)
    note: Mapped[str] = mapped_column(String(200), default="")


# ------------------------------------------------------------------ attendance
class Attendance(Base):
    """One Time In / Time Out session."""
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)          # local date (APP_TZ)
    in_at: Mapped[datetime] = mapped_column(DateTime)
    in_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    in_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    in_acc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_addr: Mapped[str] = mapped_column(String(250), default="")
    in_note: Mapped[str] = mapped_column(String(80), default="")
    out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    out_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    out_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    out_acc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    out_addr: Mapped[str] = mapped_column(String(250), default="")
    out_note: Mapped[str] = mapped_column(String(80), default="")
    source: Mapped[str] = mapped_column(String(10), default="app")    # app | correction


class AttendanceCorrection(Base):
    __tablename__ = "attendance_corrections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(3))                       # out | in | day
    in_time: Mapped[str] = mapped_column(String(5), default="")
    out_time: Mapped[str] = mapped_column(String(5), default="")
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    decided_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SyncLog(Base):
    __tablename__ = "sync_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    direction: Mapped[str] = mapped_column(String(3))                  # in | out
    entity: Mapped[str] = mapped_column(String(80))
    count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    user_name: Mapped[str] = mapped_column(String(120), default="")
