from __future__ import annotations

"""Optional local ControlNet line-art engine.

The automatic studio path stays on SD-Turbo. This module is deliberately
separate so a missing or incompatible style-control model never blocks normal
concept-to-video production.
"""

import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = PROJECT_ROOT / "assets" / "models" / "sd15-base"
DEFAULT_CONTROLNET = PROJECT_ROOT / "assets" / "models" / "controlnet" / "lineart"
_PIPELINE: Any = None


def _model_path(env_name: str, default: Path) -> Path:
    configured = Path(os.getenv(env_name, str(default)))
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def controlnet_base_path() -> Path:
    return _model_path("LOCAL_CONTROLNET_BASE", DEFAULT_BASE)


def controlnet_model_path() -> Path:
    return _model_path("LOCAL_CONTROLNET_LINEART", DEFAULT_CONTROLNET)


def controlnet_available() -> bool:
    base = controlnet_base_path()
    control = controlnet_model_path()
    required_base = (
        base / "model_index.json",
        base / "text_encoder" / "model.fp16.safetensors",
        base / "unet" / "diffusion_pytorch_model.fp16.safetensors",
        base / "vae" / "diffusion_pytorch_model.fp16.safetensors",
    )
    required_control = (control / "config.json", control / "diffusion_pytorch_model.fp16.safetensors")
    weight_files = (
        base / "text_encoder" / "model.fp16.safetensors",
        base / "unet" / "diffusion_pytorch_model.fp16.safetensors",
        base / "vae" / "diffusion_pytorch_model.fp16.safetensors",
        control / "diffusion_pytorch_model.fp16.safetensors",
    )
    config_files = (base / "model_index.json", control / "config.json")
    return os.getenv("ENABLE_LOCAL_CONTROLNET", "1") == "1" and all(path.exists() for path in config_files) and all(path.exists() and path.stat().st_size > 1024 for path in weight_files)


def _lineart_condition(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.fit(source.convert("L"), (512, 512), method=Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    edges = image.filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    # ControlNet lineart models expect a white canvas with dark strokes.
    return ImageOps.invert(edges).convert("RGB")


def _pipeline() -> Any:
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    if not controlnet_available():
        raise RuntimeError("ControlNet lineart ainda não está instalado")
    import torch
    from diffusers import ControlNetModel, StableDiffusionControlNetPipeline

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    controlnet = ControlNetModel.from_pretrained(
        str(controlnet_model_path()), torch_dtype=dtype, local_files_only=True, use_safetensors=True,
        variant="fp16",
    )
    _PIPELINE = StableDiffusionControlNetPipeline.from_pretrained(
        str(controlnet_base_path()), controlnet=controlnet, torch_dtype=dtype,
        local_files_only=True, use_safetensors=True, variant="fp16", safety_checker=None,
        feature_extractor=None,
    )
    if torch.cuda.is_available():
        _PIPELINE.enable_model_cpu_offload()
    else:
        _PIPELINE.to("cpu")
    _PIPELINE.set_progress_bar_config(disable=True)
    return _PIPELINE


def generate_controlnet_image(prompt: str, output_path: Path, reference_path: Path, seed: int = 0) -> str:
    import torch

    generator = torch.Generator(device="cpu").manual_seed(seed)
    image = _pipeline()(
        prompt=prompt,
        image=_lineart_condition(reference_path),
        height=512,
        width=512,
        num_inference_steps=8,
        guidance_scale=7.0,
        controlnet_conditioning_scale=0.9,
        generator=generator,
    ).images[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path, "PNG", optimize=True)
    return str(output_path)
