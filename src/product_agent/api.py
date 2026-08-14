"""Product Agent HTTP service — mirrors the Analyst/Architect/Builder job pattern.

  POST /projects/{pid}/product:run  -> design the product from requirements, publish product_spec.json
  GET  /jobs/{job_id}               -> status snapshot (status, stage, result{personas,surfaces,screens})
  GET  /health

A run executes in a worker thread; the JobManager keeps a snapshot the FACTORY Overview polls, and
best-effort socket.io events (lane="product") update the Product lane live — like its siblings.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from fastapi import FastAPI

from . import __version__
from . import product as product_mod


@dataclass
class Job:
    job_id: str
    project_id: str
    status: str = "queued"
    stage: str | None = None
    progress: dict = field(default_factory=dict)
    error: str | None = None
    result: dict | None = None
    started_at: float | None = None

    def snapshot(self) -> dict:
        return {"job_id": self.job_id, "project_id": self.project_id, "kind": "product",
                "status": self.status, "stage": self.stage, "progress": self.progress,
                "error": self.error, "result": self.result,
                "elapsed_s": round(time.time() - self.started_at) if self.started_at else None}


def _factory_emit(pid, stage, status="progress", message=None, progress=None):
    """Best-effort: push a stage event to the FACTORY socket.io hub (the Analyst relay) so the pipeline
    Overview's PRODUCT lane updates LIVE instead of by polling. Never breaks a run on telemetry."""
    import json as _j, os as _o, urllib.request as _u
    try:
        url = _o.environ.get("FACTORY_RELAY_URL", "http://localhost:7803").rstrip("/")
        data = _j.dumps({"lane": "product", "stage": stage, "status": status,
                         "message": message, "progress": progress}).encode()
        _u.urlopen(_u.Request(f"{url}/relay/{pid}", data=data,
                   headers={"Content-Type": "application/json"}, method="POST"), timeout=2)
    except Exception:
        pass


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def _run(self, job: Job) -> None:
        job.status = "running"
        job.started_at = time.time()
        _factory_emit(job.project_id, "product", "running", "Product design started")

        def _log(msg: str = "") -> None:
            job.stage = "product"
            job.progress = {"stage": "product", "status": "progress", "last": str(msg)[:160]}
            _factory_emit(job.project_id, "product", "progress", str(msg)[:120], job.progress)

        try:
            job.result = product_mod.design(job.project_id, log=_log)
            job.status = "done"
            job.stage = "done"
            job.progress = {"stage": "done", "status": "done", **(job.result or {})}
            r = job.result or {}
            _factory_emit(job.project_id, "done", "done",
                          f"{r.get('personas')} personas · {r.get('screens')} screens", job.progress)
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            _factory_emit(job.project_id, "error", "error", job.error)

    def create(self, pid: str) -> Job:
        job = Job(job_id=uuid.uuid4().hex, project_id=pid)
        self.jobs[job.job_id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job


api = FastAPI(title="product-agent", version=__version__)
jm = JobManager()


@api.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "product-agent", "version": __version__, "jobs": len(jm.jobs)}


@api.post("/projects/{pid}/product:run")
def product_run(pid: str) -> dict:
    job = jm.create(pid)
    return {"job_id": job.job_id, "project_id": pid, "status": job.status}


@api.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jm.jobs.get(job_id)
    return job.snapshot() if job else {"error": "unknown job_id"}
