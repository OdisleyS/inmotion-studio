from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .media import UPLOADS_ROOT, inspect_reference_quality


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LORA_TRAINING_ROOT = PROJECT_ROOT / "assets" / "models" / "lora" / "training"


def _safe_profile_id(profile_id: str) -> str:
    value = Path(str(profile_id)).name
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("style_profile_id inválido para o dataset LoRA") from exc
    return value


def _workspace(profile_id: str) -> Path:
    return LORA_TRAINING_ROOT / _safe_profile_id(profile_id)


def _caption(trigger_word: str) -> str:
    return f"{trigger_word}, hand-drawn lineart, preserved character geometry, distinct sketch line weight"


def prepare_lora_dataset(
    profile_id: str,
    filenames: list[str],
    trigger_word: str = "studio_sketch",
    resolution: int = 512,
) -> dict[str, Any]:
    """Create a local, auditable LoRA training dataset from uploaded sketches.

    This is deliberately a preparation step. It never claims that a LoRA was
    trained; a separate trainer must consume the manifest and emit the adapter.
    Three or more usable references are required so a profile is not overfit to
    one photograph of a page.
    """
    clean = list(dict.fromkeys(Path(str(name)).name for name in filenames if str(name).strip()))
    if len(clean) < 3:
        raise ValueError("O dataset LoRA exige pelo menos 3 fotos de desenho aprovadas; uma foto ainda pode ser usada apenas no ControlNet.")
    quality = [inspect_reference_quality(name) for name in clean]
    if any(not item or not item.get("usable", False) for item in quality):
        raise ValueError("Uma ou mais referências não passaram no gate de qualidade; envie fotos nítidas, contrastadas e com pelo menos 128 px.")
    if resolution not in {256, 384, 512, 768}:
        raise ValueError("A resolução do dataset precisa ser 256, 384, 512 ou 768.")
    trigger = " ".join(str(trigger_word).split())[:80] or "studio_sketch"
    workspace = _workspace(profile_id)
    image_root = workspace / "images"
    image_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, filename in enumerate(clean, start=1):
        source = UPLOADS_ROOT / filename
        try:
            image = Image.open(source).convert("RGB")
        except (OSError, ValueError) as exc:
            raise ValueError(f"Não foi possível abrir a referência {filename}.") from exc
        fitted = ImageOps.contain(image, (resolution, resolution), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (resolution, resolution), (255, 255, 255))
        canvas.paste(fitted, ((resolution - fitted.width) // 2, (resolution - fitted.height) // 2))
        output = image_root / f"image_{index:04d}.png"
        canvas.save(output, "PNG", optimize=True)
        caption_path = output.with_suffix(".txt")
        caption_path.write_text(_caption(trigger), encoding="utf-8")
        records.append({
            "source": filename,
            "image": str(output),
            "caption": str(caption_path),
            "width": image.width,
            "height": image.height,
        })
    manifest = {
        "profile_id": _safe_profile_id(profile_id),
        "status": "dataset_ready",
        "training_status": "not_started",
        "trainer": "not_configured",
        "trigger_word": trigger,
        "resolution": resolution,
        "reference_count": len(records),
        "references": records,
        "dataset_dir": str(image_root),
        "adapter_output": str(PROJECT_ROOT / "assets" / "models" / "lora" / f"{profile_id}.safetensors"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message": "Dataset local preparado; configure um trainer LoRA para gerar o adaptador.",
    }
    manifest_path = workspace / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def lora_dataset_status(profile_id: str) -> dict[str, Any]:
    workspace = _workspace(profile_id)
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        return {"profile_id": _safe_profile_id(profile_id), "status": "not_prepared"}
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"profile_id": _safe_profile_id(profile_id), "status": "invalid_manifest"}
    if not isinstance(value, dict):
        return {"profile_id": _safe_profile_id(profile_id), "status": "invalid_manifest"}
    value["manifest"] = str(manifest_path)
    return value


def start_lora_training(profile_id: str, steps: int = 40) -> dict[str, Any]:
    """Start the local trainer and return its persisted state immediately."""
    workspace = _workspace(profile_id)
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("Prepare o dataset LoRA antes de iniciar o treinamento.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("manifesto LoRA inválido") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "dataset_ready":
        raise ValueError("o dataset LoRA não está pronto para treinamento")
    if manifest.get("training_status") == "running":
        return lora_dataset_status(profile_id)
    if not 1 <= int(steps) <= 2000:
        raise ValueError("steps precisa estar entre 1 e 2000")
    script = PROJECT_ROOT / "scripts" / "train_sketch_lora.py"
    if not script.exists():
        raise ValueError("trainer local não encontrado")
    try:
        import peft  # noqa: F401
    except ImportError as exc:
        raise ValueError("peft não está instalado no ambiente de imagem") from exc
    from .diffusion import diffusion_model_root

    log_path = workspace / "training.log"
    log_handle = log_path.open("ab")
    command = [
        sys.executable,
        str(script),
        "--manifest",
        str(manifest_path),
        "--model",
        str(diffusion_model_root()),
        "--steps",
        str(int(steps)),
        "--resolution",
        str(int(manifest.get("resolution", 512))),
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
    finally:
        log_handle.close()
    manifest.update({
        "training_status": "running",
        "trainer": "local-diffusers-peft",
        "process_id": process.pid,
        "steps": int(steps),
        "completed_steps": 0,
        "log": str(log_path),
        "error": None,
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return lora_dataset_status(profile_id)
