"""API: /api/v1/auth — логин + текущий пользователь + аудит."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.services import auth_service as auth

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest):
    res = auth.authenticate(req.username, req.password)
    if not res:
        auth.audit(req.username, "login_failed")
        raise HTTPException(status_code=401, detail="Неверные учётные данные")
    auth.audit(req.username, "login_success")
    return res


def _current(authorization):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(None, 1)[1]
    return auth.decode_jwt(token)


@router.get("/me")
def me(authorization: str | None = Header(default=None)):
    payload = _current(authorization)
    if not payload:
        raise HTTPException(status_code=401, detail="Не авторизован")
    return {
        "username": payload["sub"],
        "role": payload["role"],
        "display_name": payload.get("name"),
        "permissions": sorted(auth.ROLES.get(payload["role"], set())),
        "expires_at": payload["exp"],
    }


@router.get("/audit")
def audit_log(limit: int = 100, username: str | None = None,
              authorization: str | None = Header(default=None)):
    payload = _current(authorization)
    if not payload or not auth.has_permission(payload["role"], "dashboard"):
        raise HTTPException(status_code=403, detail="Требуется роль manager/admin")
    return {"entries": auth.get_audit_log(limit=limit, username=username)}


@router.get("/roles")
def roles():
    return {"roles": {role: sorted(perms) for role, perms in auth.ROLES.items()}}
