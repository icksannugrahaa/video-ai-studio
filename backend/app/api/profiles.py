"""Per-user provider profiles (endpoint + encrypted API key + model choices)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api.deps import current_user, services
from app.providers import ProviderError
from app.security import mask_secret

router = APIRouter()


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    base_url: str = Field(min_length=8, max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    chat_model: str = Field(default="", max_length=200)
    video_model: str = Field(default="", max_length=200)
    tts_model: str = Field(default="", max_length=200)
    tts_voice: str = Field(default="", max_length=120)
    clip_seconds: int = Field(default=5, ge=2, le=30)

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url harus diawali http:// atau https://")
        return value


class ProfilePatch(ProfileBody):
    name: str | None = Field(default=None, max_length=60)  # type: ignore[assignment]
    base_url: str | None = Field(default=None, max_length=300)  # type: ignore[assignment]
    clip_seconds: int | None = Field(default=None, ge=2, le=30)  # type: ignore[assignment]


def profile_out(row: dict, svc) -> dict:
    out = {k: v for k, v in row.items() if k != "api_key_enc"}
    try:
        out["api_key_masked"] = mask_secret(svc.box.decrypt(row["api_key_enc"]))
    except ValueError:
        out["api_key_masked"] = "(tidak bisa dibaca)"
    return out


def _owned(svc, user: dict, profile_id: int) -> dict:
    row = svc.repo.profile(user["id"], profile_id)
    if not row:
        raise HTTPException(404, "profil tidak ditemukan")
    return row


@router.get("/profiles")
def list_profiles(user: dict = Depends(current_user), svc=Depends(services)):
    return [profile_out(r, svc) for r in svc.repo.profiles(user["id"])]


@router.post("/profiles")
def create_profile(body: ProfileBody, user: dict = Depends(current_user), svc=Depends(services)):
    if not body.api_key:
        raise HTTPException(400, "api_key wajib diisi")
    profile_id = svc.repo.create_profile(user["id"], body.model_dump(), svc.box.encrypt(body.api_key.strip()))
    return profile_out(svc.repo.profile(user["id"], profile_id), svc)


@router.patch("/profiles/{profile_id}")
def update_profile(profile_id: int, body: ProfilePatch, user: dict = Depends(current_user), svc=Depends(services)):
    _owned(svc, user, profile_id)
    data = body.model_dump(exclude_unset=True)
    key = (data.pop("api_key", None) or "").strip()
    svc.repo.update_profile(user["id"], profile_id, data, svc.box.encrypt(key) if key else None)
    return profile_out(svc.repo.profile(user["id"], profile_id), svc)


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    if not svc.repo.delete_profile(user["id"], profile_id):
        raise HTTPException(404, "profil tidak ditemukan")
    return {"ok": True}


class ModelsProbeBody(BaseModel):
    base_url: str = Field(min_length=8, max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    profile_id: int | None = None  # reuse the stored key when editing without retyping it

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        return ProfileBody._http_url(value)


# Which model kinds each profile field accepts (router ``kind`` vocabulary).
FIELD_KINDS = {"chat": ("chat", "vision"), "video": ("video",), "tts": ("tts",)}
# Speech models that only work over realtime/WebSocket sessions or translate speech.
_NON_HTTP_TTS = ("realtime", "livetranslate", "-s2s", "omni")


def _models_payload(client) -> dict:
    try:
        models = client.list_models()
    except ProviderError as exc:
        raise HTTPException(502, exc.message) from exc
    grouped: dict[str, list[str]] = {}
    for model in models:
        grouped.setdefault(model["kind"], []).append(model["id"])
    by_field = {
        field: sorted({m["id"] for m in models if m["kind"] in kinds
                       and not (field == "tts" and any(x in m["id"].lower() for x in _NON_HTTP_TTS))},
                      key=str.lower)
        for field, kinds in FIELD_KINDS.items()
    }
    return {"models": models, "by_kind": grouped, "by_field": by_field}


@router.get("/profiles/{profile_id}/models")
def profile_models(profile_id: int, user: dict = Depends(current_user), svc=Depends(services)):
    row = _owned(svc, user, profile_id)
    return _models_payload(svc.client_factory(row["base_url"], svc.box.decrypt(row["api_key_enc"])))


@router.post("/profiles/models")
def probe_models(body: ModelsProbeBody, user: dict = Depends(current_user), svc=Depends(services)):
    """Model list for a profile being created/edited (endpoint + key not saved yet)."""
    key = (body.api_key or "").strip()
    if not key and body.profile_id:
        key = svc.box.decrypt(_owned(svc, user, body.profile_id)["api_key_enc"])
    if not key:
        raise HTTPException(400, "isi API key dulu")
    return _models_payload(svc.client_factory(body.base_url, key))
