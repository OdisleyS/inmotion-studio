from __future__ import annotations

from pathlib import Path
import os
import shutil
import json
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import EditProjectRequest, GenerateRequest, GenerateResponse, ScriptPreviewRequest, StyleProfileRequest
from .pipeline import ProductionPipeline, build_style_profile, inspect_sketches, validate_provider_selection
from .style_profiles import create_style_profile, list_style_profiles, load_style_profile
from .lora_training import lora_dataset_status, prepare_lora_dataset, start_lora_training
from .providers import ProviderError, codex_command_available, codex_model_name, comfyui_available, comfyui_native_video_available, comfyui_url, comfyui_video_workflow_path, comfyui_workflow_path, get_model_catalog, get_provider_catalog, sadtalker_available, sadtalker_checkpoint_path, sadtalker_inference_path, sadtalker_python
from .media import GENERATED_ROOT, PROJECT_ROOT, UPLOADS_ROOT, create_storyboard_frames, ffmpeg_executable, inspect_reference_quality, piper_executable, piper_voice_available, render_frame_video, synthesize_piper, voice_model_paths
from .diffusion import diffusion_available, diffusion_model_root, generate_diffusion_image, lora_adapter_status
from .controlnet import controlnet_available, controlnet_base_path, controlnet_model_path
from .jobs import JobManager
from .settings import load_workspace_settings, save_workspace_settings
from .runtime_settings import load_runtime_overrides, runtime_overrides, save_runtime_overrides
from .hardware import gpu_diagnostics


load_runtime_overrides()
app = FastAPI(title="In-House Video Studio", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
pipeline = ProductionPipeline()
job_manager = JobManager()
GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=GENERATED_ROOT), name="media")


@app.get("/api/health")
def health() -> dict[str, object]:
    agy_available = bool(shutil.which(os.getenv("AGY_COMMAND", "agy")))
    return {
        "status": "ok",
        "service": "in-house-video-studio",
        "providers": {"script": 1, "image": 1, "audio": 1, "video": 1},
        "antigravity_cli": {"available": agy_available, "enabled": os.getenv("ENABLE_AGY_BRIDGE", "0") == "1"},
        "codex_cli": {"available": codex_command_available(), "enabled": os.getenv("ENABLE_CODEX_BRIDGE", "0") == "1", "model": os.getenv("CODEX_MODEL", "gpt-5.6-luna")},
        "hardware": gpu_diagnostics(),
        "integrations": {
            "research": {"enabled": os.getenv("ENABLE_LIVE_RESEARCH", "1") == "1", "provider": "google-news-rss + duckduckgo-lite + local-heuristic"},
            "piper": {"executable": bool(piper_executable()), "pt_BR": piper_voice_available("pt_BR"), "en_US": piper_voice_available("en_US")},
            "ffmpeg": {"available": bool(ffmpeg_executable())},
            "sd_turbo": {"enabled": os.getenv("ENABLE_LOCAL_DIFFUSION", "0") == "1", "available": diffusion_available(), "lora": lora_adapter_status()},
            "controlnet_lineart": {"enabled": os.getenv("ENABLE_LOCAL_CONTROLNET", "1") == "1", "available": controlnet_available(), "base": "sd15-base", "control": "lineart"},
            "comfyui": {"url": comfyui_url(), "available": comfyui_available(), "workflow_configured": bool(os.getenv("COMFYUI_WORKFLOW", "").strip())},
            "native_video": {"wan": {"available": comfyui_native_video_available("wan-video"), "workflow": _runtime_path(comfyui_video_workflow_path("wan-video"))}, "ltx": {"available": comfyui_native_video_available("ltx-video"), "workflow": _runtime_path(comfyui_video_workflow_path("ltx-video"))}, "sadtalker": {"available": sadtalker_available(), "inference": _runtime_path(sadtalker_inference_path()), "checkpoints": _runtime_path(sadtalker_checkpoint_path()), "python": sadtalker_python()}},
        },
    }


def _runtime_path(path: Path | None) -> dict[str, object]:
    """Expose safe local diagnostics without returning credentials or env values."""
    if path is None:
        return {"path": None, "exists": False, "size_bytes": 0, "size_mb": 0}
    exists = path.exists()
    size_bytes = path.stat().st_size if exists and path.is_file() else 0
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 2) if size_bytes else 0,
    }


@app.get("/api/runtime-config", response_model=None)
def runtime_config() -> dict[str, object]:
    """Return the effective, non-secret runtime configuration shown in Config."""
    piper_pt_model, piper_pt_config = voice_model_paths("pt_BR")
    piper_en_model, piper_en_config = voice_model_paths("en_US")
    workflow = comfyui_workflow_path()
    agy_command = os.getenv("AGY_COMMAND", "agy")
    codex_command = os.getenv("CODEX_COMMAND", "codex")
    return {
        "project_root": str(PROJECT_ROOT),
        "hardware": gpu_diagnostics(),
        "bridges": {
            "antigravity": {"command": agy_command, "available": bool(shutil.which(agy_command)), "enabled": os.getenv("ENABLE_AGY_BRIDGE", "0") == "1", "timeout_seconds": os.getenv("AGY_TIMEOUT_SECONDS", "90")},
            "codex": {"command": codex_command, "available": codex_command_available(), "enabled": os.getenv("ENABLE_CODEX_BRIDGE", "0") == "1", "model": codex_model_name(), "timeout_seconds": os.getenv("CODEX_TIMEOUT_SECONDS", "120")},
        },
        "media": {
            "piper": {"executable": piper_executable(), "pt_BR": {**_runtime_path(piper_pt_model), "config": _runtime_path(piper_pt_config)}, "en_US": {**_runtime_path(piper_en_model), "config": _runtime_path(piper_en_config)}},
            "ffmpeg": {"executable": ffmpeg_executable(), "available": bool(ffmpeg_executable())},
        },
        "image": {
            "sd_turbo": {**_runtime_path(diffusion_model_root()), "enabled": os.getenv("ENABLE_LOCAL_DIFFUSION", "0") == "1", "available": diffusion_available(), "lora": lora_adapter_status()},
            "controlnet": {"base": {**_runtime_path(controlnet_base_path())}, "lineart": {**_runtime_path(controlnet_model_path())}, "enabled": os.getenv("ENABLE_LOCAL_CONTROLNET", "1") == "1", "available": controlnet_available()},
            "comfyui": {"url": comfyui_url(), "workflow": _runtime_path(workflow), "available": comfyui_available()},
        },
        "video": {
            "comfyui": {
                "wan": {"available": comfyui_native_video_available("wan-video"), "workflow": _runtime_path(comfyui_video_workflow_path("wan-video"))},
                "ltx": {"available": comfyui_native_video_available("ltx-video"), "workflow": _runtime_path(comfyui_video_workflow_path("ltx-video"))},
                "sadtalker": {"available": sadtalker_available(), "inference": _runtime_path(sadtalker_inference_path()), "checkpoints": _runtime_path(sadtalker_checkpoint_path()), "python": sadtalker_python()},
            }
        },
        "research": {"enabled": os.getenv("ENABLE_LIVE_RESEARCH", "1") == "1", "provider": "google-news-rss + duckduckgo-lite + local-heuristic"},
        "editable": runtime_overrides(),
    }


@app.put("/api/runtime-config", response_model=None)
def update_runtime_config(payload: dict[str, object]) -> dict[str, object]:
    """Persist only safe, non-secret local runtime values supplied by Config."""
    try:
        save_runtime_overrides(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"saved": True, **runtime_config()}


@app.get("/api/providers", response_model=None)
def providers() -> dict[str, list[dict[str, object]]]:
    return get_provider_catalog()


@app.get("/api/models", response_model=None)
def models() -> dict[str, list[dict[str, object]]]:
    return get_model_catalog()


@app.post("/api/script/preview", response_model=None)
def script_preview(request: ScriptPreviewRequest) -> dict[str, object]:
    """Generate/revise only the narration draft before rendering the production."""
    try:
        return pipeline.draft_script(
            topic=request.topic,
            style=request.style,
            custom_script=request.script,
            provider_selection=request.provider_selection,
            model_selection=request.model_selection,
            target_seconds=request.target_seconds,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/integrations/probe", response_model=None)
def probe_integration(payload: dict[str, object]) -> dict[str, object]:
    """Run an explicit local connectivity check without exposing credentials."""
    integration = str(payload.get("integration", "")).strip().lower()
    if integration == "codex":
        if not pipeline.codex.available:
            return {"integration": "codex", "status": "unavailable", "message": "Codex CLI não está habilitado ou não foi encontrado."}
        try:
            result = pipeline.codex.create("Teste de conexão", "dynamic_slideshow", None, model=os.getenv("CODEX_MODEL", "auto"), target_seconds=8)
            return {"integration": "codex", "status": "ready", "model": os.getenv("CODEX_MODEL", "auto"), "message": str(result.get("script", ""))[:240]}
        except ProviderError as exc:
            return {"integration": "codex", "status": "error", "message": str(exc)}
    if integration == "antigravity":
        if not pipeline.agy.available:
            return {"integration": "antigravity", "status": "unavailable", "message": "Antigravity CLI não está habilitado ou não foi encontrado."}
        try:
            result = pipeline.agy.create("Teste de conexão", "dynamic_slideshow", None, model="auto", target_seconds=8)
            return {"integration": "antigravity", "status": "ready", "message": str(result.get("script", ""))[:240]}
        except ProviderError as exc:
            return {"integration": "antigravity", "status": "error", "message": str(exc)}
    if integration == "comfyui":
        return {"integration": "comfyui", "status": "ready" if comfyui_available() else "unavailable", "url": comfyui_url(), "message": "ComfyUI respondeu e o workflow está configurado." if comfyui_available() else "Configure o servidor e COMFYUI_WORKFLOW para ativar ControlNet/LoRA."}
    if integration == "controlnet":
        return {"integration": "controlnet", "status": "ready" if controlnet_available() else "unavailable", "message": "ControlNet Lineart local está pronto para referências de desenho." if controlnet_available() else "Baixe/configure o checkpoint SD1.5 e o ControlNet Lineart local."}
    if integration == "piper":
        if not piper_executable() or not all(piper_voice_available(language) for language in ("pt_BR", "en_US")):
            return {"integration": "piper", "status": "unavailable", "message": "Piper ou os modelos pt-BR/en-US não estão completos."}
        try:
            with tempfile.TemporaryDirectory(prefix="studio-piper-probe-") as folder:
                results = {language: synthesize_piper("Teste local de narração.", Path(folder), language) for language in ("pt_BR", "en_US")}
            return {"integration": "piper", "status": "ready", "message": f"Síntese WAV real confirmada · pt-BR {results['pt_BR']['duration_seconds']}s · en-US {results['en_US']['duration_seconds']}s"}
        except Exception as exc:
            return {"integration": "piper", "status": "error", "message": f"Piper encontrou um erro na síntese real: {exc}"}
    if integration == "sd_turbo":
        if not diffusion_available():
            return {"integration": "sd_turbo", "status": "unavailable", "message": "SD-Turbo local não está disponível para geração de imagem."}
        try:
            with tempfile.TemporaryDirectory(prefix="studio-sd-probe-") as folder:
                output = generate_diffusion_image("clean editorial illustration, abstract studio test, no text", Path(folder) / "probe.png", seed=41)
                size = Path(output).stat().st_size
            return {"integration": "sd_turbo", "status": "ready", "message": f"Imagem PNG real confirmada · {size // 1024} KB · arquivo temporário descartado"}
        except Exception as exc:
            return {"integration": "sd_turbo", "status": "error", "message": f"SD-Turbo encontrou um erro na geração real: {exc}"}
    raise HTTPException(status_code=422, detail="Integração desconhecida. Use codex, antigravity, controlnet, comfyui, piper ou sd_turbo.")


@app.get("/api/settings", response_model=None)
def settings() -> dict[str, object]:
    """Return non-secret workspace defaults for the browser studio."""
    return load_workspace_settings()


@app.put("/api/settings", response_model=None)
def update_settings(payload: dict[str, object]) -> dict[str, object]:
    """Persist provider/model defaults without ever accepting credentials."""
    safe = {
        "provider_selection": payload.get("provider_selection", {}),
        "model_selection": payload.get("model_selection", {}),
        "image_source": payload.get("image_source", "generate"),
        "video_strategy": payload.get("video_strategy", "auto"),
        "narration_language": payload.get("narration_language", "pt_BR"),
        "target_seconds": payload.get("target_seconds", 35),
        "output_format": payload.get("output_format", "vertical"),
        "stage_autonomy": payload.get("stage_autonomy", {}),
    }
    if safe["image_source"] not in {"generate", "reference"}:
        raise HTTPException(status_code=422, detail="image_source inválido")
    if safe["video_strategy"] not in {"auto", "image_sequence", "direct_video"}:
        raise HTTPException(status_code=422, detail="video_strategy inválido")
    if safe["narration_language"] not in {"pt_BR", "en_US"}:
        raise HTTPException(status_code=422, detail="narration_language inválido")
    if safe["output_format"] not in {"vertical", "horizontal", "square"}:
        raise HTTPException(status_code=422, detail="output_format inválido")
    if not isinstance(safe["stage_autonomy"], dict):
        raise HTTPException(status_code=422, detail="stage_autonomy inválido")
    if any(str(mode) not in {"autonomous", "manual", "copilot"} for mode in safe["stage_autonomy"].values()):
        raise HTTPException(status_code=422, detail="stage_autonomy contém modo inválido")
    try:
        safe["target_seconds"] = min(90, max(10, int(safe["target_seconds"])))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="target_seconds inválido") from exc
    return save_workspace_settings(safe)


@app.get("/api/projects", response_model=None)
def projects() -> list[dict[str, object]]:
    """Return persisted productions so the library survives browser refreshes."""
    records: list[dict[str, object]] = []
    for project_dir in sorted(GENERATED_ROOT.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not project_dir.is_dir():
            continue
        video_path = project_dir / "video.mp4"
        if not video_path.exists():
            continue
        manifest_path = project_dir / "project.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"project_id": project_dir.name, "title": project_dir.name, "status": "completed"}
        except (OSError, json.JSONDecodeError):
            continue
        render = _decorate_render(manifest.get("render", {"path": str(video_path)}))
        records.append({"project_id": manifest.get("project_id", project_dir.name), "title": manifest.get("title", project_dir.name), "status": manifest.get("status", "completed"), "virality_score": manifest.get("virality_score", 0), "render": render})
    return records[:30]


@app.get("/api/projects/{project_id}", response_model=None)
def project_detail(project_id: str) -> dict[str, object]:
    """Load a persisted project back into the editor."""
    safe_id = Path(project_id).name
    project_dir = GENERATED_ROOT / safe_id
    manifest_path = project_dir / "project.json"
    if safe_id != project_id or not project_dir.is_dir() or not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Manifesto inválido: {exc}") from exc
    manifest["project_id"] = manifest.get("project_id", safe_id)
    manifest["render"] = _decorate_render(manifest.get("render", {"path": str(project_dir / "video.mp4")}))
    return manifest


def _regenerate_scene_frame(manifest: dict[str, object], scene: dict[str, object], scene_output_dir: Path, output_format: str) -> tuple[str, str]:
    """Regenerate one edited scene with the original visual provider when possible."""
    topic = str(manifest.get("topic", manifest.get("title", "Projeto")))
    style = str(manifest.get("style", "dynamic_slideshow"))
    prompt = str(scene.get("prompt", topic)).strip() or topic
    selection = manifest.get("provider_selection", {})
    models = manifest.get("model_selection", {})
    chosen_provider = str(selection.get("image", "auto")) if isinstance(selection, dict) else "auto"
    chosen_model = str(models.get("image", "auto")) if isinstance(models, dict) else "auto"
    provenance = manifest.get("render", {}).get("media_provenance", {}) if isinstance(manifest.get("render"), dict) else {}
    provider_name = str(provenance.get("image_provider", "")) if isinstance(provenance, dict) else ""
    provider_name = provider_name or chosen_provider
    profile = manifest.get("style_profile", {})
    references = scene.get("sketch_inputs", [])
    if not references and isinstance(profile, dict):
        references = profile.get("reference_files", []) or []
    sketch_filenames = [str(item) for item in references if str(item).strip()] if isinstance(references, list) else []
    scene_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if provider_name == "local-sd-turbo" and pipeline.diffusion.available:
            result = pipeline.diffusion.create(topic, style, sketch_filenames, scene_output_dir, model=chosen_model, scene_prompts=[prompt], output_format=output_format)
            generated = result.get("generated_image_paths", [])
            if generated:
                return str(generated[0]), str(result.get("generation_mode", provider_name))
        elif provider_name == "local-controlnet-lineart" and pipeline.controlnet.available and sketch_filenames:
            result = pipeline.controlnet.create(topic, style, sketch_filenames, scene_output_dir, scene_prompts=[prompt], output_format=output_format)
            generated = result.get("generated_image_paths", [])
            if generated:
                return str(generated[0]), str(result.get("generation_mode", provider_name))
        elif provider_name == "comfyui-controlnet-lora" and pipeline.comfy.available:
            result = pipeline.comfy.create(topic, style, sketch_filenames, scene_output_dir, model=chosen_model, scene_prompts=[prompt], output_format=output_format)
            generated = result.get("generated_image_paths", [])
            if generated:
                return str(generated[0]), str(result.get("generation_mode", provider_name))
        elif provider_name == "antigravity-visual-planner" and pipeline.visual.available:
            result = pipeline.visual.create(topic, style, sketch_filenames, scene_output_dir, model=chosen_model, scene_prompts=[prompt], output_format=output_format)
            generated = result.get("frame_paths", [])
            if generated:
                return str(generated[0]), str(result.get("generation_mode", provider_name))
    except (ProviderError, OSError, RuntimeError):
        # Editing must remain available even when an optional provider goes offline.
        pass

    generated = create_storyboard_frames(topic, style, [scene], scene_output_dir, output_format)
    if not generated:
        raise HTTPException(status_code=500, detail="Não foi possível regenerar a cena")
    return generated[0], "local-editor-storyboard"


@app.post("/api/projects/{project_id}/edit", response_model=None)
def edit_project(project_id: str, request: EditProjectRequest) -> dict[str, object]:
    """Edit scene captions/order and rerender the existing local project."""
    safe_id = Path(project_id).name
    project_dir = GENERATED_ROOT / safe_id
    manifest_path = project_dir / "project.json"
    if safe_id != project_id or not project_dir.is_dir() or not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou ainda não possui manifesto editável")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        scenes = manifest.get("scenes", [])
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Manifesto inválido: {exc}") from exc
    if not scenes:
        raise HTTPException(status_code=400, detail="Este projeto não possui cenas editáveis")
    order = request.scene_order or list(range(len(scenes)))
    if sorted(order) != list(range(len(scenes))):
        raise HTTPException(status_code=422, detail="scene_order precisa conter cada cena exatamente uma vez")
    selected_scene_indexes = set(request.scene_indexes)
    if any(index < 0 or index >= len(scenes) for index in selected_scene_indexes) or len(selected_scene_indexes) != len(request.scene_indexes):
        raise HTTPException(status_code=422, detail="scene_indexes contém cenas inválidas ou repetidas")
    edited_scenes = [dict(scenes[index]) for index in order]
    output_format = str(manifest.get("output_format", manifest.get("render", {}).get("output_format", "vertical")))
    for index, scene in enumerate(edited_scenes):
        if index < len(request.captions):
            scene["caption"] = request.captions[index].strip()
        if index < len(request.scene_prompts):
            scene["prompt"] = request.scene_prompts[index].strip()
        if index < len(request.scene_durations):
            duration = float(request.scene_durations[index])
            if duration < 0.5 or duration > 30:
                raise HTTPException(status_code=422, detail="scene_durations precisa estar entre 0.5 e 30 segundos")
            scene["duration_seconds"] = round(duration, 2)
        else:
            scene["duration_seconds"] = float(scene.get("duration_seconds", 4.0))
    original_prompts = [str(scene.get("prompt", "")).strip() for scene in scenes]
    frame_paths: list[str] = []
    regenerated_scene_indexes: list[int] = []
    reused_scene_indexes: list[int] = []
    edit_frame_root = project_dir / "edited_frames"
    original_render_frames = manifest.get("render", {}).get("frame_paths", []) or []
    for position, (original_index, scene) in enumerate(zip(order, edited_scenes)):
        candidates = scene.get("generated_image_paths", []) or ([original_render_frames[original_index]] if original_index < len(original_render_frames) else [])
        candidate = Path(str(candidates[0])) if candidates else None
        existing_frame = str(candidate) if candidate and candidate.exists() else ""
        generated_prompt = str(scene.get("generated_prompt", original_prompts[original_index])).strip()
        scene["generated_prompt"] = generated_prompt
        prompt_changed = str(scene.get("prompt", "")).strip() != generated_prompt
        selected_for_render = not selected_scene_indexes or position in selected_scene_indexes
        if existing_frame and (not prompt_changed or not selected_for_render):
            frame_paths.append(existing_frame)
            reused_scene_indexes.append(position)
            continue
        scene_output_dir = edit_frame_root / f"scene_{position + 1:03d}"
        generated, generation_mode = _regenerate_scene_frame(manifest, scene, scene_output_dir, output_format)
        scene["generated_image_paths"] = [generated]
        scene["generated_prompt"] = str(scene.get("prompt", "")).strip()
        scene["edit_generation_mode"] = generation_mode
        frame_paths.append(generated)
        regenerated_scene_indexes.append(position)
    language = manifest.get("narration_language", "pt_BR")
    source_manifest = manifest.get("render", {}).get("audio_sources", {})
    voice_value = source_manifest.get("voice_path")
    audio_path = Path(str(voice_value)) if voice_value else project_dir / f"narration_{language}.wav"
    if not audio_path.exists():
        candidates = sorted(project_dir.glob("narration_*.wav"))
        if len(candidates) == 1:
            audio_path = candidates[0]
    if not audio_path.exists():
        raise HTTPException(status_code=409, detail="O áudio original deste projeto não está disponível para rerender")
    audio_options: dict[str, object] = {"audio_path": str(audio_path)}
    stored_mix = manifest.get("render", {}).get("audio_mix", {}) or {}
    requested_mix = request.audio_mix or stored_mix
    for key, fallback in (("voice", 1.0), ("bgm", 0.16), ("sfx", 0.28)):
        try:
            level = max(0.0, min(1.5, float(requested_mix.get(key, fallback))))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"audio_mix.{key} inválido")
        audio_options[f"{key}_volume"] = level
    bgm_value = source_manifest.get("bgm_path")
    bgm_candidate = Path(str(bgm_value)) if bgm_value else project_dir / "bgm_local_ambient.wav"
    if bgm_candidate.exists():
        audio_options["bgm_path"] = str(bgm_candidate)
    sfx_values = source_manifest.get("sfx_paths", []) or []
    if not sfx_values:
        local_sfx = project_dir / "sfx_local_whoosh.wav"
        if local_sfx.exists():
            sfx_values = [str(local_sfx)]
    audio_options["sfx_paths"] = [str(Path(str(path))) for path in sfx_values if Path(str(path)).exists()]
    transition = request.transition if request.transition in {"cut", "dissolve"} else "cut"
    motion_style = request.motion_style if request.motion_style in {"ken_burns", "static"} else "ken_burns"
    render = render_frame_video(
        frame_paths,
        audio_options,
        project_dir,
        [str(scene.get("caption", "")) for scene in edited_scenes],
        [float(scene.get("duration_seconds", 4.0)) for scene in edited_scenes],
        transition,
        output_format,
        motion_style,
    )
    render["caption_count"] = len([scene for scene in edited_scenes if str(scene.get("caption", "")).strip()])
    render["motion_style"] = motion_style
    render["frame_paths"] = frame_paths
    render["strategy"] = "image_sequence"
    render["regenerated_scene_indexes"] = regenerated_scene_indexes
    render["reused_scene_indexes"] = reused_scene_indexes
    previous_provenance = manifest.get("render", {}).get("media_provenance", {}) if isinstance(manifest.get("render"), dict) else {}
    if not isinstance(previous_provenance, dict):
        previous_provenance = {}
    regenerated_modes = [str(scene.get("edit_generation_mode", "")) for scene in edited_scenes if scene.get("edit_generation_mode")]
    render["media_provenance"] = {
        **previous_provenance,
        "images": regenerated_modes[0] if regenerated_modes else previous_provenance.get("images", "reused_existing_frames"),
        "image_provider": previous_provenance.get("image_provider", "local-editor"),
        "video": "real_mp4" if render.get("status") == "rendered" else "manifest_only",
        "video_provider": "local-ffmpeg-renderer",
    }
    manifest["scenes"] = edited_scenes
    manifest["render"] = render
    manifest["transition"] = transition
    manifest["motion_style"] = motion_style
    scope_message = "cena selecionada" if selected_scene_indexes else "alterações pendentes"
    manifest.setdefault("events", []).append({"phase": "editor", "provider": "local-editor", "status": "success", "message": f"editor localizado ({scope_message}): {len(regenerated_scene_indexes)} cena(s) regenerada(s), {len(reused_scene_indexes)} reutilizada(s)"})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"project_id": manifest.get("project_id", safe_id), "title": manifest.get("title", safe_id), "scenes": edited_scenes, "render": _decorate_render(render), "transition": transition, "motion_style": motion_style, "status": "completed"}


@app.post("/api/providers/check")
def check_providers(payload: dict[str, object]) -> dict[str, object]:
    """Validate provider, model and strategy choices before a job is queued."""
    nested_selection = payload.get("provider_selection")
    provider_selection = nested_selection if isinstance(nested_selection, dict) else payload
    model_value = payload.get("model_selection", {})
    model_selection = model_value if isinstance(model_value, dict) else {}
    video_strategy = str(payload.get("video_strategy", "auto"))
    style = str(payload.get("style", "dynamic_slideshow"))
    errors = validate_provider_selection(
        {str(key): str(value) for key, value in provider_selection.items()},
        pipeline,
        video_strategy,
        style,
        {str(key): str(value) for key, value in model_selection.items()},
    )
    return {
        "valid": not errors,
        "errors": errors,
        "selection": provider_selection,
        "model_selection": model_selection,
        "video_strategy": video_strategy,
        "style": style,
    }


@app.post("/api/uploads/sketches")
async def upload_sketches(files: list[UploadFile] = File(...)) -> dict[str, object]:
    return await _save_uploads(files, "sketches", (".png", ".jpg", ".jpeg", ".webp"))


@app.get("/api/styles/profiles")
def style_profiles() -> list[dict[str, object]]:
    return list_style_profiles()


@app.post("/api/styles/profiles")
def save_style_profile(request: StyleProfileRequest) -> dict[str, object]:
    clean = [Path(str(filename)).name for filename in request.sketch_filenames]
    fidelity = inspect_sketches(clean, "sketch_clone")
    try:
        profile = create_style_profile(request.name, clean, fidelity)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return profile


@app.get("/api/styles/profiles/{profile_id}/lora-dataset", response_model=None)
def get_lora_dataset(profile_id: str) -> dict[str, object]:
    try:
        if not load_style_profile(profile_id):
            raise HTTPException(status_code=404, detail="Perfil visual não encontrado.")
        return lora_dataset_status(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/styles/profiles/{profile_id}/lora-dataset", response_model=None)
def create_lora_dataset(profile_id: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    try:
        profile = load_style_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Perfil visual não encontrado.")
        values = payload if isinstance(payload, dict) else {}
        filenames = values.get("sketch_filenames") or profile.get("reference_files", [])
        if not isinstance(filenames, list):
            raise HTTPException(status_code=422, detail="sketch_filenames precisa ser uma lista.")
        return prepare_lora_dataset(
            profile_id,
            [str(item) for item in filenames],
            trigger_word=str(values.get("trigger_word", "studio_sketch")),
            resolution=int(values.get("resolution", 512)),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/styles/profiles/{profile_id}/lora-train", response_model=None)
def train_lora_profile(profile_id: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    try:
        if not load_style_profile(profile_id):
            raise HTTPException(status_code=404, detail="Perfil visual não encontrado.")
        values = payload if isinstance(payload, dict) else {}
        return start_lora_training(profile_id, int(values.get("steps", 40)))
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _save_uploads(files: list[UploadFile], category: str, suffixes: tuple[str, ...]) -> dict[str, object]:
    upload_root = GENERATED_ROOT.parent / "assets" / "uploads" / category
    upload_root.mkdir(parents=True, exist_ok=True)
    accepted = []
    for file in files[:10]:
        if file.filename and file.filename.lower().endswith(suffixes):
            safe_name = Path(file.filename).name
            target = upload_root / safe_name
            content = await file.read()
            if len(content) > 15 * 1024 * 1024:
                accepted.append({"filename": safe_name, "status": "rejected", "reason": "max 15 MB"})
                continue
            target.write_bytes(content)
            accepted.append({"filename": safe_name, "status": "accepted", "path": str(target)})
    return {"accepted": accepted, "count": len(accepted)}


@app.get("/api/uploads/sketches", response_model=None)
def list_uploaded_sketches() -> list[dict[str, object]]:
    """List local sketch references so a conversation attachment can be reused in Studio."""
    UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for path in sorted(UPLOADS_ROOT.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        quality = inspect_reference_quality(path.name) or {}
        records.append({
            "filename": path.name,
            "preview_url": f"/api/uploads/sketches/{path.name}",
            "quality": quality,
        })
    return records[:20]


@app.get("/api/uploads/sketches/{filename}")
def serve_uploaded_sketch(filename: str) -> FileResponse:
    """Serve only a safe, local sketch filename for the Studio preview."""
    safe_name = Path(filename).name
    path = UPLOADS_ROOT / safe_name
    if safe_name != filename or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
        raise HTTPException(status_code=404, detail="Referência de desenho não encontrada")
    return FileResponse(path)


@app.post("/api/uploads/audio")
async def upload_audio(files: list[UploadFile] = File(...)) -> dict[str, object]:
    return await _save_uploads(files, "audio", (".wav", ".mp3", ".m4a", ".ogg", ".flac"))


@app.post("/api/uploads/bgm")
async def upload_bgm(files: list[UploadFile] = File(...)) -> dict[str, object]:
    return await _save_uploads(files, "bgm", (".wav", ".mp3", ".m4a", ".ogg", ".flac"))


@app.post("/api/uploads/sfx")
async def upload_sfx(files: list[UploadFile] = File(...)) -> dict[str, object]:
    return await _save_uploads(files, "sfx", (".wav", ".mp3", ".m4a", ".ogg", ".flac"))


@app.post("/api/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> GenerateResponse:
    result = pipeline.generate(request)
    render = _decorate_render(result.render)
    return GenerateResponse(
        project_id=result.project_id, mode=request.mode, status=result.status, title=result.title, script=result.script,
        virality_score=result.virality_score, research=result.research, render=render, style_fidelity=result.style_fidelity, style_profile=result.style_profile, publish_pack=result.publish_pack or {},
        events=result.events, diagnostics=result.diagnostics, scenes=result.scenes, resolved_providers=result.resolved_providers, resolved_models=result.resolved_models,
    )


def _decorate_render(value: dict[str, object]) -> dict[str, object]:
    render = dict(value)
    if render.get("path"):
        try:
            relative = Path(str(render["path"])).resolve().relative_to(GENERATED_ROOT.resolve())
            render["url"] = f"/media/{relative.as_posix()}"
        except ValueError:
            pass
    frame_urls = []
    for frame_path in render.pop("frame_paths", []) or []:
        try:
            relative = Path(str(frame_path)).resolve().relative_to(GENERATED_ROOT.resolve())
            frame_urls.append(f"/media/{relative.as_posix()}")
        except ValueError:
            continue
    render["frame_urls"] = frame_urls
    audio_sources = render.pop("audio_sources", {}) or {}
    audio_urls: dict[str, object] = {}
    for key in ("voice_path", "bgm_path"):
        path = audio_sources.get(key) if isinstance(audio_sources, dict) else None
        if path:
            try:
                relative = Path(str(path)).resolve().relative_to(GENERATED_ROOT.resolve())
                audio_urls[key.removesuffix("_path")] = f"/media/{relative.as_posix()}"
            except ValueError:
                continue
    if isinstance(audio_sources, dict):
        sfx_urls: list[str] = []
        for path in audio_sources.get("sfx_paths", []) or []:
            try:
                relative = Path(str(path)).resolve().relative_to(GENERATED_ROOT.resolve())
                sfx_urls.append(f"/media/{relative.as_posix()}")
            except ValueError:
                continue
        if sfx_urls:
            audio_urls["sfx"] = sfx_urls
    if audio_urls:
        render["audio_urls"] = audio_urls
    return render


def _job_payload(job) -> dict[str, object]:
    payload: dict[str, object] = {"job_id": job.id, "status": job.status, "phase": job.phase, "progress": job.progress, "events": job.events, "artifacts": _decorate_artifacts(job.artifacts), "created_at": job.created_at, "cancel_requested": job.cancel_requested}
    if job.error:
        payload["error"] = job.error
    if job.result:
        render = _decorate_render(job.result.render)
        payload["result"] = {"project_id": job.result.project_id, "mode": job.request.mode, "status": job.result.status, "title": job.result.title, "script": job.result.script, "virality_score": job.result.virality_score, "target_seconds": job.request.target_seconds, "output_format": job.request.output_format, "style": job.request.style, "image_source": job.request.image_source, "research": job.result.research, "render": render, "style_fidelity": job.result.style_fidelity, "style_profile": job.result.style_profile, "publish_pack": job.result.publish_pack or {}, "events": job.result.events, "diagnostics": job.result.diagnostics, "scenes": job.result.scenes, "resolved_providers": job.result.resolved_providers, "resolved_models": job.result.resolved_models, "provider_selection": job.request.provider_selection, "model_selection": job.request.model_selection, "stage_autonomy": job.request.stage_autonomy, "video_strategy": job.request.video_strategy}
    return payload


def _decorate_artifacts(artifacts: dict[str, object]) -> dict[str, object]:
    """Expose intermediate local media through safe /media URLs while a job is running."""
    decorated = dict(artifacts or {})
    images = dict(decorated.get("images", {}) or {})
    if images.get("frame_paths"):
        frame_render = _decorate_render({"frame_paths": images.pop("frame_paths")})
        images["frame_urls"] = frame_render.get("frame_urls", [])
    if images:
        decorated["images"] = images
    return decorated


@app.post("/api/jobs")
def create_job(request: GenerateRequest) -> dict[str, object]:
    return _job_payload(job_manager.submit(request))


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, object]]:
    """Expose lightweight queue state without returning every event or artifact."""
    records: list[dict[str, object]] = []
    for job in job_manager.list():
        result = job.result
        render = _decorate_render(result.render) if result else {}
        records.append({
            "job_id": job.id,
            "project_id": result.project_id if result else None,
            "title": result.title if result else job.request.topic,
            "status": job.status,
            "phase": job.phase,
            "progress": job.progress,
            "created_at": job.created_at,
            "cancel_requested": job.cancel_requested,
            "render": {"url": render.get("url")} if render.get("url") else {},
        })
    return records


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    job = job_manager.get(job_id)
    if not job:
        return {"status": "not_found", "job_id": job_id}
    return _job_payload(job)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, object]:
    job = job_manager.cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return _job_payload(job)


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict[str, object]:
    job = job_manager.retry(job_id)
    if not job:
        raise HTTPException(status_code=409, detail="Só é possível repetir jobs falhos, bloqueados ou cancelados")
    return _job_payload(job)


@app.post("/api/jobs/{job_id}/approve")
def approve_job(job_id: str, payload: dict[str, object]) -> dict[str, object]:
    prompts = payload.get("scene_prompts", [])
    captions = payload.get("scene_captions", [])
    script = payload.get("script")
    if not isinstance(prompts, list) or not isinstance(captions, list):
        raise HTTPException(status_code=422, detail="scene_prompts e scene_captions precisam ser listas")
    job = job_manager.approve(job_id, [str(item) for item in prompts], [str(item) for item in captions], str(script) if script else None)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    if job.status == "awaiting_approval":
        raise HTTPException(status_code=409, detail="Este job não está aguardando aprovação")
    return _job_payload(job)
