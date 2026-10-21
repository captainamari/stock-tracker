"""Single administrator, persistent opaque sessions and CSRF protection."""
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from lib import db
from lib.settings import settings

router = APIRouter(prefix='/api/auth')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()


def initialize_admin(password):
    if len(password) < 12:
        raise ValueError('Use at least 12 characters')
    encoded = password_hash(password)
    with db.get_db() as conn:
        conn.execute('INSERT INTO admin_account VALUES (1,?,?)', (encoded, secrets.token_hex(32)))


def session(request):
    with db.get_db() as conn:
        row = conn.execute('SELECT csrf,expires FROM admin_sessions WHERE token_hash=? AND expires>?',
                           (digest(request.cookies.get('session', '')), time.time())).fetchone()
    return dict(row) if row else None


def require_admin(request):
    value = session(request)
    if not value:
        raise HTTPException(401, 'Administrator login required')
    return value


def login_csrf():
    with db.get_db() as conn:
        row = conn.execute('SELECT csrf_secret FROM admin_account WHERE id=1').fetchone()
    if not row:
        return None
    nonce = secrets.token_hex(24)
    return nonce + '.' + hmac.new(row[0].encode(), nonce.encode(), hashlib.sha256).hexdigest()


def valid_login_csrf(token):
    with db.get_db() as conn:
        row = conn.execute('SELECT csrf_secret FROM admin_account WHERE id=1').fetchone()
    if not row or '.' not in token:
        return False
    nonce, mac = token.split('.', 1)
    return hmac.compare_digest(mac, hmac.new(row[0].encode(), nonce.encode(), hashlib.sha256).hexdigest())


async def guard(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.url.netloc:
            return JSONResponse({'detail': 'Cross-origin write refused'}, status_code=403)
        supplied = request.headers.get('x-csrf-token', '')
        if request.url.path == '/api/auth/login':
            expected = request.cookies.get('login_csrf', '')
            valid = supplied and hmac.compare_digest(supplied, expected) and valid_login_csrf(supplied)
        else:
            auth = session(request)
            if not auth:
                return JSONResponse({'detail': 'Administrator login required'}, status_code=401)
            valid = supplied and hmac.compare_digest(supplied, auth['csrf'])
        if not valid:
            return JSONResponse({'detail': 'Invalid CSRF token'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.get('/session')
def get_session(request: Request):
    auth = session(request)
    csrf = auth['csrf'] if auth else login_csrf()
    response = JSONResponse({'authenticated': bool(auth), 'csrf': csrf, 'initialized': csrf is not None})
    if not auth and csrf:
        response.set_cookie('login_csrf', csrf, httponly=True, secure=settings().secure_cookies, samesite='strict', max_age=1800)
    return response


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1, max_length=1024)


@router.post('/login')
def login(request: Request, payload: Login):
    now = time.time()
    ip = request.client.host if request.client else 'unknown'
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM login_attempts WHERE attempted<?', (now - 600,))
        count = conn.execute('SELECT COUNT(*) FROM login_attempts WHERE ip=?', (ip,)).fetchone()[0]
        total = conn.execute('SELECT COUNT(*) FROM login_attempts').fetchone()[0]
        if count >= 5 or total >= 100:
            raise HTTPException(429, 'Too many attempts; retry after ten minutes')
        conn.execute('INSERT INTO login_attempts VALUES (?,?)', (ip, now))
        admin = conn.execute('SELECT password_hash FROM admin_account WHERE id=1').fetchone()
    if not admin or not hmac.compare_digest(password_hash(payload.password, admin[0].split(':')[0]), admin[0]):
        raise HTTPException(401, 'Invalid credentials')
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with db.get_db() as conn:
        conn.execute('DELETE FROM admin_sessions WHERE expires<?', (now,))
        conn.execute('INSERT INTO admin_sessions VALUES (?,?,?)', (digest(token), csrf, now + 43200))
    response = JSONResponse({'authenticated': True, 'csrf': csrf})
    response.set_cookie('session', token, httponly=True, secure=settings().secure_cookies, samesite='strict', max_age=43200)
    response.delete_cookie('login_csrf')
    return response


@router.post('/logout')
def logout(request: Request):
    with db.get_db() as conn:
        conn.execute('DELETE FROM admin_sessions WHERE token_hash=?', (digest(request.cookies.get('session', '')),))
    response = JSONResponse({'authenticated': False})
    response.delete_cookie('session')
    return response
