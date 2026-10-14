"""FastAPI application: API under ``/api``, built React UI from ``ui/dist``."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.api import auth, profiles, projects
from app.config import ROOT_DIR, Settings, load_settings
from app.db import Database
from app.engine import Engine
from app.providers import ProviderClient
from app.repo import Repo
from app.security import SecretBox
from app.worker import Worker

log = logging.getLogger("sav")
UI_DIST = ROOT_DIR / "ui" / "dist"


@dataclass
class Services:
    settings: Settings
    db: Database
    repo: Repo
    box: SecretBox
    engine: Engine
    worker: Worker
    client_factory: object


def create_app(settings: Settings | None = None, *, client_factory=ProviderClient,
               start_worker: bool = True) -> FastAPI:
    settings = settings or load_settings()
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    repo = Repo(db)
    repo.ensure_admin(settings.admin_username, settings.admin_password)
    box = SecretBox(settings.secret_key)
    engine = Engine(settings, repo, box, client_factory=client_factory)
    worker = Worker(repo, engine)
    svc = Services(settings, db, repo, box, engine, worker, client_factory)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_worker:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="sandroid-ai-video", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.services = svc
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="sav_session",
                       max_age=14 * 24 * 3600, same_site="lax", https_only=settings.cookie_secure)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        first = (exc.errors() or [{}])[0]
        where = ".".join(str(p) for p in first.get("loc", ())[1:])
        return JSONResponse({"error": f"{where}: {first.get('msg', 'input tidak valid')}".strip(": ")},
                            status_code=422)

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse({"error": "kesalahan internal"}, status_code=500)

    for module in (auth, profiles, projects):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    if (UI_DIST / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                return JSONResponse({"error": "endpoint tidak ditemukan"}, status_code=404)
            candidate = (UI_DIST / path).resolve()
            if path and UI_DIST.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(UI_DIST / "index.html")

    return app


def run() -> None:  # pragma: no cover - entry point
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":  # pragma: no cover
    run()
