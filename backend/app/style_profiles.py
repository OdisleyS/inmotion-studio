from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .media import GENERATED_ROOT, inspect_reference_quality


STYLE_PROFILES_ROOT = GENERATED_ROOT.parent / "assets" / "style_profiles"
_PROFILE_ID = re.compile(r"^[a-f0-9-]{8,64}$", re.IGNORECASE)


def _path(profile_id: str) -> Path:
    safe_id = Path(str(profile_id)).name
    if safe_id != str(profile_id) or not _PROFILE_ID.fullmatch(safe_id):
        raise ValueError("style_profile_id inválido")
    return STYLE_PROFILES_ROOT / f"{safe_id}.json"


def load_style_profile(profile_id: str) -> dict[str, Any] | None:
    try:
        path = _path(profile_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def list_style_profiles() -> list[dict[str, Any]]:
    STYLE_PROFILES_ROOT.mkdir(parents=True, exist_ok=True)
    profiles: list[dict[str, Any]] = []
    for path in sorted(STYLE_PROFILES_ROOT.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get("profile_id"):
            profiles.append(value)
    return profiles


def create_style_profile(name: str, filenames: list[str], fidelity: dict[str, Any]) -> dict[str, Any]:
    clean_names = [Path(str(filename)).name for filename in filenames if Path(str(filename)).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    if not clean_names:
        raise ValueError("Envie pelo menos um PNG, JPG ou WEBP para salvar um perfil visual.")
    quality = [inspect_reference_quality(filename) for filename in clean_names]
    quality = [item for item in quality if item]
    if not quality or any(not item.get("usable", False) for item in quality):
        raise ValueError("Uma ou mais referências não passaram no gate de qualidade; envie imagens nítidas, contrastadas e com pelo menos 128 px.")
    profile_id = str(uuid.uuid4())
    profile = {
        "profile_id": profile_id,
        "name": str(name or "Meu traço").strip()[:80] or "Meu traço",
        "style": "sketch_clone",
        "mode": "reference",
        "reference_count": len(clean_names),
        "reference_files": clean_names,
        "quality_gate": fidelity.get("status", "verified"),
        "quality": quality,
        "conditioning": "controlnet_lineart",
        "conditioning_provider": "local-controlnet-lineart",
        "preservation_targets": ["geometry", "line_weight", "character_traits"],
        "style_reference_id": fidelity.get("style_reference_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    STYLE_PROFILES_ROOT.mkdir(parents=True, exist_ok=True)
    _path(profile_id).write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile
