"""Train a small local SD-Turbo LoRA from a prepared sketch manifest.

This script is intentionally explicit and local-only. It consumes the manifest
created by backend.app.lora_training, never downloads a model, and writes a
real safetensors adapter only after the optimization loop completes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import torch
from PIL import Image, ImageOps


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifesto LoRA inválido")
    return value


def _write(path: Path, manifest: dict[str, Any], **updates: Any) -> None:
    manifest.update(updates)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _images(manifest: dict[str, Any], resolution: int) -> list[tuple[Path, str]]:
    records = manifest.get("references", [])
    if not isinstance(records, list) or len(records) < 3:
        raise ValueError("o manifesto precisa conter pelo menos 3 referências")
    values: list[tuple[Path, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        image_path = Path(str(record.get("image", "")))
        caption_path = Path(str(record.get("caption", "")))
        if not image_path.exists() or not caption_path.exists():
            raise ValueError(f"asset do dataset ausente: {image_path}")
        caption = caption_path.read_text(encoding="utf-8").strip()
        if not caption:
            raise ValueError(f"caption vazia: {caption_path}")
        values.append((image_path, caption))
    if not values:
        raise ValueError("nenhuma imagem válida no dataset")
    return values


def _batch(values: list[tuple[Path, str]], tokenizer: Any, resolution: int, device: torch.device, dtype: torch.dtype) -> tuple[torch.Tensor, torch.Tensor]:
    images: list[torch.Tensor] = []
    captions: list[str] = []
    for path, caption in values:
        image = Image.open(path).convert("RGB")
        image = ImageOps.fit(image, (resolution, resolution), method=Image.Resampling.LANCZOS)
        pixels = torch.from_numpy(__import__("numpy").asarray(image)).permute(2, 0, 1).float() / 127.5 - 1.0
        images.append(pixels)
        captions.append(caption)
    pixel_values = torch.stack(images).to(device=device, dtype=dtype)
    tokens = tokenizer(
        captions,
        padding="max_length",
        max_length=tokenizer.model_max_length,
        truncation=True,
        return_tensors="pt",
    ).input_ids.to(device)
    return pixel_values, tokens


def train(manifest_path: Path, model_root: Path, steps: int, resolution: int, learning_rate: float, device_name: str) -> Path:
    manifest = _read(manifest_path)
    if manifest.get("status") != "dataset_ready":
        raise ValueError("o dataset precisa estar em status dataset_ready")
    if steps < 1 or steps > 2000:
        raise ValueError("steps precisa estar entre 1 e 2000")
    if resolution not in {256, 384, 512, 768}:
        raise ValueError("resolution inválida")
    try:
        from peft import LoraConfig
        from diffusers import AutoencoderKL, DDPMScheduler, UNet2DConditionModel
        from diffusers.loaders import LoraLoaderMixin
        from transformers import CLIPTextModel, CLIPTokenizer
    except ImportError as exc:
        raise RuntimeError("instale peft, diffusers e transformers no ambiente de imagem") from exc

    device = torch.device("cuda" if device_name == "auto" and torch.cuda.is_available() else device_name)
    dtype = torch.float16 if device.type == "cuda" else torch.float32
    values = _images(manifest, resolution)
    output = Path(str(manifest.get("adapter_output")))
    output.parent.mkdir(parents=True, exist_ok=True)
    _write(manifest_path, manifest, training_status="running", trainer="local-diffusers-peft", steps=steps, completed_steps=0, error=None)

    tokenizer = CLIPTokenizer.from_pretrained(str(model_root / "tokenizer"), local_files_only=True)
    text_encoder = CLIPTextModel.from_pretrained(str(model_root / "text_encoder"), torch_dtype=dtype, local_files_only=True).to(device)
    vae = AutoencoderKL.from_pretrained(str(model_root / "vae"), torch_dtype=dtype, local_files_only=True).to(device)
    unet = UNet2DConditionModel.from_pretrained(str(model_root / "unet"), torch_dtype=dtype, local_files_only=True).to(device)
    text_encoder.requires_grad_(False)
    vae.requires_grad_(False)
    unet.requires_grad_(False)
    unet.add_adapter(
        LoraConfig(
            r=4,
            lora_alpha=4,
            lora_dropout=0.05,
            target_modules=["to_q", "to_k", "to_v", "to_out.0"],
            bias="none",
        ),
        adapter_name="sketch",
    )
    unet.set_adapter("sketch")
    if hasattr(unet, "enable_gradient_checkpointing"):
        unet.enable_gradient_checkpointing()
    trainable = [parameter for parameter in unet.parameters() if parameter.requires_grad]
    if not trainable:
        raise RuntimeError("o UNet não expôs parâmetros LoRA treináveis")
    optimizer = torch.optim.AdamW(trainable, lr=learning_rate)
    scheduler = DDPMScheduler(num_train_timesteps=1000, beta_start=0.00085, beta_end=0.012, beta_schedule="scaled_linear", prediction_type="epsilon")
    vae_scale = float(getattr(vae.config, "scaling_factor", 0.18215))
    torch.manual_seed(41)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(41)
    try:
        for step in range(steps):
            pixel_values, input_ids = _batch(values, tokenizer, resolution, device, dtype)
            with torch.no_grad():
                latents = vae.encode(pixel_values).latent_dist.sample() * vae_scale
                hidden_states = text_encoder(input_ids)[0]
            noise = torch.randn_like(latents)
            timesteps = torch.randint(0, scheduler.config.num_train_timesteps, (latents.shape[0],), device=device).long()
            noisy_latents = scheduler.add_noise(latents, noise, timesteps)
            model_pred = unet(noisy_latents, timesteps, encoder_hidden_states=hidden_states).sample
            loss = torch.nn.functional.mse_loss(model_pred.float(), noise.float(), reduction="mean")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            if step == 0 or (step + 1) % 5 == 0 or step + 1 == steps:
                _write(manifest_path, manifest, training_status="running", completed_steps=step + 1, last_loss=round(float(loss.detach().cpu()), 6))
        unet.save_lora_adapter(output.parent, adapter_name="sketch", weight_name=output.name, safe_serialization=True)
        _write(manifest_path, manifest, training_status="completed", completed_steps=steps, adapter_output=str(output), error=None)
        return output
    except Exception as exc:
        _write(manifest_path, manifest, training_status="failed", error=str(exc))
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    try:
        output = train(Path(args.manifest), Path(args.model), args.steps, args.resolution, args.learning_rate, args.device)
        print(json.dumps({"status": "completed", "adapter": str(output)}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
