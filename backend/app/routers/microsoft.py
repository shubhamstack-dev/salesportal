"""Sign in with Microsoft (Entra ID, the Microsoft 365 accounts of samuraifoods.co.in).

OpenID Connect authorization-code flow, run by this server as a confidential client:
  /api/auth/microsoft/start     -> Microsoft's sign-in page
  /api/auth/microsoft/callback  <- Microsoft sends the code back; the server swaps it for an ID token (with the
                                   client secret), checks the token's signature, audience, issuer and nonce, and
                                   finds the portal user.
The browser then lands on /#ms_token=... (or ms_error / ms_info). A fragment never reaches any server log.

Users are matched by their Microsoft account (object id) once linked, else by e-mail or username. Someone from an
allowed domain who is not a user yet becomes a registration request, approved by an administrator as usual.
"""
import secrets
import time
from urllib.parse import quote, urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import JWT_SECRET, get_db
from ..models import User
from ..security import hash_password, make_token
from ..services.common import MAX_PENDING_SIGNUPS, get_settings, local_today, pending_signups, save_pending_signups

router = APIRouter(prefix="/api/auth/microsoft", tags=["auth"])
LOGIN = "https://login.microsoftonline.com"
STATE_MINUTES = 10
_jwks: dict = {}          # tenant -> (fetched at, keys)


class MsError(Exception):
    pass


def ms_settings(db: Session) -> dict:
    return get_settings(db).get("microsoft") or {}


def ready(ms: dict) -> bool:
    return bool(ms.get("enabled") and ms.get("tenant_id") and ms.get("client_id") and ms.get("client_secret"))


def redirect_uri(request: Request) -> str:
    """The address Microsoft sends people back to. Built from the address the browser used (behind Caddy and nginx
    the scheme comes from X-Forwarded-Proto), so it is the same one to register in Azure."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host.split(',')[0].strip()}/api/auth/microsoft/callback"


# The mobile app opens /start?ret=<its own address>; the result goes back to the app instead of the web page.
APP_SCHEMES = ("salesportal://", "exp://", "exps://")


def app_return(ret: str) -> str:
    return ret if ret and ret.startswith(APP_SCHEMES) and len(ret) < 300 else ""


def _back(ret: str = "", **kv) -> RedirectResponse:
    frag = urlencode({k: v for k, v in kv.items() if v}, quote_via=quote)
    return RedirectResponse((app_return(ret) or "/") + "#" + frag, status_code=302)


@router.get("/start")
def start(request: Request, ret: str = "", db: Session = Depends(get_db)):
    ret = app_return(ret)
    ms = ms_settings(db)
    if not ready(ms):
        return _back(ret, ms_error="Sign in with Microsoft is not set up. Ask your administrator.")
    nonce = secrets.token_urlsafe(16)
    state = jwt.encode({"n": nonce, "exp": int(time.time()) + STATE_MINUTES * 60, "p": "ms", "r": ret}, JWT_SECRET, algorithm="HS256")
    q = {"client_id": ms["client_id"], "response_type": "code", "redirect_uri": redirect_uri(request), "response_mode": "query",
         "scope": "openid profile email", "state": state, "nonce": nonce, "prompt": "select_account"}
    return RedirectResponse(f"{LOGIN}/{ms['tenant_id'].strip()}/oauth2/v2.0/authorize?{urlencode(q)}", status_code=302)


def _keys(tenant: str) -> list[dict]:
    hit = _jwks.get(tenant)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    try:
        conf = httpx.get(f"{LOGIN}/{tenant}/v2.0/.well-known/openid-configuration", timeout=20).json()
        keys = httpx.get(conf["jwks_uri"], timeout=20).json()["keys"]
    except Exception as e:  # noqa: BLE001
        raise MsError(f"Could not reach Microsoft to check the sign-in ({e}).")
    _jwks[tenant] = (time.time(), keys)
    return keys


def check_id_token(id_token: str, ms: dict, nonce: str) -> dict:
    """Signature (Microsoft's published keys), audience (our app), issuer (a Microsoft tenant), expiry and nonce."""
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
    except jwt.PyJWTError:
        raise MsError("Microsoft returned an unreadable sign-in.")
    tenant = ms["tenant_id"].strip()
    keys = _keys(tenant)
    jwk = next((k for k in keys if k.get("kid") == kid), None)
    if not jwk:                                    # keys rotated: fetch once more
        _jwks.pop(tenant, None)
        jwk = next((k for k in _keys(tenant) if k.get("kid") == kid), None)
    if not jwk:
        raise MsError("Microsoft's signing key for this sign-in was not found.")
    try:
        claims = jwt.decode(id_token, jwt.PyJWK(jwk).key, algorithms=["RS256"], audience=ms["client_id"], leeway=120)
    except jwt.PyJWTError as e:
        raise MsError(f"The Microsoft sign-in could not be verified ({e}).")
    if claims.get("nonce") != nonce:
        raise MsError("The Microsoft sign-in did not match this request. Try again.")
    iss, tid = claims.get("iss", ""), claims.get("tid", "")
    if not tid or iss != f"{LOGIN}/{tid}/v2.0":
        raise MsError("The Microsoft sign-in came from an unexpected issuer.")
    return claims


def _domains(ms: dict) -> set[str]:
    return {d.strip().lower().lstrip("@") for d in str(ms.get("domains") or "").replace(";", ",").split(",") if d.strip()}


def find_or_request(db: Session, ms: dict, claims: dict) -> tuple[User | None, str]:
    """(user to sign in, message). No user: a message saying why, or that a registration request was made."""
    oid = str(claims.get("oid") or claims.get("sub") or "")
    email = str(claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
    upn = str(claims.get("preferred_username") or "").strip().lower()
    name = str(claims.get("name") or email.split("@")[0]).strip()[:120]
    domains = _domains(ms)
    if domains and not any(x.split("@")[-1] in domains for x in (email, upn) if "@" in x):
        return None, f"{email or 'This account'} is not from {', '.join(sorted(domains))}. Use your company Microsoft account."
    u = db.scalar(select(User).where(User.ms_oid == oid)) if oid else None
    if not u:
        keys = [k for k in {email, upn} if k]
        u = db.scalar(select(User).where(or_(func.lower(User.email).in_(keys), func.lower(User.username).in_(keys)))) if keys else None
        if u and u.ms_oid and u.ms_oid != oid:
            return None, "This portal user is linked to a different Microsoft account. Ask your administrator."
        if u:
            u.ms_oid = oid
    if u:
        if not u.email and email:
            u.email = email
        if not u.active:
            db.commit()
            if u.id in pending_signups(db):
                return None, "Your registration is waiting for administrator approval."
            return None, "This account is inactive. Ask your administrator."
        db.commit()
        return u, ""
    if not ms.get("auto_register", True):
        return None, f"{email} has no portal account. Ask your administrator to add you."
    pending = pending_signups(db)
    if len(pending) >= MAX_PENDING_SIGNUPS:
        return None, "Too many registrations are waiting. Ask your administrator."
    username = email or upn
    if db.scalar(select(User).where(User.username == username)):
        username = f"{username}.{secrets.token_hex(2)}"
    u = User(name=name or username, username=username[:80], email=email[:120], role="rep", active=False, ms_oid=oid,
             password_hash=hash_password(secrets.token_urlsafe(24)), joined_on=local_today())
    db.add(u)
    db.flush()
    save_pending_signups(db, pending | {u.id})
    db.commit()
    return None, "REQUESTED"


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = "",
             db: Session = Depends(get_db)):
    try:                                     # where to send the result: the app's address, kept in the signed state
        ret = app_return(jwt.decode(state, JWT_SECRET, algorithms=["HS256"], options={"verify_exp": False}).get("r", ""))
    except jwt.PyJWTError:
        ret = ""
    if error:
        msg = "Microsoft sign-in was cancelled." if error == "access_denied" else f"Microsoft sign-in failed: {error_description or error}"
        return _back(ret, ms_error=msg[:300])
    ms = ms_settings(db)
    if not ready(ms):
        return _back(ret, ms_error="Sign in with Microsoft is not set up.")
    try:
        st = jwt.decode(state, JWT_SECRET, algorithms=["HS256"])
        if st.get("p") != "ms":
            raise jwt.PyJWTError()
    except jwt.ExpiredSignatureError:
        return _back(ret, ms_error="The Microsoft sign-in took too long. Try again.")
    except jwt.PyJWTError:
        return _back(ret, ms_error="The Microsoft sign-in did not come from this portal. Try again.")
    try:
        r = httpx.post(f"{LOGIN}/{ms['tenant_id'].strip()}/oauth2/v2.0/token", timeout=30, data={
            "grant_type": "authorization_code", "client_id": ms["client_id"], "client_secret": ms["client_secret"], "code": code,
            "redirect_uri": redirect_uri(request), "scope": "openid profile email"})
        body = r.json() if r.content else {}
        if r.status_code != 200 or "id_token" not in body:
            raise MsError(f"Microsoft refused the sign-in: {str(body.get('error_description') or body.get('error') or r.status_code)[:220]}")
        claims = check_id_token(body["id_token"], ms, st["n"])
        user, msg = find_or_request(db, ms, claims)
    except MsError as e:
        return _back(ret, ms_error=str(e))
    except httpx.HTTPError as e:
        return _back(ret, ms_error=f"Could not reach Microsoft ({e}).")
    if msg == "REQUESTED":
        return _back(ret, ms_info="Registration sent. You can sign in with Microsoft once an administrator approves it.")
    if not user:
        return _back(ret, ms_error=msg)
    return _back(ret, ms_token=make_token(user))
