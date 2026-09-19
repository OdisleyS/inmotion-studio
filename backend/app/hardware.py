from __future__ import annotations

import shutil
import subprocess


def gpu_diagnostics() -> dict[str, object]:
    """Read the local NVIDIA GPU without exposing credentials or user files."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {
            "available": False,
            "vendor": "unknown",
            "name": None,
            "memory_mb": None,
            "driver": None,
            "native_video_guidance": "GPU NVIDIA não detectada; use o render local por sequência de imagens.",
        }

    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        first = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        parts = [part.strip() for part in first.split(",")]
        name = parts[0] if parts else None
        memory_mb = None
        if len(parts) > 1:
            try:
                memory_mb = int(float(parts[1]))
            except ValueError:
                memory_mb = None
        driver = parts[2] if len(parts) > 2 else None
        if result.returncode != 0 or not name:
            raise RuntimeError(result.stderr.strip() or "nvidia-smi não retornou uma GPU")
        guidance = (
            "Frame a frame local recomendado; Wan/LTX nativo exige checkpoints e normalmente mais VRAM."
            if memory_mb is not None and memory_mb < 8192
            else "GPU com memória suficiente para testar engines nativos quando runtime/checkpoints estiverem configurados."
        )
        return {
            "available": True,
            "vendor": "nvidia",
            "name": name,
            "memory_mb": memory_mb,
            "driver": driver,
            "native_video_guidance": guidance,
        }
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return {
            "available": False,
            "vendor": "nvidia",
            "name": None,
            "memory_mb": None,
            "driver": None,
            "native_video_guidance": f"Não foi possível ler a GPU local: {exc}",
        }
