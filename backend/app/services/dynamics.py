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
from urllib.parse import quote
from datetime import date, datetime

import httpx
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import (Charge, Customer, ExpenseClaim, HsnCode, Material, MaterialAttribute, Payment, Price, SalesDoc, StockEntry, User)
from .common import STATES, get_settings, now_utc, r2

ENT = {
    "customers": {"label": "Customers", "hint": r"customer", "fields": {
        "code": ["No.", "No", "Customer No.", "Customer Code", "Code", "number", "CustomerAccount", "AccountNum"],
        "name": ["Name", "Customer Name", "displayName", "OrganizationName", "CustomerName"],
        "gstin": ["GST Registration No.", "GSTIN", "GST No.", "GST No", "gstRegistrationNo", "TaxRegistrationNumber"],
        "state": ["State Code", "GST State Code", "State", "state", "AddressState", "County"],
        "name2": ["Name 2", "name2"], "address": ["Address", "addressLine1", "AddressStreet"],
        "address2": ["Address 2", "addressLine2"], "city": ["City", "city", "AddressCity"],
        "pin": ["Post Code", "PIN Code", "PIN", "Pincode", "postalCode", "AddressZipCode"],
        "phone": ["Phone No.", "Mobile Phone No.", "Phone", "phoneNumber", "mobilePhoneNumber"], "email": ["E-Mail", "Email", "email"],
        "price_group": ["Customer Price Group", "Price Group", "customerPriceGroup", "PriceGroup"],
        "terms": ["Payment Terms Code", "Payment Terms", "paymentTermsCode", "paymentTermsId"],
        "credit_limit": ["Credit Limit (LCY)", "Credit Limit", "creditLimit"],
        "balance": ["Balance (LCY)", "Balance", "balanceDue", "Balance Due (LCY)"], "blocked": ["Blocked", "blocked"]}},
    "materials": {"label": "Materials", "hint": r"^(?!.*(attrib|price)).*(item|material|product)", "fields": {
        "code": ["No.", "No", "Item No.", "Item Code", "Code", "number", "ItemNumber", "ProductNumber"],
        "name": ["Description", "Name", "Item Name", "displayName", "ProductName"],
        "uom": ["Sales Unit of Measure", "Base Unit of Measure", "UOM", "Unit", "baseUnitOfMeasureCode", "SalesUnitSymbol", "Base Unit of Measure Code"],
        "hsn": ["HSN/SAC Code", "HSN Code", "HSN", "HSNCode", "hsnSacCode", "HSN SAC Code"],
        "category": ["Item Category Code", "Category", "itemCategoryCode"], "price": ["Unit Price", "unitPrice", "Price"],
        "mrp": ["MRP", "MRP Price", "Maximum Retail Price", "MRP/Kg"],
        "pack": ["Pack Size", "Net Weight", "netWeight", "Qty per Pack", "Pack Qty"],
        "incl": ["Price Includes VAT", "Price Inclusive of Tax", "Price Includes Tax", "Price Incl. Tax", "priceIncludesTax"],
        "blocked": ["Blocked", "Sales Blocked", "blocked"]}},
    "attributes": {"label": "Material attributes", "hint": r"attrib", "fields": {
        "material": ["Item No.", "No.", "Item", "ItemNumber", "Material", "itemNumber"],
        "name": ["Attribute", "Attribute Name", "Item Attribute Name", "Name", "attributeName"],
        "value": ["Value", "Attribute Value", "Item Attribute Value", "attributeValue"]}},
    "prices": {"label": "Prices", "hint": r"price", "fields": {
        "type": ["Sales Type", "Source Type", "Assign-to Type", "Type", "AccountCode"],
        "code": ["Sales Code", "Source No.", "Assign-to No.", "Customer Price Group", "Customer No.", "AccountRelation", "Code"],
        "material": ["Item No.", "Product No.", "Asset No.", "No.", "ItemNumber", "ItemRelation"],
        "uom": ["Unit of Measure Code", "Unit of Measure", "UOM", "UnitId"], "price": ["Unit Price", "Price", "Amount", "unitPrice"],
        "min_qty": ["Minimum Quantity", "Min. Quantity", "Min Qty", "QuantityAmountFrom"],
        "from": ["Starting Date", "Valid From", "From Date", "FromDate"], "to": ["Ending Date", "Valid To", "To Date", "ToDate"],
        "status": ["Status", "Line Status"], "price_type": ["Price Type"], "incl": ["Price Includes VAT", "Price Inclusive of Tax", "Price Includes Tax", "Price Incl. Tax", "priceIncludesTax"]}},
    "hsn": {"label": "HSN codes", "hint": r"hsn|gst|sac", "fields": {
        "code": ["HSN/SAC Code", "Code", "HSN", "HSN Code"], "description": ["Description", "Name"],
        "rate": ["GST %", "GST Rate", "GST Rate %", "Rate", "Tax %"], "cess": ["Cess %", "Cess"],
        "gst_group": ["GST Group Code", "GST Group"]}},
    "charges": {"label": "Charges", "hint": r"charge", "fields": {
        "code": ["Code", "Charge Code", "Charge No.", "No."], "name": ["Description", "Charge Name", "Name"],
        "calc": ["Calculation Type", "Calculation", "Calc Type", "Type"], "value": ["Value", "Rate %", "Rate", "Percentage", "Charge %", "Amount"],
        "sign": ["Charge or Discount", "Add/Deduct", "Nature", "Sign"], "stage": ["Applied On", "Calculate On", "After GST", "Stage"],
        "auto": ["Mandatory", "Apply Always", "Auto", "Default"], "active": ["Active", "Blocked", "Status"]}},
    "stock": {"label": "Stock by location", "hint": r"stock|inventor|ledger", "fields": {
        "material": ["Item No.", "Item_No", "itemNumber", "Item", "No."],
        "location": ["Location Code", "Location_Code", "locationCode", "Location"],
        "qty": ["Remaining Quantity", "Remaining_Quantity", "Inventory", "Quantity on Hand", "Qty. on Hand", "Quantity"],
        "lot": ["Lot No.", "Lot_No", "lotNumber", "Lot"], "expiry": ["Expiration Date", "Expiration_Date", "Expiry Date", "expirationDate"],
        "open": ["Open", "open"]}},
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
    """Business Central sends 0001-01-01 for an empty date; that means no date."""
    if isinstance(v, datetime):
        v = v.date()
    if isinstance(v, date):
        return v if v.year >= 1900 else None
    s = _s(v)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3])) if int(m[1]) >= 1900 else None
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    return None


STATE_ABBR = {"JK": "01", "HP": "02", "PB": "03", "CH": "04", "UK": "05", "UT": "05", "HR": "06", "DL": "07", "RJ": "08", "UP": "09",
              "BR": "10", "SK": "11", "AR": "12", "NL": "13", "MN": "14", "MZ": "15", "TR": "16", "ML": "17", "AS": "18", "WB": "19",
              "JH": "20", "OD": "21", "OR": "21", "CG": "22", "CT": "22", "MP": "23", "GJ": "24", "DN": "26", "DD": "26", "MH": "27",
              "KA": "29", "GA": "30", "LD": "31", "KL": "32", "TN": "33", "PY": "34", "AN": "35", "TS": "36", "TG": "36", "AP": "37", "LA": "38"}


def _state(v, gstin: str) -> str:
    s = _s(v)
    if re.fullmatch(r"\d{1,2}", s):
        return s.zfill(2)
    if s.upper() in STATE_ABBR:
        return STATE_ABBR[s.upper()]
    hit = next((k for k, n in STATES.items() if n.lower() == s.lower()), "")
    return hit or (gstin[:2] if re.match(r"^\d{2}", gstin) else "")


GST_RATES = (0, 0.1, 0.25, 1.5, 3, 5, 6, 7.5, 12, 18, 28, 40)


def rate_from_group(v) -> float:
    """Business Central keeps GST rates in its tax engine, not on the HSN code. GST group codes are usually named
    after the rate (GST18, 18%, G-5), so the rate is read from the code when it is one of the GST slabs."""
    m = re.search(r"\d+(?:\.\d+)?", _s(v))
    return float(m[0]) if m and float(m[0]) in GST_RATES else 0.0


BLANK = "(blank)"


def rate_key(grp: str, code: str) -> str:
    """The key a GST rate is entered under: the GST group, or the HSN code itself when Dynamics sends no group."""
    return grp.strip() if grp.strip() else f"HSN {code}"


def group_rate(key: str, gst_rates: dict | None) -> float:
    """The rate entered in the portal for this GST group (or HSN code), else read from the group's name (GST18 -> 18)."""
    rates = {str(k).strip().upper(): v for k, v in (gst_rates or {}).items()}
    if key.strip().upper() in rates and rates[key.strip().upper()] not in ("", None):
        return _num(rates[key.strip().upper()])
    return 0.0 if key.startswith("HSN ") else rate_from_group(key)


def gst_groups(rows: list[dict], m: dict, gst_rates: dict | None) -> list[dict]:
    """What a GST rate has to be entered for in the import dialog: each GST group, or each HSN code when the
    HSN page sends no GST group."""
    if m.get("rate") or not m.get("code"):
        return []
    seen: dict[str, int] = {}
    for r in rows:
        code = re.sub(r"\.0+$", "", _s(r.get(m["code"])))
        if not re.fullmatch(r"\d{4,8}", code):
            continue
        k = rate_key(_s(r.get(m["gst_group"])) if m.get("gst_group") else "", code)
        seen[k] = seen.get(k, 0) + 1
    known = {str(k).strip().upper() for k, v in (gst_rates or {}).items() if v not in ("", None)}
    return [{"code": k, "hsn": n, "rate": group_rate(k, gst_rates), "set": k.upper() in known, "by_hsn": k.startswith("HSN ")}
            for k, n in sorted(seen.items())]


def pack_qty(given: float, code: str, uom: str) -> float:
    """Units in one packet, used to print Pkts. From Dynamics when it has a pack size or net weight; otherwise read from
    an item number ending in the pack weight in grams (SF-001-500 = 0.5 kg, SF-010-1000 = 1 kg) when sold by the kg."""
    if given > 0:
        return given
    m = re.search(r"-(\d{2,5})\.?$", code or "")
    if m and (uom or "").upper() in ("KG", "KGS", "KILOGRAM"):
        g = int(m[1])
        if 50 <= g <= 50000:
            return g / 1000
    return 0.0


def apply_rows(db: Session, ent: str, rows: list[dict], m: dict, dry: bool, gst_rates: dict | None = None, full: bool = False) -> dict:
    """full: rows are the whole list from the Dynamics API, so customers and items not in it were deleted there."""
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
            if c.status == "removed":                    # back in Dynamics
                c.status = None
            c.name, c.gstin, c.state = name[:160], gstin, _state(get(r, "state"), gstin)
            addr = "\n".join(x for x in (_s(get(r, "name2")), _s(get(r, "address")), _s(get(r, "address2"))) if x)
            c.address, c.city, c.pin = addr[:250], _s(get(r, "city"))[:80], _s(get(r, "pin"))[:10]
            c.phone, c.email, c.price_group, c.terms = _s(get(r, "phone"))[:40], _s(get(r, "email"))[:120], _s(get(r, "price_group"))[:40], _s(get(r, "terms"))[:40]
            c.credit_limit, c.balance, c.balance_at, c.synced_at = _num(get(r, "credit_limit")), _num(get(r, "balance")), now, now
            c.blocked = _yes(get(r, "blocked")) if m.get("blocked") else False
            db.add(c)
        if full:
            drop_missing(db, "customers", {_s(get(r, "code")) for r in rows}, res, dry)
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
            # MRP: its own column when Dynamics has one, else the item's Unit Price (the list price before customer prices)
            mat.mrp = _num(get(r, "mrp")) if m.get("mrp") else _num(get(r, "price"))
            mat.pack_qty = pack_qty(_num(get(r, "pack")) if m.get("pack") else 0, code, mat.uom)
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
                incl = _yes(get(r, "incl")) if m.get("incl") else None
                if p:
                    p.price, p.uom, p.incl_gst = price, mat.uom, incl
                else:
                    db.add(Price(type="all", code="", material_code=code, uom=mat.uom, price=price, min_qty=0, incl_gst=incl))
        if full:
            drop_missing(db, "materials", {_s(get(r, "code")) for r in rows}, res, dry)
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
            if m.get("price_type") and re.search(r"purchase", _s(get(r, "price_type")), re.I):
                skip(i, "purchase price"); continue
            if m.get("status") and _s(get(r, "status")) and not re.fullmatch(r"active", _s(get(r, "status")), re.I):
                skip(i, f"price list line is {_s(get(r, 'status')).lower()}, not active"); continue
            mat, price = _s(get(r, "material")), _num(get(r, "price"))
            if mat not in codes or price <= 0:
                skip(i, f"item {mat} is not in the materials" if mat not in codes else "no unit price"); continue
            code, typ = _s(get(r, "code")), _s(get(r, "type")).lower()
            kind = "group" if "group" in typ else "all" if ("all" in typ or (not typ and not code)) else "customer" if ("customer" in typ or typ == "0") else ("group" if code else "all")
            fresh.append(Price(type=kind, code="" if kind == "all" else code[:40], material_code=mat, uom=_s(get(r, "uom"))[:10], price=price,
                               min_qty=_num(get(r, "min_qty")), valid_from=_date(get(r, "from")), valid_to=_date(get(r, "to")),
                               incl_gst=_yes(get(r, "incl")) if m.get("incl") else None))
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
            key = rate_key(_s(get(r, "gst_group")), code)
            rate = _num(get(r, "rate")) if m.get("rate") else group_rate(key, gst_rates)
            entered = {str(k).strip().upper() for k, v in (gst_rates or {}).items() if v not in ("", None)}
            if not m.get("rate") and not rate and key.upper() not in entered \
                    and not re.search(r"exempt|nil|zero|^0+(\.0+)?%?$|non.?gst", key, re.I) and len(res["errors"]) < 20:
                res["errors"].append(f"Row {i + 2}: HSN {code} gets 0% GST: enter the GST % for "
                                     f"{key if key.startswith('HSN ') else 'GST group ' + chr(34) + key + chr(34)} below.")
            if dry:
                continue
            h = h or HsnCode(code=code)
            h.description, h.rate, h.cess = _s(get(r, "description"))[:200], rate, _num(get(r, "cess"))
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
    elif ent == "stock":
        # open item ledger entries: added up per item, location, lot and expiry; closed entries and zero quantities left out
        tot, known = {}, set(db.scalars(select(Material.code)))
        for i, r in enumerate(rows):
            code, qty = _s(get(r, "material")), _num(get(r, "qty"))
            if not code:
                skip(i, "no item number"); continue
            if m.get("open") and not _yes(get(r, "open")):
                continue
            k = (code[:40], _s(get(r, "location")).upper()[:20], _s(get(r, "lot"))[:50], _date(get(r, "expiry")))
            tot[k] = tot.get(k, 0) + qty
        fresh = [StockEntry(material_code=k[0], location=k[1], lot=k[2], expiry=k[3], qty=round(q, 4)) for k, q in tot.items() if abs(q) > 0.00005]
        res["added"] = len(fresh)
        res["items"] = len({x.material_code for x in fresh})
        unknown = sorted({x.material_code for x in fresh} - known)
        if unknown:
            res["errors"].append(f"{len(unknown)} items are not among the materials here (download materials first): {', '.join(unknown[:5])}")
        if not dry:
            db.query(StockEntry).delete()
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
    if path.startswith("http"):
        return path
    return f"{base}/{path.lstrip('/')}" if path.strip("/") else base


def api_call(s: dict, token: str, path: str, method="GET", body=None, headers: dict | None = None) -> dict:
    try:
        r = httpx.request(method, api_url(s, path), json=body, timeout=120,
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {})})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach Dynamics: {e}")
    data = r.json() if r.content and "json" in r.headers.get("content-type", "") else {}
    if r.status_code >= 400:
        msg = (data.get("error") or {}).get("message") if isinstance(data, dict) else ""
        raise HTTPException(502, f"Dynamics returned {r.status_code}{': ' + msg if msg else ''}")
    return data


# Business Central has two kinds of web address:
#   API v2.0  .../v2.0/{tenant}/{env}/api/v2.0/companies({id})/customers      (the API address + "customers")
#   OData V4  .../v2.0/{tenant}/{env}/ODataV4/Company('{name}')/{service}     (pages published under Web Services)
# The standard API has no GSTIN, HSN codes or price lists, so those come from published pages: an endpoint written
# "odata:ServiceName" (optionally with ?$filter=...) is turned into the OData V4 address of the same company.
def _bc_root(s: dict) -> tuple[str, str]:
    base = (s["dynamics"].get("base_url") or "").rstrip("/")
    m = re.match(r"^(https?://.+?)/api/[^/]+/[^/]+/[^/]+/companies\(([^)]+)\)", base) or \
        re.match(r"^(https?://.+?)/api/v2\.0/companies\(([^)]+)\)", base)
    if not m:
        raise HTTPException(422, "For odata: endpoints the API address must be the Business Central one, ending in /api/v2.0/companies(<company id>).")
    return m[1], m[2]


def odata_company_url(s: dict, token: str) -> str:
    root, _ = _bc_root(s)
    name = api_call(s, token, "").get("name")
    if not name:
        raise HTTPException(502, "Dynamics did not return the company name for the API address.")
    return f"{root}/ODataV4/Company('{quote(name.replace(chr(39), chr(39) * 2), safe='')}')"


def endpoint_url(s: dict, token: str, ep: str, cache: dict | None = None) -> str:
    ep = (ep or "").strip()
    if ep.lower().startswith("odata:"):
        cache = cache if cache is not None else {}
        if "company" not in cache:
            cache["company"] = odata_company_url(s, token)
        return f"{cache['company']}/{ep[6:].strip().lstrip('/')}"
    return ep


def odata_services(s: dict) -> list[dict]:
    """Pages and queries published under Web Services in Business Central (OData V4)."""
    root, _ = _bc_root(s)
    token = access_token(s)
    b = api_call(s, token, f"{root}/ODataV4/")
    return sorted(({"name": x.get("name"), "kind": x.get("kind", "")} for x in b.get("value", []) if x.get("name")), key=lambda x: x["name"].lower())


def drop_missing(db: Session, ent: str, codes: set, res: dict, dry: bool) -> None:
    """A customer or item deleted in Dynamics goes here too: deleted when nothing here uses it, else hidden (kept for the
    documents that name it). Not done when most of them would go, which means a filter or a part list, not deletions."""
    from ..models import SalesDocLine, UserCustomer
    codes.discard("")
    if ent == "customers":
        have = [c for c in db.scalars(select(Customer).where(or_(Customer.status.is_(None), Customer.status != "removed")))
                if c.created_by is None or c.sync_status == "synced"]
    else:
        have = list(db.scalars(select(Material)))
    gone = [x for x in have if x.code not in codes]
    if not gone:
        return
    if len(gone) > 5 and len(gone) * 2 > len(have):
        res["errors"].append(f"{len(gone)} of {len(have)} {ent} here are not in this download; none removed (check the endpoint's filter).")
        return
    res["removed"] = len(gone)
    if dry:
        return
    for x in gone:
        if ent == "customers":
            used = db.scalar(select(SalesDoc.id).where(SalesDoc.customer_id == x.id).limit(1)) or db.scalar(select(Payment.id).where(Payment.customer_id == x.id).limit(1))
            if used:
                x.status, x.blocked = "removed", True
            else:
                db.query(UserCustomer).filter(UserCustomer.customer_id == x.id).delete()
                db.delete(x)
        else:
            if db.scalar(select(SalesDocLine.id).where(SalesDocLine.material_code == x.code).limit(1)):
                x.blocked = True
            else:
                db.query(Price).filter(Price.material_code == x.code).delete()
                db.delete(x)
    db.flush()


def stock_endpoint(ep: str) -> str:
    """Item Ledger Entries hold every movement; only the open ones (Remaining Quantity not zero) are stock, so they are
    asked for that way unless the endpoint already has its own $filter."""
    ep = (ep or "").strip()
    if ep and re.search("ledger", ep, re.I) and "$filter" not in ep:
        ep += ("&" if "?" in ep else "?") + "$filter=Open eq true"
    return ep


def location_names(s: dict, token: str) -> dict:
    """Location code -> name, from the standard API (locations); empty when it cannot be read."""
    try:
        rows = api_call(s, token, "locations").get("value") or []
    except HTTPException:
        return {}
    return {_s(x.get("code")).upper(): _s(x.get("displayName") or x.get("name")) for x in rows if x.get("code")}


def api_pull(s: dict, ent: str, token: str | None = None, cache: dict | None = None) -> list[dict]:
    ep = s["dynamics"]["ep"].get(ent)
    if ent == "stock":
        ep = stock_endpoint(ep)
    if not ep:
        raise HTTPException(422, f"No API endpoint is set for {ENT[ent]['label'].lower()}. Set it under Dynamics connection.")
    token = token or access_token(s)
    url, rows, pages = endpoint_url(s, token, ep, cache), [], 0
    while url and pages < 500:
        b = api_call(s, token, url)
        rows += [{k: v for k, v in x.items() if not k.startswith("@") and (v is None or not isinstance(v, (dict, list)))} for x in b.get("value", [])]
        url, pages = b.get("@odata.nextLink"), pages + 1
    if url:
        raise HTTPException(502, f"Dynamics has more than {pages} pages of {ENT[ent]['label'].lower()}; nothing changed. Add a $filter to the endpoint.")
    return rows


REQUIRED = {"customers": ("code", "name"), "materials": ("code", "name"), "attributes": ("material", "name", "value"),
            "prices": ("material", "price"), "hsn": ("code",), "charges": ("code", "name", "value"), "stock": ("material", "qty")}
PULL_ORDER = ("customers", "materials", "hsn", "attributes", "prices", "charges", "stock")


def api_map(s: dict, ent: str, headers: list[str]) -> dict:
    """The columns chosen the last time this master came from the API, where they still exist; the rest automatic."""
    auto = auto_map(ent, headers)
    saved = (s["dynamics"].get("api_map") or {}).get(ent) or {}
    return {k: (saved[k] if saved.get(k) and saved[k] in headers else v) for k, v in auto.items()}


def item_price_fallback(db: Session, rows: list[dict], m: dict) -> int:
    """As in Business Central, an item's own Unit Price applies when no price list line is for all customers.
    Run after prices are replaced, so the price list wins and the item price fills the gaps."""
    if not m.get("price") or not m.get("code"):
        return 0
    have = set(db.scalars(select(Price.material_code).where(Price.type == "all")))
    mats = {x.code: x for x in db.scalars(select(Material))}
    n = 0
    for r in rows:
        code, price = _s(r.get(m["code"])), _num(r.get(m["price"]))
        if code in mats and code not in have and price > 0:
            incl = _yes(r.get(m["incl"])) if m.get("incl") else None
            db.add(Price(type="all", code="", material_code=code, uom=mats[code].uom, price=price, min_qty=0, incl_gst=incl))
            have.add(code)
            n += 1
    return n


def missing_fields(ent: str, m: dict) -> list[str]:
    return [k for k in REQUIRED[ent] if not m.get(k)]


# ------------------------------------------------------------------ out
def out_queues(db: Session) -> dict:
    waiting = ("pending", "error")
    return {
        "quotes": list(db.scalars(select(SalesDoc).where(SalesDoc.kind == "quote", SalesDoc.status.in_(["open", "converted"]), SalesDoc.sync_status.in_(waiting)))),
        "orders": list(db.scalars(select(SalesDoc).where(SalesDoc.kind == "order", SalesDoc.status == "approved", SalesDoc.sync_status.in_(waiting)))),
        "customers": list(db.scalars(select(Customer).where(Customer.status == "active", Customer.sync_status.in_(waiting)))),
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
    def unit_price(l):     # a price that includes GST goes as its value without GST, so the amount matches the portal
        p = float(l.price)
        return round(p / (1 + (float(l.gst_rate) + float(l.cess_rate or 0)) / 100), 5) if l.price_incl else p
    lines = [{"lineType": "Item", "lineObjectNumber": l.material_code, "quantity": float(l.qty), "unitPrice": unit_price(l),
              "discountPercent": float(l.disc), "unitOfMeasureCode": l.uom or None} for l in d.lines]
    body = {"customerNumber": c.code, "externalDocumentNumber": d.no, "salesperson": rep.emp_code or None}
    if d.kind == "quote":
        body.update(documentDate=d.doc_date.isoformat(), dueDate=d.valid_to.isoformat() if d.valid_to else None, salesQuoteLines=lines)
    else:
        body.update(orderDate=d.doc_date.isoformat(), requestedDeliveryDate=d.delivery_date.isoformat() if d.delivery_date else None, salesOrderLines=lines)
    return {k: v for k, v in body.items() if v is not None}


def _same_line(have: dict, want: dict) -> bool:
    return ((have.get("lineObjectNumber") or "").strip().upper() == want["lineObjectNumber"].strip().upper()
            and abs(float(have.get("quantity") or 0) - want["quantity"]) < 1e-6
            and abs(float(have.get("unitPrice") or 0) - want["unitPrice"]) < 0.01
            and abs(float(have.get("discountPercent") or 0) - want["discountPercent"]) < 0.001)


def make_order_from_quote(db: Session, s: dict, token: str, d: SalesDoc, orders_url: str) -> str | None:
    """Business Central's own flow for an order made from a quotation: Make Order on the quote (the quote becomes the
    order and leaves the quote list). Lines changed in the portal are then made the same in Business Central.
    None when the quote is not (or no longer) in Business Central: the order is then created as a new one."""
    q = db.get(SalesDoc, d.quote_id) if d.quote_id else None
    if not q or q.sync_status != "synced" or not q.sync_no:
        return None
    quotes_url = endpoint_url(s, token, s["dynamics"]["ep"].get("quotes") or "salesQuotes")
    found = api_call(s, token, f"{quotes_url}?$filter=number eq '{_q(q.sync_no)}'").get("value") or []
    if not found:
        return None
    r = api_call(s, token, f"{quotes_url}({found[0]['id']})/Microsoft.NAV.makeOrder", "POST")
    order = r if r.get("id") and r.get("number") else None
    if not order:      # the action answers without a body: the new order carries the quote's External Document No.
        c = db.get(Customer, d.customer_id)
        made = [x for x in api_call(s, token, f"{orders_url}?$filter=externalDocumentNumber eq '{_q(q.no)}'").get("value") or []
                if not x.get("customerNumber") or x.get("customerNumber") == c.code]
        made.sort(key=lambda x: (x.get("orderDate") or "", x.get("number") or ""))
        order = made[-1] if made else None
    if not order:
        raise HTTPException(502, f"Dynamics made an order from quote {q.sync_no}, but it was not found. Check Sales Orders there.")
    oid, want = order["id"], order_payload(db, d)["salesOrderLines"]
    have = [x for x in api_call(s, token, f"{orders_url}({oid})/salesOrderLines").get("value", []) if x.get("lineType") == "Item"]
    if len(have) != len(want) or not all(_same_line(h, w) for h, w in zip(have, want)):
        for x in have:
            api_call(s, token, f"{orders_url}({oid})/salesOrderLines({x['id']})", "DELETE", headers={"If-Match": "*"})
        for w in want:
            api_call(s, token, f"{orders_url}({oid})/salesOrderLines", "POST", w)
    head = {"externalDocumentNumber": d.no}
    if d.delivery_date:
        head["requestedDeliveryDate"] = d.delivery_date.isoformat()
    api_call(s, token, f"{orders_url}({oid})", "PATCH", head, headers={"If-Match": "*"})
    return str(order["number"])


def _q(v: str) -> str:
    return quote(str(v).replace("'", "''"), safe="")


def send_doc(db: Session, s: dict, token: str, d: SalesDoc, path: str) -> None:
    """Creates one quotation or sales order in Dynamics and records the result on the document. An order made from a
    quotation that is in Dynamics comes from that quote (Make Order). If Dynamics does not know the employee code as a
    salesperson, the document is sent without one rather than lost."""
    body = order_payload(db, d)
    try:
        if d.kind == "order":
            no = make_order_from_quote(db, s, token, d, path)
            if no:
                d.sync_status, d.sync_no, d.sync_at, d.sync_error = "synced", no[:40], now_utc(), None
                return
        try:
            r = api_call(s, token, path, "POST", body)
        except HTTPException as e:
            if "salesperson" in str(e.detail).lower() and body.get("salesperson"):
                body.pop("salesperson")
                r = api_call(s, token, path, "POST", body)
            else:
                raise
        no = r.get("number") or r.get("No") or r.get("id") or ""
        d.sync_status, d.sync_no, d.sync_at, d.sync_error = "synced", str(no)[:40], now_utc(), None
    except HTTPException as e:
        d.sync_status, d.sync_error, d.sync_at = "error", str(e.detail)[:500], now_utc()
        raise


def auto_send(doc_id: int) -> None:
    """Runs after a quotation is saved or an order approved, when automatic sending is on. Never raises:
    a failure leaves the document as "Sync error", still in the Dynamics sync queue for Send via API."""
    from ..db import SessionLocal
    from ..models import SyncLog
    with SessionLocal() as db:
        d = db.get(SalesDoc, doc_id)
        if not d or d.sync_status not in ("pending", "error"):
            return
        s = get_settings(db)
        kind = "quotes" if d.kind == "quote" else "orders"
        ep = s["dynamics"]["ep"].get(kind)
        if not s["dynamics"].get("auto_push") or not ep:
            return
        label = "Quotation" if d.kind == "quote" else "Sales order"
        try:
            token = access_token(s)
            send_doc(db, s, token, d, endpoint_url(s, token, ep))
            db.add(SyncLog(direction="out", entity=label, count=1, status="ok", message=f"Sent automatically: {d.no} is {d.sync_no} in Dynamics"))
        except HTTPException as e:
            if d.sync_status != "error":
                d.sync_status, d.sync_error, d.sync_at = "error", str(e.detail)[:500], now_utc()
            db.add(SyncLog(direction="out", entity=label, count=0, status="error", message=f"Automatic send of {d.no} failed: {e.detail}"))
        except Exception as e:      # network or anything unexpected: keep it in the queue
            d.sync_status, d.sync_error, d.sync_at = "error", f"Automatic send failed: {e}"[:500], now_utc()
        db.commit()



# ------------------------------------------------------------------ new customers: created in Business Central
CARD_ALT = {"contact": ["Contact", "ContactName", "Contact_Name", "Primary_Contact_Name"], "address2": ["Address_2", "Address2"],
            "email": ["E_Mail", "EMail", "Email"], "phone": ["Phone_No", "PhoneNo", "Mobile_Phone_No"], "pin": ["Post_Code", "PostCode"],
            "gstin": ["GST_Registration_No", "GSTRegistrationNo"], "state": ["State_Code", "State"], "terms": ["Payment_Terms_Code"],
            "price_group": ["Customer_Price_Group"]}
CARD_FIELDS = {"code": "No", "name": "Name", "contact": "Contact", "address": "Address", "address2": "Address_2", "city": "City",
               "pin": "Post_Code", "state": "State_Code", "gstin": "GST_Registration_No", "phone": "Phone_No", "email": "E_Mail",
               "price_group": "Customer_Price_Group", "terms": "Payment_Terms_Code"}
# copied from the template customer (like a customer template in Business Central), when not given here
COPY_FIELDS = {"genbuspostinggroup", "customerpostinggroup", "vatbuspostinggroup", "countryregioncode", "paymenttermscode",
               "paymentmethodcode", "locationcode", "customerpricegroup", "customerdiscgroup", "remindertermscode", "currencycode",
               "taxliable", "taxareacode", "salespersoncode", "applicationmethod", "printstatements", "gstcustomertype",
               "finchargetermscode", "shipmentmethodcode", "languagecode", "allowlinedisc", "prepayment"}


def _odata_eq(field: str, v: str) -> str:
    return f"$filter={field} eq '{_q(v)}'"


def bc_state(s: dict, token: str, url: str, fields: dict, code: str) -> str:
    """The portal keeps the GST state code (09); Business Central's State table has its own codes (UP, U.P., ...).
    Learnt from the customers already there: the State Code used by customers in that GST state."""
    sf, gf = fields.get("state"), fields.get("gstin")
    if not code or not sf:
        return code
    try:
        rows = api_call(s, token, f"{url}?$select={sf}{',' + gf if gf else ''}").get("value") or []
    except HTTPException:
        rows = []
    seen = {}
    for r in rows:
        v = _s(r.get(sf))
        if v and _state(v, _s(r.get(gf)) if gf else "") == code:
            seen[v] = seen.get(v, 0) + 1
    if seen:
        return max(seen, key=seen.get)
    return next((a for a, k in STATE_ABBR.items() if k == code and len(a) == 2), code)


def customer_card_body(s: dict, c: Customer, fields: dict, template: dict | None, state: str | None = None) -> dict:
    """The new customer as Customer Card fields: the template customer's posting setup first, then this customer."""
    body = {}
    for k, v in (template or {}).items():
        if _norm(k) in COPY_FIELDS and v not in (None, "", "0001-01-01") and not k.startswith("@"):
            body[k] = v
    addr = (c.address or "").replace("\n", ", ")
    vals = {"name": c.name[:100], "contact": (c.contact or "")[:100], "address": addr[:100], "address2": addr[100:150], "city": (c.city or "")[:30],
            "pin": (c.pin or "")[:20], "state": state if state is not None else (c.state or ""), "gstin": c.gstin or "", "phone": (c.phone or "")[:30], "email": (c.email or "")[:80],
            "price_group": c.price_group or "", "terms": c.terms or ""}
    for k, v in vals.items():
        if v and fields.get(k):
            body[fields[k]] = v
    gst_type = next((k for k in (template or {}) if _norm(k) == "gstcustomertype"), None)
    if gst_type:
        body[gst_type] = "Registered" if c.gstin else "Unregistered"
    return body


def send_customer(db: Session, s: dict, token: str, c: Customer) -> str:
    """Creates the customer in Business Central (or links one there with the same GSTIN) and takes its number."""
    ep = (s["dynamics"]["ep"].get("customers") or "").split("?")[0].strip()
    if not ep:
        raise HTTPException(422, "No Customers endpoint is set under Dynamics connection.")
    url = endpoint_url(s, token, ep)
    if ep.lower().startswith("odata:"):
        saved = (s["dynamics"].get("api_map") or {}).get("customers") or {}
        fields = {k: (saved.get(k) or v) for k, v in CARD_FIELDS.items()}
        key = fields["code"]
        started = not (c.code or "").startswith("NEW-")     # made in an earlier try; only its GST details are left
        if c.gstin and fields.get("gstin") and not started:
            same = api_call(s, token, f"{url}?{_odata_eq(fields['gstin'], c.gstin)}").get("value") or []
            if same:
                return _s(same[0].get(key))
        template = None
        t = (s["dynamics"].get("new_customer_template") or "").strip()
        if t:
            rows = api_call(s, token, f"{url}?{_odata_eq(key, t)}").get("value") or []
            if not rows:
                raise HTTPException(422, f"Template customer {t} (Dynamics connection, New customers) was not found in Business Central.")
            template = rows[0]
        # only fields the published page has (pages differ by version and localisation): its own row shows them
        known = set(template or {}) or set((api_call(s, token, f"{url}?$top=1").get("value") or [{}])[0])
        if known:
            for k in list(fields):
                if fields[k] not in known:
                    fields[k] = next((a for a in CARD_ALT.get(k, []) if a in known), None)
        body = customer_card_body(s, c, fields, template, bc_state(s, token, url, fields, c.state or ""))
        if known:
            body = {k: v for k, v in body.items() if k in known}
        # India: GST Registration No. needs the P.A.N. No. (characters 3-12 of the GSTIN) first, and Business Central
        # checks it as the page orders its fields, so the customer is made with the PAN, then given its GST details
        gst_type = next((k for k in body if _norm(k) == "gstcustomertype"), None)
        gst = {k: body.pop(k) for k in [gst_type, fields.get("gstin")] if k and k in body}
        pan = next((k for k in known if _norm(k) in ("pano", "panno")), None)
        if pan and c.gstin:
            body[pan] = c.gstin[2:12]
        if started:
            no = c.code
        else:
            r = api_call(s, token, url, "POST", body)
            no = _s(r.get(key) or r.get("No") or r.get("number"))
            if not no:
                raise HTTPException(502, "Business Central created the customer but did not return its number.")
            if gst:
                other = db.scalar(select(Customer).where(Customer.code == no[:40], Customer.id != c.id))
                if not other:
                    c.code = no[:40]                    # so a retry finishes this one instead of making another
                    db.flush()
        rec = f"{url}('{_q(no)}')"
        for k, v in gst.items():                      # customer type first, then the GSTIN
            try:
                api_call(s, token, rec, "PATCH", {k: v}, headers={"If-Match": "*"})
            except HTTPException as e:
                raise HTTPException(e.status_code, f"Created in Business Central as {no}, but its {k.replace('_', ' ')} could not be set: {e.detail} "
                                                   "Fix it there, or here and press Send to Dynamics again.")
    else:                                    # standard API v2.0 customers: no GST or posting groups there
        if c.gstin:
            same = api_call(s, token, f"{url}?$filter=taxRegistrationNumber eq '{_q(c.gstin)}'").get("value") or []
            if same:
                return _s(same[0].get("number"))
        r = api_call(s, token, url, "POST", {k: v for k, v in {
            "displayName": c.name[:100], "addressLine1": (c.address or "")[:100], "city": (c.city or "")[:30], "postalCode": (c.pin or "")[:20],
            "phoneNumber": (c.phone or "")[:30], "email": (c.email or "")[:80], "taxRegistrationNumber": c.gstin or ""}.items() if v})
        no = _s(r.get("number"))
    if not no:
        raise HTTPException(502, "Business Central created the customer but did not return its number.")
    return no


def push_customer(db: Session, s: dict, token: str, c: Customer) -> str:
    """send_customer, then the number from Business Central becomes the customer's code here."""
    try:
        no = send_customer(db, s, token, c)
    except HTTPException as e:
        c.sync_status, c.sync_error, c.sync_at = "error", str(e.detail)[:500], now_utc()
        raise
    other = db.scalar(select(Customer).where(Customer.code == no[:40], Customer.id != c.id))
    if other:
        c.sync_status, c.sync_error, c.sync_at = "error", f"Business Central already has this customer as {no}, which is {other.name} here. Use that one.", now_utc()
        raise HTTPException(409, c.sync_error)
    c.code, c.sync_status, c.sync_error, c.sync_at, c.synced_at = no[:40], "synced", None, now_utc(), now_utc()
    return no


def auto_send_customer(cid: int) -> None:
    """After a customer is added by a manager or approved. Never raises; a failure stays in the Dynamics sync queue."""
    from ..db import SessionLocal
    from ..models import SyncLog
    with SessionLocal() as db:
        c = db.get(Customer, cid)
        if not c or c.status != "active" or c.sync_status not in ("pending", "error"):
            return
        s = get_settings(db)
        if not s["dynamics"].get("auto_customers") or not s["dynamics"]["ep"].get("customers"):
            return
        try:
            no = push_customer(db, s, access_token(s), c)
            db.add(SyncLog(direction="out", entity="Customer", count=1, status="ok", message=f"{c.name}: created in Dynamics as {no}"))
        except HTTPException as e:
            db.add(SyncLog(direction="out", entity="Customer", count=0, status="error", message=f"{c.name}: {e.detail}"[:2000]))
        except Exception as e:  # noqa: BLE001
            c.sync_status, c.sync_error, c.sync_at = "error", f"Sending failed: {e}"[:500], now_utc()
        db.commit()


# ------------------------------------------------------------------ company details for printing
COMPANY_FIELDS = {        # first match wins; names normalised (lower case, letters and digits only)
    "name": ["name", "displayname"], "addr1": ["address", "addressline1"], "addr2": ["address2", "addressline2"],
    "city": ["city"], "pin": ["postcode", "postalcode"], "country": ["countryregioncode", "country", "countrycode"],
    "phone": ["phoneno", "phonenumber"], "email": ["email"], "gstin": ["gstregistrationno", "gstin", "taxregistrationnumber", "taxregistrationno"],
    "pan": ["panno", "pan", "pano", "pandetails"], "bank_name": ["bankname"], "branch": ["bankbranchno", "bankbranch"],
    "account_no": ["bankaccountno", "bankaccountnumber"], "ifsc": ["ifsccode", "ifsc", "iban"],
}
COUNTRIES = {"IN": "India", "IND": "India"}


def company_from_dynamics(s: dict) -> dict:
    """Company Information from Business Central: the standard API (companyInformation) gives the name, address,
    phone and e-mail; the Company Information page published as a web service also gives GSTIN, PAN, bank details
    and any FSSAI or UPI fields added to it."""
    ep = s["dynamics"]["ep"].get("company") or "companyInformation"
    token = access_token(s)
    b = api_call(s, token, endpoint_url(s, token, ep))
    row = (b.get("value") or [b])[0] if isinstance(b, dict) else {}
    norm = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in row.items() if not k.startswith("@") and not isinstance(v, (dict, list))}
    pick = lambda f: next((_s(norm[k]) for k in COMPANY_FIELDS[f] if _s(norm.get(k))), "")
    find = lambda word: next((_s(v) for k, v in norm.items() if word in k and _s(v)), "")
    gstin = pick("gstin").upper()
    if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]", gstin):
        gstin = ""
    country = pick("country")
    lines = [pick("addr1"), pick("addr2"), ", ".join(x for x in (pick("city"), pick("pin")) if x), COUNTRIES.get(country.upper(), country)]
    company = {"legal_name": pick("name"), "address": "\n".join(x for x in lines if x), "phone": pick("phone"), "email": pick("email"),
               "gstin": gstin, "pan": pick("pan").upper(), "fssai": find("fssai")}
    if gstin:
        company["state"] = gstin[:2]
    bank = {"bank_name": pick("bank_name"), "branch": pick("branch"), "account_no": pick("account_no"), "ifsc": pick("ifsc").upper(),
            "upi_id": find("upi")}
    return {"company": {k: v for k, v in company.items() if v}, "print": {k: v for k, v in bank.items() if v}, "fields": len(norm)}



def apply_packs(db: Session, s: dict, token: str | None = None, cache: dict | None = None) -> dict:
    """Packets per item for the printed Pkts. column, as the Business Central report does it: the item's PACKET
    unit of measure (Item Units of Measure, Qty. per Unit of Measure). Items without that unit print no packets."""
    ep = s["dynamics"]["ep"].get("units")
    if not ep:
        return {"items": 0}
    pack_code = (s["dynamics"].get("pack_uom") or "PACKET").strip().upper()
    token = token or access_token(s)
    rows = api_pull(s, "units", token, cache)
    norm = lambda r: {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in r.items()}
    found = {}
    for r in rows:
        n = norm(r)
        item = _s(n.get("itemno") or n.get("itemnumber") or n.get("no"))
        code = _s(n.get("code") or n.get("unitofmeasurecode")).upper()
        qty = _num(n.get("qtyperunitofmeasure") or n.get("qtyperunit") or n.get("quantityperunitofmeasure"))
        if item and code == pack_code and qty > 0:
            found[item] = qty
    for mat in db.scalars(select(Material)):
        mat.pack_qty = found.get(mat.code, 0)
    return {"items": len(found)}


# ------------------------------------------------------------------ invoicing: post the Business Central sales order
class PostError(Exception):
    pass


EXT_PATH = "api/samuraiFoods/portal/v1.0"      # the Samurai Sales Portal extension for Business Central (bc-extension folder)
LOT_HINT = ("Business Central needs lot numbers for this item. Install the Samurai Sales Portal extension (it assigns lots "
            "first-expiry-first-out when posting), or assign the lots on the order in Business Central and post it there; "
            "then press Post in Dynamics here to link the posted invoice.")


def _ext_url(s: dict, path: str) -> str:
    """The same company in the extension's API: .../api/v2.0/companies(x) -> .../api/samuraiFoods/portal/v1.0/companies(x)"""
    base = (s["dynamics"].get("base_url") or "").rstrip("/")
    m = re.match(r"^(https?://.+?)/api/[^/]+(?:/[^/]+/[^/]+)?/(companies\([^)]+\))$", base) or re.match(r"^(https?://.+?)/api/v2\.0/(companies\([^)]+\))$", base)
    if not m:
        raise PostError("The API address must end in /api/v2.0/companies(<company id>) to post invoices.")
    return f"{m[1]}/{EXT_PATH}/{m[2]}/{path}"


def _posted_for(s: dict, token: str, order_no: str) -> list[dict]:
    inv_ep = s["dynamics"]["ep"].get("invoices") or "salesInvoices"
    rows = api_call(s, token, f"{endpoint_url(s, token, inv_ep)}?$filter=orderNumber eq '{_q(order_no)}'").get("value") or []
    rows.sort(key=lambda x: (x.get("postingDate") or x.get("invoiceDate") or "", x.get("lastModifiedDateTime") or "", x.get("number") or ""))
    return rows


def post_invoice_in_bc(db: Session, s: dict, token: str, inv: SalesDoc) -> tuple[str, str]:
    """Posts the invoice's sales order in Business Central for exactly the invoiced quantities and returns
    (posted invoice number, how). Business Central's flow:
      0. an invoice already posted in Business Central for this order (lots assigned and posted there by hand) and not
         yet linked to a portal invoice is linked instead of posting again
      1. find the order; check its item lines are the portal's
      2. posting date = the invoice date; Qty. to Ship and Qty. to Invoice = this invoice's quantity (0 on other lines)
      3. post: with the Samurai Sales Portal extension, lot numbers are assigned FEFO and the order posted (Ship and
         Invoice) in one go; without it, the standard Ship and Invoice action (fine for items without lot tracking)
      4. read the posted invoice number back"""
    order = db.get(SalesDoc, inv.order_id) if inv.order_id else None
    if not order:
        raise PostError("This invoice has no sales order.")
    if order.sync_status != "synced" or not order.sync_no:
        raise PostError(f"Order {order.no} is not in Dynamics yet. Send it (Dynamics sync, Send via API), then Post in Dynamics.")
    taken = {x.sync_no for x in db.scalars(select(SalesDoc).where(SalesDoc.kind == "inv", SalesDoc.order_id == order.id,
                                                                   SalesDoc.id != inv.id, SalesDoc.status != "cancelled")) if x.sync_no}
    before = _posted_for(s, token, order.sync_no)
    loose = [x for x in before if x.get("number") and x["number"] not in taken]
    if loose:                                    # posted in Business Central already: link it
        return loose[0]["number"], "linked"
    base = endpoint_url(s, token, s["dynamics"]["ep"].get("orders") or "salesOrders")
    found = api_call(s, token, f"{base}?$filter=number eq '{_q(order.sync_no)}'").get("value") or []
    if not found:
        raise PostError(f"Dynamics has no open sales order {order.sync_no}; it may already be fully invoiced or deleted there.")
    bc_id = found[0]["id"]
    bc_lines = [x for x in api_call(s, token, f"{base}({bc_id})/salesOrderLines").get("value", []) if x.get("lineType") == "Item"]
    want = {l.src_line_id: float(l.qty) for l in inv.lines}
    if len(bc_lines) != len(order.lines):
        raise PostError(f"Dynamics order {order.sync_no} has {len(bc_lines)} item lines, the portal order {len(order.lines)}; it was changed in Dynamics.")
    plan = []
    for ol, bl in zip(order.lines, bc_lines):
        if (bl.get("lineObjectNumber") or "").strip().upper() != ol.material_code.strip().upper():
            raise PostError(f"Line {ol.line_no}: Dynamics has {bl.get('lineObjectNumber')}, the portal {ol.material_code}.")
        q = round(want.get(ol.id, 0.0), 5)
        left = float(bl.get("quantity") or 0) - float(bl.get("invoicedQuantity") or 0)
        if q > left + 0.00001:
            raise PostError(f"{ol.material_code}: Dynamics has only {left:g} left to invoice on {order.sync_no}, the invoice has {q:g}.")
        plan.append((bl, q))
    api_call(s, token, f"{base}({bc_id})", "PATCH", {"postingDate": inv.doc_date.isoformat()}, headers={"If-Match": "*"})
    for bl, q in plan:
        api_call(s, token, f"{base}({bc_id})/salesOrderLines({bl['id']})", "PATCH",
                 {"shipQuantity": q, "invoiceQuantity": q}, headers={"If-Match": bl.get("@odata.etag") or "*"})
    how = "lots assigned (FEFO) and posted"
    try:
        api_call(s, token, _ext_url(s, f"portalSalesOrders({bc_id})/Microsoft.NAV.assignLotsAndPost"), "POST")
    except HTTPException as e:
        if " 404" not in str(e.detail) and "No HTTP resource" not in str(e.detail) and "not found" not in str(e.detail).lower():
            raise
        how = "posted"                            # extension not installed: the standard action
        try:
            api_call(s, token, f"{base}({bc_id})/Microsoft.NAV.shipAndInvoice", "POST")
        except HTTPException as e2:
            if re.search(r"lot (number|no)", str(e2.detail), re.I):
                raise PostError(f"{e2.detail} {LOT_HINT}")
            raise
    fresh = [x for x in _posted_for(s, token, order.sync_no) if x.get("number") and x["number"] not in taken]
    if not fresh:
        raise PostError(f"Order {order.sync_no} was posted in Dynamics, but its posted invoice was not found. Check Posted Sales Invoices there.")
    return fresh[-1]["number"], how


def post_invoice(doc_id: int) -> None:
    """Background job after an invoice is made (and the Post in Dynamics button). Never raises: a failure is kept on the
    invoice as "Sync error" with the reason, and can be retried."""
    from ..db import SessionLocal
    from ..models import SyncLog
    with SessionLocal() as db:
        inv = db.get(SalesDoc, doc_id)
        if not inv or inv.kind != "inv" or inv.status != "open" or inv.sync_status not in ("pending", "error"):
            return
        s = get_settings(db)
        try:
            no, how = post_invoice_in_bc(db, s, access_token(s), inv)
            inv.sync_status, inv.sync_no, inv.sync_error, inv.sync_at = "synced", no[:40], None, now_utc()
            msg = f"linked to invoice {no} posted in Dynamics" if how == "linked" else f"order {how} in Dynamics, invoice {no}"
            db.add(SyncLog(direction="out", entity="Sales invoice", count=1, status="ok", message=f"{inv.no}: {msg}"))
        except (PostError, HTTPException) as e:
            msg = str(e.detail if isinstance(e, HTTPException) else e)
            inv.sync_status, inv.sync_error, inv.sync_at = "error", msg[:500], now_utc()
            db.add(SyncLog(direction="out", entity="Sales invoice", count=0, status="error", message=f"{inv.no}: {msg}"))
        except Exception as e:  # noqa: BLE001
            inv.sync_status, inv.sync_error, inv.sync_at = "error", f"Posting failed: {e}"[:500], now_utc()
        db.commit()
        posted = inv.sync_status == "synced"
    if posted:                       # the shipment took stock out in Business Central: read it again now
        from ..routers.stock import _auto_refresh
        _auto_refresh()


def payment_api_lines(db: Session, p: Payment, negative: bool = True) -> list[dict]:
    """The Business Central customerPayments API writes the amount to the cash receipt journal line exactly as sent
    (checked in AequmTest: +660 sent, +660 on the line, which then fails to post), and a customer payment must be
    negative to post, so the API always gets negative amounts, whatever the export-file setting says.

    Customer payment journal lines for one receipt, applied as in Business Central: one line per invoice that is
    posted there (Applies-to Doc. No. = its posted invoice number), and one line for the rest (on account / advances)."""
    c = db.get(Customer, p.customer_id)
    sign = -1 if negative else 1
    base = {"customerNumber": c.code, "postingDate": p.pay_date.isoformat(), "documentNumber": p.no,
            "externalDocumentNumber": p.ref or p.no, "description": f"{p.mode.upper()} {p.ref}".strip()[:100]}
    lines, rest = [], float(p.amount)
    for a in p.allocations:
        d = db.get(SalesDoc, a.order_id)
        if d and d.kind == "inv" and d.sync_status == "synced" and d.sync_no:
            lines.append({**base, "amount": round(sign * float(a.amount), 2), "appliesToInvoiceNumber": d.sync_no})
            rest -= float(a.amount)
    if rest > 0.004 or not lines:
        lines.append({**base, "amount": round(sign * rest, 2)})
    return lines
