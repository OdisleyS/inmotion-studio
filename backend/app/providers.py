from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable

import json
import re

from .media import audio_duration_seconds, create_reference_frames, create_storyboard_frames, ffmpeg_executable, media_enabled, mux_native_video, piper_voice_available, render_frame_video, synthesize_piper, uploaded_audio_path, uploaded_sketch_path
from .diffusion import diffusion_available, generate_diffusion_image, lora_adapter_available, lora_adapter_path
from .controlnet import controlnet_available, generate_controlnet_image


class ProviderError(RuntimeError):
    """Expected provider failure; safe for the fallback coordinator to catch."""


def _compose_scene_prompt(raw: str, prefix: str, suffixes: list[str]) -> str:
    """Compose a provider prompt idempotently when a Director review is rerun."""
    prompt = raw.strip() or "visual scene"
    if prefix.casefold() not in prompt.casefold():
        prompt = f"{prefix}; {prompt}"
    for suffix in suffixes:
        if suffix.casefold() not in prompt.casefold():
            prompt = f"{prompt}; {suffix}"
    return prompt


AGY_MODELS = [
    "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low",
    "gemini-3.7-flash-high",
    "gemini-3.7-flash-medium",
    "gemini-3.7-flash-low",
    "gemini-3.6-flash-high",
    "gemini-3.6-flash-medium",
    "gemini-3.6-flash-low",
    "gemini-3.1-pro-high",
    "gemini-3.1-pro-low",
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
]


def comfyui_url() -> str:
    return os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")


def comfyui_workflow_path() -> Path | None:
    value = os.getenv("COMFYUI_WORKFLOW", "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def comfyui_server_available() -> bool:
    try:
        with urllib.request.urlopen(f"{comfyui_url()}/system_stats", timeout=0.35) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def comfyui_available() -> bool:
    """A ComfyUI image provider is ready only when its API and workflow are configured."""
    workflow = comfyui_workflow_path()
    return bool(workflow and workflow.exists() and comfyui_server_available())


def comfyui_video_workflow_path(provider: str) -> Path | None:
    key = "COMFYUI_WAN_WORKFLOW" if provider == "wan-video" else "COMFYUI_LTX_WORKFLOW"
    value = os.getenv(key, "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def comfyui_native_video_available(provider: str) -> bool:
    workflow = comfyui_video_workflow_path(provider)
    return bool(workflow and workflow.exists() and comfyui_server_available())


def sadtalker_root() -> Path:
    value = os.getenv("SADTALKER_ROOT", "").strip()
    if value:
        path = Path(value)
        return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path
    return Path(__file__).resolve().parents[2] / "third_party" / "SadTalker"


def sadtalker_inference_path() -> Path:
    return sadtalker_root() / "inference.py"


def sadtalker_checkpoint_path() -> Path:
    value = os.getenv("SADTALKER_CHECKPOINT_DIR", "").strip()
    if value:
        path = Path(value)
        return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path
    return sadtalker_root() / "checkpoints"


def sadtalker_python() -> str:
    value = os.getenv("SADTALKER_PYTHON", "").strip()
    if value:
        return value
    return sys.executable


def sadtalker_python_available() -> bool:
    executable = sadtalker_python()
    return bool(Path(executable).exists() if Path(executable).is_absolute() else shutil.which(executable))


def sadtalker_available() -> bool:
    """SadTalker is ready only when its entrypoint and checkpoint bundle are local."""
    return bool(sadtalker_inference_path().exists() and sadtalker_checkpoint_path().exists() and sadtalker_python_available())


def codex_command_available() -> bool:
    return shutil.which(os.getenv("CODEX_COMMAND", "codex")) is not None


def codex_bridge_available() -> bool:
    return codex_command_available() and os.getenv("ENABLE_CODEX_BRIDGE", "0") == "1"


def codex_model_name() -> str:
    return os.getenv("CODEX_MODEL", "gpt-5.6-luna")


def get_model_catalog() -> dict[str, list[dict[str, Any]]]:
    """Models exposed to the UI, separate from provider adapters."""
    agy_ready = shutil.which(os.getenv("AGY_COMMAND", "agy")) is not None and os.getenv("ENABLE_AGY_BRIDGE", "0") == "1"
    codex_ready = codex_bridge_available()
    return {
        "script": [
            {"name": "auto", "label": "Automático", "provider": "auto", "status": "ready", "capabilities": ["text"]},
            *[{"name": model, "label": model, "provider": "antigravity-cli", "status": "ready" if agy_ready else "unavailable", "capabilities": ["text"]} for model in AGY_MODELS],
            # The UI keeps a stable provider-specific id, while the raw model
            # name is also accepted by the API/config layer.  This matters for
            # callers that read CODEX_MODEL directly from health/runtime-config.
            {"name": f"codex-{codex_model_name()}", "aliases": [codex_model_name()], "label": f"Codex · {codex_model_name()}", "provider": "codex-cli", "status": "ready" if codex_ready else "unavailable", "capabilities": ["text"]},
            {"name": "local-template-text", "label": "Template local", "provider": "local-template-text", "status": "ready", "capabilities": ["text"]},
        ],
        "image": [
            {"name": "auto", "label": "Automático", "provider": "auto", "status": "ready", "capabilities": ["image_generation", "image_sequence"]},
            {"name": "sd-turbo-local", "label": "SD-Turbo local · RTX 3050", "provider": "local-sd-turbo", "status": "ready" if diffusion_available() else "unavailable", "capabilities": ["image_generation", "image_sequence"]},
            {"name": "controlnet-lineart-local", "label": "ControlNet Lineart · local", "provider": "local-controlnet-lineart", "status": "ready" if controlnet_available() else "unavailable", "capabilities": ["image_generation", "image_sequence", "style_control", "geometry_control"]},
            {"name": "antigravity-visual-planner", "label": "Antigravity · direção visual", "provider": "antigravity-visual-planner", "status": "ready" if agy_ready else "unavailable", "capabilities": ["image_generation", "scene_planning", "image_sequence"]},
            {"name": "local-storyboard", "label": "Gerador local de storyboard", "provider": "local-storyboard", "status": "ready", "capabilities": ["image_generation", "image_sequence"]},
            {"name": "comfyui-controlnet-lora", "label": "ComfyUI + ControlNet + LoRA", "provider": "comfyui-controlnet-lora", "status": "ready" if comfyui_available() else "unavailable", "capabilities": ["image_generation", "style_control"]},
        ],
        "audio": [
            {"name": "auto", "label": "Automático", "provider": "auto", "status": "ready", "capabilities": ["audio_manifest"]},
            {"name": "manual-audio-file", "label": "Arquivo manual", "provider": "manual-audio-upload", "status": "ready", "capabilities": ["audio"]},
            {"name": "piper-pt_BR-faber-medium", "label": "Piper · Português Faber", "provider": "piper-local", "status": "ready" if piper_voice_available("pt_BR") else "ready-manifest", "capabilities": ["audio"] if piper_voice_available("pt_BR") else ["audio_manifest"]},
            {"name": "piper-en_US-amy-medium", "label": "Piper · English Amy", "provider": "piper-local", "status": "ready" if piper_voice_available("en_US") else "ready-manifest", "capabilities": ["audio"] if piper_voice_available("en_US") else ["audio_manifest"]},
            {"name": "piper-xtts", "label": "Piper / XTTS", "provider": "piper-xtts", "status": "planned", "capabilities": ["audio", "voice_clone"]},
        ],
        "video": [
            {"name": "auto", "label": "Automático por capability", "provider": "auto", "status": "ready", "capabilities": ["video_render", "image_sequence"]},
            {"name": "local-ffmpeg-renderer", "label": "FFmpeg local", "provider": "local-ffmpeg-renderer", "status": "ready" if ffmpeg_executable() else "ready-manifest", "capabilities": ["video_render", "image_sequence"]},
            {"name": "wan-video", "label": "Wan 2.1 · ComfyUI", "provider": "wan-video", "status": "ready" if comfyui_native_video_available("wan-video") else "planned", "capabilities": ["video_generation"]},
            {"name": "ltx-video", "label": "LTX-Video · ComfyUI", "provider": "ltx-video", "status": "ready" if comfyui_native_video_available("ltx-video") else "planned", "capabilities": ["video_generation"]},
            {"name": "sadtalker-lipsync", "label": "SadTalker · avatar lip-sync", "provider": "sadtalker-lipsync", "status": "ready" if sadtalker_available() else "planned", "capabilities": ["video_generation", "lip_sync"]},
        ],
    }


def get_provider_catalog() -> dict[str, list[dict[str, Any]]]:
    """Capabilities exposed to the UI so users can choose providers per phase."""
    agy_ready = shutil.which(os.getenv("AGY_COMMAND", "agy")) is not None and os.getenv("ENABLE_AGY_BRIDGE", "0") == "1"
    codex_ready = codex_bridge_available()
    piper_ready = piper_voice_available("pt_BR")
    video_ready = ffmpeg_executable() is not None
    return {
        "script": [
            {"name": "auto", "label": "Automático (recomendado)", "status": "ready", "capabilities": ["text"]},
            {"name": "antigravity-cli", "label": "Antigravity CLI / Gemini", "status": "ready" if agy_ready else "unavailable", "capabilities": ["text"]},
            {"name": "codex-cli", "label": "Codex CLI / OpenAI", "status": "ready" if codex_ready else "unavailable", "capabilities": ["text"]},
            {"name": "local-template-text", "label": "Template local", "status": "ready", "capabilities": ["text"]},
        ],
        "image": [
            {"name": "auto", "label": "Automático (recomendado)", "status": "ready", "capabilities": ["image_generation", "image_sequence"]},
            {"name": "local-sd-turbo", "label": "SD-Turbo local · GPU", "status": "ready" if diffusion_available() else "unavailable", "capabilities": ["image_generation", "image_sequence"]},
            {"name": "local-controlnet-lineart", "label": "ControlNet Lineart · local", "status": "ready" if controlnet_available() else "unavailable", "capabilities": ["image_generation", "image_sequence", "style_control", "geometry_control"]},
            {"name": "antigravity-visual-planner", "label": "Antigravity · direção visual", "status": "ready" if agy_ready else "unavailable", "capabilities": ["image_generation", "scene_planning", "image_sequence"]},
            {"name": "local-storyboard", "label": "Storyboard local", "status": "ready", "capabilities": ["image_generation", "image_sequence"]},
            {"name": "manual-image-reference", "label": "Referência manual enviada", "status": "ready", "capabilities": ["image_sequence", "manual_input"]},
            {"name": "comfyui-controlnet-lora", "label": "ComfyUI + ControlNet + LoRA", "status": "ready" if comfyui_available() else "unavailable", "capabilities": ["image_generation", "image_sequence", "style_control", "geometry_control"]},
        ],
        "audio": [
            {"name": "auto", "label": "Automático (recomendado)", "status": "ready", "capabilities": ["audio", "audio_manifest"]},
            {"name": "manual-audio-upload", "label": "Arquivo manual enviado", "status": "ready", "capabilities": ["audio"]},
            {"name": "piper-local", "label": "Piper local (pt-BR / en-US)", "status": "ready" if piper_ready else "ready-manifest", "capabilities": ["audio"] if piper_ready else ["audio_manifest"]},
            {"name": "piper-xtts", "label": "Piper / XTTS", "status": "planned", "capabilities": ["audio", "voice_clone"]},
        ],
        "video": [
            {"name": "auto", "label": "Automático por estilo", "status": "ready", "capabilities": ["video_render", "image_sequence"]},
            {"name": "local-ffmpeg-renderer", "label": "FFmpeg local", "status": "ready" if video_ready else "ready-manifest", "capabilities": ["video_render", "image_sequence"]},
            {"name": "wan-video", "label": "Wan 2.1 · ComfyUI", "status": "ready" if comfyui_native_video_available("wan-video") else "planned", "capabilities": ["video_generation"]},
            {"name": "ltx-video", "label": "LTX-Video · ComfyUI", "status": "ready" if comfyui_native_video_available("ltx-video") else "planned", "capabilities": ["video_generation"]},
            {"name": "sadtalker-lipsync", "label": "SadTalker · avatar lip-sync", "status": "ready" if sadtalker_available() else "planned", "capabilities": ["video_generation", "lip_sync"]},
        ],
    }


@dataclass
class ProviderResult:
    provider: str
    value: Any


class FallbackChain:
    """Try providers in order, bounded by a per-phase retry budget."""

    def __init__(self, phase: str, providers: list[tuple[str, Callable[[], Any]]], max_attempts: int = 3):
        self.phase = phase
        self.providers = providers
        self.max_attempts = max_attempts
        self.events: list[dict[str, str]] = []

    def run(self) -> ProviderResult:
        attempts = 0
        failures: list[str] = []
        for name, operation in self.providers:
            if attempts >= self.max_attempts:
                break
            attempts += 1
            try:
                value = operation()
                status = "success" if attempts == 1 else "fallback"
                self.events.append({"phase": self.phase, "provider": name, "status": status, "message": "completed"})
                return ProviderResult(name, value)
            except ProviderError as exc:
                failures.append(f"{name}: {exc}")
                self.events.append({"phase": self.phase, "provider": name, "status": "failed", "message": str(exc)})
        raise ProviderError(f"{self.phase} blocked after {attempts} attempts; " + " | ".join(failures))


class LocalTextProvider:
    name = "local-template-text"

    def create(self, topic: str, style: str, custom_script: str | None, model: str | None = None) -> dict[str, Any]:
        if custom_script and custom_script.strip():
            script = custom_script.strip()
        else:
            script = (
                f"Você sabia? {topic}. "
                "Em poucos segundos, vamos separar o fato do mito. "
                "Fique até o final para descobrir o detalhe que quase todo mundo ignora."
            )
        title = topic.strip().capitalize()
        return {"title": title, "script": script, "hook": script.split(".")[0] + "."}

    def rewrite_hook(self, topic: str, script: str) -> dict[str, Any]:
        """Local recovery writer used when the retention heuristic is too low."""
        sentences = [part.strip() for part in re.split(r"[.!?]", script) if part.strip()]
        body = " ".join(sentences[1:] or sentences)
        rewritten = f"Você sabia? {topic.strip()} guarda um detalhe que quase ninguém percebe. "
        rewritten += body or "Fique até o final para descobrir por que essa história é surpreendente."
        if "até o final" not in rewritten.lower():
            rewritten += " Fique até o final para descobrir a virada."
        return {"title": topic.strip().capitalize(), "script": rewritten, "hook": rewritten.split(".")[0] + "."}


def _agy_timeout_seconds() -> int:
    """Allow a slower local Agy session without hard-coding a long timeout."""
    try:
        return max(30, min(300, int(os.getenv("AGY_TIMEOUT_SECONDS", "90"))))
    except ValueError:
        return 90


def _agy_permission_args() -> list[str]:
    """Allow the authenticated Agy bridge to run from a headless backend."""
    value = os.getenv("AGY_SKIP_PERMISSIONS", "1").strip().lower()
    return ["--dangerously-skip-permissions"] if value in {"1", "true", "yes", "on"} else []


def _codex_timeout_seconds() -> int:
    try:
        return max(30, min(300, int(os.getenv("CODEX_TIMEOUT_SECONDS", "120"))))
    except ValueError:
        return 120


class AntigravityTextProvider:
    """Bridge to the user's already-authenticated Antigravity CLI session."""

    name = "antigravity-cli"

    def __init__(self) -> None:
        self.command = os.getenv("AGY_COMMAND", "agy")

    @property
    def available(self) -> bool:
        return shutil.which(self.command) is not None and os.getenv("ENABLE_AGY_BRIDGE", "0") == "1"

    def create(self, topic: str, style: str, custom_script: str | None, model: str | None = None, research: dict[str, Any] | None = None, target_seconds: int = 35) -> dict[str, Any]:
        research_context = ""
        if research and research.get("sources"):
            signals = []
            for source in research["sources"][:3]:
                title = str(source.get("title", "")).strip()
                snippet = str(source.get("snippet", "")).strip()[:180]
                if title:
                    signals.append(f"{title}: {snippet}" if snippet else title)
            if signals:
                research_context = " Sinais recentes (use como contexto, sem inventar fatos): " + " | ".join(signals)
        prompt = (
            "Você é o roteirista do In-House Video Studio. "
            "Crie um roteiro curto em português brasileiro para Shorts/TikTok. "
            "Responda somente com a locução falada, em texto natural, sem markdown. "
            "Não use horários, Visual:, Texto na tela:, Voz:, Locução:, Slide, Cena ou colchetes. "
            f"Tema: {topic}. Estilo: {style}. Duração alvo aproximada: {target_seconds} segundos. "
            + research_context
            + (f"Use este roteiro como base e melhore o hook: {custom_script}" if custom_script else "")
        )
        timeout_seconds = _agy_timeout_seconds()
        try:
            completed = subprocess.run(
                [self.command] + _agy_permission_args() + ["--output-format", "text", "--print-timeout", f"{max(30, timeout_seconds - 10)}s"] + (["--model", model] if model and model != "auto" else []) + [f"--print={prompt}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProviderError(f"Antigravity CLI indisponível: {exc}") from exc
        if completed.returncode != 0 or not completed.stdout.strip():
            detail = completed.stderr.strip() or f"exit code {completed.returncode}"
            raise ProviderError(f"Antigravity CLI falhou: {detail}")
        script = completed.stdout.strip().encode("utf-8", "replace").decode("utf-8")
        script = "".join(char for char in script if not 0xD800 <= ord(char) <= 0xDFFF)
        return {"title": topic.strip().capitalize(), "script": script, "hook": script.split(".")[0] + "."}


class CodexTextProvider:
    """Optional bridge to the locally authenticated Codex CLI, restricted to read-only text generation."""

    name = "codex-cli"

    def __init__(self) -> None:
        self.command = os.getenv("CODEX_COMMAND", "codex")

    @property
    def available(self) -> bool:
        return codex_bridge_available()

    def create(self, topic: str, style: str, custom_script: str | None, model: str | None = None, research: dict[str, Any] | None = None, target_seconds: int = 35) -> dict[str, Any]:
        research_context = ""
        if research and research.get("sources"):
            signals = []
            for source in research["sources"][:3]:
                title = str(source.get("title", "")).strip()
                snippet = str(source.get("snippet", "")).strip()[:180]
                if title:
                    signals.append(f"{title}: {snippet}" if snippet else title)
            if signals:
                research_context = " Sinais recentes (use como contexto, sem inventar fatos): " + " | ".join(signals)
        prompt = (
            "Você é o roteirista do In-House Video Studio. "
            "Crie um roteiro curto em português brasileiro para Shorts/TikTok. "
            "Responda somente com a locução falada, em texto natural, sem markdown, sem comandos e sem explicar o processo. "
            "Não use horários, Visual:, Texto na tela:, Voz:, Locução:, Slide, Cena ou colchetes. "
            f"Tema: {topic}. Estilo: {style}. Duração alvo aproximada: {target_seconds} segundos. "
            + research_context
            + (f"Use este roteiro como base e melhore o hook: {custom_script}" if custom_script else "")
        )
        selected_model = (model or "").removeprefix("codex-")
        timeout_seconds = _codex_timeout_seconds()
        args = [self.command, "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never", "--json"]
        if selected_model and selected_model != "auto":
            args.extend(["--model", selected_model])
        args.append(prompt)
        try:
            completed = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProviderError(f"Codex CLI indisponível: {exc}") from exc
        if completed.returncode != 0:
            raise ProviderError(completed.stderr.strip() or f"exit code {completed.returncode}")
        response_text = ""
        for line in reversed(completed.stdout.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item", {}) if isinstance(event, dict) else {}
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                response_text = str(item.get("text", "")).strip()
                if response_text:
                    break
        if not response_text:
            raise ProviderError("Codex CLI não retornou uma mensagem de roteiro")
        return {"title": topic.strip().capitalize(), "script": response_text, "hook": response_text.split(".")[0] + "."}


class AntigravityVisualProvider:
    """Uses the authenticated CLI to turn a concept into scene directions, then renders real local PNGs."""

    name = "antigravity-visual-planner"

    def __init__(self) -> None:
        self.command = os.getenv("AGY_COMMAND", "agy")

    @property
    def available(self) -> bool:
        return shutil.which(self.command) is not None and os.getenv("ENABLE_AGY_BRIDGE", "0") == "1"

    def create(self, topic: str, style: str, sketch_filenames: list[str], output_dir=None, model: str | None = None, scene_prompts: list[str] | None = None, output_format: str = "vertical") -> dict[str, Any]:
        if not self.available:
            raise ProviderError("Antigravity visual planner indisponível")
        prompt = (
            "Você é o diretor visual de um gerador de vídeos. Retorne somente JSON válido, sem markdown, "
            "com uma lista de exatamente 3 objetos. Cada objeto deve ter as chaves prompt, subject, action e caption. "
            f"Descreva imagens em composição {output_format}, visualmente fortes, coerentes entre si, sem texto longo. "
            f"Tema: {topic}. Estilo: {style}. Referências de desenho enviadas: {len(sketch_filenames)}."
        )
        if scene_prompts:
            prompt += " Preserve/refine estas direções de cena, nesta ordem: " + " | ".join(str(item).strip() for item in scene_prompts[:3] if str(item).strip())
        timeout_seconds = _agy_timeout_seconds()
        try:
            completed = subprocess.run(
                [self.command] + _agy_permission_args() + ["--output-format", "text", "--print-timeout", f"{max(30, timeout_seconds - 10)}s"] + (["--model", model] if model and model != "auto" else []) + [f"--print={prompt}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProviderError(f"Antigravity visual planner indisponível: {exc}") from exc
        if completed.returncode != 0 or not completed.stdout.strip():
            raise ProviderError(completed.stderr.strip() or f"exit code {completed.returncode}")
        raw = completed.stdout.encode("utf-8", "replace").decode("utf-8")
        raw = "".join(char for char in raw if not 0xD800 <= ord(char) <= 0xDFFF)
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ProviderError("Antigravity não retornou uma lista JSON de cenas")
        try:
            scenes = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ProviderError(f"JSON visual inválido: {exc.msg}") from exc
        if not isinstance(scenes, list) or len(scenes) < 3:
            raise ProviderError("Antigravity retornou menos de 3 cenas visuais")
        frames = [{"index": index, "prompt": str(scene.get("prompt", "Cena visual")), "subject": str(scene.get("subject", "")), "action": str(scene.get("action", "")), "caption": str(scene.get("caption", "")), "sketch_inputs": sketch_filenames} for index, scene in enumerate(scenes[:3], start=1)]
        result = {"style": style, "frames": frames, "source": self.name, "generation_mode": "ai_scene_plan_plus_local_render"}
        if output_dir is not None and media_enabled():
            result["frame_paths"] = create_storyboard_frames(topic, style, frames, output_dir, output_format)
        return result


class ComfyUIImageProvider:
    """Run a user-supplied ComfyUI API workflow without coupling the studio to its UI."""

    name = "comfyui-controlnet-lora"

    @property
    def available(self) -> bool:
        return comfyui_available()

    def _submit(self, workflow: dict[str, Any], seed: int, prompt_text: str) -> str:
        graph = deepcopy(workflow)
        positive_written = False
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            class_type = str(node.get("class_type", ""))
            if class_type == "CLIPTextEncode" and "text" in inputs:
                title = str(node.get("_meta", {}).get("title", "")).lower()
                if "negative" not in title and not positive_written:
                    inputs["text"] = prompt_text
                    positive_written = True
            if class_type == "KSampler" and "seed" in inputs:
                inputs["seed"] = seed
        payload = json.dumps({"prompt": graph, "client_id": str(uuid.uuid4())}).encode("utf-8")
        request = urllib.request.Request(f"{comfyui_url()}/prompt", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ProviderError(f"ComfyUI não aceitou o workflow: {exc}") from exc
        prompt_id = str(body.get("prompt_id", ""))
        if not prompt_id:
            raise ProviderError(f"ComfyUI retornou uma resposta sem prompt_id: {body}")
        return prompt_id

    def _wait_for_image(self, prompt_id: str, output_path: Path) -> str:
        deadline = time.monotonic() + float(os.getenv("COMFYUI_TIMEOUT_SECONDS", "180"))
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{comfyui_url()}/history/{urllib.parse.quote(prompt_id)}", timeout=5) as response:
                    history = json.loads(response.read().decode("utf-8"))
                record = history.get(prompt_id, {})
                for node_output in record.get("outputs", {}).values():
                    for image in node_output.get("images", []) or []:
                        query = urllib.parse.urlencode({"filename": image.get("filename", ""), "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
                        with urllib.request.urlopen(f"{comfyui_url()}/view?{query}", timeout=30) as image_response:
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_bytes(image_response.read())
                        if output_path.exists() and output_path.stat().st_size > 0:
                            return str(output_path)
                if record.get("status", {}).get("status_str") == "error":
                    raise ProviderError("ComfyUI marcou o workflow como erro")
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                raise ProviderError(f"Falha ao consultar a imagem do ComfyUI: {exc}") from exc
            time.sleep(0.35)
        raise ProviderError("ComfyUI excedeu o tempo limite aguardando a imagem")

    def create(self, topic: str, style: str, sketch_filenames: list[str], output_dir=None, model: str | None = None, scene_prompts: list[str] | None = None, artifact_callback: Callable[[dict[str, Any]], None] | None = None, output_format: str = "vertical") -> dict[str, Any]:
        workflow_path = comfyui_workflow_path()
        if not self.available or workflow_path is None:
            raise ProviderError("ComfyUI indisponível; configure COMFYUI_URL e COMFYUI_WORKFLOW")
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Workflow ComfyUI inválido: {exc}") from exc
        prompts = scene_prompts or []
        frames = [{"index": index, "prompt": prompts[index - 1] if len(prompts) >= index else topic, "subject": topic, "action": "ControlNet/LoRA visual generation", "caption": "", "sketch_inputs": sketch_filenames} for index in range(1, 4)]
        result = {"style": style, "frames": frames, "source": self.name, "generation_mode": "comfyui_workflow_controlnet_lora"}
        if output_dir is None or not media_enabled():
            return result
        paths: list[str] = []
        for index, frame in enumerate(frames, start=1):
            prompt_marker = frame["prompt"]
            prompt_id = self._submit(workflow, index * 101, f"{prompt_marker}; {output_format} composition; {style}; coherent character design; no text")
            image_path = self._wait_for_image(prompt_id, Path(output_dir) / f"comfyui_image_{index:03d}.png")
            frame["generated_image_paths"] = [image_path]
            paths.append(image_path)
            if artifact_callback:
                artifact_callback({"frames": [dict(item) for item in frames[:index]], "frame_paths": paths, "provider": self.name, "completed": index, "total": len(frames)})
        result["generated_image_paths"] = paths
        result["frame_paths"] = create_storyboard_frames(topic, style, frames, output_dir, output_format)
        return result


class ComfyUINativeVideoProvider:
    """Run a Wan/LTX video workflow through ComfyUI's API and mux local narration."""

    def __init__(self, provider_name: str) -> None:
        self.name = provider_name

    @property
    def available(self) -> bool:
        return comfyui_native_video_available(self.name)

    def _submit(self, workflow: dict[str, Any], prompt_text: str, seed: int) -> str:
        graph = deepcopy(workflow)
        positive_written = False
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            class_type = str(node.get("class_type", ""))
            if class_type == "CLIPTextEncode" and "text" in inputs:
                title = str(node.get("_meta", {}).get("title", "")).lower()
                if "negative" not in title and not positive_written:
                    inputs["text"] = prompt_text
                    positive_written = True
            if class_type in {"KSampler", "KSamplerAdvanced"} and "seed" in inputs:
                inputs["seed"] = seed
        payload = json.dumps({"prompt": graph, "client_id": str(uuid.uuid4())}).encode("utf-8")
        request = urllib.request.Request(f"{comfyui_url()}/prompt", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ProviderError(f"ComfyUI não aceitou o workflow de vídeo: {exc}") from exc
        prompt_id = str(body.get("prompt_id", ""))
        if not prompt_id:
            raise ProviderError(f"ComfyUI retornou uma resposta sem prompt_id: {body}")
        return prompt_id

    def _wait_for_video(self, prompt_id: str, output_dir: Path) -> str:
        deadline = time.monotonic() + float(os.getenv("COMFYUI_VIDEO_TIMEOUT_SECONDS", "600"))
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{comfyui_url()}/history/{urllib.parse.quote(prompt_id)}", timeout=8) as response:
                    history = json.loads(response.read().decode("utf-8"))
                record = history.get(prompt_id, {})
                for node_output in record.get("outputs", {}).values():
                    for media_key in ("videos", "gifs"):
                        for media in node_output.get(media_key, []) or []:
                            filename = str(media.get("filename", ""))
                            if not filename:
                                continue
                            query = urllib.parse.urlencode({"filename": filename, "subfolder": media.get("subfolder", ""), "type": media.get("type", "output")})
                            suffix = Path(filename).suffix.lower() or ".mp4"
                            downloaded = output_dir / f"native_source{suffix}"
                            with urllib.request.urlopen(f"{comfyui_url()}/view?{query}", timeout=60) as media_response:
                                output_dir.mkdir(parents=True, exist_ok=True)
                                downloaded.write_bytes(media_response.read())
                            if downloaded.exists() and downloaded.stat().st_size > 0:
                                if downloaded.suffix.lower() == ".mp4":
                                    return str(downloaded)
                                ffmpeg = ffmpeg_executable()
                                if ffmpeg:
                                    converted = output_dir / "native_source.mp4"
                                    completed = subprocess.run([ffmpeg, "-y", "-i", str(downloaded), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(converted)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
                                    if completed.returncode == 0 and converted.exists():
                                        return str(converted)
                if record.get("status", {}).get("status_str") == "error":
                    raise ProviderError(f"ComfyUI marcou o workflow {self.name} como erro")
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                raise ProviderError(f"Falha ao consultar o vídeo do ComfyUI: {exc}") from exc
            time.sleep(0.5)
        raise ProviderError(f"ComfyUI excedeu o tempo limite aguardando {self.name}")

    def create(self, storyboard: dict[str, Any], audio: dict[str, Any], captions: list[str], output_dir=None, scene_durations: list[float] | None = None, transition: str = "cut", output_format: str = "vertical") -> dict[str, Any]:
        workflow_path = comfyui_video_workflow_path(self.name)
        if not self.available or workflow_path is None:
            raise ProviderError(f"{self.name} indisponível; configure o workflow ComfyUI correspondente")
        if output_dir is None or not media_enabled():
            return {"format": "mp4", "status": "manifest", "strategy": "native_video", "native_engine": self.name, "frames": 0}
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Workflow {self.name} inválido: {exc}") from exc
        prompts = [str(frame.get("prompt", "")) for frame in storyboard.get("frames", []) if str(frame.get("prompt", "")).strip()]
        prompt_text = "; ".join(prompts[:6]) or "coherent short animation"
        prompt_id = self._submit(workflow, f"{prompt_text}; {output_format} composition; {self.name}; preserve character consistency; no text", 701)
        native_source = self._wait_for_video(prompt_id, Path(output_dir))
        result = mux_native_video(native_source, audio, Path(output_dir), output_format)
        result["native_engine"] = self.name
        result["strategy"] = "native_video"
        return result


class SadTalkerVideoProvider:
    """Run the optional local SadTalker CLI against the first generated portrait."""

    name = "sadtalker-lipsync"

    @property
    def available(self) -> bool:
        return sadtalker_available()

    def _source_image(self, storyboard: dict[str, Any]) -> Path | None:
        candidates: list[str] = []
        for frame in storyboard.get("frames", []) or []:
            if not isinstance(frame, dict):
                continue
            candidates.extend(str(path) for path in frame.get("generated_image_paths", []) or [])
            if frame.get("image_path"):
                candidates.append(str(frame["image_path"]))
        candidates.extend(str(path) for path in storyboard.get("frame_paths", []) or [])
        for candidate in candidates:
            path = Path(candidate)
            if path.exists() and path.is_file():
                return path
        return None

    def _result_video(self, result_dir: Path) -> Path | None:
        videos = [path for path in result_dir.rglob("*.mp4") if path.is_file() and path.stat().st_size > 0]
        return max(videos, key=lambda path: path.stat().st_mtime) if videos else None

    def create(self, storyboard: dict[str, Any], audio: dict[str, Any], captions: list[str], output_dir=None, scene_durations: list[float] | None = None, transition: str = "cut", output_format: str = "vertical") -> dict[str, Any]:
        if not self.available:
            raise ProviderError("SadTalker indisponível; configure SADTALKER_ROOT e os checkpoints locais")
        source_image = self._source_image(storyboard)
        audio_path = Path(str(audio.get("audio_path", ""))) if audio.get("audio_path") else None
        if source_image is None:
            raise ProviderError("SadTalker precisa de pelo menos um frame/imagem de avatar gerado")
        if audio_path is None or not audio_path.exists():
            raise ProviderError("SadTalker precisa de uma narração WAV real")
        if output_dir is None or not media_enabled():
            return {"format": "mp4", "status": "manifest", "strategy": "avatar_lipsync", "native_engine": self.name, "frames": 0}

        result_dir = Path(output_dir) / "sadtalker"
        result_dir.mkdir(parents=True, exist_ok=True)
        command = [
            sadtalker_python(), str(sadtalker_inference_path()),
            "--driven_audio", str(audio_path),
            "--source_image", str(source_image),
            "--result_dir", str(result_dir),
            "--still",
            "--checkpoint_dir", str(sadtalker_checkpoint_path()),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "SadTalker retornou erro")[-1400:]
            raise ProviderError(f"SadTalker falhou: {detail}")
        native_video = self._result_video(result_dir)
        if native_video is None:
            raise ProviderError("SadTalker terminou sem gerar um MP4")
        result = mux_native_video(native_video, audio, Path(output_dir), output_format)
        result["native_engine"] = self.name
        result["strategy"] = "avatar_lipsync"
        result["source_image"] = str(source_image)
        return result


class LocalImageProvider:
    name = "local-storyboard"

    def create(self, topic: str, style: str, sketch_filenames: list[str], output_dir=None, scene_prompts: list[str] | None = None, output_format: str = "vertical") -> dict[str, Any]:
        prompts = scene_prompts or []
        result = {
            "style": style,
            "frames": [
                {"index": 1, "prompt": prompts[0] if len(prompts) > 0 else f"Hook visual: {topic}", "sketch_inputs": sketch_filenames},
                {"index": 2, "prompt": prompts[1] if len(prompts) > 1 else "Close-up with clear visual contrast", "sketch_inputs": sketch_filenames},
                {"index": 3, "prompt": prompts[2] if len(prompts) > 2 else "Final reveal with bold caption", "sketch_inputs": sketch_filenames},
            ],
        }
        if output_dir is not None and media_enabled():
            result["frame_paths"] = create_storyboard_frames(topic, style, result["frames"], output_dir, output_format)
        return result


class ManualImageProvider:
    """Use uploaded drawings as the actual visual source for manual mode."""

    name = "manual-image-reference"

    def create(self, topic: str, style: str, sketch_filenames: list[str], output_dir=None, scene_prompts: list[str] | None = None, output_format: str = "vertical") -> dict[str, Any]:
        references = [Path(filename).name for filename in sketch_filenames if uploaded_sketch_path(filename)]
        if not references:
            raise ProviderError("A etapa manual de imagens exige pelo menos uma referência enviada")
        prompts = scene_prompts or []
        frames = [
            {
                "index": index,
                "prompt": prompts[index - 1] if len(prompts) >= index else f"Referência manual para a cena {index}: {topic}",
                "subject": topic,
                "action": "composição baseada no desenho enviado",
                "caption": "",
                "sketch_inputs": references,
                "manual_reference": references[(index - 1) % len(references)],
            }
            for index in range(1, 4)
        ]
        result = {"style": style, "frames": frames, "source": self.name, "generation_mode": "manual_uploaded_reference", "reference_strategy": "scene_cycle"}
        if output_dir is not None and media_enabled():
            paths = create_reference_frames(topic, style, frames, Path(output_dir), output_format)
            for frame, path in zip(frames, paths):
                frame["generated_image_paths"] = [path]
            result["generated_image_paths"] = paths
            result["frame_paths"] = paths
            result["reference_usage"] = [frame["manual_reference"] for frame in frames]
        return result


class LocalDiffusionImageProvider:
    """Generates real images locally with the downloaded SD-Turbo checkpoint."""

    name = "local-sd-turbo"

    @property
    def available(self) -> bool:
        return diffusion_available()

    def create(self, topic: str, style: str, sketch_filenames: list[str], output_dir=None, model: str | None = None, scene_prompts: list[str] | None = None, artifact_callback: Callable[[dict[str, Any]], None] | None = None, output_format: str = "vertical") -> dict[str, Any]:
        if not self.available:
            raise ProviderError("SD-Turbo local não está habilitado ou o modelo não foi baixado")
        style_desc = {
            "sketch_clone": "2D hand-drawn animation, clean expressive line art, consistent character design",
            "couples_fruits_2d": "stylized 2D cartoon, colorful fruit characters, expressive faces",
            "dynamic_slideshow": "high contrast editorial illustration, dynamic composition",
        }.get(style, "polished illustrated short-video frame")
        prompts = scene_prompts or []
        frames = [
            {
                "index": index,
                "prompt": _compose_scene_prompt(
                    prompts[index - 1] if len(prompts) >= index else topic,
                    style_desc,
                    [f"scene {index} of 3", "coherent visual story", "no written words", f"{output_format} composition"],
                ),
                "subject": topic,
                "action": "dynamic visual storytelling",
                "caption": "",
                "sketch_inputs": sketch_filenames,
            }
            for index in range(1, 4)
        ]
        reference_path = uploaded_sketch_path(sketch_filenames[0]) if sketch_filenames else None
        generation_mode = "sd_turbo_local_img2img" if reference_path else "sd_turbo_local_text_to_image"
        lora_path = lora_adapter_path() if lora_adapter_available() else None
        if lora_path:
            generation_mode += "+lora"
        reference_fallback = False
        result = {
            "style": style,
            "frames": frames,
            "source": self.name,
            "generation_mode": generation_mode,
            "style_adapter": str(lora_path) if lora_path else None,
        }
        if output_dir is not None and media_enabled():
            paths = []
            try:
                for index, frame in enumerate(frames, start=1):
                    try:
                        paths.append(generate_diffusion_image(frame["prompt"], output_dir / f"ai_image_{index:03d}.png", seed=index * 101, reference_path=reference_path))
                    except Exception:
                        if reference_path is None:
                            raise
                        # A checkpoint may expose text-to-image only. Keep production alive
                        # and preserve the uploaded line art in the composition fallback.
                        reference_fallback = True
                        paths.append(generate_diffusion_image(frame["prompt"], output_dir / f"ai_image_{index:03d}.png", seed=index * 101))
                    frame["generated_image_paths"] = [paths[-1]]
                    live_paths = create_storyboard_frames(topic, style, frames[:index], output_dir, output_format)
                    if artifact_callback:
                        artifact_callback({"frames": [dict(item) for item in frames[:index]], "frame_paths": live_paths, "provider": self.name, "completed": index, "total": len(frames)})
            except Exception as exc:
                raise ProviderError(f"SD-Turbo local falhou: {exc}") from exc
            result["generated_image_paths"] = paths
            result["frame_paths"] = create_storyboard_frames(topic, style, frames, output_dir, output_format)
            if reference_fallback:
                result["generation_mode"] = "sd_turbo_local_text_to_image_with_reference_overlay"
        return result


class LocalControlNetImageProvider:
    """Preserve a supplied drawing's line geometry with a local ControlNet."""

    name = "local-controlnet-lineart"

    @property
    def available(self) -> bool:
        return controlnet_available()

    def create(self, topic: str, style: str, sketch_filenames: list[str], output_dir=None, model: str | None = None, scene_prompts: list[str] | None = None, artifact_callback: Callable[[dict[str, Any]], None] | None = None, output_format: str = "vertical") -> dict[str, Any]:
        if not self.available:
            raise ProviderError("ControlNet Lineart local ainda não está instalado")
        reference_paths = [
            path
            for filename in sketch_filenames
            if (path := uploaded_sketch_path(filename)) is not None
        ]
        if not reference_paths:
            raise ProviderError("ControlNet Lineart exige pelo menos uma imagem de referência")
        prompts = scene_prompts or []
        frames = [
            {
                "index": index,
                "prompt": _compose_scene_prompt(
                    prompts[index - 1] if len(prompts) >= index else topic,
                    "hand-drawn lineart animation, preserve the reference character and geometry",
                    [f"scene {index} of 3", f"{output_format} composition", "no written words"],
                ),
                "subject": topic,
                "action": "controlled line-art animation",
                "caption": "",
                "sketch_inputs": sketch_filenames,
            }
            for index in range(1, 4)
        ]
        result = {"style": style, "frames": frames, "source": self.name, "generation_mode": "controlnet_lineart_local", "style_control": "controlnet_lineart", "reference_strategy": "scene_cycle"}
        if output_dir is not None and media_enabled():
            paths: list[str] = []
            try:
                for index, frame in enumerate(frames, start=1):
                    reference_path = reference_paths[(index - 1) % len(reference_paths)]
                    frame["sketch_reference"] = Path(reference_path).name
                    path = generate_controlnet_image(frame["prompt"], Path(output_dir) / f"controlnet_image_{index:03d}.png", reference_path, seed=index * 101)
                    paths.append(path)
                    frame["generated_image_paths"] = [path]
                    live_paths = create_storyboard_frames(topic, style, frames[:index], Path(output_dir), output_format)
                    if artifact_callback:
                        artifact_callback({"frames": [dict(item) for item in frames[:index]], "frame_paths": live_paths, "provider": self.name, "completed": index, "total": len(frames)})
            except Exception as exc:
                raise ProviderError(f"ControlNet Lineart local falhou: {exc}") from exc
            result["generated_image_paths"] = paths
            result["frame_paths"] = create_storyboard_frames(topic, style, frames, Path(output_dir), output_format)
            result["reference_usage"] = [frame.get("sketch_reference") for frame in frames]
        return result


class ManualAudioProvider:
    name = "manual-audio-upload"

    def create(self, filename: str, output_dir=None, language: str = "pt_BR") -> dict[str, Any]:
        path = uploaded_audio_path(filename, "audio")
        if not path:
            raise ProviderError("Arquivo de narração manual não encontrado; envie um áudio válido")
        duration = audio_duration_seconds(path)
        if duration <= 0:
            raise ProviderError("Não foi possível ler a duração do áudio manual; envie um WAV/áudio válido")
        return {"duration_seconds": duration, "voice": "manual-upload", "stereo": True, "real_audio": True, "audio_path": str(path), "source_filename": path.name}


class LocalAudioProvider:
    name = "piper-local"

    def create(self, script: str, output_dir=None, language: str = "pt_BR") -> dict[str, Any]:
        if output_dir is not None and media_enabled():
            return synthesize_piper(script, output_dir, language)
        word_count = max(1, len(script.split()))
        return {"duration_seconds": max(10, round(word_count / 2.6, 1)), "voice": f"{language}-manifest", "stereo": True, "real_audio": False}


class LocalVideoProvider:
    name = "local-ffmpeg-renderer"

    def create(self, storyboard: dict[str, Any], audio: dict[str, Any], captions: list[str], output_dir=None, scene_durations: list[float] | None = None, transition: str = "cut", output_format: str = "vertical", motion_style: str = "ken_burns") -> dict[str, Any]:
        if output_dir is not None and media_enabled():
            result = render_frame_video(storyboard.get("frame_paths", []), audio, output_dir, captions, scene_durations, transition, output_format, motion_style)
            result["caption_count"] = len(captions)
            return result
        return {
            "format": "mp4",
            "width": 1080 if output_format == "vertical" else 1920 if output_format == "horizontal" else 1080,
            "height": 1920 if output_format == "vertical" else 1080,
            "aspect_ratio": "9:16" if output_format == "vertical" else "16:9" if output_format == "horizontal" else "1:1",
            "output_format": output_format,
            "audio_channels": 2 if audio.get("stereo") else 1,
            "caption_count": len(captions),
            "frames": len(storyboard.get("frames", [])),
            "strategy": "direct_video",
        }

    def create_frame_sequence(self, storyboard: dict[str, Any], audio: dict[str, Any], captions: list[str], output_dir=None, scene_durations: list[float] | None = None, transition: str = "cut", output_format: str = "vertical", motion_style: str = "ken_burns") -> dict[str, Any]:
        result = self.create(storyboard, audio, captions, output_dir, scene_durations, transition, output_format, motion_style)
        result["strategy"] = "image_sequence"
        result["assembly"] = "FFmpeg frame sequence + captions + stereo audio"
        result["recommended_for"] = ["sketch_clone", "couples_fruits_2d", "dynamic_slideshow"]
        return result
