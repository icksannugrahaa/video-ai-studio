"""Login/logout/register, current user, API tokens, and admin user management."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import admin_user, current_user, public_user, services
from app.security import verify_password

router = APIRouter()
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    username: str
    password: str


class TokenBody(BaseModel):
    name: str = Field(default="api", max_length=60)


class NewUserBody(Credentials):
    role: str = Field(default="user", pattern="^(admin|user)$")


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class SettingsBody(BaseModel):
    registration_open: bool


def _check_username(name: str) -> str:
    if not _USERNAME_RE.match(name):
        raise HTTPException(400, "username 3–32 karakter: huruf, angka, _ . -")
    return name


@router.post("/auth/login")
def login(body: LoginBody, request: Request, svc=Depends(services)):
    user = svc.repo.user_by_name(body.username)
    if not user or not user["active"] or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "username atau password salah")
    request.session.clear()
    request.session["uid"] = user["id"]
    return public_user(user)


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(current_user), svc=Depends(services)):
    return {**public_user(user), "registration_open": svc.db.get_setting("registration_open", "0") == "1"}


@router.get("/auth/config")
def auth_config(svc=Depends(services)):
    return {"registration_open": svc.db.get_setting("registration_open", "0") == "1"}


@router.post("/auth/register")
def register(body: Credentials, request: Request, svc=Depends(services)):
    if svc.db.get_setting("registration_open", "0") != "1":
        raise HTTPException(403, "registrasi ditutup — minta admin membuatkan akun")
    if svc.repo.user_by_name(_check_username(body.username)):
        raise HTTPException(409, "username sudah dipakai")
    user_id = svc.repo.create_user(body.username, body.password)
    request.session.clear()
    request.session["uid"] = user_id
    return public_user(svc.repo.user(user_id))


@router.get("/auth/tokens")
def list_tokens(user: dict = Depends(current_user), svc=Depends(services)):
    return svc.repo.tokens(user["id"])


@router.post("/auth/tokens")
def create_token(body: TokenBody, user: dict = Depends(current_user), svc=Depends(services)):
    token, row = svc.repo.create_token(user["id"], body.name)
    return {**row, "token": token}  # the plaintext token is shown exactly once


@router.delete("/auth/tokens/{token_id}")
def delete_token(token_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    if not svc.repo.delete_token(user["id"], token_id):
        raise HTTPException(404, "token tidak ditemukan")
    return {"ok": True}


# ── admin ──────────────────────────────────────────────────────────────
@router.get("/users")
def list_users(_admin: dict = Depends(admin_user), svc=Depends(services)):
    return svc.repo.users()


@router.post("/users")
def create_user(body: NewUserBody, _admin: dict = Depends(admin_user), svc=Depends(services)):
    if svc.repo.user_by_name(_check_username(body.username)):
        raise HTTPException(409, "username sudah dipakai")
    user_id = svc.repo.create_user(body.username, body.password, role=body.role)
    return public_user(svc.repo.user(user_id))


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, admin: dict = Depends(admin_user), svc=Depends(services)):
    if not svc.repo.user(user_id):
        raise HTTPException(404, "user tidak ditemukan")
    if user_id == admin["id"] and (body.active is False or body.role == "user"):
        raise HTTPException(400, "tidak bisa menonaktifkan / menurunkan akun sendiri")
    svc.repo.update_user(user_id, role=body.role, active=body.active, password=body.password)
    return public_user(svc.repo.user(user_id))


@router.get("/settings")
def get_settings(_admin: dict = Depends(admin_user), svc=Depends(services)):
    return {"registration_open": svc.db.get_setting("registration_open", "0") == "1"}


@router.put("/settings")
def put_settings(body: SettingsBody, _admin: dict = Depends(admin_user), svc=Depends(services)):
    svc.db.set_setting("registration_open", "1" if body.registration_open else "0")
    return {"registration_open": body.registration_open}
