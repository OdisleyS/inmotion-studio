import os
from pathlib import Path
import tempfile
import time
import unittest
import json
from unittest.mock import patch

os.environ.setdefault("ENABLE_REAL_MEDIA", "0")
os.environ.setdefault("ENABLE_AGY_BRIDGE", "0")

from backend.app.jobs import Job, JobManager
from backend.app.models import GenerateRequest


class JobManagerTests(unittest.TestCase):
    def test_intermediate_artifacts_emit_live_progress_events(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = JobManager(max_workers=1, state_path=Path(folder) / "jobs.json")
            job = Job(id="live-events", request=GenerateRequest(topic="Eventos ao vivo"))
            manager._update_artifact(job, "images", {"completed": 2, "total": 3, "provider": "local-sd-turbo"})
            manager._update_artifact(job, "audio", {"voice": "piper-pt_BR", "provider": "piper-local"})
            self.assertEqual(job.artifacts["images"]["completed"], 2)
            self.assertIn("Frame 2/3 pronto", job.events[0]["message"])
            self.assertIn("Narração pronta", job.events[1]["message"])

    def test_job_moves_from_queue_to_completed(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = JobManager(max_workers=1, state_path=Path(folder) / "jobs.json")
            job = manager.submit(GenerateRequest(topic="Fila de produção", provider_selection={"script": "local-template-text"}))
            deadline = time.time() + 5
            while time.time() < deadline:
                current = manager.get(job.id)
                if current and current.status in {"completed", "failed", "blocked"}:
                    break
                time.sleep(0.05)
            current = manager.get(job.id)
            self.assertIsNotNone(current)
            self.assertEqual(current.status, "completed")
            self.assertEqual(current.progress, 100)
            snapshot = manager.list()
            self.assertEqual(len(snapshot), 1)
            self.assertEqual(snapshot[0].id, job.id)

    def test_completed_job_survives_manager_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "jobs.json"
            manager = JobManager(max_workers=1, state_path=state_path)
            job = manager.submit(GenerateRequest(topic="Persistência de produção", provider_selection={"script": "local-template-text"}))
            deadline = time.time() + 5
            while time.time() < deadline and manager.get(job.id).status not in {"completed", "failed", "blocked"}:
                time.sleep(0.05)
            self.assertEqual(manager.get(job.id).status, "completed")
            restored = JobManager(max_workers=1, state_path=state_path)
            self.assertEqual(restored.get(job.id).status, "completed")
            self.assertEqual(restored.get(job.id).result.project_id, manager.get(job.id).result.project_id)

    def test_unfinished_job_is_requeued_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "jobs.json"
            state_path.write_text(json.dumps([{"id": "recover-me", "request": {"topic": "Job recuperável"}, "status": "running", "phase": "image", "progress": 48, "events": [], "artifacts": {}}]), encoding="utf-8")
            with patch.object(JobManager, "_run", autospec=True) as runner:
                manager = JobManager(max_workers=1, state_path=state_path)
                recovered = manager.get("recover-me")
                self.assertIsNotNone(recovered)
                self.assertEqual(recovered.status, "queued")
                self.assertEqual(recovered.phase, "queued")
                runner.assert_called_once()

    def test_failed_job_can_be_retried_as_a_fresh_queue_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "jobs.json"
            manager = JobManager(max_workers=1, state_path=state_path)
            original = Job(
                id="failed-job",
                request=GenerateRequest(topic="Retry de produção"),
                status="failed",
                phase="failed",
                error="provider indisponível",
            )
            with manager.lock:
                manager.jobs[original.id] = original
                manager._persist_locked()
            with patch.object(manager, "_run") as runner:
                retried = manager.retry(original.id)
            self.assertIsNotNone(retried)
            self.assertNotEqual(retried.id, original.id)
            self.assertEqual(retried.status, "queued")
            self.assertEqual(retried.request.topic, original.request.topic)
            self.assertIn("Nova tentativa criada", retried.events[0]["message"])
            runner.assert_called_once_with(retried)
