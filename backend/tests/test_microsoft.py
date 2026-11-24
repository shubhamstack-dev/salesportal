"""Sign in with Microsoft against a simulated Entra ID: real RS256-signed ID tokens, published keys,
the authorization-code exchange, and the checks a forged or replayed sign-in must fail."""
import os
import tempfile
import time
from urllib.parse import parse_qs, unquote, urlparse

os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/t.db"))

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.routers import microsoft as M  # noqa: E402

TENANT, CLIENT = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k1", "use": "sig"}
CODES: dict = {}          # code -> claims Microsoft will put in the ID token
TOKEN_CALLS = []


def idt(claims, key=KEY, kid="k1"):
    now = int(time.time())
    base = {"aud": CLIENT, "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT, "iat": now, "nbf": now, "exp": now + 3600}
    return jwt.encode({**base, **claims}, key, algorithm="RS256", headers={"kid": kid})


def resp(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("GET", "https://login.microsoftonline.com"))


def fake_get(url, **kw):
    if url.endswith("/.well-known/openid-configuration"):
        return resp(200, {"jwks_uri": f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"})
    if url.endswith("/discovery/v2.0/keys"):
        return resp(200, {"keys": [JWK]})
    return resp(404, {})


def fake_post(url, data=None, **kw):
    assert url == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
    TOKEN_CALLS.append(data)
    if data["client_secret"] != "s3cret" or data["code"] not in CODES:
        return resp(400, {"error": "invalid_grant", "error_description": "AADSTS70008: The provided authorization code is invalid."})
    spec = CODES.pop(data["code"])
    return resp(200, {"id_token": spec(data) if callable(spec) else spec, "token_type": "Bearer"})


@pytest.fixture(scope="module")
def c():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    mp = pytest.MonkeyPatch()
    mp.setattr(httpx, "get", fake_get)
    mp.setattr(httpx, "post", fake_post)
    M._jwks.clear()
    with TestClient(app, follow_redirects=False) as client:
        tok = client.post("/api/auth/setup", json={"name": "Shubham Singh", "username": "admin", "password": "admin12345"}).json()["token"]
        client.headers["Authorization"] = "Bearer " + tok
        yield client
    mp.undo()


def setup_ms(c, **kw):
    r = c.put("/api/settings", json={"microsoft": {"enabled": True, "tenant_id": TENANT, "client_id": CLIENT, "client_secret": "s3cret",
                                                   "domains": "samuraifoods.co.in", "auto_register": True, **kw}})
    assert r.status_code == 200, r.text


def sign_in(c, claims=None, token=None, state=None, host="salesportal.nexdaequmsupport.com"):
    """Start -> (Microsoft) -> callback. Returns the fragment the browser lands on, as a dict."""
    h = {"host": host, "x-forwarded-proto": "https"}
    r = c.get("/api/auth/microsoft/start", headers=h)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    nonce, st = q["nonce"][0], state or q["state"][0]
    code = "code-" + str(len(TOKEN_CALLS)) + str(time.time())
    CODES[code] = token or (lambda data: idt({**claims, "nonce": nonce}))
    r = c.get(f"/api/auth/microsoft/callback?code={code}&state={st}", headers=h)
    assert r.status_code == 302 and r.headers["location"].startswith("/#")
    return {k: unquote(v[0]) for k, v in parse_qs(r.headers["location"][2:]).items()}


def test_not_set_up(c):
    assert c.get("/api/auth/status").json()["microsoft"] is False
    r = c.get("/api/auth/microsoft/start")
    assert "not set up" in unquote(r.headers["location"])


def test_settings_hide_the_secret(c):
    setup_ms(c)
    assert c.get("/api/auth/status").json()["microsoft"] is True
    s = c.get("/api/settings").json()["microsoft"]
    assert s["client_secret"] == "••••••" and s["tenant_id"] == TENANT
    c.put("/api/settings", json={"microsoft": {"client_secret": "••••••", "domains": "samuraifoods.co.in"}})   # masked: kept
    assert c.get("/api/auth/status").json()["microsoft"] is True
    assert c.put("/api/settings", json={"microsoft": {"tenant_id": "not a tenant!"}}).status_code == 422


def test_redirect_goes_to_microsoft_with_this_sites_callback(c):
    r = c.get("/api/auth/microsoft/start", headers={"host": "salesportal.nexdaequmsupport.com", "x-forwarded-proto": "https"})
    u = urlparse(r.headers["location"])
    q = parse_qs(u.query)
    assert u.netloc == "login.microsoftonline.com" and u.path == f"/{TENANT}/oauth2/v2.0/authorize"
    assert q["client_id"] == [CLIENT] and q["redirect_uri"] == ["https://salesportal.nexdaequmsupport.com/api/auth/microsoft/callback"]
    assert "openid" in q["scope"][0] and q["nonce"] and q["state"]


def test_new_person_becomes_a_registration_request(c):
    f = sign_in(c, {"oid": "oid-neha", "preferred_username": "Neha.Verma@samuraifoods.co.in", "name": "Neha Verma"})
    assert "Registration sent" in f["ms_info"] and "ms_token" not in f
    assert TOKEN_CALLS[-1]["redirect_uri"] == "https://salesportal.nexdaequmsupport.com/api/auth/microsoft/callback"
    neha = next(u for u in c.get("/api/users").json() if u["username"] == "neha.verma@samuraifoods.co.in")
    assert neha["pending"] and not neha["active"] and neha["microsoft"] and neha["name"] == "Neha Verma"
    f = sign_in(c, {"oid": "oid-neha", "preferred_username": "neha.verma@samuraifoods.co.in", "name": "Neha Verma"})
    assert "waiting for administrator approval" in f["ms_error"]
    upd = {k: neha[k] for k in ["name", "username", "role", "emp_code", "phone", "email", "territory", "customer_ids"]}
    assert c.patch(f"/api/users/{neha['id']}", json={**upd, "active": True}).status_code == 200      # approve
    f = sign_in(c, {"oid": "oid-neha", "preferred_username": "neha.verma@samuraifoods.co.in", "name": "Neha Verma"})
    me = c.get("/api/auth/me", headers={"Authorization": "Bearer " + f["ms_token"]}).json()
    assert me["user"]["username"] == "neha.verma@samuraifoods.co.in"


def test_existing_user_is_matched_by_email_then_by_account(c):
    r = c.post("/api/users", json={"name": "Alok Srivastava", "username": "alok", "password": "alok12345", "role": "manager",
                                   "email": "Alok.Srivastava@samuraifoods.co.in"})
    assert r.status_code == 200, r.text
    f = sign_in(c, {"oid": "oid-alok", "preferred_username": "alok.srivastava@samuraifoods.co.in", "name": "Alok S"})
    me = c.get("/api/auth/me", headers={"Authorization": "Bearer " + f["ms_token"]}).json()
    assert me["user"]["username"] == "alok" and me["user"]["role"] == "manager"
    with SessionLocal() as db:
        assert db.query(User).filter_by(username="alok").one().ms_oid == "oid-alok"
    # later the e-mail changes in Microsoft 365: still the same person, by the linked account
    f = sign_in(c, {"oid": "oid-alok", "preferred_username": "alok.s@samuraifoods.co.in"})
    assert "ms_token" in f
    # someone else claiming Alok's e-mail with another account is refused
    f = sign_in(c, {"oid": "oid-impostor", "preferred_username": "alok.srivastava@samuraifoods.co.in"})
    assert "different Microsoft account" in f["ms_error"]


def test_other_domains_and_closed_registration(c):
    f = sign_in(c, {"oid": "oid-x", "preferred_username": "someone@gmail.com"})
    assert "not from samuraifoods.co.in" in f["ms_error"]
    setup_ms(c, auto_register=False)
    f = sign_in(c, {"oid": "oid-new", "preferred_username": "new.person@samuraifoods.co.in"})
    assert "no portal account" in f["ms_error"]
    setup_ms(c)


def test_inactive_user_is_refused(c):
    r = c.post("/api/users", json={"name": "Left Company", "username": "left@samuraifoods.co.in", "password": "left12345", "active": False})
    assert r.status_code == 200
    f = sign_in(c, {"oid": "oid-left", "preferred_username": "left@samuraifoods.co.in"})
    assert "inactive" in f["ms_error"]


def test_forged_and_replayed_sign_ins_fail(c):
    claims = {"oid": "oid-alok", "preferred_username": "alok.s@samuraifoods.co.in"}
    f = sign_in(c, token=lambda d: idt({**claims, "nonce": "x"}, key=OTHER_KEY))          # signed by someone else
    assert "could not be verified" in f["ms_error"]
    f = sign_in(c, token=lambda d: idt({**claims, "nonce": "wrong"}))                     # nonce of another request
    assert "did not match" in f["ms_error"]
    f = sign_in(c, token=lambda d: idt({**claims, "nonce": "x", "aud": "another-app"}))    # token for another app
    assert "could not be verified" in f["ms_error"]
    f = sign_in(c, claims, state="forged-state")
    assert "did not come from this portal" in f["ms_error"]
    old = jwt.encode({"n": "n", "exp": int(time.time()) - 5, "p": "ms"}, os.getenv("JWT_SECRET", "change-this-secret"), algorithm="HS256")
    f = sign_in(c, claims, state=old)
    assert "took too long" in f["ms_error"]
    r = c.get("/api/auth/microsoft/callback?code=used-or-unknown&state=" + parse_qs(urlparse(
        c.get("/api/auth/microsoft/start").headers["location"]).query)["state"][0])
    assert "refused the sign-in" in unquote(r.headers["location"])
    r = c.get("/api/auth/microsoft/callback?error=access_denied&error_description=cancelled")
    assert "cancelled" in unquote(r.headers["location"])


def test_password_sign_in_still_works(c):
    assert c.post("/api/auth/login", json={"username": "alok", "password": "alok12345"}).status_code == 200
