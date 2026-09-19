from __future__ import annotations

"""Safe, non-secret runtime overrides editable from the local Studio."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SETTINGS_PATH = PROJECT_ROOT / "assets" / "runtime-settings.json"
EDITABLE_KEYS = {
    "ENABLE_AGY_BRIDGE",
    "AGY_COMMAND",
    "AGY_TIMEOUT_SECONDS",
    "AGY_SKIP_PERMISSIONS",
    "ENABLE_CODEX_BRIDGE",
    "CODEX_COMMAND",
    "CODEX_TIMEOUT_SECONDS",
    "CODEX_MODEL",
    "COMFYUI_URL",
    "COMFYUI_WORKFLOW",
    "COMFYUI_WAN_WORKFLOW",
    "COMFYUI_LTX_WORKFLOW",
    "COMFYUI_VIDEO_TIMEOUT_SECONDS",
    "SADTALKER_ROOT",
    "SADTALKER_PYTHON",
    "SADTALKER_CHECKPOINT_DIR",
    "LOCAL_DIFFUSION_MODEL",
    "LOCAL_LORA_ADAPTER",
    "LOCAL_LORA_WEIGHT",
    "LOCAL_CONTROLNET_BASE",
    "LOCAL_CONTROLNET_LINEART",
    "PIPER_PT_MODEL",
    "PIPER_PT_CONFIG",
    "PIPER_EN_MODEL",
    "PIPER_EN_CONFIG",
}
_SAFE_VALUE = re.compile(r"^[^\r\n]{1,500}$")


def _read() -> dict[str, str]:
    if not RUNTIME_SETTINGS_PATH.exists():
        return {}
    try:
        payload = json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if str(key) in EDITABLE_KEYS and isinstance(value, (str, int, float, bool))}


def load_runtime_overrides() -> dict[str, str]:
    values = _read()
    for key, value in values.items():
        os.environ[key] = value
    return values


def runtime_overrides() -> dict[str, str]:
    return {key: os.getenv(key, "") for key in sorted(EDITABLE_KEYS) if os.getenv(key) is not None}


def _validate(key: str, value: Any) -> str:
    if key not in EDITABLE_KEYS:
        raise ValueError(f"Configuração não editável: {key}")
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"Valor inválido para {key}")
    if key.startswith("ENABLE_") or key == "AGY_SKIP_PERMISSIONS":
        if isinstance(value, bool):
            return "1" if value else "0"
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return "1"
        if normalized in {"0", "false", "no", "off"}:
            return "0"
        raise ValueError(f"{key} precisa ser 0 ou 1")
    normalized = str(value).strip()
    if key in {"COMFYUI_WORKFLOW", "COMFYUI_WAN_WORKFLOW", "COMFYUI_LTX_WORKFLOW", "SADTALKER_ROOT", "SADTALKER_PYTHON", "SADTALKER_CHECKPOINT_DIR", "LOCAL_LORA_ADAPTER"} and not normalized:
        return ""
    if not _SAFE_VALUE.fullmatch(normalized):
        raise ValueError(f"Valor inválido para {key}")
    if key == "CODEX_MODEL" and not re.fullmatch(r"[A-Za-z0-9._:/-]+", normalized):
        raise ValueError("CODEX_MODEL contém caracteres inválidos")
    if key in {"AGY_TIMEOUT_SECONDS", "CODEX_TIMEOUT_SECONDS"}:
        try:
            timeout = int(normalized)
        except ValueError as exc:
            raise ValueError(f"{key} precisa ser um número inteiro") from exc
        if not 30 <= timeout <= 300:
            raise ValueError(f"{key} precisa estar entre 30 e 300 segundos")
        return str(timeout)
    if key == "COMFYUI_VIDEO_TIMEOUT_SECONDS":
        try:
            timeout = int(normalized)
        except ValueError as exc:
            raise ValueError("COMFYUI_VIDEO_TIMEOUT_SECONDS precisa ser um número inteiro") from exc
        if not 60 <= timeout <= 1800:
            raise ValueError("COMFYUI_VIDEO_TIMEOUT_SECONDS precisa estar entre 60 e 1800 segundos")
        return str(timeout)
    if key == "LOCAL_LORA_WEIGHT":
        try:
            weight = float(normalized)
        except ValueError as exc:
            raise ValueError("LOCAL_LORA_WEIGHT precisa ser numérico") from exc
        if not 0 <= weight <= 2:
            raise ValueError("LOCAL_LORA_WEIGHT precisa estar entre 0 e 2")
        return str(weight)
    if key in {"AGY_COMMAND", "CODEX_COMMAND"}:
        if not normalized or any(char in normalized for char in '"\'`$(){}') or re.search(r"\s+--?\S", normalized):
            raise ValueError(f"{key} precisa ser um executável ou caminho simples, sem argumentos")
    if key == "COMFYUI_URL":
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("COMFYUI_URL precisa ser uma URL http(s) sem credenciais")
    if key != "COMFYUI_URL" and any(char in normalized for char in "&|;<>"):
        raise ValueError(f"Valor inválido para {key}")
    return normalized


def save_runtime_overrides(payload: dict[str, Any]) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("O payload de configuração precisa ser um objeto")
    current = _read()
    for key, value in payload.items():
        normalized = _validate(str(key), value)
        current[str(key)] = normalized
        os.environ[str(key)] = normalized
    RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return runtime_overrides()
