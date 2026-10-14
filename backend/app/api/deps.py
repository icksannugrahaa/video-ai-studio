"""Shared FastAPI dependencies: app services and the authenticated user.

Auth sources: ``Authorization: Bearer sav_…`` (API clients) or the signed
session cookie (web UI). Cookie-authenticated writes must carry the custom
header ``X-Requested-With: sav`` — browsers cannot add it cross-site, which
blocks CSRF without token plumbing.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.security import TOKEN_PREFIX

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def services(request: Request):
    return request.app.state.services


def current_user(request: Request, svc=Depends(services)) -> dict:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        user = svc.repo.user_by_token(token) if token.startswith(TOKEN_PREFIX) else None
        if not user or not user["active"]:
            raise HTTPException(401, "token tidak valid")
        return user
    user_id = request.session.get("uid")
    user = svc.repo.user(user_id) if user_id else None
    if not user or not user["active"]:
        raise HTTPException(401, "belum login")
    if request.method not in SAFE_METHODS and request.headers.get("X-Requested-With") != "sav":
        raise HTTPException(403, "header X-Requested-With wajib untuk request dari browser")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "khusus admin")
    return user


def public_user(user: dict) -> dict:
    return {"id": user["id"], "username": user["username"], "role": user["role"],
            "active": bool(user["active"]), "created_at": user["created_at"]}
