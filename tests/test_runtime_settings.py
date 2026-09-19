from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import runtime_settings


class RuntimeSettingsTests(unittest.TestCase):
    def test_safe_runtime_values_are_persisted_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runtime-settings.json"
            with patch.object(runtime_settings, "RUNTIME_SETTINGS_PATH", path), patch.dict(os.environ, {}, clear=False):
                values = runtime_settings.save_runtime_overrides({"CODEX_MODEL": "gpt-5.6-luna", "COMFYUI_URL": "http://127.0.0.1:8188"})
                self.assertEqual(values["CODEX_MODEL"], "gpt-5.6-luna")
                self.assertEqual(values["COMFYUI_URL"], "http://127.0.0.1:8188")
                self.assertNotIn("API_KEY", path.read_text(encoding="utf-8"))

    def test_optional_workflow_can_be_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runtime-settings.json"
            with patch.object(runtime_settings, "RUNTIME_SETTINGS_PATH", path), patch.dict(os.environ, {}, clear=False):
                runtime_settings.save_runtime_overrides({"COMFYUI_WORKFLOW": ""})
                self.assertEqual(runtime_settings._read()["COMFYUI_WORKFLOW"], "")

    def test_shell_and_credential_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            runtime_settings._validate("CODEX_MODEL", "model;whoami")
        with self.assertRaises(ValueError):
            runtime_settings._validate("COMFYUI_URL", "http://user:secret@127.0.0.1:8188")

    def test_bridge_settings_are_normalized_and_bounded(self) -> None:
        self.assertEqual(runtime_settings._validate("ENABLE_CODEX_BRIDGE", True), "1")
        self.assertEqual(runtime_settings._validate("ENABLE_AGY_BRIDGE", "off"), "0")
        self.assertEqual(runtime_settings._validate("AGY_SKIP_PERMISSIONS", True), "1")
        self.assertEqual(runtime_settings._validate("AGY_SKIP_PERMISSIONS", "off"), "0")
        self.assertEqual(runtime_settings._validate("CODEX_TIMEOUT_SECONDS", 180), "180")
        self.assertEqual(runtime_settings._validate("COMFYUI_VIDEO_TIMEOUT_SECONDS", 600), "600")
        self.assertEqual(runtime_settings._validate("SADTALKER_ROOT", r"third_party\SadTalker"), r"third_party\SadTalker")
        self.assertEqual(runtime_settings._validate("SADTALKER_CHECKPOINT_DIR", r"third_party\SadTalker\checkpoints"), r"third_party\SadTalker\checkpoints")
        self.assertEqual(runtime_settings._validate("LOCAL_LORA_ADAPTER", r"assets\models\lora\meu-traco.safetensors"), r"assets\models\lora\meu-traco.safetensors")
        self.assertEqual(runtime_settings._validate("LOCAL_LORA_WEIGHT", "1.25"), "1.25")
        self.assertEqual(runtime_settings._validate("AGY_COMMAND", r"C:\Tools\agy.exe"), r"C:\Tools\agy.exe")
        with self.assertRaises(ValueError):
            runtime_settings._validate("CODEX_TIMEOUT_SECONDS", 301)
        with self.assertRaises(ValueError):
            runtime_settings._validate("CODEX_COMMAND", "codex --dangerous")
        with self.assertRaises(ValueError):
            runtime_settings._validate("COMFYUI_VIDEO_TIMEOUT_SECONDS", 30)
        with self.assertRaises(ValueError):
            runtime_settings._validate("LOCAL_LORA_WEIGHT", 2.1)


if __name__ == "__main__":
    unittest.main()
