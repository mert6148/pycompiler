#!/usr/bin/env python3
"""
authserver_pro - sağlamlaştırılmış auth server (FastAPI + SQLite)

Özellikler
  * Argon2id şifre hash'i, şifre politikası, argon2 parametre yükseltme (rehash)
  * EdDSA (Ed25519) imzalı JWT + /.well-known/jwks.json (başka servisler public key ile doğrular)
  * Oturum (session) tabanlı refresh token: rotasyon + yeniden kullanım (reuse) tespiti
  * Access token bir oturuma bağlı -> logout / iptal ANINDA geçerli olur
  * Cihaz/oturum listesi, tek oturumu kapatma, tüm oturumları kapatma
  * Hesap kilidi (kademeli artan) + IP ve hesap bazlı rate limit
  * TOTP 2FA (secret DB'de şifreli, tekrar kullanım engelli) + kurtarma kodları
  * E-posta doğrulama, şifre sıfırlama, şifre değiştirme (diğer oturumlar kapanır)
  * Admin uçları (rol bazlı), denetim (audit) logu
  * Güvenlik header'ları, CORS allowlist, arka plan temizlik

Kurulum
  pip install fastapi uvicorn pyjwt cryptography argon2-cffi pyotp

Çalıştırma
  export AUTH_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")
  uvicorn authserver_pro:app --host 127.0.0.1 --port 8000

Ortam değişkenleri (hepsi opsiyonel, AUTH_SECRET hariç)
  AUTH_SECRET            zorunlu, >=32 karakter (token HMAC + TOTP şifreleme türetmesi)
  AUTH_DB                sqlite yolu (varsayılan auth.db)
  AUTH_KEY_PATH          Ed25519 private key PEM yolu (yoksa üretilir, 0600)
  AUTH_ISSUER / AUTH_AUDIENCE   JWT iss / aud (varsayılan authserver / api)
  AUTH_REQUIRE_VERIFIED  1 ise e-postası doğrulanmayan giriş yapamaz
  AUTH_TRUST_PROXY       1 ise client IP için X-Forwarded-For'un SON değeri kullanılır
  AUTH_CORS_ORIGINS      virgülle ayrılmış origin listesi
  AUTH_BOOTSTRAP_ADMIN   açılışta bu kullanıcı adını admin yapar (kullanıcı varsa)
  AUTH_DOCS              1 ise /docs açılır (production'da kapalı tut)
  AUTH_HTTPS             1 ise HSTS header'ı eklenir
  AUTH_SMTP_HOST/PORT/USER/PASS/FROM   mail ayarları (yoksa mail loga yazılır = sadece geliştirme)
"""
import base64
import hashlib
import hmac
import logging
import os
import secrets
import smtplib
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

log = logging.getLogger("authserver")

# --------------------------------------------------------------------------- config
SECRET = os.environ.get("AUTH_SECRET", "")
if len(SECRET) < 32:
    raise RuntimeError("AUTH_SECRET zorunlu ve en az 32 karakter olmalı")

AUTH_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("AUTH_DB", str(AUTH_DIR / "auth.db"))
KEY_PATH = os.environ.get("AUTH_KEY_PATH", str(AUTH_DIR / "auth_ed25519.pem"))
ISSUER = os.environ.get("AUTH_ISSUER", "authserver")
AUDIENCE = os.environ.get("AUTH_AUDIENCE", "api")
REQUIRE_VERIFIED = os.environ.get("AUTH_REQUIRE_VERIFIED") == "1"
TRUST_PROXY = os.environ.get("AUTH_TRUST_PROXY") == "1"
DOCS = os.environ.get("AUTH_DOCS") == "1"
HTTPS = os.environ.get("AUTH_HTTPS") == "1"

ACCESS_TTL = 10 * 60                 # 10 dk
REFRESH_TTL = 14 * 24 * 3600         # kayan pencere: 14 gün
ABS_TTL = 90 * 24 * 3600             # mutlak üst sınır: 90 gün
VERIFY_TTL = 24 * 3600
RESET_TTL = 30 * 60
LOCK_THRESHOLD = 5

ph = PasswordHasher()                # argon2id, güncel varsayılanlar
DUMMY_HASH = ph.hash("dummy-password-for-timing")
bearer = HTTPBearer(auto_error=False)


def _derive(label: bytes) -> bytes:
    return hmac.new(SECRET.encode(), label, hashlib.sha256).digest()


_TOKEN_KEY = _derive(b"token-hash")
_FERNET = Fernet(base64.urlsafe_b64encode(_derive(b"totp-encryption")))


def th(token: str) -> str:
    """Token'ı DB'de anahtarlı hash olarak sakla (DB sızsa bile token çıkmaz)."""
    return hmac.new(_TOKEN_KEY, token.encode(), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- signing key
def _load_or_create_key() -> Ed25519PrivateKey:
    if not os.path.exists(KEY_PATH):
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        try:
            fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(pem)
        except FileExistsError:
            pass  # başka worker yazdı
    with open(KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


_PRIV = _load_or_create_key()
PRIV_PEM = _PRIV.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
)
_PUB = _PRIV.public_key()
PUB_PEM = _PUB.public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)
_PUB_RAW = _PUB.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
KID = hashlib.sha256(_PUB_RAW).hexdigest()[:16]
JWKS = {
    "keys": [
        {
            "kty": "OKP",
            "crv": "Ed25519",
            "alg": "EdDSA",
            "use": "sig",
            "kid": KID,
            "x": base64.urlsafe_b64encode(_PUB_RAW).rstrip(b"=").decode(),
        }
    ]
}

# --------------------------------------------------------------------------- database
@contextmanager
def db(write: bool = False):
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def init_db() -> None:
    boot = sqlite3.connect(DB_PATH, timeout=15)
    boot.execute("PRAGMA journal_mode = WAL")
    boot.close()
    with db(True) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                pw_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                email_verified INTEGER NOT NULL DEFAULT 0,
                totp_secret TEXT,
                totp_enabled INTEGER NOT NULL DEFAULT 0,
                last_totp_step INTEGER NOT NULL DEFAULT 0,
                failed_logins INTEGER NOT NULL DEFAULT 0,
                locked_until INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                pw_changed_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                refresh_hash TEXT NOT NULL,
                prev_hash TEXT,
                created_at INTEGER NOT NULL,
                last_used INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                ip TEXT,
                ua TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS one_time_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                purpose TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS recovery_codes (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                code_hash TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, code_hash)
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                user_id INTEGER,
                event TEXT NOT NULL,
                ip TEXT,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit(user_id);
            """
        )


def audit(c, user_id: Optional[int], event: str, ip: str = "", detail: str = "") -> None:
    c.execute(
        "INSERT INTO audit (ts, user_id, event, ip, detail) VALUES (?, ?, ?, ?, ?)",
        (int(time.time()), user_id, event, ip, detail[:200]),
    )


# --------------------------------------------------------------------------- helpers
_hits: dict = defaultdict(deque)
_hits_lock = threading.Lock()


def limit(key: str, n: int, window: int) -> None:
    now = time.monotonic()
    with _hits_lock:
        q = _hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= n:
            retry = int(window - (now - q[0])) + 1
            raise HTTPException(429, "Çok fazla deneme, sonra tekrar dene",
                                headers={"Retry-After": str(retry)})
        q.append(now)


def client_ip(req: Request) -> str:
    if TRUST_PROXY:
        xff = req.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[-1].strip()[:64]
    return req.client.host if req.client else "unknown"


COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "1234567890", "123456789",
    "12345678910", "qwertyuiop", "qwerty12345", "iloveyou123", "letmein1234",
    "admin12345", "welcome123", "abc1234567", "11111111111", "passw0rd123",
}


def check_password(pw: str, username: str = "", email: str = "") -> None:
    low = pw.lower()
    problems = []
    if not 10 <= len(pw) <= 128:
        problems.append("şifre 10-128 karakter olmalı")
    if low in COMMON_PASSWORDS or len(set(pw)) < 5:
        problems.append("şifre çok tahmin edilebilir")
    if username and len(username) >= 3 and username.lower() in low:
        problems.append("şifre kullanıcı adını içeremez")
    if email and email.split("@")[0].lower() in low and len(email.split("@")[0]) >= 4:
        problems.append("şifre e-postanı içeremez")
    if problems:
        raise HTTPException(422, "; ".join(problems))


def send_email(to: str, subject: str, body: str) -> None:
    host = os.environ.get("AUTH_SMTP_HOST")
    if not host:
        log.warning("[DEV MAIL] to=%s subject=%s\n%s", to, subject, body)
        return
    try:
        msg = EmailMessage()
        msg["From"] = os.environ.get("AUTH_SMTP_FROM", "no-reply@localhost")
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.environ.get("AUTH_SMTP_PORT", "587")), timeout=10) as s:
            s.starttls()
            user = os.environ.get("AUTH_SMTP_USER")
            if user:
                s.login(user, os.environ.get("AUTH_SMTP_PASS", ""))
            s.send_message(msg)
    except Exception:
        log.exception("mail gönderilemedi")


def _token_response(uid: int, sid: str, refresh: str) -> dict:
    now = int(time.time())
    access = jwt.encode(
        {
            "iss": ISSUER, "aud": AUDIENCE, "sub": str(uid), "sid": sid,
            "iat": now, "nbf": now, "exp": now + ACCESS_TTL, "jti": secrets.token_hex(8),
        },
        PRIV_PEM,
        algorithm="EdDSA",
        headers={"kid": KID},
    )
    return {"access_token": access, "refresh_token": refresh,
            "token_type": "bearer", "expires_in": ACCESS_TTL}


def _new_session(c, uid: int, ip: str, ua: str) -> dict:
    now = int(time.time())
    sid = secrets.token_urlsafe(12)
    refresh = f"{sid}.{secrets.token_urlsafe(40)}"
    c.execute(
        "INSERT INTO sessions (id, user_id, refresh_hash, created_at, last_used, expires_at, ip, ua) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, uid, th(refresh), now, now, now + REFRESH_TTL, ip, (ua or "")[:200]),
    )
    return _token_response(uid, sid, refresh)


def _consume_token(c, token: str, purpose: str) -> Optional[int]:
    row = c.execute(
        "SELECT user_id, expires_at FROM one_time_tokens WHERE token_hash = ? AND purpose = ? AND used = 0",
        (th(token), purpose),
    ).fetchone()
    if row is None or row["expires_at"] < int(time.time()):
        return None
    cur = c.execute("UPDATE one_time_tokens SET used = 1 WHERE token_hash = ? AND used = 0", (th(token),))
    return row["user_id"] if cur.rowcount == 1 else None


def _issue_one_time(c, uid: int, purpose: str, ttl: int) -> str:
    c.execute("UPDATE one_time_tokens SET used = 1 WHERE user_id = ? AND purpose = ?", (uid, purpose))
    token = secrets.token_urlsafe(32)
    c.execute(
        "INSERT INTO one_time_tokens (token_hash, user_id, purpose, expires_at) VALUES (?, ?, ?, ?)",
        (th(token), uid, purpose, int(time.time()) + ttl),
    )
    return token


def _verify_pw(stored: str, pw: str) -> bool:
    try:
        return ph.verify(stored, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _check_totp(c, u, code: str) -> bool:
    if not u["totp_secret"]:
        return False
    try:
        secret = _FERNET.decrypt(u["totp_secret"].encode()).decode()
    except InvalidToken:
        return False
    totp = pyotp.TOTP(secret)
    base = int(time.time()) // 30
    for off in (0, -1, 1):
        step = base + off
        if hmac.compare_digest(totp.at(step * 30), code):
            cur = c.execute(
                "UPDATE users SET last_totp_step = ? WHERE id = ? AND last_totp_step < ?",
                (step, u["id"], step),
            )
            return cur.rowcount == 1   # aynı kod ikinci kez kullanılamaz
    return False


def _check_second_factor(c, u, code: str) -> bool:
    code = code.strip()
    if len(code) == 6 and code.isdigit():
        return _check_totp(c, u, code)
    cur = c.execute(
        "UPDATE recovery_codes SET used = 1 WHERE user_id = ? AND code_hash = ? AND used = 0",
        (u["id"], th(code.lower())),
    )
    return cur.rowcount == 1


def _register_failure(c, u, ip: str) -> None:
    n = u["failed_logins"] + 1
    locked_until = u["locked_until"]
    if n >= LOCK_THRESHOLD:
        locked_until = int(time.time()) + min(60 * 2 ** min(n - LOCK_THRESHOLD, 10), 86400)
    c.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
              (n, locked_until, u["id"]))
    audit(c, u["id"], "login_failed", ip, f"count={n}")


def _revoke_sessions(c, uid: int, except_sid: Optional[str] = None) -> None:
    if except_sid:
        c.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ? AND id != ?", (uid, except_sid))
    else:
        c.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (uid,))


# --------------------------------------------------------------------------- auth dependencies
def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    err = HTTPException(401, "Geçersiz veya süresi dolmuş token",
                        headers={"WWW-Authenticate": "Bearer"})
    if cred is None:
        raise err
    try:
        p = jwt.decode(
            cred.credentials, PUB_PEM, algorithms=["EdDSA"], audience=AUDIENCE, issuer=ISSUER,
            leeway=5, options={"require": ["exp", "iat", "sub", "sid", "iss", "aud"]},
        )
        uid = int(p["sub"])
    except (jwt.PyJWTError, ValueError):
        raise err
    with db() as c:
        row = c.execute(
            "SELECT u.id, u.username, u.email, u.role, u.is_active, u.email_verified, "
            "u.totp_enabled, s.id AS sid FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id = ? AND u.id = ? AND s.revoked = 0 AND s.expires_at > ?",
            (p["sid"], uid, int(time.time())),
        ).fetchone()
    if row is None or not row["is_active"]:
        raise err
    return dict(row)


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Yetkin yok")
    return user


# --------------------------------------------------------------------------- schemas
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(max_length=254, pattern=EMAIL_RE)
    password: str = Field(min_length=1, max_length=128)


class LoginBody(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    otp: Optional[str] = Field(default=None, max_length=32)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ForgotBody(BaseModel):
    email: str = Field(max_length=254, pattern=EMAIL_RE)


class ResetBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=1, max_length=128)


class ChangePwBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class CodeBody(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaDisableBody(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=32)


# --------------------------------------------------------------------------- app
def _janitor() -> None:
    while True:
        time.sleep(3600)
        try:
            now = int(time.time())
            with db(True) as c:
                c.execute("DELETE FROM sessions WHERE expires_at < ? OR (revoked = 1 AND last_used < ?)",
                          (now, now - 7 * 86400))
                c.execute("DELETE FROM one_time_tokens WHERE expires_at < ?", (now - 86400,))
                c.execute("DELETE FROM audit WHERE ts < ?", (now - 180 * 86400,))
            with _hits_lock:
                for k in [k for k, q in _hits.items() if not q]:
                    del _hits[k]
        except Exception:
            log.exception("janitor hatası")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    admin = os.environ.get("AUTH_BOOTSTRAP_ADMIN")
    if admin:
        with db(True) as c:
            c.execute("UPDATE users SET role = 'admin' WHERE username = ?", (admin.lower(),))
    threading.Thread(target=_janitor, daemon=True).start()
    yield


app = FastAPI(
    title="authserver_pro",
    lifespan=lifespan,
    docs_url="/docs" if DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS else None,
)

_origins = [o.strip() for o in os.environ.get("AUTH_CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    if not DOCS:
        resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if HTTPS:
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


# --------------------------------------------------------------------------- public endpoints
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/.well-known/jwks.json")
def jwks():
    return JWKS


@app.post("/auth/register", status_code=201)
def register(body: RegisterBody, req: Request, bg: BackgroundTasks):
    ip = client_ip(req)
    limit(f"reg:{ip}", 5, 3600)
    username, email = body.username.lower(), body.email.lower()
    check_password(body.password, username, email)
    pw_hash = ph.hash(body.password)
    now = int(time.time())
    try:
        with db(True) as c:
            uid = c.execute(
                "INSERT INTO users (username, email, pw_hash, created_at, pw_changed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, email, pw_hash, now, now),
            ).lastrowid
            token = _issue_one_time(c, uid, "verify", VERIFY_TTL)
            audit(c, uid, "register", ip)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Kullanıcı adı veya e-posta kullanımda")
    bg.add_task(send_email, email, "E-postanı doğrula", f"Doğrulama kodun:\n{token}")
    return {"username": username, "email": email, "verify_required": True}


@app.post("/auth/verify-email")
def verify_email(body: TokenBody, req: Request):
    limit(f"verify:{client_ip(req)}", 20, 600)
    with db(True) as c:
        uid = _consume_token(c, body.token, "verify")
        if uid is not None:
            c.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (uid,))
            audit(c, uid, "email_verified", client_ip(req))
    if uid is None:
        raise HTTPException(400, "Token geçersiz veya süresi dolmuş")
    return {"verified": True}


@app.post("/auth/login")
def login(body: LoginBody, req: Request):
    ip, ua = client_ip(req), req.headers.get("user-agent", "")
    ident = body.identifier.strip().lower()
    limit(f"login:ip:{ip}", 30, 60)
    limit(f"login:id:{ident}", 10, 300)

    with db() as c:
        u = c.execute("SELECT id, pw_hash FROM users WHERE username = ? OR email = ?",
                      (ident, ident)).fetchone()
    # kullanıcı olmasa da argon2 çalışır -> süre farkından kullanıcı tespit edilemez
    pw_ok = _verify_pw(u["pw_hash"] if u else DUMMY_HASH, body.password) and u is not None
    if u is None:
        raise HTTPException(401, "Kullanıcı adı veya şifre hatalı")

    status, tokens = "bad", None
    now = int(time.time())
    with db(True) as c:
        user = c.execute("SELECT * FROM users WHERE id = ?", (u["id"],)).fetchone()
        if user is not None:
            locked = user["locked_until"] > now
            if not pw_ok or locked:
                if not locked:
                    _register_failure(c, user, ip)
            elif not user["is_active"]:
                status = "disabled"
            elif REQUIRE_VERIFIED and not user["email_verified"]:
                status = "unverified"
            elif user["totp_enabled"] and not body.otp:
                status = "otp_required"
            elif user["totp_enabled"] and not _check_second_factor(c, user, body.otp):
                _register_failure(c, user, ip)
                status = "bad_otp"
            else:
                c.execute("UPDATE users SET failed_logins = 0, locked_until = 0 WHERE id = ?", (user["id"],))
                if ph.check_needs_rehash(user["pw_hash"]):
                    c.execute("UPDATE users SET pw_hash = ? WHERE id = ?",
                              (ph.hash(body.password), user["id"]))
                tokens = _new_session(c, user["id"], ip, ua)
                audit(c, user["id"], "login", ip)
                status = "ok"

    if status == "ok":
        return tokens
    messages = {
        "bad": (401, "Kullanıcı adı veya şifre hatalı"),
        "bad_otp": (401, "2FA kodu hatalı"),
        "otp_required": (401, "otp_required"),
        "disabled": (403, "Hesap devre dışı"),
        "unverified": (403, "E-posta doğrulanmamış"),
    }
    code, msg = messages[status]
    raise HTTPException(code, msg)


@app.post("/auth/refresh")
def refresh(body: RefreshBody, req: Request):
    ip = client_ip(req)
    limit(f"refresh:{ip}", 60, 60)
    sid, dot, _ = body.refresh_token.partition(".")
    if not dot:
        raise HTTPException(401, "Geçersiz refresh token")
    now, h, out = int(time.time()), th(body.refresh_token), None
    with db(True) as c:
        s = c.execute(
            "SELECT s.*, u.is_active FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
            (sid,),
        ).fetchone()
        if s is not None and not s["revoked"]:
            if hmac.compare_digest(h, s["refresh_hash"]):
                if s["expires_at"] < now or not s["is_active"]:
                    c.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (sid,))
                else:
                    new = f"{sid}.{secrets.token_urlsafe(40)}"
                    c.execute(
                        "UPDATE sessions SET refresh_hash = ?, prev_hash = ?, last_used = ?, "
                        "expires_at = ?, ip = ? WHERE id = ?",
                        (th(new), h, now, min(now + REFRESH_TTL, s["created_at"] + ABS_TTL), ip, sid),
                    )
                    out = _token_response(s["user_id"], sid, new)
            elif s["prev_hash"] and hmac.compare_digest(h, s["prev_hash"]):
                # eski token tekrar kullanıldı -> çalınmış olabilir, oturumu öldür
                c.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (sid,))
                audit(c, s["user_id"], "refresh_reuse_detected", ip, sid)
    if out is None:
        raise HTTPException(401, "Geçersiz refresh token")
    return out


@app.post("/auth/logout", status_code=204)
def logout(body: RefreshBody):
    sid, dot, _ = body.refresh_token.partition(".")
    if dot:
        h = th(body.refresh_token)
        with db(True) as c:
            c.execute("UPDATE sessions SET revoked = 1 WHERE id = ? AND (refresh_hash = ? OR prev_hash = ?)",
                      (sid, h, h))
    return Response(status_code=204)


@app.post("/auth/password/forgot", status_code=202)
def forgot(body: ForgotBody, req: Request, bg: BackgroundTasks):
    ip, email = client_ip(req), body.email.lower()
    limit(f"forgot:ip:{ip}", 5, 3600)
    limit(f"forgot:em:{email}", 3, 3600)
    with db(True) as c:
        u = c.execute("SELECT id FROM users WHERE email = ? AND is_active = 1", (email,)).fetchone()
        if u is not None:
            token = _issue_one_time(c, u["id"], "reset", RESET_TTL)
            audit(c, u["id"], "reset_requested", ip)
            bg.add_task(send_email, email, "Şifre sıfırlama", f"Sıfırlama kodun (30 dk geçerli):\n{token}")
    return {"detail": "Eğer bu e-posta kayıtlıysa sıfırlama kodu gönderildi"}


@app.post("/auth/password/reset")
def reset(body: ResetBody, req: Request):
    ip = client_ip(req)
    limit(f"reset:{ip}", 10, 600)
    check_password(body.new_password)
    new_hash = ph.hash(body.new_password)
    with db(True) as c:
        uid = _consume_token(c, body.token, "reset")
        if uid is not None:
            c.execute(
                "UPDATE users SET pw_hash = ?, pw_changed_at = ?, failed_logins = 0, locked_until = 0 WHERE id = ?",
                (new_hash, int(time.time()), uid),
            )
            _revoke_sessions(c, uid)
            audit(c, uid, "password_reset", ip)
    if uid is None:
        raise HTTPException(400, "Token geçersiz veya süresi dolmuş")
    return {"detail": "Şifre güncellendi, tüm oturumlar kapatıldı"}


# --------------------------------------------------------------------------- authenticated endpoints
@app.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return {k: user[k] for k in ("id", "username", "email", "role", "email_verified", "totp_enabled")}


@app.get("/auth/sessions")
def list_sessions(user: dict = Depends(current_user)):
    with db() as c:
        rows = c.execute(
            "SELECT id, created_at, last_used, expires_at, ip, ua FROM sessions "
            "WHERE user_id = ? AND revoked = 0 AND expires_at > ? ORDER BY last_used DESC",
            (user["id"], int(time.time())),
        ).fetchall()
    return [{**dict(r), "current": r["id"] == user["sid"]} for r in rows]


@app.delete("/auth/sessions/{sid}", status_code=204)
def delete_session(sid: str, user: dict = Depends(current_user)):
    with db(True) as c:
        cur = c.execute("UPDATE sessions SET revoked = 1 WHERE id = ? AND user_id = ?", (sid, user["id"]))
        n = cur.rowcount
    if n != 1:
        raise HTTPException(404, "Oturum bulunamadı")
    return Response(status_code=204)


@app.post("/auth/logout-all", status_code=204)
def logout_all(user: dict = Depends(current_user)):
    with db(True) as c:
        _revoke_sessions(c, user["id"])
        audit(c, user["id"], "logout_all")
    return Response(status_code=204)


@app.post("/auth/password/change")
def change_password(body: ChangePwBody, req: Request, user: dict = Depends(current_user)):
    ip = client_ip(req)
    limit(f"chpw:{user['id']}", 5, 300)
    check_password(body.new_password, user["username"], user["email"])
    with db() as c:
        row = c.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not _verify_pw(row["pw_hash"], body.current_password):
        raise HTTPException(401, "Mevcut şifre hatalı")
    new_hash = ph.hash(body.new_password)
    with db(True) as c:
        c.execute("UPDATE users SET pw_hash = ?, pw_changed_at = ? WHERE id = ?",
                  (new_hash, int(time.time()), user["id"]))
        _revoke_sessions(c, user["id"], except_sid=user["sid"])
        audit(c, user["id"], "password_changed", ip)
    return {"detail": "Şifre değişti, diğer oturumlar kapatıldı"}


# --------------------------------------------------------------------------- MFA
def _require_password(user: dict, password: str) -> None:
    limit(f"mfa:{user['id']}", 10, 300)
    with db() as c:
        row = c.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not _verify_pw(row["pw_hash"], password):
        raise HTTPException(401, "Şifre hatalı")


@app.post("/auth/mfa/setup")
def mfa_setup(body: PasswordBody, user: dict = Depends(current_user)):
    if user["totp_enabled"]:
        raise HTTPException(409, "2FA zaten açık")
    _require_password(user, body.password)
    secret = pyotp.random_base32()
    with db(True) as c:
        c.execute("UPDATE users SET totp_secret = ?, last_totp_step = 0 WHERE id = ?",
                  (_FERNET.encrypt(secret.encode()).decode(), user["id"]))
    uri = pyotp.TOTP(secret).provisioning_uri(name=user["email"], issuer_name=ISSUER)
    return {"secret": secret, "otpauth_uri": uri}


@app.post("/auth/mfa/enable")
def mfa_enable(body: CodeBody, req: Request, user: dict = Depends(current_user)):
    if user["totp_enabled"]:
        raise HTTPException(409, "2FA zaten açık")
    limit(f"mfa:{user['id']}", 10, 300)
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(10)]
    ok = False
    with db(True) as c:
        u = c.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if u["totp_secret"] and _check_totp(c, u, body.code.strip()):
            ok = True
            c.execute("UPDATE users SET totp_enabled = 1 WHERE id = ?", (user["id"],))
            c.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user["id"],))
            c.executemany("INSERT INTO recovery_codes (user_id, code_hash) VALUES (?, ?)",
                          [(user["id"], th(x)) for x in codes])
            audit(c, user["id"], "mfa_enabled", client_ip(req))
    if not ok:
        raise HTTPException(400, "Kod hatalı veya önce /auth/mfa/setup çağır")
    return {"enabled": True, "recovery_codes": codes,
            "note": "Kurtarma kodlarını şimdi kaydet, bir daha gösterilmez"}


@app.post("/auth/mfa/disable")
def mfa_disable(body: MfaDisableBody, req: Request, user: dict = Depends(current_user)):
    if not user["totp_enabled"]:
        raise HTTPException(409, "2FA zaten kapalı")
    _require_password(user, body.password)
    ok = False
    with db(True) as c:
        u = c.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if _check_second_factor(c, u, body.code):
            ok = True
            c.execute("UPDATE users SET totp_enabled = 0, totp_secret = NULL WHERE id = ?", (user["id"],))
            c.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user["id"],))
            audit(c, user["id"], "mfa_disabled", client_ip(req))
    if not ok:
        raise HTTPException(401, "Kod hatalı")
    return {"enabled": False}


# --------------------------------------------------------------------------- admin
@app.get("/admin/users")
def admin_users(limit_: int = 50, offset: int = 0, _: dict = Depends(require_admin)):
    limit_ = max(1, min(limit_, 200))
    with db() as c:
        rows = c.execute(
            "SELECT id, username, email, role, is_active, email_verified, totp_enabled, "
            "failed_logins, locked_until, created_at FROM users ORDER BY id LIMIT ? OFFSET ?",
            (limit_, max(0, offset)),
        ).fetchall()
    return [dict(r) for r in rows]


def _admin_set_active(uid: int, active: bool, admin: dict, req: Request) -> dict:
    if uid == admin["id"]:
        raise HTTPException(400, "Kendi hesabını değiştiremezsin")
    with db(True) as c:
        cur = c.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, uid))
        if cur.rowcount != 1:
            raise HTTPException(404, "Kullanıcı yok")
        if not active:
            _revoke_sessions(c, uid)
        audit(c, admin["id"], "admin_enable" if active else "admin_disable", client_ip(req), f"target={uid}")
    return {"id": uid, "is_active": active}


@app.post("/admin/users/{uid}/disable")
def admin_disable(uid: int, req: Request, admin: dict = Depends(require_admin)):
    return _admin_set_active(uid, False, admin, req)


@app.post("/admin/users/{uid}/enable")
def admin_enable(uid: int, req: Request, admin: dict = Depends(require_admin)):
    return _admin_set_active(uid, True, admin, req)


@app.post("/admin/users/{uid}/unlock")
def admin_unlock(uid: int, req: Request, admin: dict = Depends(require_admin)):
    with db(True) as c:
        cur = c.execute("UPDATE users SET failed_logins = 0, locked_until = 0 WHERE id = ?", (uid,))
        if cur.rowcount != 1:
            raise HTTPException(404, "Kullanıcı yok")
        audit(c, admin["id"], "admin_unlock", client_ip(req), f"target={uid}")
    return {"id": uid, "unlocked": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
