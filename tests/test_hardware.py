from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from backend.app import hardware


class HardwareDiagnosticsTests(unittest.TestCase):
    def test_reports_nvidia_memory_and_low_vram_guidance(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["nvidia-smi"],
            returncode=0,
            stdout="NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 610.62\n",
            stderr="",
        )
        with patch.object(hardware.shutil, "which", return_value="nvidia-smi"), patch.object(
            hardware.subprocess, "run", return_value=completed
        ):
            result = hardware.gpu_diagnostics()

        self.assertTrue(result["available"])
        self.assertEqual(result["name"], "NVIDIA GeForce RTX 3050 Laptop GPU")
        self.assertEqual(result["memory_mb"], 4096)
        self.assertIn("Frame a frame", str(result["native_video_guidance"]))

    def test_reports_missing_gpu_without_throwing(self) -> None:
        with patch.object(hardware.shutil, "which", return_value=None):
            result = hardware.gpu_diagnostics()

        self.assertFalse(result["available"])
        self.assertIsNone(result["name"])
        self.assertIn("GPU NVIDIA não detectada", str(result["native_video_guidance"]))


if __name__ == "__main__":
    unittest.main()
