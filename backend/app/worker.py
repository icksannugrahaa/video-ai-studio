"""Background worker: runs queued jobs one at a time (phone CPU budget).

Preview jobs ("render sementara": compose the clips that are ready so far)
have their own lane so they never wait behind a long render.

On start, jobs left ``running`` by a previous process are queued again; the
engine skips finished scenes, so they resume instead of starting over.
"""

from __future__ import annotations

import logging
import threading

from app.engine import Engine, JobCanceled, JobFailed
from app.pipeline.media import MediaError
from app.pipeline.planner import PlanError
from app.providers import ProviderError
from app.repo import Repo

log = logging.getLogger("sav.worker")
IDLE_SECONDS = 2.0


class Worker:
    def __init__(self, repo: Repo, engine: Engine):
        self.repo = repo
        self.engine = engine
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._preview_thread: threading.Thread | None = None

    def start(self) -> None:
        resumed = self.repo.requeue_interrupted()
        if resumed:
            log.info("resuming %s interrupted job(s)", resumed)
        self._thread = threading.Thread(target=self._loop, name="sav-worker", daemon=True)
        self._thread.start()
        self._preview_thread = threading.Thread(target=self._loop, kwargs={"preview": True},
                                                name="sav-worker-preview", daemon=True)
        self._preview_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def notify(self) -> None:
        self._wake.set()

    def _loop(self, preview: bool = False) -> None:
        while not self._stop.is_set():
            job = self.repo.next_queued_job(preview=preview)
            if job is None:
                # Both lanes share one wake event; the timeout keeps the other lane responsive.
                self._wake.wait(1.0 if preview else IDLE_SECONDS)
                if not preview:
                    self._wake.clear()
                continue
            self.run_one(job)

    def run_one(self, job: dict) -> None:
        self.repo.update_job(job["id"], status="running", message="Mulai…")
        try:
            result = self.engine.run(job)
        except JobCanceled:
            self.repo.update_job(job["id"], status="canceled", message="Dibatalkan")
            return
        except (JobFailed, PlanError, ProviderError, MediaError, ValueError) as exc:
            message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
            self.repo.update_job(job["id"], status="failed", message=message[:500])
            return
        except Exception:  # noqa: BLE001 — never let one job kill the worker
            log.exception("job %s crashed", job["id"])
            self.repo.update_job(job["id"], status="failed", message="Kesalahan internal (lihat log server)")
            return
        current = self.repo.job(job["id"]) or {}
        merged = {**(current.get("result") or {}), **(result or {})}
        self.repo.update_job(job["id"], status="succeeded", progress=1.0, message="Selesai", result=merged)
