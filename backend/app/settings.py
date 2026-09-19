from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .media import PROJECT_ROOT


SETTINGS_PATH = PROJECT_ROOT / "assets" / "workspace-settings.json"
DEFAULT_SETTINGS: dict[str, Any] = {
    "provider_selection": {"script": "auto", "image": "auto", "audio": "auto", "video": "auto"},
    "model_selection": {"script": "auto", "image": "auto", "audio": "auto", "video": "auto"},
    "image_source": "generate",
    "video_strategy": "auto",
    "narration_language": "pt_BR",
    "target_seconds": 35,
    "output_format": "vertical",
    "stage_autonomy": {
        "research": "autonomous",
        "script": "autonomous",
        "image": "autonomous",
        "audio": "autonomous",
        "sfx": "autonomous",
        "bgm": "autonomous",
        "video": "autonomous",
    },
}


def load_workspace_settings() -> dict[str, Any]:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if not SETTINGS_PATH.exists():
        return settings
    try:
        stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if not isinstance(stored, dict):
        return settings
    for key in ("image_source", "video_strategy", "narration_language", "target_seconds", "output_format"):
        if key in stored:
            settings[key] = stored[key]
    for key in ("provider_selection", "model_selection", "stage_autonomy"):
        if isinstance(stored.get(key), dict):
            settings[key].update({str(name): str(value) for name, value in stored[key].items()})
    return settings


def save_workspace_settings(value: dict[str, Any]) -> dict[str, Any]:
    settings = load_workspace_settings()
    for key in ("image_source", "video_strategy", "narration_language", "target_seconds", "output_format"):
        if key in value:
            settings[key] = value[key]
    for key in ("provider_selection", "model_selection", "stage_autonomy"):
        if isinstance(value.get(key), dict):
            settings[key].update({str(name): str(item) for name, item in value[key].items()})
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings
