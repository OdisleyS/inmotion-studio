from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_ROOT = PROJECT_ROOT / "assets" / "models" / "sd-turbo"
_PIPELINE: Any = None
_IMAGE2IMAGE_PIPELINE: Any = None
_IMAGE2IMAGE_DISABLED = False
_LORA_LOAD_ERRORS: dict[str, str] = {}
_LORA_SUFFIXES = {".safetensors", ".bin", ".pt"}


def diffusion_model_root() -> Path:
    configured = Path(os.getenv("LOCAL_DIFFUSION_MODEL", str(DEFAULT_MODEL_ROOT)))
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def _configured_lora_adapter_path() -> Path | None:
    """Resolve the explicit adapter path, if the user configured one."""
    configured = os.getenv("LOCAL_LORA_ADAPTER", "").strip()
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if path.suffix.lower() not in _LORA_SUFFIXES:
        return None
    return path


def _completed_training_adapters() -> list[dict[str, object]]:
    """Find adapters emitted by the local trainer, without trusting unfinished manifests."""
    root = PROJECT_ROOT / "assets" / "models" / "lora" / "training"
    if not root.exists():
        return []
    discovered: list[dict[str, object]] = []
    for manifest_path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict) or manifest.get("training_status") != "completed":
            continue
        raw_output = str(manifest.get("adapter_output", "")).strip()
        if not raw_output:
            continue
        output = Path(raw_output)
        if not output.is_absolute():
            output = PROJECT_ROOT / output
        if output.suffix.lower() not in _LORA_SUFFIXES:
            continue
        discovered.append({
            "path": output,
            "profile_id": str(manifest.get("profile_id", manifest_path.parent.name)),
            "manifest": manifest_path,
            "source": "completed-training-manifest",
        })
    return discovered


def lora_adapter_path() -> Path | None:
    """Resolve an optional adapter, preferring explicit config then latest trained profile."""
    configured = _configured_lora_adapter_path()
    if os.getenv("LOCAL_LORA_ADAPTER", "").strip():
        return configured
    candidates = [item for item in _completed_training_adapters() if isinstance(item.get("path"), Path)]
    candidates.sort(key=lambda item: item["path"].stat().st_mtime if item["path"].exists() else 0, reverse=True)
    return candidates[0]["path"] if candidates else None


def lora_adapter_available() -> bool:
    path = lora_adapter_path()
    return bool(path and path.exists() and path.is_file() and path.stat().st_size > 1024)


def lora_adapter_catalog() -> list[dict[str, object]]:
    """List local adapters that can be selected without exposing file contents."""
    root = PROJECT_ROOT / "assets" / "models" / "lora"
    candidates: dict[Path, dict[str, object]] = {}
    if root.exists():
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in _LORA_SUFFIXES:
                candidates[path.resolve()] = {"source": "manual-file"}
    for item in _completed_training_adapters():
        path = item.get("path")
        if isinstance(path, Path):
            candidates[path.resolve()] = {
                "source": item.get("source"),
                "profile_id": item.get("profile_id"),
                "manifest": str(item.get("manifest")),
            }
    explicit = _configured_lora_adapter_path()
    if explicit:
        candidates.setdefault(explicit.resolve(), {"source": "explicit-config"})
    selected = lora_adapter_path()
    return [
        {
            "name": path.name,
            "path": str(path),
            "available": path.exists() and path.is_file() and path.stat().st_size > 1024,
            "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
            "selected": bool(selected and path.resolve() == selected.resolve()),
            **metadata,
        }
        for path, metadata in sorted(candidates.items(), key=lambda item: item[0].name.casefold())
    ]


def lora_adapter_status() -> dict[str, object]:
    path = lora_adapter_path()
    explicit = _configured_lora_adapter_path()
    selected_item = next((item for item in _completed_training_adapters() if item.get("path") == path), None)
    return {
        "configured": bool(explicit),
        "discovered": bool(path and not explicit),
        "available": lora_adapter_available(),
        "path": str(path) if path else None,
        "source": "explicit-config" if explicit else (selected_item.get("source") if selected_item else None),
        "profile_id": selected_item.get("profile_id") if selected_item else None,
        "size_bytes": path.stat().st_size if path and path.exists() and path.is_file() else 0,
        "error": _LORA_LOAD_ERRORS.get(str(path)) if path else None,
        "adapters": lora_adapter_catalog(),
    }


def _apply_optional_lora(pipe: Any) -> Path | None:
    """Load a configured adapter only when one exists; base SD remains usable without it."""
    path = lora_adapter_path()
    if path is None:
        return None
    if not lora_adapter_available():
        raise RuntimeError(f"LoRA configurado, mas o arquivo não existe ou está incompleto: {path}")
    marker = str(path.resolve())
    if getattr(pipe, "_studio_lora_path", None) == marker:
        return path
    try:
        loader = getattr(pipe, "load_lora_weights")
        loader(str(path.parent), weight_name=path.name, adapter_name="studio")
        set_adapters = getattr(pipe, "set_adapters", None)
        if callable(set_adapters):
            try:
                weight = max(0.0, min(2.0, float(os.getenv("LOCAL_LORA_WEIGHT", "0.8"))))
            except ValueError:
                weight = 0.8
            set_adapters(["studio"], adapter_weights=[weight])
        setattr(pipe, "_studio_lora_path", marker)
        _LORA_LOAD_ERRORS.pop(marker, None)
        return path
    except Exception as exc:
        _LORA_LOAD_ERRORS[marker] = str(exc)
        raise RuntimeError(f"Não foi possível carregar o LoRA local {path.name}: {exc}") from exc


def diffusion_dependencies_available() -> bool:
    try:
        import torch  # noqa: F401
        import diffusers  # noqa: F401
    except ImportError:
        return False
    return True


def diffusion_available() -> bool:
    """Capability check: no expensive model import happens during health checks."""
    root = diffusion_model_root()
    required_weights = (
        root / "unet" / "diffusion_pytorch_model.fp16.safetensors",
        root / "text_encoder" / "model.fp16.safetensors",
        root / "vae" / "diffusion_pytorch_model.fp16.safetensors",
    )
    return (
        os.getenv("ENABLE_LOCAL_DIFFUSION", "0") == "1"
        and diffusion_dependencies_available()
        and (root / "model_index.json").exists()
        and all(path.exists() and path.stat().st_size > 1024 for path in required_weights)
    )


def _pipeline() -> Any:
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    if not diffusion_available():
        raise RuntimeError("Local SD-Turbo não está habilitado ou o checkpoint ainda não foi baixado")
    import torch
    from diffusers import AutoPipelineForText2Image

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    _PIPELINE = AutoPipelineForText2Image.from_pretrained(
        str(diffusion_model_root()),
        torch_dtype=dtype,
        local_files_only=True,
        use_safetensors=True,
    )
    if torch.cuda.is_available():
        # CPU offload keeps the 4 GB RTX 3050 usable alongside the desktop.
        _PIPELINE.enable_model_cpu_offload()
    else:
        _PIPELINE.to("cpu")
    _PIPELINE.set_progress_bar_config(disable=True)
    return _PIPELINE


def _image2image_pipeline() -> Any:
    global _IMAGE2IMAGE_PIPELINE, _IMAGE2IMAGE_DISABLED
    if _IMAGE2IMAGE_DISABLED:
        raise RuntimeError("pipeline image-to-image indisponível para este checkpoint")
    if _IMAGE2IMAGE_PIPELINE is not None:
        return _IMAGE2IMAGE_PIPELINE
    if not diffusion_available():
        raise RuntimeError("Local SD-Turbo não está habilitado ou o checkpoint ainda não foi baixado")
    import torch
    from diffusers import AutoPipelineForImage2Image

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    try:
        _IMAGE2IMAGE_PIPELINE = AutoPipelineForImage2Image.from_pretrained(
            str(diffusion_model_root()),
            torch_dtype=dtype,
            local_files_only=True,
            use_safetensors=True,
        )
        if torch.cuda.is_available():
            _IMAGE2IMAGE_PIPELINE.enable_model_cpu_offload()
        else:
            _IMAGE2IMAGE_PIPELINE.to("cpu")
        _IMAGE2IMAGE_PIPELINE.set_progress_bar_config(disable=True)
        return _IMAGE2IMAGE_PIPELINE
    except Exception:
        _IMAGE2IMAGE_DISABLED = True
        raise


def generate_diffusion_image(prompt: str, output_path: Path, seed: int = 0, reference_path: Path | None = None) -> str:
    """Generate one real SD-Turbo image, optionally conditioned by a drawing reference."""
    import torch

    generator = torch.Generator(device="cpu").manual_seed(seed)
    if reference_path is not None:
        reference = Image.open(reference_path).convert("RGB").resize((512, 512))
        pipe = _image2image_pipeline()
        _apply_optional_lora(pipe)
        image = pipe(prompt=prompt, image=reference, strength=0.58, guidance_scale=0.0, num_inference_steps=2, generator=generator).images[0]
    else:
        pipe = _pipeline()
        _apply_optional_lora(pipe)
        image = pipe(prompt=prompt, guidance_scale=0.0, num_inference_steps=1, height=512, width=512, generator=generator).images[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(image, Image.Image):
        raise RuntimeError("Diffusers não retornou uma imagem PIL")
    image.convert("RGB").save(output_path, "PNG", optimize=True)
    return str(output_path)
