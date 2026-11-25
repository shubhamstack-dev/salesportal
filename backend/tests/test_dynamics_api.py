"""Masters downloaded from a simulated Business Central: API v2.0 plus pages published as OData V4 web services,
with the field names, empty dates (0001-01-01), paging (@odata.nextLink) and India fields a real tenant returns."""
import os
import tempfile
from urllib.parse import unquote

os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/t.db"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Customer, HsnCode, Material, Price  # noqa: E402

TENANT, ENVN, CID = "5d63832e-tenant", "AequmTest", "9a182596-company"
ROOT = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT}/{ENVN}"
BASE = f"{ROOT}/api/v2.0/companies({CID})"
COMPANY = "Samurai Foods Private Limited"
OD = f"{ROOT}/ODataV4/Company('Samurai%20Foods%20Private%20Limited')"
EMPTY = "0001-01-01"

CUSTOMERS = [
    {"@odata.etag": "W/1", "No": "C0001", "Name": "Lucknow Frozen Mart", "Address": "Hazratganj", "City": "Lucknow", "Post_Code": "226001",
     "State_Code": "UP", "GST_Registration_No": "09AAACL1234F1Z5", "Phone_No": "9800000001", "E_Mail": "lfm@example.in",
     "Customer_Price_Group": "RETAIL", "Payment_Terms_Code": "30D", "Credit_Limit_LCY": 500000, "Balance_LCY": 125000.5, "Blocked": " "},
    {"No": "C0002", "Name": "Delhi Foods", "City": "New Delhi", "State_Code": "DL", "GST_Registration_No": "07AAACD9999K1Z1",
     "Customer_Price_Group": "", "Credit_Limit_LCY": 0, "Balance_LCY": 0, "Blocked": " "},
    {"No": "C0003", "Name": "Blocked Buyer", "State_Code": "", "GST_Registration_No": "27AAACB1111B1Z2", "Blocked": "All"},
]
ITEMS = [
    {"No": "SF-001-500", "Description": "Chk. Seekh Kebab (Regular)", "Base_Unit_of_Measure": "KG", "HSN_SAC_Code": "16010000",
     "GST_Group_Code": "GST5", "Item_Category_Code": "KEBAB", "Unit_Price": 660, "Blocked": False},
    {"No": "SF-002-500", "Description": "Chk. Garlic Seekh Kebab", "Base_Unit_of_Measure": "KG", "HSN_SAC_Code": "16010000",
     "GST_Group_Code": "GST5", "Item_Category_Code": "KEBAB", "Unit_Price": 640, "Blocked": False},
    {"No": "SF-900", "Description": "Sauce", "Base_Unit_of_Measure": "PCS", "HSN_SAC_Code": "21039090", "GST_Group_Code": "GST18",
     "Item_Category_Code": "", "Unit_Price": 0, "Blocked": True},
]
HSN = [
    {"GST_Group_Code": "GST5", "Code": "16010000", "Description": "Sausages and similar products of meat", "Type": "HSN"},
    {"GST_Group_Code": "GST18", "Code": "21039090", "Description": "Sauces and preparations", "Type": "HSN"},
    {"GST_Group_Code": "EXEMPT", "Code": "07019000", "Description": "Potatoes", "Type": "HSN"},
    {"GST_Group_Code": "FOOD", "Code": "19059090", "Description": "Bakery products", "Type": "HSN"},
]
PRICES = [
    {"Price_List_Code": "S00001", "Price_Type": "Sale", "Source_Type": "All Customers", "Source_No": "", "Asset_Type": "Item",
     "Product_No": "SF-001-500", "Unit_of_Measure_Code": "KG", "Minimum_Quantity": 0, "Unit_Price": 660, "Starting_Date": EMPTY, "Ending_Date": EMPTY, "Status": "Active"},
    {"Price_List_Code": "S00002", "Price_Type": "Sale", "Source_Type": "Customer Price Group", "Source_No": "RETAIL", "Asset_Type": "Item",
     "Product_No": "SF-001-500", "Unit_of_Measure_Code": "KG", "Minimum_Quantity": 10, "Unit_Price": 630, "Starting_Date": "2026-04-01", "Ending_Date": EMPTY, "Status": "Active"},
    {"Price_List_Code": "S00003", "Price_Type": "Sale", "Source_Type": "Customer", "Source_No": "C0002", "Asset_Type": "Item",
     "Product_No": "SF-002-500", "Unit_of_Measure_Code": "KG", "Minimum_Quantity": 0, "Unit_Price": 600, "Starting_Date": EMPTY, "Ending_Date": "2026-12-31", "Status": "Active"},
    {"Price_List_Code": "P00001", "Price_Type": "Purchase", "Source_Type": "Vendor", "Source_No": "V001", "Asset_Type": "Item",
     "Product_No": "SF-001-500", "Unit_of_Measure_Code": "KG", "Minimum_Quantity": 0, "Unit_Price": 400, "Starting_Date": EMPTY, "Ending_Date": EMPTY, "Status": "Active"},
    {"Price_List_Code": "S00009", "Price_Type": "Sale", "Source_Type": "All Customers", "Source_No": "", "Asset_Type": "Item",
     "Product_No": "SF-002-500", "Unit_of_Measure_Code": "KG", "Minimum_Quantity": 0, "Unit_Price": 1, "Starting_Date": EMPTY, "Ending_Date": EMPTY, "Status": "Draft"},
]
ATTRS = [{"Item_No": "SF-001-500", "Attribute": "Pack size", "Value": "500 g"}, {"Item_No": "SF-002-500", "Attribute": "Pack size", "Value": "500 g"}]
CHARGES = [{"Code": "FRT", "Description": "Freight", "Calculation_Type": "Percentage", "Value": 2, "Charge_or_Discount": "Charge", "Applied_On": "Before GST"},
           {"Code": "TCS", "Description": "TCS 0.1%", "Calculation_Type": "Percentage", "Value": 0.1, "Charge_or_Discount": "Charge", "Applied_On": "After GST"}]

PAGES = {"Customer_Card": CUSTOMERS, "Item_Card": ITEMS, "HSN_SAC": HSN, "PriceListLines": PRICES, "ItemAttributes": ATTRS, "SalesCharges": CHARGES}
calls = []


def _json(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("GET", "https://x"))


def fake_post(url, data=None, **kw):
    assert url == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
    if data["client_secret"] != "right-secret":
        return _json(401, {"error_description": "AADSTS7000215: Invalid client secret provided."})
    return _json(200, {"access_token": "tok-123"})


BC_DOCS = []
BC_DOWN = {"on": False}
SALESPEOPLE = {"SP01"}


def bc_create(kind, body):
    """What Business Central checks when a quote or order is posted to salesQuotes / salesOrders."""
    if BC_DOWN["on"]:
        return _json(503, {"error": {"message": "Service unavailable"}})
    if body.get("customerNumber") not in {c["No"] for c in CUSTOMERS}:
        return _json(400, {"error": {"message": f"The Customer does not exist. Identification fields and values: No.='{body.get('customerNumber')}'"}})
    sp = body.get("salesperson")
    if sp and sp not in SALESPEOPLE:
        return _json(400, {"error": {"message": f"The field Salesperson Code of table Sales Header contains a value ({sp}) that cannot be found in the related table (Salesperson/Purchaser)."}})
    lines = body.get("salesQuoteLines" if kind == "quote" else "salesOrderLines") or []
    items = {i["No"] for i in ITEMS}
    for ln in lines:
        if ln["lineType"] != "Item" or ln["lineObjectNumber"] not in items or ln["quantity"] <= 0:
            return _json(400, {"error": {"message": f"Bad line {ln}"}})
    no = ("SQ" if kind == "quote" else "SO") + str(1001 + len(BC_DOCS))
    BC_DOCS.append({"kind": kind, "number": no, **body})
    (BC_QUOTES if kind == "quote" else BC_ORDERS)[no] = _bc_doc(no, body, lines)
    return _json(201, {"id": f"guid-{no}", "number": no, **body})


def _bc_line(no, i, ln):
    return {"id": f"{no}-L{i + 1}", "lineType": "Item", "lineObjectNumber": ln["lineObjectNumber"], "quantity": ln["quantity"],
            "unitPrice": ln.get("unitPrice", 0), "discountPercent": ln.get("discountPercent", 0),
            "invoicedQuantity": 0, "shipQuantity": ln["quantity"], "invoiceQuantity": ln["quantity"], "etag": 1}


def _bc_doc(no, body, lines):
    return {"id": f"guid-{no}", "number": no, "customerNumber": body.get("customerNumber"), "externalDocumentNumber": body.get("externalDocumentNumber"),
            "orderDate": body.get("orderDate") or body.get("documentDate"), "postingDate": None, "lines": [_bc_line(no, i, ln) for i, ln in enumerate(lines)]}


BC_QUOTES: dict = {}          # open Business Central sales quotes by number
BC_ORDERS: dict = {}          # open Business Central sales orders by number
LOT_ITEMS = {"SF-001-500"}    # items with lot tracking: posting needs lot numbers
LOTS = {"SF-001-500": [("L-2611", "2027-01-31", 4), ("L-2605", "2026-12-15", 5), ("L-2702", "2027-03-01", 20)]}   # lot, expiry, qty
BC_EXT = {"installed": False}
BC_LOT_USE: list = []         # (order, item, lot, qty) assigned by the extension
BC_PAYMENTS: list = []
BC_POSTED: list = []          # posted sales invoices
BC_PATCHES: list = []


def bc_orders(method, path, query, body, headers):
    """salesOrders lookup, its lines, setting Qty. to Ship / Invoice, Ship and Invoice, and salesInvoices, as Business Central does."""
    from urllib.parse import unquote
    q = unquote(query)
    if method == "GET" and path == f"{BASE}/salesOrders":
        if "externalDocumentNumber eq '" in q:
            ext = q.split("externalDocumentNumber eq '")[1].rstrip("'")
            return _json(200, {"value": [{k: v for k, v in o.items() if k != "lines"} for o in BC_ORDERS.values() if o["externalDocumentNumber"] == ext]})
        num = q.split("number eq '")[1].rstrip("'")
        o = BC_ORDERS.get(num)
        return _json(200, {"value": [{"id": o["id"], "number": num}] if o else []})
    if method == "GET" and path == f"{BASE}/salesInvoices":
        num = q.split("orderNumber eq '")[1].rstrip("'")
        return _json(200, {"value": [x for x in BC_POSTED if x["orderNumber"] == num]})
    o = next((x for x in BC_ORDERS.values() if path.startswith(f"{BASE}/salesOrders({x['id']})")), None)
    if not o:
        return _json(404, {"error": {"message": "The sales order does not exist."}})
    rest = path[len(f"{BASE}/salesOrders({o['id']})"):]
    if method == "PATCH" and rest == "":
        assert headers.get("If-Match")
        o.update({k: v for k, v in body.items() if k in ("externalDocumentNumber", "requestedDeliveryDate", "postingDate")})
        return _json(200, {k: v for k, v in o.items() if k != "lines"})
    if method == "DELETE" and rest.startswith("/salesOrderLines("):
        assert headers.get("If-Match")
        o["lines"] = [l for l in o["lines"] if rest != f"/salesOrderLines({l['id']})"]
        return httpx.Response(204, request=httpx.Request("DELETE", "https://x"))
    if method == "POST" and rest == "/salesOrderLines":
        o["lines"].append(_bc_line(o["number"], len(o["lines"]) + 50, body))
        return _json(201, o["lines"][-1])
    if method == "GET" and rest == "/salesOrderLines":
        return _json(200, {"value": [{**{k: v for k, v in l.items() if k != "etag"}, "@odata.etag": f'W/"{l["etag"]}"'} for l in o["lines"]]})
    if method == "PATCH" and rest.startswith("/salesOrderLines("):
        l = next(x for x in o["lines"] if rest == f"/salesOrderLines({x['id']})")
        if headers.get("If-Match") not in ("*", f'W/"{l["etag"]}"'):
            return _json(412, {"error": {"message": "Another user has already changed the record."}})
        left = l["quantity"] - l["invoicedQuantity"]
        if body["invoiceQuantity"] > left + 1e-9:
            return _json(400, {"error": {"message": f"You cannot invoice more than {left} units."}})
        BC_PATCHES.append((l["lineObjectNumber"], body["shipQuantity"], body["invoiceQuantity"]))
        l.update(shipQuantity=body["shipQuantity"], invoiceQuantity=body["invoiceQuantity"], etag=l["etag"] + 1)
        return _json(200, l)
    if method == "POST" and rest == "/Microsoft.NAV.shipAndInvoice":
        if not any(l["invoiceQuantity"] > 0 for l in o["lines"]):
            return _json(400, {"error": {"message": "There is nothing to post."}})
        for l in o["lines"]:
            if l["invoiceQuantity"] > 0 and l["lineObjectNumber"] in LOT_ITEMS and not l.get("lots"):
                return _json(400, {"error": {"message": f"You must assign a lot number for item {l['lineObjectNumber']}.  CorrelationId: 1833."}})
        o["posted_on"] = o.get("postingDate")
        for l in o["lines"]:
            l.pop("lots", None)
            l["invoicedQuantity"] += l["invoiceQuantity"]
            l["shipQuantity"] = l["invoiceQuantity"] = l["quantity"] - l["invoicedQuantity"]
        BC_POSTED.append({"number": f"PSI-{101 + len(BC_POSTED)}", "orderNumber": o["number"], "postingDate": o.get("posted_on") or "2026-11-24",
                          "lastModifiedDateTime": f"2026-11-24T10:{len(BC_POSTED):02d}:00Z"})
        if all(l["invoicedQuantity"] >= l["quantity"] for l in o["lines"]):
            del BC_ORDERS[o["number"]]          # Business Central deletes a fully invoiced order
        return httpx.Response(204, request=httpx.Request("POST", "https://x"))
    return _json(404, {"error": {"message": "not found"}})


def fake_request(method, url, json=None, headers=None, **kw):
    calls.append((method, url))
    if headers.get("Authorization") != "Bearer tok-123":
        return _json(401, {"error": {"message": "The credentials provided are incorrect"}})
    path, _, query = url.partition("?")
    if path.startswith(f"{BASE}/salesOrders") and not (method == "POST" and path == f"{BASE}/salesOrders") or path == f"{BASE}/salesInvoices":
        return bc_orders(method, path, query, json, headers)
    if method == "GET" and path == f"{BASE}/salesQuotes":
        num = unquote(query).split("number eq '")[1].rstrip("'")
        x = BC_QUOTES.get(num)
        return _json(200, {"value": [{"id": x["id"], "number": num}] if x else []})
    if method == "POST" and path.startswith(f"{BASE}/salesQuotes(") and path.endswith(")/Microsoft.NAV.makeOrder"):
        x = next((v for v in BC_QUOTES.values() if path == f"{BASE}/salesQuotes({v['id']})/Microsoft.NAV.makeOrder"), None)
        if not x:
            return _json(404, {"error": {"message": "The sales quote does not exist."}})
        del BC_QUOTES[x["number"]]                       # Make Order: the quote becomes the order
        no = "SO" + str(1001 + len(BC_DOCS))
        BC_DOCS.append({"kind": "order", "number": no, "from_quote": x["number"]})
        BC_ORDERS[no] = {**x, "id": f"guid-{no}", "number": no,
                         "lines": [{**l, "id": f"{no}-L{i + 1}"} for i, l in enumerate(x["lines"])]}
        return httpx.Response(204, request=httpx.Request("POST", "https://x"))
    ext = f"{ROOT}/api/samuraiFoods/portal/v1.0/companies({CID})/portalSalesOrders("
    if path.startswith(ext):
        if not BC_EXT["installed"]:
            return _json(404, {"error": {"message": f"No HTTP resource was found that matches the request URI '{url}'."}})
        o = next((v for v in BC_ORDERS.values() if path == f"{ext}{v['id']})/Microsoft.NAV.assignLotsAndPost"), None)
        if not o:
            return _json(404, {"error": {"message": "The sales order does not exist."}})
        for l in o["lines"]:                             # the extension: lots first-expiry-first-out, then Ship and Invoice
            need = l["invoiceQuantity"] if l["lineObjectNumber"] in LOT_ITEMS else 0
            for lot in sorted(LOTS.get(l["lineObjectNumber"], []), key=lambda z: z[1]):
                if need <= 0:
                    break
                used = sum(u[3] for u in BC_LOT_USE if u[1] == l["lineObjectNumber"] and u[2] == lot[0])
                take = min(need, lot[2] - used)
                if take > 0:
                    BC_LOT_USE.append((o["number"], l["lineObjectNumber"], lot[0], take)); need -= take
            if need > 0:
                return _json(400, {"error": {"message": f"Not enough stock with lot numbers for item {l['lineObjectNumber']} at location LKO: {need:g} short."}})
            l["lots"] = True
        return bc_orders("POST", f"{BASE}/salesOrders({o['id']})/Microsoft.NAV.shipAndInvoice", "", None, {})
    if method == "GET" and path == f"{BASE}/customerPaymentJournals":
        return _json(200, {"value": [{"id": "j-cash-1", "code": "CASHRCPT", "displayName": "Cash receipts"},
                                     {"id": "j-bank-2", "code": "BANK", "displayName": "Bank receipts"}]})
    if method == "POST" and path.endswith("/customerPayments"):
        BC_PAYMENTS.append(json)
        # like the real customerPayments API: a positive amount is a payment received; the journal line gets it negated,
        # and posting a cash receipt line for a customer needs it negative
        BC_PAYMENTS[-1] = {**json, "journalAmount": -json.get("amount", 0)}
        return _json(201, {**json, "id": f"pay-{len(BC_PAYMENTS)}"})
    if method == "POST" and path == f"{BASE}/salesQuotes":
        return bc_create("quote", json)
    if method == "POST" and path == f"{BASE}/salesOrders":
        return bc_create("order", json)
    if path == BASE:
        return _json(200, {"id": CID, "name": COMPANY, "displayName": "SAMURAI FOODS"})
    if path == f"{BASE}/customers":                      # standard API v2.0, used by Test connection
        return _json(200, {"value": [{"number": "C0001", "displayName": "Lucknow Frozen Mart"}]})
    if path == f"{ROOT}/ODataV4/":
        return _json(200, {"value": [{"name": n, "kind": "EntitySet", "url": n} for n in PAGES] + [{"name": "Chart_of_Accounts", "kind": "EntitySet"}]})
    if path.startswith(OD + "/"):
        name = path[len(OD) + 1:]
        rows = PAGES.get(name)
        if rows is None:
            return _json(404, {"error": {"message": f"No HTTP resource was found that matches the request URI '{unquote(url)}'."}})
        if "$skiptoken=2" in query:                      # second page
            return _json(200, {"value": rows[2:]})
        nxt = {"@odata.nextLink": f"{OD}/{name}?$skiptoken=2"} if len(rows) > 2 else {}
        return _json(200, {"@odata.context": "x", "value": rows[:2], **nxt})
    return _json(404, {"error": {"message": "not found"}})


@pytest.fixture(scope="module")
def c():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    mp = pytest.MonkeyPatch()
    mp.setattr(httpx, "post", fake_post)
    mp.setattr(httpx, "request", fake_request)
    with TestClient(app) as client:
        r = client.post("/api/auth/setup", json={"name": "Admin", "username": "admin", "password": "admin12345"})
        client.headers["Authorization"] = "Bearer " + r.json()["token"]
        yield client
    mp.undo()


def connect(c, secret="right-secret", **ep):
    eps = {"customers": "odata:Customer_Card", "materials": "odata:Item_Card", "attributes": "odata:ItemAttributes",
           "prices": "odata:PriceListLines", "hsn": "odata:HSN_SAC", "charges": "odata:SalesCharges", **ep}
    r = c.put("/api/settings", json={"dynamics": {"product": "bc", "base_url": BASE, "tenant_id": TENANT, "client_id": "app-id",
                                                  "client_secret": secret, "ep": eps}})
    assert r.status_code == 200, r.text


def test_wrong_secret_is_explained(c):
    connect(c, secret="wrong")
    r = c.post("/api/integration/test")
    assert r.status_code == 502 and "Invalid client secret" in r.json()["detail"]


def test_connection_and_published_pages(c):
    connect(c)
    r = c.post("/api/integration/test")
    assert r.status_code == 200, r.text
    assert r.json()["company"] == COMPANY and r.json()["rows"] >= 1
    names = [x["name"] for x in c.get("/api/integration/services").json()["services"]]
    assert "Customer_Card" in names and "PriceListLines" in names


def test_every_master_has_an_api_button(c):
    masters = {m["entity"]: m["api"] for m in c.get("/api/integration/summary").json()["masters"]}
    assert masters == {k: True for k in ["customers", "materials", "attributes", "prices", "hsn", "charges"]}


def test_customers_with_gstin_state_and_paging(c):
    p = c.post("/api/integration/import/customers/api").json()
    assert p["map"]["gstin"] == "GST_Registration_No" and p["map"]["state"] == "State_Code" and p["map"]["credit_limit"] == "Credit_Limit_LCY"
    assert p["result"]["added"] == 3                                  # page 2 (nextLink) was read too
    r = c.post("/api/integration/import/customers/apply", json={"import_id": p["import_id"], "map": p["map"]})
    assert r.json()["added"] == 3
    with SessionLocal() as db:
        lfm = db.query(Customer).filter_by(code="C0001").one()
        assert (lfm.gstin, lfm.state, lfm.city, lfm.price_group, float(lfm.credit_limit)) == ("09AAACL1234F1Z5", "09", "Lucknow", "RETAIL", 500000)
        assert lfm.blocked is False
        assert db.query(Customer).filter_by(code="C0002").one().state == "07"      # DL -> 07
        b = db.query(Customer).filter_by(code="C0003").one()
        assert b.blocked is True and b.state == "27"                               # no state code: from the GSTIN


def test_download_all_masters(c):
    r = c.post("/api/integration/pull-all")
    assert r.status_code == 200, r.text
    res = {x["entity"]: x for x in r.json()["results"]}
    assert all(x["status"] in ("ok", "warning") for x in res.values()), res
    assert res["prices"]["added"] == 3 and res["prices"]["skipped"] == 2           # purchase and draft lines left out
    with SessionLocal() as db:
        assert db.query(Material).filter_by(code="SF-001-500").one().hsn == "16010000"
        assert db.query(Material).filter_by(code="SF-900").one().blocked is True
        assert {h.code: float(h.rate) for h in db.query(HsnCode)} == {"16010000": 5.0, "21039090": 18.0, "07019000": 0.0, "19059090": 0.0}
        hsn_errs = res["hsn"]["errors"]
        assert len(hsn_errs) == 1 and "19059090" in hsn_errs[0] and '"FOOD"' in hsn_errs[0]     # warned, EXEMPT is not
        prices = {(p.type, p.code, p.material_code): p for p in db.query(Price)}
        # the price list, plus the item's own Unit Price where no price list line is for all customers (as in Business Central)
        assert set(prices) == {("all", "", "SF-001-500"), ("group", "RETAIL", "SF-001-500"), ("customer", "C0002", "SF-002-500"), ("all", "", "SF-002-500")}
        assert float(prices[("all", "", "SF-002-500")].price) == 640
        allp = prices[("all", "", "SF-001-500")]
        assert allp.valid_from is None and allp.valid_to is None                    # 0001-01-01 means no date
        assert str(prices[("customer", "C0002", "SF-002-500")].valid_to) == "2026-12-31"
        assert float(prices[("group", "RETAIL", "SF-001-500")].min_qty) == 10
    assert c.get("/api/hsn").json()["materials_without_hsn"] == 0
    charges = {x["code"]: x for x in c.get("/api/charges").json()}
    assert charges["TCS"]["stage"] == "post" and charges["FRT"]["stage"] == "pre"
    attrs = c.get("/api/materials").json()
    assert next(m for m in attrs if m["code"] == "SF-001-500")["attrs"]["Pack size"] == "500 g"


def test_materials_take_gst_from_downloaded_hsn(c):
    mats = {m["code"]: m for m in c.get("/api/materials").json()}
    assert mats["SF-001-500"]["gst"] == 5 and mats["SF-001-500"]["hsn_known"]
    assert mats["SF-900"]["gst"] == 18


def test_chosen_columns_are_remembered(c):
    p = c.post("/api/integration/import/attributes/api").json()
    m = {**p["map"], "value": "Attribute"}                         # a deliberate, odd choice
    c.post("/api/integration/import/attributes/apply", json={"import_id": p["import_id"], "map": m})
    again = c.post("/api/integration/import/attributes/api").json()
    assert again["map"]["value"] == "Attribute"


def test_bad_page_name_reports_and_keeps_data(c):
    connect(c, prices="odata:Sales_Price_Typo")
    res = {x["entity"]: x for x in c.post("/api/integration/pull-all").json()["results"]}
    assert res["prices"]["status"] == "error" and "No HTTP resource" in res["prices"]["message"]
    with SessionLocal() as db:
        assert db.query(Price).filter(Price.type != "all").count() == 2      # price list lines not wiped
    connect(c, charges="")
    res = {x["entity"]: x for x in c.post("/api/integration/pull-all").json()["results"]}
    assert res["charges"]["status"] == "skipped"


def test_standard_api_names_still_work(c):
    connect(c, customers="customers")
    p = c.post("/api/integration/import/customers/api").json()
    assert p["map"]["code"] == "number" and p["map"]["name"] == "displayName" and p["result"]["updated"] == 1


def test_gst_rate_entered_per_gst_group(c):
    connect(c)
    p = c.post("/api/integration/import/hsn/api").json()
    groups = {g["code"]: g for g in p["gst_groups"]}
    assert groups["GST5"]["rate"] == 5 and groups["FOOD"]["rate"] == 0 and not groups["FOOD"]["set"]
    assert any('"FOOD"' in e for e in p["result"]["errors"])
    # the administrator enters the rate for FOOD; the preview no longer warns
    p2 = c.post("/api/integration/import/hsn/preview", json={"import_id": p["import_id"], "map": p["map"], "gst_rates": {"FOOD": 18}}).json()
    assert {g["code"]: g["rate"] for g in p2["gst_groups"]}["FOOD"] == 18 and not p2["result"]["errors"]
    c.post("/api/integration/import/hsn/apply", json={"import_id": p["import_id"], "map": p["map"], "gst_rates": {"FOOD": 18}})
    with SessionLocal() as db:
        assert float(db.get(HsnCode, "19059090").rate) == 18
    # remembered: the next download (and Download all) use it without asking
    p3 = c.post("/api/integration/import/hsn/api").json()
    assert {g["code"]: g for g in p3["gst_groups"]}["FOOD"]["set"] and not p3["result"]["errors"]
    res = {x["entity"]: x for x in c.post("/api/integration/pull-all").json()["results"]}
    assert not res["hsn"]["errors"]
    with SessionLocal() as db:
        assert float(db.get(HsnCode, "19059090").rate) == 18 and float(db.get(HsnCode, "16010000").rate) == 5


def test_rate_per_hsn_code_when_page_has_no_gst_group(c, monkeypatch):
    no_group = [{k: v for k, v in r.items() if k != "GST_Group_Code"} for r in HSN]
    monkeypatch.setitem(PAGES, "HSN_SAC", no_group)
    connect(c)
    p = c.post("/api/integration/import/hsn/api").json()
    assert not p["map"]["gst_group"]
    keys = {g["code"] for g in p["gst_groups"]}
    assert keys == {"HSN 16010000", "HSN 21039090", "HSN 07019000", "HSN 19059090"} and all(g["by_hsn"] for g in p["gst_groups"])
    assert len(p["result"]["errors"]) == 4
    rates = {"HSN 16010000": 5, "HSN 21039090": 18, "HSN 07019000": 0, "HSN 19059090": 12}
    p2 = c.post("/api/integration/import/hsn/preview", json={"import_id": p["import_id"], "map": p["map"], "gst_rates": rates}).json()
    assert not p2["result"]["errors"]
    c.post("/api/integration/import/hsn/apply", json={"import_id": p["import_id"], "map": p["map"], "gst_rates": rates})
    with SessionLocal() as db:
        assert float(db.get(HsnCode, "19059090").rate) == 12 and float(db.get(HsnCode, "16010000").rate) == 5
    res = {x["entity"]: x for x in c.post("/api/integration/pull-all").json()["results"]}
    assert not res["hsn"]["errors"]
    with SessionLocal() as db:
        assert float(db.get(HsnCode, "19059090").rate) == 12


def test_blank_gst_group_can_be_given_a_rate(c, monkeypatch):
    blank = [{**r, "GST_Group_Code": ""} for r in HSN]
    monkeypatch.setitem(PAGES, "HSN_SAC", blank)
    connect(c)
    p = c.post("/api/integration/import/hsn/api").json()
    assert p["map"]["gst_group"] == "GST_Group_Code" and all(g["by_hsn"] for g in p["gst_groups"])



def _doc(c, kind, cust="C0001", **extra):
    cid = next(x["id"] for x in c.get("/api/customers").json() if x["code"] == cust)
    from app.services.common import local_today
    body = {"kind": kind, "customer_id": cid, "date": local_today().isoformat(), "lines": [{"material": "SF-001-500", "qty": 12}], **extra}
    r = c.post("/api/docs", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_quotes_and_orders_go_to_dynamics_automatically(c):
    connect(c, customers="odata:Customer_Card")
    c.post("/api/integration/pull-all")
    c.put("/api/settings", json={"dynamics": {"auto_push": True, "ep": {"quotes": "salesQuotes", "orders": "salesOrders"}}})
    BC_DOCS.clear()

    q = _doc(c, "quote")
    got = c.get(f"/api/docs/{q['id']}").json()
    assert got["sync"]["status"] == "synced" and got["sync"]["no"] == "SQ1001", got
    sent = BC_DOCS[0]
    assert sent["customerNumber"] == "C0001" and sent["externalDocumentNumber"] == q["no"]
    assert sent["salesQuoteLines"][0]["lineObjectNumber"] == "SF-001-500" and sent["salesQuoteLines"][0]["quantity"] == 12

    o = _doc(c, "order", quote_id=q["id"])                 # an administrator's order is approved at once
    got = c.get(f"/api/docs/{o['id']}").json()
    assert got["status"] == "approved" and got["sync"]["status"] == "synced" and got["sync"]["no"] == "SO1002"
    # Business Central's flow: Make Order on the quote; the quote is gone from the quote list, nothing made twice
    assert BC_DOCS[1] == {"kind": "order", "number": "SO1002", "from_quote": "SQ1001"} and "SQ1001" not in BC_QUOTES
    bo = BC_ORDERS["SO1002"]
    assert bo["externalDocumentNumber"] == o["no"] and bo["lines"][0]["quantity"] == 12 and bo["lines"][0]["unitPrice"] > 0
    assert c.get("/api/counts").json().get("integration", 0) == 0          # nothing left waiting
    log = c.get("/api/integration/summary").json()["log"]
    assert any("Sent automatically" in x["message"] for x in log)


def test_unknown_salesperson_is_left_out_not_lost(c):
    with SessionLocal() as db:
        from app.models import User
        u = db.query(User).filter_by(username="admin").one()
        u.emp_code = "EMP-77"                               # not a salesperson in Business Central
        db.commit()
    q = _doc(c, "quote")
    got = c.get(f"/api/docs/{q['id']}").json()
    assert got["sync"]["status"] == "synced" and "salesperson" not in BC_DOCS[-1]
    with SessionLocal() as db:
        from app.models import User
        u = db.query(User).filter_by(username="admin").one()
        u.emp_code = "SP01"
        db.commit()
    q = _doc(c, "quote")
    assert BC_DOCS[-1]["salesperson"] == "SP01"


def test_dynamics_down_keeps_document_waiting(c):
    BC_DOWN["on"] = True
    try:
        q = _doc(c, "quote")
    finally:
        BC_DOWN["on"] = False
    got = c.get(f"/api/docs/{q['id']}").json()
    assert got["sync"]["status"] == "error" and "503" in (got["sync"]["error"] or "")
    assert c.get("/api/counts").json()["integration"] == 1                 # still in the queue
    r = c.post("/api/integration/push").json()                             # Send via API later
    assert r["sent"] == 1 and c.get(f"/api/docs/{q['id']}").json()["sync"]["status"] == "synced"


def test_automatic_sending_off_waits_for_send_via_api(c):
    c.put("/api/settings", json={"dynamics": {"auto_push": False}})
    n = len(BC_DOCS)
    q = _doc(c, "quote")
    assert c.get(f"/api/docs/{q['id']}").json()["sync"]["status"] == "pending" and len(BC_DOCS) == n
    c.post("/api/integration/push")
    assert c.get(f"/api/docs/{q['id']}").json()["sync"]["status"] == "synced"


COMPANY_PAGE = [{"Name": "SAMURAI FOODS", "Address": "SHOP NO K 28 KISAN BAZAAR", "Address_2": "GOMTI NAGAR", "City": "LUCKNOW",
                 "Post_Code": "226010", "Country_Region_Code": "IN", "Phone_No": "", "E_Mail": "", "GST_Registration_No": "09AFUFS4116C1ZT",
                 "P_A_N_No": "AFUFS4116C", "SF_FSSAI_No": "12725066002389", "Bank_Name": "Bandhan Bank", "Bank_Branch_No": "Lalbagh, Lucknow",
                 "Bank_Account_No": "20100076657855", "IBAN": "BDBL0001582", "SF_UPI_Id": "3285679a@bandhan"}]


def test_company_details_from_dynamics(c, monkeypatch):
    monkeypatch.setitem(PAGES, "Company_Information", COMPANY_PAGE)
    connect(c, company="odata:Company_Information")
    r = c.post("/api/integration/company")
    assert r.status_code == 200, r.text
    s = c.get("/api/settings").json()
    co, pr = s["company"], s["print"]
    assert co["legal_name"] == "SAMURAI FOODS" and co["gstin"] == "09AFUFS4116C1ZT" and co["pan"] == "AFUFS4116C" and co["fssai"] == "12725066002389"
    assert co["address"] == "SHOP NO K 28 KISAN BAZAAR\nGOMTI NAGAR\nLUCKNOW, 226010\nIndia" and co["state"] == "09"
    assert (pr["bank_name"], pr["account_no"], pr["branch"], pr["ifsc"], pr["upi_id"]) == ("Bandhan Bank", "20100076657855", "Lalbagh, Lucknow", "BDBL0001582", "3285679a@bandhan")


def test_customer_address_lines_and_item_mrp_pack(c, monkeypatch):
    cust = [{**CUSTOMERS[0], "Name": "Mr.Durgesh K Gupta", "Name_2": "D.S Associates", "Address": "Ward No.-41,", "Address_2": "Rahmatnagar, Mirzapur",
             "City": "Gorakhpur", "Post_Code": "273005"}]
    items = [{**ITEMS[0], "No": "SF-001-1000.", "Unit_Price": 660}, {**ITEMS[1], "No": "SF-013-1000", "Unit_Price": 690, "Net_Weight": 0}]
    monkeypatch.setitem(PAGES, "Customer_Card", cust)
    monkeypatch.setitem(PAGES, "Item_Card", items)
    connect(c)
    for ent in ("customers", "materials"):
        p = c.post(f"/api/integration/import/{ent}/api").json()
        c.post(f"/api/integration/import/{ent}/apply", json={"import_id": p["import_id"], "map": p["map"]})
    with SessionLocal() as db:
        cu = db.query(Customer).filter_by(code="C0001").one()
        assert cu.address == "D.S Associates\nWard No.-41,\nRahmatnagar, Mirzapur" and cu.city == "Gorakhpur"
        m = db.query(Material).filter_by(code="SF-001-1000.").one()
        assert float(m.mrp) == 660 and float(m.pack_qty) == 1.0


UNITS = [{"Item_No": "SF-001-500", "Code": "KG", "Qty_per_Unit_of_Measure": 1},
         {"Item_No": "SF-001-500", "Code": "PACKET", "Qty_per_Unit_of_Measure": 0.5},
         {"Item_No": "SF-002-500", "Code": "KG", "Qty_per_Unit_of_Measure": 1}]


def test_mrp_includes_gst_price_groups_do_not(c, monkeypatch):
    """MRP (item Unit Price / all customers) has GST in it; SRP, CRP and HORECA prices get GST added.
    Each customer gets its own price group's price; the MRP only when its group has none for the item.
    The report's example: MRP 900, 20% discount, 2 kg, 5% GST -> 1371.43 + 68.57 = 1440. Pkts from the PACKET unit."""
    items = [{**ITEMS[0], "Unit_Price": 900}, {**ITEMS[1], "Unit_Price": 640}]
    groups = [("SRP", 700), ("CRP", 650), ("HORECA", 600)]
    prices = [{"Price_Type": "Sale", "Source_Type": "Customer Price Group", "Source_No": g, "Product_No": "SF-001-500", "Unit_of_Measure_Code": "KG",
               "Minimum_Quantity": 0, "Unit_Price": v, "Starting_Date": EMPTY, "Ending_Date": EMPTY, "Status": "Active"} for g, v in groups]
    custs = [{**CUSTOMERS[0], "No": f"G-{g}", "Name": f"{g} buyer", "Customer_Price_Group": g} for g, _ in groups] + \
            [{**CUSTOMERS[0], "No": "G-NONE", "Name": "No group", "Customer_Price_Group": ""},
             {**CUSTOMERS[0], "No": "G-horeca2", "Name": "Lower case group", "Customer_Price_Group": " horeca "}]
    monkeypatch.setitem(PAGES, "Item_Card", items)
    monkeypatch.setitem(PAGES, "PriceListLines", prices)
    monkeypatch.setitem(PAGES, "Customer_Card", custs)
    monkeypatch.setitem(PAGES, "Item_Units_of_Measure", UNITS)
    monkeypatch.setitem(globals(), "CUSTOMERS", CUSTOMERS + custs)      # Business Central knows them too
    connect(c, units="odata:Item_Units_of_Measure")
    c.put("/api/settings", json={"dynamics": {"auto_push": True}, "round_off": False, "mrp_incl_gst": True, "incl_gst_groups": "MRP"})
    res = {x["entity"]: x for x in c.post("/api/integration/pull-all").json()["results"]}
    assert res["prices"]["status"] in ("ok", "warning"), res["prices"]
    with SessionLocal() as db:
        assert float(db.query(Material).filter_by(code="SF-001-500").one().pack_qty) == 0.5
        assert float(db.query(Material).filter_by(code="SF-002-500").one().pack_qty) == 0     # no PACKET unit: no packets
    ids = {x["code"]: x["id"] for x in c.get("/api/customers").json()}
    from app.services.common import local_today

    def line(cust, mat="SF-001-500", qty=1, disc=0):
        r = c.post("/api/docs", json={"kind": "order", "customer_id": ids[cust], "date": local_today().isoformat(),
                                      "lines": [{"material": mat, "qty": qty, "disc": disc}]})
        assert r.status_code == 200, r.text
        return c.get(f"/api/docs/{r.json()['id']}").json()

    for g, v in groups:                                    # group price, GST added on top
        d = line(f"G-{g}")
        l = d["lines"][0]
        assert (l["price"], l["price_incl"], l["taxable"], l["gst"]) == (v, False, v, v * 0.05), (g, l)
        assert l["price_source"] == f"{g} price" and d["customer_detail"]["price_group"] == g
    d = line("G-horeca2")                                  # " horeca " still finds HORECA
    assert d["lines"][0]["price"] == 600 and not d["lines"][0]["price_incl"]
    d = line("G-NONE", qty=2, disc=20)                     # no group: the MRP, GST inside it
    l = d["lines"][0]
    assert l["price"] == 900 and l["price_incl"] and l["taxable"] == 1371.43 and l["gst"] == 68.57 and d["total"] == 1440
    assert l["mrp"] == 900 and l["pack_qty"] == 0.5
    d = line("G-SRP", mat="SF-002-500")                    # SRP group has no price for this item: its MRP
    assert d["lines"][0]["price"] == 640 and d["lines"][0]["price_incl"] and d["total"] == 640
    # Business Central gets prices without GST, so its amounts are the portal's
    assert d["sync"]["status"] == "synced", d["sync"]
    sent = BC_DOCS[-1]["salesOrderLines"][0]
    assert abs(sent["unitPrice"] * 1.05 - 640) < 0.01


def test_mrp_group_can_be_listed_as_including_gst(c):
    c.put("/api/settings", json={"incl_gst_groups": "MRP, HORECA", "round_off": False})
    ids = {x["code"]: x["id"] for x in c.get("/api/customers").json()}
    from app.services.common import local_today
    d = c.post("/api/docs", json={"kind": "quote", "customer_id": ids["G-HORECA"], "date": local_today().isoformat(),
                                  "lines": [{"material": "SF-001-500", "qty": 1}]}).json()
    assert d["total"] == 600                               # now 571.43 + 28.57
    c.put("/api/settings", json={"incl_gst_groups": "MRP"})



def test_invoice_posts_the_order_in_business_central(c, monkeypatch):
    """Invoice here -> the Business Central order is posted (Ship and Invoice) for exactly the invoiced quantities,
    and the posted invoice number comes back; in two parts, then the order is gone from Business Central."""
    connect(c, quotes="salesQuotes", orders="salesOrders")
    c.put("/api/settings", json={"dynamics": {"auto_push": True, "post_invoices": True}, "round_off": True})
    BC_EXT["installed"] = True                               # lot-tracked item: the extension assigns lots
    ids = {x["code"]: x["id"] for x in c.get("/api/customers").json()}
    from app.services.common import local_today
    today = local_today().isoformat()
    o = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": today,
                                  "lines": [{"material": "SF-001-500", "qty": 10}, {"material": "SF-002-500", "qty": 4}]}).json()
    o = c.get(f"/api/docs/{o['id']}").json()
    bc_no = o["sync"]["no"]
    assert o["sync"]["status"] == "synced" and bc_no in BC_ORDERS
    l1, l2 = [l["line_id"] for l in o["lines"]]
    BC_PATCHES.clear()

    i1 = c.post(f"/api/docs/{o['id']}/invoice", json={"lines": [{"line_id": l1, "qty": 6}]}).json()
    g1 = c.get(f"/api/docs/{i1['id']}").json()
    assert g1["sync"]["status"] == "synced" and g1["sync"]["no"] == BC_POSTED[-1]["number"], g1["sync"]
    assert BC_PATCHES == [("SF-001-500", 6, 6), ("SF-002-500", 0, 0)]                    # only what this invoice bills
    assert [l["invoicedQuantity"] for l in BC_ORDERS[bc_no]["lines"]] == [6, 0]

    i2 = c.post(f"/api/docs/{o['id']}/invoice", json={}).json()                          # the rest
    g2 = c.get(f"/api/docs/{i2['id']}").json()
    assert g2["sync"]["status"] == "synced" and g2["sync"]["no"] != g1["sync"]["no"]
    assert bc_no not in BC_ORDERS                                                         # fully invoiced: gone in BC
    od = c.get(f"/api/docs/{o['id']}").json()
    assert [x["dyn"] for x in od["invoices"]] == [g1["sync"]["no"], g2["sync"]["no"]]
    r = c.post(f"/api/docs/{i2['id']}/cancel")                                            # posted: credit memo in BC
    assert r.status_code == 409 and "credit memo" in r.json()["detail"]
    assert not g2["can_cancel"] and not g2["can_post"]


def test_order_not_in_dynamics_yet_then_retry(c):
    c.put("/api/settings", json={"dynamics": {"auto_push": False, "post_invoices": True}})
    ids = {x["code"]: x["id"] for x in c.get("/api/customers").json()}
    from app.services.common import local_today
    o = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": local_today().isoformat(),
                                  "lines": [{"material": "SF-001-500", "qty": 2}]}).json()
    inv = c.post(f"/api/docs/{o['id']}/invoice", json={}).json()
    g = c.get(f"/api/docs/{inv['id']}").json()
    assert g["sync"]["status"] == "error" and "not in Dynamics yet" in g["sync"]["error"] and g["can_post"]
    BC_EXT["installed"] = True
    assert c.post("/api/integration/push").json()["sent"] >= 1                           # send the order
    r = c.post(f"/api/docs/{inv['id']}/post-dynamics")
    assert r.status_code == 200 and r.json()["sync"]["status"] == "synced" and r.json()["sync"]["no"].startswith("PSI-")
    assert c.post(f"/api/docs/{inv['id']}/post-dynamics").status_code == 409            # not twice


def test_changed_order_in_dynamics_is_not_posted(c):
    c.put("/api/settings", json={"dynamics": {"auto_push": True, "post_invoices": True}})
    ids = {x["code"]: x["id"] for x in c.get("/api/customers").json()}
    from app.services.common import local_today
    o = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": local_today().isoformat(),
                                  "lines": [{"material": "SF-001-500", "qty": 3}]}).json()
    o = c.get(f"/api/docs/{o['id']}").json()
    BC_ORDERS[o["sync"]["no"]]["lines"][0]["lineObjectNumber"] = "SF-999"                # someone changed it in BC
    n = len(BC_POSTED)
    inv = c.post(f"/api/docs/{o['id']}/invoice", json={}).json()
    g = c.get(f"/api/docs/{inv['id']}").json()
    assert g["sync"]["status"] == "error" and "SF-999" in g["sync"]["error"] and len(BC_POSTED) == n
    # the invoice stays valid here; it can be cancelled (not posted) and the order invoiced again later
    assert g["can_cancel"] and c.post(f"/api/docs/{inv['id']}/cancel").json()["status"] == "cancelled"


def test_posting_off_leaves_invoices_local(c):
    c.put("/api/settings", json={"dynamics": {"auto_push": True, "post_invoices": False}})
    ids = {x["code"]: x["id"] for x in c.get("/api/customers").json()}
    from app.services.common import local_today
    o = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": local_today().isoformat(),
                                  "lines": [{"material": "SF-001-500", "qty": 1}]}).json()
    n = len(BC_POSTED)
    inv = c.post(f"/api/docs/{o['id']}/invoice", json={}).json()
    g = c.get(f"/api/docs/{inv['id']}").json()
    assert g["sync"]["status"] == "na" and g["can_post"] and len(BC_POSTED) == n


def _setup_bc(c, ext=False):
    connect(c, quotes="salesQuotes", orders="salesOrders", payments="customerPaymentJournals(j1)/customerPayments")
    c.put("/api/settings", json={"dynamics": {"auto_push": True, "post_invoices": True, "payments_negative": True}, "round_off": True})
    BC_EXT["installed"] = ext
    return {x["code"]: x["id"] for x in c.get("/api/customers").json()}


def test_screenshot_flow_quote_lots_manual_post_and_payment(c):
    """The flow from the screenshots: quotation -> order (Make Order in Business Central), invoice fails for lot
    numbers, lots assigned and posted in Business Central, linked here; 1,320 received with 500 allocated, the
    rest applied from on account; the payment goes to Business Central applied to the posted invoice."""
    ids = _setup_bc(c, ext=False)
    from app.services.common import local_today
    today = local_today().isoformat()
    q = c.post("/api/docs", json={"kind": "quote", "customer_id": ids["C0001"], "date": today, "lines": [{"material": "SF-001-500", "qty": 2}]}).json()
    qd = c.get(f"/api/docs/{q['id']}").json()
    assert qd["sync"]["status"] == "synced" and qd["sync"]["no"] in BC_QUOTES
    o = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": today, "quote_id": q["id"],
                                  "lines": [{"material": "SF-001-500", "qty": 2}]}).json()
    od = c.get(f"/api/docs/{o['id']}").json()
    assert od["sync"]["status"] == "synced" and qd["sync"]["no"] not in BC_QUOTES         # the quote became the order in BC
    bo = BC_ORDERS[od["sync"]["no"]]
    assert bo["externalDocumentNumber"] == o["no"]

    inv = c.post(f"/api/docs/{o['id']}/invoice", json={}).json()
    g = c.get(f"/api/docs/{inv['id']}").json()
    assert g["sync"]["status"] == "error" and "lot number" in g["sync"]["error"] and "Post in Dynamics" in g["sync"]["error"]

    # in Business Central: lots assigned on the order and posted there
    for l in bo["lines"]:
        l["lots"] = True
    bc_orders("POST", f"{BASE}/salesOrders({bo['id']})/Microsoft.NAV.shipAndInvoice", "", None, {})
    posted = BC_POSTED[-1]["number"]
    n = len(BC_POSTED)
    r = c.post(f"/api/docs/{inv['id']}/post-dynamics").json()
    assert r["sync"]["status"] == "synced" and r["sync"]["no"] == posted and len(BC_POSTED) == n        # linked, not posted twice
    assert any("linked to invoice" in x["message"] for x in c.get("/api/integration/summary").json()["log"])

    # 1,320 received, only 500 allocated: 820 stays on account and can pay the invoice later
    total = r["total"]
    p = c.post("/api/payments", json={"customer_id": ids["C0001"], "date": today, "amount": total, "mode": "cash", "ref": "",
                                      "allocations": [{"order_id": inv["id"], "amount": 500}]}).json()
    assert p["unallocated"] == round(total - 500, 2)
    g = c.get(f"/api/docs/{inv['id']}").json()
    assert g["pay"] == "partly" and g["on_account"] >= round(total - 500, 2)
    g = c.post(f"/api/docs/{inv['id']}/apply-on-account").json()
    assert g["pay"] == "paid" and g["due"] == 0
    assert c.get(f"/api/payments/{p['id']}").json()["unallocated"] == 0
    assert c.post(f"/api/docs/{inv['id']}/apply-on-account").status_code == 422

    # Business Central gets the payment applied to the posted invoice
    BC_PAYMENTS.clear()
    c.post("/api/integration/push")
    mine = [x for x in BC_PAYMENTS if x["documentNumber"] == p["no"]]
    assert len(mine) == 1 and mine[0]["appliesToInvoiceNumber"] == posted and mine[0]["amount"] == total and mine[0]["journalAmount"] == -total


def test_order_differs_from_quote(c):
    ids = _setup_bc(c, ext=True)
    from app.services.common import local_today
    today = local_today().isoformat()
    q = c.post("/api/docs", json={"kind": "quote", "customer_id": ids["C0001"], "date": today, "lines": [{"material": "SF-001-500", "qty": 12}]}).json()
    qno = c.get(f"/api/docs/{q['id']}").json()["sync"]["no"]
    o = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": today, "quote_id": q["id"],
                                  "lines": [{"material": "SF-001-500", "qty": 10}, {"material": "SF-002-500", "qty": 2}]}).json()
    bo = BC_ORDERS[c.get(f"/api/docs/{o['id']}").json()["sync"]["no"]]
    assert qno not in BC_QUOTES
    assert [(l["lineObjectNumber"], l["quantity"]) for l in bo["lines"]] == [("SF-001-500", 10), ("SF-002-500", 2)]


def test_quote_gone_from_dynamics_order_made_new(c):
    ids = _setup_bc(c, ext=True)
    from app.services.common import local_today
    today = local_today().isoformat()
    q = c.post("/api/docs", json={"kind": "quote", "customer_id": ids["C0001"], "date": today, "lines": [{"material": "SF-002-500", "qty": 1}]}).json()
    BC_QUOTES.pop(c.get(f"/api/docs/{q['id']}").json()["sync"]["no"])                   # deleted in BC meanwhile
    o = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": today, "quote_id": q["id"],
                                  "lines": [{"material": "SF-002-500", "qty": 1}]}).json()
    od = c.get(f"/api/docs/{o['id']}").json()
    assert od["sync"]["status"] == "synced" and BC_DOCS[-1]["externalDocumentNumber"] == o["no"]


def test_extension_assigns_lots_first_expiry_first_out(c):
    ids = _setup_bc(c, ext=True)
    BC_LOT_USE.clear()
    from app.services.common import local_today
    today = local_today().isoformat()
    o = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": today, "lines": [{"material": "SF-001-500", "qty": 6}]}).json()
    bno = c.get(f"/api/docs/{o['id']}").json()["sync"]["no"]
    inv = c.post(f"/api/docs/{o['id']}/invoice", json={}).json()
    g = c.get(f"/api/docs/{inv['id']}").json()
    assert g["sync"]["status"] == "synced", g["sync"]
    assert [(u[2], u[3]) for u in BC_LOT_USE if u[0] == bno] == [("L-2605", 5), ("L-2611", 1)]      # earliest expiry first
    assert BC_POSTED[-1]["postingDate"] == today                                            # posting date = invoice date
    assert any("lots assigned (FEFO)" in x["message"] for x in c.get("/api/integration/summary").json()["log"])
    o2 = c.post("/api/docs", json={"kind": "order", "customer_id": ids["C0001"], "date": today, "lines": [{"material": "SF-001-500", "qty": 500}]}).json()
    inv2 = c.post(f"/api/docs/{o2['id']}/invoice", json={}).json()
    assert "Not enough stock with lot numbers" in c.get(f"/api/docs/{inv2['id']}").json()["sync"]["error"]
    BC_EXT["installed"] = False



def test_find_payment_journals_and_warn_without_endpoint(c):
    connect(c, payments="")
    ids = {x["code"]: x["id"] for x in c.get("/api/customers").json()}
    from app.services.common import local_today
    c.post("/api/payments", json={"customer_id": ids["C0001"], "date": local_today().isoformat(), "amount": 100, "mode": "cash", "ref": "", "allocations": []})
    r = c.post("/api/integration/push").json()
    assert "payments" in r["skipped"]
    log = c.get("/api/integration/summary").json()["log"][0]
    assert "no endpoint set: payments" in log["message"] and log["status"] == "error"
    j = c.get("/api/integration/payment-journals").json()["journals"]
    assert j[0] == {"id": "j-cash-1", "code": "CASHRCPT", "name": "Cash receipts", "endpoint": "customerPaymentJournals(j-cash-1)/customerPayments"}
    connect(c, payments=j[0]["endpoint"])
    BC_PAYMENTS.clear()
    assert c.post("/api/integration/push").json()["skipped"] == [] and len(BC_PAYMENTS) >= 1


def test_journal_payments_post_negative_in_bc(c):
    connect(c, payments="customerPaymentJournals(j-cash-1)/customerPayments")
    s = c.get("/api/settings").json()["dynamics"]; s["payments_negative"] = False
    c.put("/api/settings", json={"dynamics": s})
    ids = {x["code"]: x["id"] for x in c.get("/api/customers").json()}
    from app.services.common import local_today
    c.post("/api/payments", json={"customer_id": ids["C0001"], "date": local_today().isoformat(), "amount": 250, "mode": "cash", "ref": "", "allocations": []})
    BC_PAYMENTS.clear()
    c.post("/api/integration/push")
    assert BC_PAYMENTS and all(x["amount"] > 0 and x["journalAmount"] < 0 for x in BC_PAYMENTS), BC_PAYMENTS
    s = c.get("/api/settings").json()["dynamics"]; s["payments_negative"] = True     # export-file setting: no effect on the API
    c.put("/api/settings", json={"dynamics": s})
    c.post("/api/payments", json={"customer_id": ids["C0001"], "date": local_today().isoformat(), "amount": 90, "mode": "cash", "ref": "", "allocations": []})
    BC_PAYMENTS.clear()
    c.post("/api/integration/push")
    assert BC_PAYMENTS and all(x["amount"] > 0 and x["journalAmount"] < 0 for x in BC_PAYMENTS), BC_PAYMENTS
