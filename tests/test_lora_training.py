from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.app.lora_training import lora_dataset_status, prepare_lora_dataset, start_lora_training
from backend.app.diffusion import lora_adapter_path, lora_adapter_status


class LoraTrainingTests(unittest.TestCase):
    def test_dataset_preparation_requires_three_references(self):
        with self.assertRaises(ValueError):
            prepare_lora_dataset(str(uuid.uuid4()), ["one.png", "two.png"])

    def test_dataset_preparation_writes_images_captions_and_manifest(self):
        profile_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            uploads = root / "uploads"
            training = root / "training"
            uploads.mkdir()
            for index, name in enumerate(("one.png", "two.png", "three.png"), start=1):
                Image.new("RGB", (640 + index, 420), (240, 240, 240)).save(uploads / name)
            quality = [{"filename": name, "usable": True, "width": 640, "height": 420} for name in ("one.png", "two.png", "three.png")]
            with patch("backend.app.lora_training.UPLOADS_ROOT", uploads), patch("backend.app.lora_training.LORA_TRAINING_ROOT", training), patch("backend.app.lora_training.inspect_reference_quality", side_effect=quality):
                result = prepare_lora_dataset(profile_id, ["one.png", "two.png", "three.png"], trigger_word="meu_traco")
                status = lora_dataset_status(profile_id)
            self.assertEqual(result["status"], "dataset_ready")
            self.assertEqual(result["training_status"], "not_started")
            self.assertEqual(result["reference_count"], 3)
            self.assertEqual(status["trigger_word"], "meu_traco")
            manifest = Path(result["manifest"])
            self.assertTrue(manifest.exists())
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["status"], "dataset_ready")
            image_files = list((training / profile_id / "images").glob("*.png"))
            caption_files = list((training / profile_id / "images").glob("*.txt"))
            self.assertEqual(len(image_files), 3)
            self.assertEqual(len(caption_files), 3)
            self.assertIn("meu_traco", caption_files[0].read_text(encoding="utf-8"))

    def test_start_training_persists_running_state_without_launching_real_process(self):
        profile_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            training = root / "training"
            workspace = training / profile_id
            workspace.mkdir(parents=True)
            manifest_path = workspace / "manifest.json"
            manifest_path.write_text(
                json.dumps({
                    "profile_id": profile_id,
                    "status": "dataset_ready",
                    "training_status": "not_started",
                    "resolution": 512,
                }),
                encoding="utf-8",
            )
            # Load the image-training dependency before mocking Popen: Torch's
            # import path uses subprocess internally on Windows.
            import peft  # noqa: F401

            class FakeProcess:
                pid = 9876

            with (
                patch("backend.app.lora_training.LORA_TRAINING_ROOT", training),
                patch("backend.app.lora_training.subprocess.Popen", return_value=FakeProcess()) as popen,
                patch("backend.app.diffusion.diffusion_model_root", return_value=root / "sd15-base"),
            ):
                result = start_lora_training(profile_id, steps=12)

            self.assertEqual(result["training_status"], "running")
            self.assertEqual(result["process_id"], 9876)
            self.assertEqual(result["steps"], 12)
            self.assertTrue(Path(result["log"]).exists())
            popen.assert_called_once()
            command = popen.call_args.args[0]
            self.assertIn("--steps", command)
            self.assertIn("12", command)

    def test_completed_training_adapter_is_discovered_without_env_override(self):
        profile_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            adapter = root / "assets" / "models" / "lora" / f"{profile_id}.safetensors"
            adapter.parent.mkdir(parents=True)
            adapter.write_bytes(b"adapter" * 512)
            manifest = root / "assets" / "models" / "lora" / "training" / profile_id / "manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                "profile_id": profile_id,
                "training_status": "completed",
                "adapter_output": str(adapter),
            }), encoding="utf-8")
            with patch("backend.app.diffusion.PROJECT_ROOT", root), patch.dict("os.environ", {"LOCAL_LORA_ADAPTER": ""}, clear=False):
                self.assertEqual(lora_adapter_path(), adapter)
                status = lora_adapter_status()
            self.assertFalse(status["configured"])
            self.assertTrue(status["discovered"])
            self.assertTrue(status["available"])
            self.assertEqual(status["profile_id"], profile_id)
            self.assertEqual(status["source"], "completed-training-manifest")
            self.assertTrue(any(item["selected"] for item in status["adapters"]))


if __name__ == "__main__":
    unittest.main()
