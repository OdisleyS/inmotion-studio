from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid
from typing import Any

from .models import GenerateRequest
from .pipeline import PipelineCancelled, PipelineOutput, ProductionPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JOB_STATE_PATH = PROJECT_ROOT / "assets" / "jobs-state.json"
TERMINAL_STATES = {"completed", "awaiting_approval", "blocked", "failed", "cancelled"}


@dataclass
class Job:
    id: str
    request: GenerateRequest
    status: str = "queued"
    phase: str = "queued"
    progress: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    events: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    result: PipelineOutput | None = None
    error: str | None = None
    cancel_requested: bool = False


class JobManager:
    def __init__(self, max_workers: int = 2, state_path: Path | None = None) -> None:
        self.pipeline = ProductionPipeline()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="studio-job")
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.state_path = state_path or JOB_STATE_PATH
        self._load_state()

    def _request_data(self, request: GenerateRequest) -> dict[str, Any]:
        return request.model_dump() if hasattr(request, "model_dump") else request.dict()

    def _record(self, job: Job) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": job.id,
            "request": self._request_data(job.request),
            "status": job.status,
            "phase": job.phase,
            "progress": job.progress,
            "created_at": job.created_at,
            "events": job.events[-120:],
            "artifacts": job.artifacts,
            "error": job.error,
            "cancel_requested": job.cancel_requested,
        }
        if job.result:
            record["result"] = asdict(job.result)
        return record

    def _persist_locked(self) -> None:
        """Atomically persist queue state so a restart can recover unfinished work."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_name(f"{self.state_path.name}.tmp")
            temporary.write_text(json.dumps([self._record(job) for job in self.jobs.values()], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            # A read-only workspace must not make a media job fail.
            return

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            records = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(records, list):
            return
        recover: list[Job] = []
        for record in records[-50:]:
            if not isinstance(record, dict) or not isinstance(record.get("request"), dict):
                continue
            try:
                request = GenerateRequest(**record["request"])
                result_data = record.get("result")
                result = PipelineOutput(**result_data) if isinstance(result_data, dict) else None
                job = Job(
                    id=str(record.get("id") or uuid.uuid4()),
                    request=request,
                    status=str(record.get("status") or "queued"),
                    phase=str(record.get("phase") or "queued"),
                    progress=int(record.get("progress") or 0),
                    created_at=str(record.get("created_at") or datetime.now(timezone.utc).isoformat()),
                    events=list(record.get("events") or []),
                    artifacts=dict(record.get("artifacts") or {}),
                    result=result,
                    error=str(record["error"]) if record.get("error") else None,
                    cancel_requested=bool(record.get("cancel_requested", False)),
                )
            except (TypeError, ValueError, KeyError):
                continue
            if job.status not in TERMINAL_STATES:
                job.status = "queued"
                job.phase = "queued"
                job.progress = min(job.progress, 5)
                job.cancel_requested = False
                job.events.append({"phase": "recovered", "message": "Job recuperado após reinício do backend", "progress": job.progress})
                recover.append(job)
            self.jobs[job.id] = job
        for job in recover:
            self.executor.submit(self._run, job)

    def submit(self, request: GenerateRequest) -> Job:
        job = Job(id=str(uuid.uuid4()), request=request)
        with self.lock:
            self.jobs[job.id] = job
            self._persist_locked()
        self.executor.submit(self._run, job)
        return job

    def _update(self, job: Job, phase: str, progress: int, message: str) -> None:
        with self.lock:
            job.status = "running"
            job.phase = phase
            job.progress = progress
            job.events.append({"phase": phase, "message": message, "progress": progress})
            self._persist_locked()

    def _update_artifact(self, job: Job, kind: str, value: dict[str, Any]) -> None:
        with self.lock:
            job.artifacts[kind] = value
            event: dict[str, Any] | None = None
            if kind == "research":
                event = {"phase": "research", "status": "success", "message": f"Pesquisa pronta · {len(value.get('sources', []) or [])} fonte(s)", "progress": 12}
            elif kind == "script":
                event = {"phase": "script", "status": "success", "message": f"Roteiro pronto · {value.get('provider', 'fallback local')}", "progress": 24}
            elif kind == "images":
                completed = int(value.get("completed") or len(value.get("frames", []) or []))
                total = int(value.get("total") or max(completed, 1))
                event = {"phase": "image", "status": "success", "message": f"Frame {completed}/{total} pronto · {value.get('provider', 'provider')}", "progress": min(60, 28 + round(32 * completed / max(total, 1)))}
            elif kind == "audio":
                voice = value.get("voice") or value.get("provider", "provider")
                event = {"phase": "audio", "status": "success", "message": f"Narração pronta · {voice}", "progress": 72}
            if event:
                job.events.append(event)
            self._persist_locked()

    def _run(self, job: Job) -> None:
        try:
            result = self.pipeline.generate(
                job.request,
                progress_callback=lambda phase, message: self._update(job, phase, {"research": 12, "script": 24, "image": 48, "audio": 72, "bgm": 78, "sfx": 84, "video": 92}.get(phase, 8), message),
                artifact_callback=lambda kind, value: self._update_artifact(job, kind, value),
                cancel_callback=lambda: job.cancel_requested,
            )
            with self.lock:
                job.result = result
                job.status = result.status
                if result.status == "completed":
                    job.phase = "completed"
                    job.progress = 100
                elif result.status == "awaiting_approval":
                    job.phase = "director_review"
                    job.progress = max(job.progress, 55)
                else:
                    job.phase = "blocked"
                self._persist_locked()
        except PipelineCancelled:
            with self.lock:
                job.status = "cancelled"
                job.phase = "cancelled"
                job.events.append({"phase": "cancelled", "message": "Produção cancelada pelo usuário", "progress": job.progress})
                self._persist_locked()
        except Exception as exc:
            with self.lock:
                job.status = "failed"
                job.phase = "failed"
                job.error = str(exc)
                self._persist_locked()

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        """Return a stable newest-first snapshot for the studio queue panel."""
        with self.lock:
            return sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)

    def cancel(self, job_id: str) -> Job | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status in {"completed", "blocked", "failed", "cancelled"}:
                return job
            if job.status == "awaiting_approval":
                job.cancel_requested = True
                job.status = "cancelled"
                job.phase = "cancelled"
                job.events.append({"phase": "cancelled", "message": "Revisão do diretor cancelada pelo usuário", "progress": job.progress})
                self._persist_locked()
                return job
            job.cancel_requested = True
            job.events.append({"phase": "cancelling", "message": "Cancelamento solicitado; concluindo a operação atual", "progress": job.progress})
            if job.status == "queued":
                job.status = "cancelling"
                job.phase = "cancelling"
            self._persist_locked()
            return job

    def approve(self, job_id: str, scene_prompts: list[str], scene_captions: list[str], script: str | None = None) -> Job | None:
        """Resume a Director job with the reviewed visual plan."""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status != "awaiting_approval" or not job.result:
                return job
            values = job.request.model_dump() if hasattr(job.request, "model_dump") else job.request.dict()
            values["script"] = (script or job.result.script).strip()
            values["scene_prompts"] = scene_prompts[:90]
            values["scene_captions"] = scene_captions[:90]
            values["director_approved"] = True
            autonomy = dict(values.get("stage_autonomy") or {})
            autonomy["script"] = "manual"
            values["stage_autonomy"] = autonomy
            job.request = GenerateRequest(**values)
            job.result = None
            job.error = None
            job.artifacts = {}
            job.status = "queued"
            job.phase = "queued"
            job.progress = 3
            job.cancel_requested = False
            job.events.append({"phase": "queued", "message": "Plano aprovado; render final enfileirado", "progress": 3})
            self._persist_locked()
            self.executor.submit(self._run, job)
            return job

    def retry(self, job_id: str) -> Job | None:
        """Create a fresh queue entry from a failed/blocked/cancelled request."""
        with self.lock:
            original = self.jobs.get(job_id)
            if not original or original.status not in {"failed", "blocked", "cancelled"}:
                return None
            retry_job = Job(id=str(uuid.uuid4()), request=original.request)
            retry_job.events.append({"phase": "queued", "message": f"Nova tentativa criada a partir de {original.id[:8]}", "progress": 3})
            self.jobs[retry_job.id] = retry_job
            self._persist_locked()
        self.executor.submit(self._run, retry_job)
        return retry_job
