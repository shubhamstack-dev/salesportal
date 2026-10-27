"""Microsoft Dynamics exchange.

In:   customers, materials, attributes, prices, HSN codes, charges, from an Excel/CSV export or the API.
      Columns are recognised by Business Central / Finance and Operations names and can be re-mapped.
Out:  quotations, approved orders, payments and approved expense claims, as an Excel file in Dynamics import
      layout or posted to the API. File route: status 'exported' until the Dynamics numbers are imported back.
The API is called from this server, so browser CORS rules do not apply. Tokens come from Microsoft Entra ID
with the client-credentials flow (tenant, client id, secret), or from a pasted token."""
import csv
import io
import json
import os
import re
import tempfile
import time
import uuid
from datetime import date, datetime

import httpx
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (Charge, Customer, ExpenseClaim, HsnCode, Material, MaterialAttribute, Payment, Price, SalesDoc, User)
from .common import STATES, get_settings, now_utc, r2

ENT = {
    "customers": {"label": "Customers", "hint": r"customer", "fields": {
        "code": ["No.", "No", "Customer No.", "Customer Code", "Code", "number", "CustomerAccount", "AccountNum"],
        "name": ["Name", "Customer Name", "displayName", "OrganizationName", "CustomerName"],
        "gstin": ["GST Registration No.", "GSTIN", "GST No.", "GST No", "gstRegistrationNo", "TaxRegistrationNumber"],
        "state": ["State Code", "GST State Code", "State", "state", "AddressState"],
        "address": ["Address", "addressLine1", "AddressStreet"], "city": ["City", "city", "AddressCity"],
        "pin": ["Post Code", "PIN Code", "PIN", "Pincode", "postalCode", "AddressZipCode"],
        "phone": ["Phone No.", "Mobile Phone No.", "Phone", "phoneNumber"], "email": ["E-Mail", "Email", "email"],
        "price_group": ["Customer Price Group", "Price Group", "customerPriceGroup", "PriceGroup"],
        "terms": ["Payment Terms Code", "Payment Terms", "paymentTermsId"],
        "credit_limit": ["Credit Limit (LCY)", "Credit Limit", "creditLimit"],
        "balance": ["Balance (LCY)", "Balance", "balanceDue", "Balance Due (LCY)"], "blocked": ["Blocked", "blocked"]}},
    "materials": {"label": "Materials", "hint": r"^(?!.*(attrib|price)).*(item|material|product)", "fields": {
        "code": ["No.", "No", "Item No.", "Item Code", "Code", "number", "ItemNumber", "ProductNumber"],
        "name": ["Description", "Name", "Item Name", "displayName", "ProductName"],
        "uom": ["Sales Unit of Measure", "Base Unit of Measure", "UOM", "Unit", "baseUnitOfMeasureCode", "SalesUnitSymbol"],
        "hsn": ["HSN/SAC Code", "HSN Code", "HSN", "HSNCode", "hsnSacCode"],
        "category": ["Item Category Code", "Category", "itemCategoryCode"], "price": ["Unit Price", "unitPrice", "Price"],
        "blocked": ["Blocked", "Sales Blocked", "blocked"]}},
    "attributes": {"label": "Material attributes", "hint": r"attrib", "fields": {
        "material": ["Item No.", "No.", "Item", "ItemNumber", "Material"], "name": ["Attribute", "Attribute Name", "Name"],
        "value": ["Value", "Attribute Value"]}},
    "prices": {"label": "Prices", "hint": r"price", "fields": {
        "type": ["Sales Type", "Assign-to Type", "Price Type", "Type", "AccountCode"],
        "code": ["Sales Code", "Assign-to No.", "Customer Price Group", "Customer No.", "AccountRelation", "Code"],
        "material": ["Item No.", "Product No.", "Asset No.", "No.", "ItemNumber", "ItemRelation"],
        "uom": ["Unit of Measure Code", "Unit of Measure", "UOM", "UnitId"], "price": ["Unit Price", "Price", "Amount", "unitPrice"],
        "min_qty": ["Minimum Quantity", "Min. Quantity", "Min Qty", "QuantityAmountFrom"],
        "from": ["Starting Date", "Valid From", "From Date", "FromDate"], "to": ["Ending Date", "Valid To", "To Date", "ToDate"]}},
    "hsn": {"label": "HSN codes", "hint": r"hsn|gst|sac", "fields": {
        "code": ["HSN/SAC Code", "Code", "HSN", "HSN Code"], "description": ["Description", "Name"],
        "rate": ["GST %", "GST Rate", "GST Rate %", "Rate", "Tax %"], "cess": ["Cess %", "Cess"]}},
    "charges": {"label": "Charges", "hint": r"charge", "fields": {
        "code": ["Code", "Charge Code", "Charge No.", "No."], "name": ["Description", "Charge Name", "Name"],
        "calc": ["Calculation Type", "Calculation", "Calc Type", "Type"], "value": ["Value", "Rate %", "Rate", "Percentage", "Charge %", "Amount"],
        "sign": ["Charge or Discount", "Add/Deduct", "Nature", "Sign"], "stage": ["Applied On", "Calculate On", "After GST", "Stage"],
        "auto": ["Mandatory", "Apply Always", "Auto", "Default"], "active": ["Active", "Blocked", "Status"]}},
}

# Uploaded rows wait here between the preview and Apply. A folder rather than memory, so it works with several
# server workers. Entries older than 30 minutes are removed.
IMPORT_DIR = os.getenv("IMPORT_DIR", os.path.join(tempfile.gettempdir(), "sales-portal-imports"))


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9%]", "", str(s).lower())


def auto_map(ent: str, headers: list[str]) -> dict:
    out = {}
    for field, aliases in ENT[ent]["fields"].items():
        hit = next((h for a in aliases for h in headers if _norm(h) == _norm(a)), "")
        out[field] = hit
    return out


def _cell(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def read_file(data: bytes, filename: str) -> list[dict]:
    """[{name, headers, rows: [dict]}] for every sheet with data."""
    if filename.lower().endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        return [{"name": filename, "headers": list(rows[0].keys()) if rows else [], "rows": rows}] if rows else []
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception:
        raise HTTPException(422, "That file could not be read as Excel (.xlsx) or CSV.")
    sheets = []
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        head = next(it, None)
        if not head:
            continue
        headers = [str(h).strip() if h is not None else f"Column {i + 1}" for i, h in enumerate(head)]
        rows = [{headers[i]: _cell(v) for i, v in enumerate(r) if i < len(headers)} for r in it if any(v not in (None, "") for v in r)]
        if rows:
            sheets.append({"name": ws.title, "headers": headers, "rows": rows})
    return sheets


def stash(sheets: list[dict], source: str) -> str:
    os.makedirs(IMPORT_DIR, exist_ok=True)
    for name in os.listdir(IMPORT_DIR):
        path = os.path.join(IMPORT_DIR, name)
        if time.time() - os.path.getmtime(path) > 1800:
            os.remove(path)
    key = uuid.uuid4().hex
    with open(os.path.join(IMPORT_DIR, key + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"sheets": sheets, "source": source}, fh, default=str)
    return key


def unstash(key: str) -> dict:
    path = os.path.join(IMPORT_DIR, re.sub(r"[^a-f0-9]", "", key) + ".json")
    if not os.path.exists(path):
        raise HTTPException(410, "The uploaded data has expired. Choose the file again.")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def pick_sheet(ent: str, sheets: list[dict]) -> int:
    return next((i for i, s in enumerate(sheets) if re.search(ENT[ent]["hint"], s["name"], re.I)), 0)


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").replace("₹", "").strip() or 0)
    except ValueError:
        return 0.0


def _yes(v) -> bool:
    return v is True or bool(re.fullmatch(r"(yes|true|1|y|all|ship|invoice)", _s(v), re.I))


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _s(v)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    return None


def _state(v, gstin: str) -> str:
    s = _s(v)
    if re.fullmatch(r"\d{1,2}", s):
        return s.zfill(2)
    hit = next((k for k, n in STATES.items() if n.lower() == s.lower()), "")
    return hit or (gstin[:2] if re.match(r"^\d{2}", gstin) else "")


def apply_rows(db: Session, ent: str, rows: list[dict], m: dict, dry: bool) -> dict:
    """Upserts the rows (or only counts them when dry). Returns added, updated, skipped and first errors."""
    get = lambda r, k: r.get(m.get(k)) if m.get(k) else None  # noqa: E731
    res = {"added": 0, "updated": 0, "skipped": 0, "errors": []}
    now = now_utc()

    def skip(i, why):
        res["skipped"] += 1
        if len(res["errors"]) < 20:
            res["errors"].append(f"Row {i + 2}: {why}")

    if ent == "customers":
        for i, r in enumerate(rows):
            code, name = _s(get(r, "code")), _s(get(r, "name"))
            if not code or not name:
                skip(i, "no customer number or name"); continue
            gstin = _s(get(r, "gstin")).upper()[:15]
            c = db.scalar(select(Customer).where(Customer.code == code))
            res["updated" if c else "added"] += 1
            if dry:
                continue
            c = c or Customer(code=code)
            c.name, c.gstin, c.state = name[:160], gstin, _state(get(r, "state"), gstin)
            c.address, c.city, c.pin = _s(get(r, "address"))[:250], _s(get(r, "city"))[:80], _s(get(r, "pin"))[:10]
            c.phone, c.email, c.price_group, c.terms = _s(get(r, "phone"))[:40], _s(get(r, "email"))[:120], _s(get(r, "price_group"))[:40], _s(get(r, "terms"))[:40]
            c.credit_limit, c.balance, c.balance_at, c.synced_at = _num(get(r, "credit_limit")), _num(get(r, "balance")), now, now
            c.blocked = _yes(get(r, "blocked")) if m.get("blocked") else False
            db.add(c)
    elif ent == "materials":
        for i, r in enumerate(rows):
            code, name = _s(get(r, "code")), _s(get(r, "name"))
            if not code or not name:
                skip(i, "no item number or description"); continue
            mat = db.scalar(select(Material).where(Material.code == code))
            res["updated" if mat else "added"] += 1
            if dry:
                continue
            mat = mat or Material(code=code)
            mat.name, mat.uom = name[:200], (_s(get(r, "uom")) or "NOS")[:10]
            mat.hsn = re.sub(r"\.0+$", "", _s(get(r, "hsn")))[:8]
            mat.blocked = _yes(get(r, "blocked")) if m.get("blocked") else False
            mat.synced_at = now
            db.add(mat)
            db.flush()
            cat = _s(get(r, "category"))
            if cat:
                a = next((x for x in mat.attributes if x.name == "Category"), None)
                if a:
                    a.value = cat
                else:
                    mat.attributes.append(MaterialAttribute(name="Category", value=cat))
            price = _num(get(r, "price"))
            if m.get("price") and price > 0:
                p = db.scalar(select(Price).where(Price.type == "all", Price.material_code == code, Price.min_qty == 0,
                                                  Price.valid_from.is_(None), Price.valid_to.is_(None)))
                if p:
                    p.price, p.uom = price, mat.uom
                else:
                    db.add(Price(type="all", code="", material_code=code, uom=mat.uom, price=price, min_qty=0))
    elif ent == "attributes":
        mats = {x.code: x for x in db.scalars(select(Material))}
        for i, r in enumerate(rows):
            mat, name = mats.get(_s(get(r, "material"))), _s(get(r, "name"))
            if not mat or not name:
                skip(i, "no attribute name" if mat else f"item {_s(get(r, 'material'))} is not in the materials"); continue
            a = next((x for x in mat.attributes if x.name == name), None)
            res["updated" if a else "added"] += 1
            if dry:
                continue
            if a:
                a.value = _s(get(r, "value"))[:120]
            else:
                mat.attributes.append(MaterialAttribute(name=name[:60], value=_s(get(r, "value"))[:120]))
    elif ent == "prices":
        codes = set(db.scalars(select(Material.code)))
        fresh = []
        for i, r in enumerate(rows):
            mat, price = _s(get(r, "material")), _num(get(r, "price"))
            if mat not in codes or price <= 0:
                skip(i, f"item {mat} is not in the materials" if mat not in codes else "no unit price"); continue
            code, typ = _s(get(r, "code")), _s(get(r, "type")).lower()
            kind = "group" if "group" in typ else "all" if ("all" in typ or (not typ and not code)) else "customer" if ("customer" in typ or typ == "0") else ("group" if code else "all")
            fresh.append(Price(type=kind, code="" if kind == "all" else code[:40], material_code=mat, uom=_s(get(r, "uom"))[:10], price=price,
                               min_qty=_num(get(r, "min_qty")), valid_from=_date(get(r, "from")), valid_to=_date(get(r, "to"))))
        res["added"], res["updated"] = len(fresh), db.query(Price).count()
        if not dry:
            db.query(Price).delete()
            db.add_all(fresh)
    elif ent == "hsn":
        for i, r in enumerate(rows):
            code = re.sub(r"\.0+$", "", _s(get(r, "code")))
            if not re.fullmatch(r"\d{4,8}", code):
                skip(i, f'"{code}" is not an HSN/SAC code'); continue
            h = db.get(HsnCode, code)
            res["updated" if h else "added"] += 1
            if dry:
                continue
            h = h or HsnCode(code=code)
            h.description, h.rate, h.cess = _s(get(r, "description"))[:200], _num(get(r, "rate")), _num(get(r, "cess"))
            db.add(h)
    elif ent == "charges":
        fresh = []
        known = set(db.scalars(select(Charge.code)))
        for i, r in enumerate(rows):
            code, name, value = _s(get(r, "code")).upper(), _s(get(r, "name")), _num(get(r, "value"))
            if not code or not name or not value:
                skip(i, "no code, name or rate"); continue
            sign_t, stage_t = _s(get(r, "sign")).lower(), _s(get(r, "stage")).lower()
            sign = -1 if re.search(r"deduct|discount|less|minus|^-1$", sign_t) or value < 0 else 1
            post = bool(re.search(r"after|post|invoice|total|tcs", stage_t)) or (re.search("after", m.get("stage") or "", re.I) and _yes(get(r, "stage"))) \
                or (not m.get("stage") and re.search("tcs", code + name, re.I))
            act = get(r, "active")
            active = True if not m.get("active") else (not _yes(act)) if re.search("blocked", m["active"], re.I) \
                else not re.search(r"inactive|blocked|^no$|false|^0$", _s(act), re.I)
            fresh.append(Charge(code=code[:20], name=name[:80], calc="fixed" if re.search(r"fix|amount|lump", _s(get(r, "calc")), re.I) else "percent",
                                value=abs(value), sign=sign, stage="post" if post else "pre", auto=_yes(get(r, "auto")) if m.get("auto") else False, active=active))
            res["updated" if code in known else "added"] += 1
        if not dry:
            db.query(Charge).delete()
            db.flush()
            db.add_all(fresh)
    return res


# ------------------------------------------------------------------ API
def access_token(s: dict) -> str:
    d = s["dynamics"]
    if d.get("tenant_id") and d.get("client_id") and d.get("client_secret"):
        try:
            r = httpx.post(f"https://login.microsoftonline.com/{d['tenant_id']}/oauth2/v2.0/token", timeout=30,
                           data={"grant_type": "client_credentials", "client_id": d["client_id"], "client_secret": d["client_secret"],
                                 "scope": d.get("scope") or "https://api.businesscentral.dynamics.com/.default"})
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Could not reach Microsoft Entra ID: {e}")
        if r.status_code != 200:
            raise HTTPException(502, f"Microsoft Entra ID refused the credentials ({r.status_code}): {r.json().get('error_description', '')[:200] if r.headers.get('content-type','').startswith('application/json') else ''}")
        return r.json()["access_token"]
    if d.get("token"):
        return d["token"]
    raise HTTPException(422, "Set the Entra ID tenant, client id and secret (or paste a token) under Dynamics connection.")


def api_url(s: dict, path: str) -> str:
    base = (s["dynamics"].get("base_url") or "").rstrip("/")
    if not base and not path.startswith("http"):
        raise HTTPException(422, "Enter the Dynamics API address under Dynamics connection.")
    return path if path.startswith("http") else f"{base}/{path.lstrip('/')}"


def api_call(s: dict, token: str, path: str, method="GET", body=None) -> dict:
    try:
        r = httpx.request(method, api_url(s, path), json=body, timeout=60,
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach Dynamics: {e}")
    data = r.json() if r.content and "json" in r.headers.get("content-type", "") else {}
    if r.status_code >= 400:
        msg = (data.get("error") or {}).get("message") if isinstance(data, dict) else ""
        raise HTTPException(502, f"Dynamics returned {r.status_code}{': ' + msg if msg else ''}")
    return data


def api_pull(s: dict, ent: str) -> list[dict]:
    ep = s["dynamics"]["ep"].get(ent)
    if not ep:
        raise HTTPException(422, f"No API endpoint is set for {ENT[ent]['label'].lower()}. Use a file, or set the endpoint.")
    token, url, rows, pages = access_token(s), ep, [], 0
    while url and pages < 500:
        b = api_call(s, token, url)
        rows += [{k: v for k, v in x.items() if not k.startswith("@") and (v is None or not isinstance(v, (dict, list)))} for x in b.get("value", [])]
        url, pages = b.get("@odata.nextLink"), pages + 1
    return rows


# ------------------------------------------------------------------ out
def out_queues(db: Session) -> dict:
    waiting = ("pending", "error")
    return {
        "quotes": list(db.scalars(select(SalesDoc).where(SalesDoc.kind == "quote", SalesDoc.status.in_(["open", "converted"]), SalesDoc.sync_status.in_(waiting)))),
        "orders": list(db.scalars(select(SalesDoc).where(SalesDoc.kind == "order", SalesDoc.status == "approved", SalesDoc.sync_status.in_(waiting)))),
        "payments": list(db.scalars(select(Payment).where(Payment.cancelled.is_(False), Payment.sync_status.in_(waiting)))),
        "expenses": list(db.scalars(select(ExpenseClaim).where(ExpenseClaim.status == "approved", ExpenseClaim.sync_status.in_(waiting)))),
    }


def _emp(db: Session, uid: int) -> User:
    return db.get(User, uid)


def expense_lines(db: Session, x: ExpenseClaim) -> list[dict]:
    u = _emp(db, x.user_id)
    c, r = x.calc, x.rates
    base = {"Posting Date": x.date_to.isoformat(), "Document No.": x.no, "Account Type": "Employee", "Account No.": u.emp_code, "Employee Name": u.name,
            "Grade": x.grade_code, "From Date": x.date_from.isoformat(), "To Date": x.date_to.isoformat(), "Station": "Out-station" if x.type == "out" else "In-station"}
    rows = []
    if c["fixed"]:
        rows.append({**base, "Expense Type": "DA", "Description": f"Daily allowance {c['days']} day(s) x {r['da']}", "Quantity": c["days"], "Rate": r["da"], "Amount": c["fixed"]})
    if c["variable"]:
        rows.append({**base, "Expense Type": "TRAVEL", "Description": f"Travel {float(x.km)} km x {r['km']}", "Quantity": float(x.km), "Rate": r["km"], "Amount": c["variable"]})
    if c["hotel"]:
        rows.append({**base, "Expense Type": "HOTEL", "Description": f"Hotel {x.nights} night(s) {x.hotel_name} {('bill ' + x.hotel_bill) if x.hotel_bill else ''}".strip(),
                     "Quantity": x.nights, "Rate": r2(c["hotel"] / x.nights) if x.nights else c["hotel"], "Amount": c["hotel"]})
    for o in x.others:
        rows.append({**base, "Expense Type": "OTHER", "Description": f"{o.category}: {o.note}", "Quantity": 1, "Rate": float(o.amount), "Amount": float(o.amount)})
    return rows


def doc_header(db: Session, d: SalesDoc) -> dict:
    c, rep = db.get(Customer, d.customer_id), _emp(db, d.rep_id)
    h = {"Document Type": "Quote" if d.kind == "quote" else "Order", "External Document No.": d.no, "Sell-to Customer No.": c.code,
         "Document Date": d.doc_date.isoformat(), "Salesperson Code": rep.emp_code, "Your Reference": d.po_ref, "Amount Including GST": float(d.total), "Remarks": d.remarks}
    if d.kind == "quote":
        h["Quote Valid Until Date"] = d.valid_to.isoformat() if d.valid_to else ""
    else:
        h["Requested Delivery Date"] = d.delivery_date.isoformat() if d.delivery_date else ""
        q = db.get(SalesDoc, d.quote_id) if d.quote_id else None
        h["Quote No."] = q.no if q else ""
    return h


def doc_lines(d: SalesDoc) -> list[dict]:
    return [{"External Document No.": d.no, "Line No.": l.line_no * 10000, "Type": "Item", "No.": l.material_code, "Description": l.name,
             "Unit of Measure Code": l.uom, "Quantity": float(l.qty), "Unit Price": float(l.price), "Line Discount %": float(l.disc),
             "HSN/SAC Code": l.hsn, "GST %": float(l.gst_rate), "Line Amount": float(l.taxable)} for l in d.lines]


def doc_charges(d: SalesDoc) -> list[dict]:
    t = d.totals or {}
    return [{"External Document No.": d.no, "Charge Code": c["code"], "Description": c["name"], "Amount": c["amount"], "Before GST": "Yes" if c in t.get("pre", []) else "No"}
            for c in t.get("pre", []) + t.get("post", [])]


def payment_row(db: Session, p: Payment, negative: bool) -> dict:
    c, rep = db.get(Customer, p.customer_id), _emp(db, p.rep_id)
    return {"Posting Date": p.pay_date.isoformat(), "Document Type": "Payment", "Document No.": p.no, "Account Type": "Customer", "Account No.": c.code,
            "Amount": -float(p.amount) if negative else float(p.amount), "Payment Method Code": p.mode.upper(), "External Document No.": p.ref,
            "Description": f"{p.mode.upper()} {p.ref}".strip(), "Applies-to Orders": " ".join(db.get(SalesDoc, a.order_id).no for a in p.allocations),
            "Received By": rep.emp_code}


def order_payload(db: Session, d: SalesDoc) -> dict:
    c, rep = db.get(Customer, d.customer_id), _emp(db, d.rep_id)
    lines = [{"lineType": "Item", "lineObjectNumber": l.material_code, "quantity": float(l.qty), "unitPrice": float(l.price),
              "discountPercent": float(l.disc), "unitOfMeasureCode": l.uom or None} for l in d.lines]
    body = {"customerNumber": c.code, "externalDocumentNumber": d.no, "salesperson": rep.emp_code or None}
    if d.kind == "quote":
        body.update(documentDate=d.doc_date.isoformat(), dueDate=d.valid_to.isoformat() if d.valid_to else None, salesQuoteLines=lines)
    else:
        body.update(orderDate=d.doc_date.isoformat(), requestedDeliveryDate=d.delivery_date.isoformat() if d.delivery_date else None, salesOrderLines=lines)
    return {k: v for k, v in body.items() if v is not None}
