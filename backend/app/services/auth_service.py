"""AuthService: JWT + 4 роли + аудит-лог в SQLite.

Роли:
  researcher — базовые запросы, чтение графа
  analyst    — + сравнение, экспорт, детекция противоречий
  manager    — + доступ к дашбордам и метрикам
  admin      — + загрузка корпуса, ручная корректировка графа
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# ---------- Роли и права ----------

ROLES = {
    "researcher": {"read_graph", "ask", "explorer", "gaps"},
    "analyst":    {"read_graph", "ask", "explorer", "gaps", "compare", "export"},
    "manager":    {"read_graph", "ask", "explorer", "gaps", "compare", "export", "metrics", "dashboard"},
    "admin":      {"read_graph", "ask", "explorer", "gaps", "compare", "export", "metrics", "dashboard",
                   "load_corpus", "edit_graph", "manage_users"},
}


def has_permission(role, permission):
    return permission in ROLES.get(role, set())


# ---------- Простой JWT (HMAC-SHA256, без внешних зависимостей) ----------

SECRET = os.environ.get("JWT_SECRET", "scientific-tangle-dev-secret-CHANGE-ME")
TOKEN_TTL_S = 24 * 3600


def _b64url_encode(data):
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s):
    import base64
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode_jwt(payload):
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url_encode(sig)}"


def decode_jwt(token):
    try:
        h, p, s = token.split(".")
        sig = hmac.new(SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
        if _b64url_encode(sig) != s:
            return None
        payload = json.loads(_b64url_decode(p))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception as e:
        logger.warning(f"JWT decode failed: {e}")
        return None


# ---------- Пароли: PBKDF2 ----------

def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password, stored):
    try:
        _, salt_hex, hash_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ---------- SQLite users + audit_log ----------

DB_PATH = os.environ.get("AUTH_DB_PATH", "/data/auth.db")


def _init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('researcher','analyst','manager','admin')),
            display_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            action TEXT NOT NULL,
            resource TEXT,
            meta JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(created_at DESC)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(username)")

    # Seed 4 демо-юзера с одинаковым паролем "demo123"
    demo = [
        ("researcher", "researcher", "Иванов И. (исследователь)"),
        ("analyst", "analyst", "Петров П. (аналитик)"),
        ("manager", "manager", "Сидорова С. (руководитель)"),
        ("admin", "admin", "Администратор"),
    ]
    for username, role, dname in demo:
        con.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role, display_name) "
            "VALUES (?, ?, ?, ?)",
            (username, hash_password("demo123"), role, dname),
        )
    con.commit()
    con.close()


def get_user(username):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT username, password_hash, role, display_name FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    con.close()
    return dict(row) if row else None


def authenticate(username, password):
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    payload = {
        "sub": username, "role": user["role"], "name": user.get("display_name"),
        "exp": int(time.time() + TOKEN_TTL_S),
    }
    return {"token": encode_jwt(payload), "user": {
        "username": username, "role": user["role"],
        "display_name": user.get("display_name"),
        "permissions": sorted(ROLES.get(user["role"], set())),
    }}


def audit(username, action, resource=None, meta=None):
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT INTO audit_log (username, action, resource, meta) VALUES (?, ?, ?, ?)",
            (username, action, resource, json.dumps(meta or {}, ensure_ascii=False)),
        )
        con.commit()
        con.close()
    except Exception as e:
        logger.warning(f"audit failed: {e}")


def get_audit_log(limit=100, username=None):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    if username:
        rows = con.execute(
            "SELECT username, action, resource, meta, created_at FROM audit_log "
            "WHERE username = ? ORDER BY id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT username, action, resource, meta, created_at FROM audit_log "
            "ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


_initialized = False


def init_auth():
    global _initialized
    if _initialized:
        return
    _init_db()
    _initialized = True
    logger.info(f"Auth DB ready: {DB_PATH}")
