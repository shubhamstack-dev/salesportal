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


def fake_request(method, url, json=None, headers=None, **kw):
    calls.append((method, url))
    if headers.get("Authorization") != "Bearer tok-123":
        return _json(401, {"error": {"message": "The credentials provided are incorrect"}})
    path, _, query = url.partition("?")
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
