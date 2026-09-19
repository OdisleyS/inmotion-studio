from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import GenerateRequest
from .media import GENERATED_ROOT, create_procedural_bgm, create_procedural_sfx, inspect_reference_quality, media_enabled, output_dimensions, uploaded_audio_path
from .research import GoogleNewsResearchProvider, LiveTrendResearchProvider, LocalResearchProvider
from .style_profiles import load_style_profile
from .providers import (
    FallbackChain,
    AntigravityTextProvider,
    AntigravityVisualProvider,
    CodexTextProvider,
    ComfyUIImageProvider,
    LocalAudioProvider,
    LocalControlNetImageProvider,
    LocalDiffusionImageProvider,
    LocalImageProvider,
    ManualImageProvider,
    LocalTextProvider,
    LocalVideoProvider,
    ManualAudioProvider,
    ComfyUINativeVideoProvider,
    SadTalkerVideoProvider,
    ProviderError,
    codex_model_name,
    get_model_catalog,
    get_provider_catalog,
)


@dataclass
class PipelineOutput:
    project_id: str
    status: str
    title: str
    script: str
    virality_score: float
    render: dict[str, Any]
    style_fidelity: dict[str, Any]
    style_profile: dict[str, Any]
    events: list[dict[str, str]]
    diagnostics: list[str]
    scenes: list[dict[str, Any]]
    research: dict[str, Any]
    publish_pack: dict[str, Any] | None = None
    resolved_providers: dict[str, str] = field(default_factory=dict)
    resolved_models: dict[str, str] = field(default_factory=dict)


class PipelineCancelled(RuntimeError):
    """Raised when a user cancels a production before the next irreversible phase."""


def score_virality(topic: str, script: str) -> float:
    """Transparent heuristic: hook, specificity, pacing, and curiosity markers."""
    text = f"{topic} {script}".lower()
    score = 38.0
    score += 16 if "você sabia" in text or "sabia" in text else 0
    score += 12 if "?" in text else 0
    score += 10 if any(token in text for token in ("surpresa", "segredo", "detalhe", "mito")) else 0
    score += 8 if len(script.split()) <= 100 else 0
    score += 6 if re.search(r"\b(até o final|final)\b", text) else 0
    return round(min(96.0, score), 1)


def build_publish_pack(topic: str, script: str, virality_score: float) -> dict[str, Any]:
    """Create local, editable publishing metadata without another provider call."""
    clean_topic = re.sub(r"\s+", " ", str(topic or "")).strip()
    clean_script = re.sub(r"\s+", " ", str(script or "")).strip()
    first_sentence = re.split(r"(?<=[.!?])\s+", clean_script, maxsplit=1)[0].strip(" .!?\n")
    title = first_sentence if 20 <= len(first_sentence) <= 100 else clean_topic[:100].rstrip(" .!?")
    stopwords = {
        "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos", "e", "em", "era",
        "o", "os", "para", "por", "que", "uma", "um", "até", "ate", "como", "desde",
    }
    normalized_topic = unicodedata.normalize("NFKD", clean_topic.lower())
    normalized_script = unicodedata.normalize("NFKD", clean_script.lower())
    plain_topic = "".join(char for char in normalized_topic if not unicodedata.combining(char))
    plain_script = "".join(char for char in normalized_script if not unicodedata.combining(char))
    words: list[str] = []
    for word in re.findall(r"[a-z0-9]{4,}", plain_topic):
        if word not in stopwords and word not in words:
            words.append(word)
    for word in re.findall(r"[a-z0-9]{4,}", plain_script):
        if len(words) >= 5:
            break
        if word not in stopwords and word not in words:
            words.append(word)
    hashtags = [f"#{word}" for word in words[:5]]
    for hashtag in ("#shorts", "#tiktok"):
        if hashtag not in hashtags:
            hashtags.append(hashtag)
    return {
        "title": title or "Nova produção",
        "description": clean_script,
        "hashtags": hashtags[:8],
        "virality_score": virality_score,
        "editable": True,
    }


def normalize_script_for_narration(script: str) -> str:
    """Turn a director-style Agy script into clean spoken narration."""
    raw = str(script or "").strip()
    if not raw:
        return raw
    inline_voice = re.findall(
        r"(?is)(?:\b(?:voz|locução|voice|áudio|audio)\s*:\s*)(.*?)(?=\s*(?:\[(?:cena|slide)\s*\d+\]|(?:slide|cena)\s+\d+|(?:voz|locução|voice|áudio|audio)\s*:)|$)",
        raw,
    )
    if inline_voice:
        return re.sub(r"\s+", " ", " ".join(inline_voice)).replace("[", " ").strip()
    if re.search(r"(?i)\b(?:visual|texto na tela)\s*:|\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", raw):
        # Some CLI models ignore the plain-narration contract and return a
        # one-line director sheet. Remove visual directions and timecodes
        # before the text reaches Piper; spoken prose remains available.
        cleaned = re.sub(r"(?i)\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\s*\]?", " ", raw)
        cleaned = re.sub(r"(?is)\bvisual\s*:\s*.*?(?=\s*(?:visual|texto na tela|voz|locução|voice|áudio|audio)\s*:|$)", " ", cleaned)
        cleaned = re.sub(
            r"(?is)\btexto na tela\s*:\s*.*?(?=\s*(?:\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}|visual|voz|locução|voice|áudio|audio)\s*:|(?<=[.!?])\s+(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]))",
            " ",
            cleaned,
        )
        cleaned = re.sub(r"(?i)\b(?:visual|texto na tela|voz|locução|voice|áudio|audio)\s*:\s*", " ", cleaned)
        cleaned = re.sub(r"(?i)\b(?:slide|cena)\s+\d+\s*:?", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).replace("[", " ").strip()
        if cleaned:
            return cleaned
    blocks = re.split(r"(?im)^\s*(?:slide|cena)\s+\d+\s*:?\s*$", raw)
    voice_segments: list[str] = []
    for block in blocks:
        match = re.search(r"(?is)(?:^|\n)\s*voz\s*:\s*(.+)", block)
        if match:
            segment = re.sub(r"\s+", " ", match.group(1)).strip()
            if segment:
                voice_segments.append(segment)
    if voice_segments:
        return " ".join(voice_segments)
    cleaned_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"(?i)^(?:slide|cena)\s+\d+", stripped):
            continue
        if re.match(r"(?i)^(?:visual|texto na tela)\s*:", stripped):
            continue
        stripped = re.sub(r"(?i)^(?:visual|texto na tela|voz|locução|áudio|audio)\s*:\s*", "", stripped).strip()
        if stripped:
            cleaned_lines.append(stripped)
    return re.sub(r"\s+", " ", " ".join(cleaned_lines)).replace("[", " ").strip() or raw


def extract_visual_scene_prompts(script: str) -> list[str]:
    """Extract visual direction from slide/cena scripts for image generation."""
    raw = str(script or "").strip()
    if not raw:
        return []
    blocks = re.split(r"(?im)(?=^\s*(?:slide|cena)\s+\d+|\[\s*(?:slide|cena)\s+\d+\s*\])", raw)
    prompts: list[str] = []
    for block in blocks:
        if not re.search(r"(?i)(?:slide|cena)\s+\d+", block):
            continue
        match = re.search(r"(?is)\bvisual\s*:\s*(.*?)(?=\s*(?:texto na tela|voz|locução|voice)\s*:|$)", block)
        if match:
            prompt = re.sub(r"\s+", " ", match.group(1)).strip(" .")
            if prompt:
                prompts.append(prompt)
    if not prompts and raw.count("[") >= 2:
        for fragment in raw.split("[")[1:]:
            fragment = re.split(r"(?i)\b(?:voz|locução|voice|áudio|audio)\s*:", fragment, maxsplit=1)[0]
            fragment = re.sub(r"\s+", " ", fragment).strip(" .]")
            if fragment:
                prompts.append(fragment)
            if len(prompts) == 3:
                break
    if not prompts:
        # Agy/Codex may return clean narration instead of a director sheet.
        # Split that narration into balanced story beats so each generated
        # frame receives a different visual moment instead of the full topic.
        sentences = [
            re.sub(r"\s+", " ", sentence).strip(" .")
            for sentence in re.split(r"(?<=[.!?])\s+", raw)
            if sentence.strip()
        ]
        if sentences:
            for index in range(min(3, len(sentences))):
                start = round(index * len(sentences) / 3)
                end = round((index + 1) * len(sentences) / 3)
                chunk = " ".join(sentences[start:end]).strip(" .")
                if chunk:
                    prompts.append(chunk)
            while prompts and len(prompts) < 3:
                prompts.append(prompts[-1])
    return prompts


def fit_script_to_target(script: str, target_seconds: int) -> tuple[str, bool]:
    """Keep generated narration near the requested duration using sentence boundaries."""
    words = str(script or "").split()
    maximum = max(20, int(round(max(10, target_seconds) * 2.6)))
    if len(words) <= maximum:
        return str(script or "").strip(), False
    candidate = " ".join(words[:maximum])
    sentence_ends = list(re.finditer(r"[.!?](?:\s|$)", candidate))
    if sentence_ends:
        candidate = candidate[:sentence_ends[-1].end()].strip()
    return candidate, True


def distribute_scene_captions(captions: list[str], scene_count: int) -> list[str]:
    """Pack narration sentences into one editable caption block per visual scene."""
    if scene_count <= 0:
        return []
    if not captions:
        return [""] * scene_count
    return [
        " ".join(captions[round(index * len(captions) / scene_count):round((index + 1) * len(captions) / scene_count)]).strip()
        for index in range(scene_count)
    ]


def inspect_sketches(filenames: list[str], style: str) -> dict[str, Any]:
    if style != "sketch_clone":
        return {"status": "not_applicable", "inputs": 0, "line_weight_preserved": None}
    if not filenames:
        return {"status": "generated_without_reference", "inputs": 0, "line_weight_preserved": None, "message": "Nenhum desenho enviado; o sistema vai gerar as imagens automaticamente com um estilo ilustrado local."}
    supported = [name for name in filenames if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    digest = hashlib.sha256("|".join(sorted(supported)).encode()).hexdigest()[:12]
    quality = [entry for entry in (inspect_reference_quality(name) for name in supported) if entry]
    poor_quality = [entry for entry in quality if not entry.get("usable", False)]
    return {
        "status": "needs_upload" if poor_quality else "verified" if supported else "needs_upload",
        "inputs": len(supported),
        "line_weight_preserved": bool(supported),
        "geometry_control": "ControlNet-ready",
        "style_reference_id": digest,
        "quality": quality,
        "message": "Foto com baixa resolução/contraste; envie outra referência com boa luz e pelo menos 128 px." if poor_quality else "Estrutura de linha preservada no storyboard; conecte o adaptador ControlNet/LoRA para frames reais.",
    }


def build_style_profile(style: str, fidelity: dict[str, Any]) -> dict[str, Any]:
    """Create a small, auditable style contract for each production.

    This is intentionally metadata, not a claim that a LoRA was trained. It records
    which references passed the local gate and which conditioning path generated
    the frames, so a project can be reopened without losing the visual provenance.
    """
    quality = [dict(item) for item in fidelity.get("quality", []) if isinstance(item, dict)]
    references = [str(item.get("filename")) for item in quality if item.get("filename")]
    has_reference = bool(fidelity.get("inputs", 0))
    return {
        "profile_id": fidelity.get("style_reference_id") or f"{style}-automatic",
        "style": style,
        "mode": "reference" if has_reference else "automatic",
        "reference_count": int(fidelity.get("inputs", 0) or 0),
        "reference_files": references,
        "quality_gate": fidelity.get("status", "not_applicable"),
        "conditioning": "controlnet_lineart" if has_reference and fidelity.get("status") != "needs_upload" else "automatic_illustration",
        "preservation_targets": ["geometry", "line_weight", "character_traits"] if style == "sketch_clone" else ["composition", "palette", "scene_continuity"],
        "quality": quality,
    }


def persist_style_profile(output_dir: Any, profile: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "style_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def recommended_video_strategy(style: str) -> str:
    # Until a native video provider is connected, every style has a reliable local frame path.
    return "image_sequence"


def provider_for_model(phase: str, provider: str, model: str | None) -> str:
    """Resolve an explicit model into its adapter when provider routing is automatic."""
    if provider and provider != "auto":
        return provider
    if not model or model == "auto":
        return "auto"
    item = next(
        (
            entry
            for entry in get_model_catalog().get(phase, [])
            if entry["name"] == model or model in entry.get("aliases", [])
        ),
        None,
    )
    resolved = str(item.get("provider", "auto")) if item else "auto"
    return "auto" if resolved == "auto" else resolved


def resolved_model_label(phase: str, provider: str, requested_model: str | None, narration_language: str = "pt_BR") -> str:
    """Return an auditable label for the model/engine that actually ran a phase."""
    if requested_model and requested_model != "auto":
        return requested_model
    defaults = {
        "script": {
            "antigravity-cli": "Antigravity · modelo padrão do CLI",
            "codex-cli": f"Codex · {codex_model_name()}",
            "local-template-text": "Template local",
        },
        "image": {
            "local-sd-turbo": "SD-Turbo local",
            "local-controlnet-lineart": "ControlNet Lineart local",
            "antigravity-visual-planner": "Antigravity · direção visual",
            "local-storyboard": "Storyboard local",
            "manual-image-reference": "Referência enviada",
        },
        "video": {
            "local-ffmpeg-renderer": "FFmpeg local",
            "wan-video": "Wan 2.1",
            "ltx-video": "LTX-Video",
            "sadtalker-lipsync": "SadTalker",
        },
    }
    if phase == "audio" and provider == "piper-local":
        return f"Piper · {narration_language}"
    return defaults.get(phase, {}).get(provider, provider)


def validate_provider_selection(selection: dict[str, str], pipeline: "ProductionPipeline", video_strategy: str = "auto", style: str = "dynamic_slideshow", model_selection: dict[str, str] | None = None) -> list[str]:
    catalog = get_provider_catalog()
    errors: list[str] = []
    operations = {
        "script": {pipeline.text.name, pipeline.agy.name, pipeline.codex.name},
        "image": {pipeline.image.name, pipeline.manual_image.name, pipeline.visual.name, pipeline.diffusion.name, pipeline.controlnet.name, pipeline.comfy.name},
        "audio": {pipeline.audio.name, pipeline.manual_audio.name},
        "video": {pipeline.video.name, pipeline.wan_video.name, pipeline.ltx_video.name, pipeline.sadtalker.name},
    }
    for phase, chosen in selection.items():
        if phase not in catalog or chosen in ("", "auto"):
            continue
        item = next((entry for entry in catalog[phase] if entry["name"] == chosen), None)
        if item is None:
            errors.append(f"Provider '{chosen}' não existe para a etapa {phase}.")
        elif item["status"] not in ("ready", "ready-manifest"):
            errors.append(f"Provider '{chosen}' está {item['status']} e ainda não pode ser usado.")
        elif chosen not in operations.get(phase, set()):
            errors.append(f"Provider '{chosen}' ainda não está conectado ao pipeline da etapa {phase}.")
        else:
            if phase == "video":
                resolved_strategy = recommended_video_strategy(style) if video_strategy == "auto" else video_strategy
                required_capability = "video_generation" if resolved_strategy == "direct_video" else "image_sequence"
            else:
                required_capability = {"script": "text", "image": "image_sequence" if chosen == pipeline.manual_image.name else "image_generation", "audio": "audio"}.get(phase)
            if required_capability and required_capability not in item.get("capabilities", []):
                errors.append(f"Provider '{chosen}' não possui capability '{required_capability}' para a etapa escolhida.")
    if selection.get("script") == pipeline.agy.name and not pipeline.agy.available:
        errors.append("Antigravity CLI foi escolhido, mas a ponte está desabilitada ou não autenticada.")
    model_selection = model_selection or {}
    models = get_model_catalog()
    required_model_capability = {
        "script": "text",
        "image": "image_generation",
        "audio": "audio",
    }
    for phase, chosen_model in model_selection.items():
        if not chosen_model or chosen_model == "auto":
            continue
        item = next(
            (
                entry
                for entry in models.get(phase, [])
                if entry["name"] == chosen_model or chosen_model in entry.get("aliases", [])
            ),
            None,
        )
        if item is None:
            errors.append(f"Modelo '{chosen_model}' não existe para a etapa {phase}.")
        elif item["status"] not in ("ready", "ready-manifest"):
            errors.append(f"Modelo '{chosen_model}' está {item['status']} e não pode ser usado.")
        elif item.get("provider") not in ("auto", selection.get(phase, "auto"), "") and selection.get(phase, "auto") != "auto":
            errors.append(f"Modelo '{chosen_model}' pertence ao provider '{item['provider']}', mas a etapa {phase} está usando '{selection.get(phase)}'.")
        else:
            capability = required_model_capability.get(phase)
            if phase == "video":
                resolved_strategy = recommended_video_strategy(style) if video_strategy == "auto" else video_strategy
                capability = "video_generation" if resolved_strategy == "direct_video" else "image_sequence"
            if capability and capability not in item.get("capabilities", []):
                errors.append(f"Modelo '{chosen_model}' não possui capability '{capability}' para a etapa {phase}.")
    if video_strategy == "direct_video" and selection.get("video", "auto") in ("", "auto"):
        native_ready = any(
            entry["name"] != "auto"
            and entry["status"] in ("ready", "ready-manifest")
            and "video_generation" in entry.get("capabilities", [])
            for entry in catalog.get("video", [])
        )
        if not native_ready:
            errors.append("Vídeo nativo foi solicitado, mas nenhum modelo com capability 'video_generation' está conectado; use Frame por frame ou conecte Wan/LTX.")
    return errors


class ProductionPipeline:
    def __init__(self) -> None:
        self.text = LocalTextProvider()
        self.agy = AntigravityTextProvider()
        self.codex = CodexTextProvider()
        self.image = LocalImageProvider()
        self.manual_image = ManualImageProvider()
        self.diffusion = LocalDiffusionImageProvider()
        self.controlnet = LocalControlNetImageProvider()
        self.comfy = ComfyUIImageProvider()
        self.visual = AntigravityVisualProvider()
        self.audio = LocalAudioProvider()
        self.manual_audio = ManualAudioProvider()
        self.video = LocalVideoProvider()
        self.wan_video = ComfyUINativeVideoProvider("wan-video")
        self.ltx_video = ComfyUINativeVideoProvider("ltx-video")
        self.sadtalker = SadTalkerVideoProvider()
        self.research = LiveTrendResearchProvider()
        self.news_research = GoogleNewsResearchProvider()
        self.local_research = LocalResearchProvider()

    def draft_script(
        self,
        topic: str,
        style: str,
        custom_script: str | None,
        provider_selection: dict[str, str] | None = None,
        model_selection: dict[str, str] | None = None,
        target_seconds: int = 35,
    ) -> dict[str, Any]:
        """Draft a script without creating a project or rendering media.

        This is the same research/provider cascade used by production, exposed as
        a deliberate pre-production step so a creator can review the narration
        before spending time on image, voice, and video generation.
        """
        provider_selection = provider_selection or {}
        model_selection = model_selection or {}
        events: list[dict[str, str]] = []
        research_result = self._run_phase(
            "research",
            ([(self.news_research.name, lambda: self.news_research.create(topic))] if self.news_research.available else [])
            + ([(self.research.name, lambda: self.research.create(topic))] if self.research.available else [])
            + [(self.local_research.name, lambda: self.local_research.create(topic))],
            events,
        )
        research_data = research_result.value
        script_choice = provider_for_model("script", provider_selection.get("script", "auto"), model_selection.get("script"))
        if script_choice == "auto":
            script_providers = (
                ([(self.agy.name, lambda: self.agy.create(topic, style, custom_script, model_selection.get("script"), research_data, target_seconds))] if self.agy.available else [])
                + ([(self.codex.name, lambda: self.codex.create(topic, style, custom_script, model_selection.get("script"), research_data, target_seconds))] if self.codex.available else [])
                + [(self.text.name, lambda: self.text.create(topic, style, custom_script))]
            )
        elif script_choice == self.agy.name:
            script_providers = [(self.agy.name, lambda: self.agy.create(topic, style, custom_script, model_selection.get("script"), research_data, target_seconds))]
            if self.codex.available:
                script_providers.append((self.codex.name, lambda: self.codex.create(topic, style, custom_script, None, research_data, target_seconds)))
            script_providers.append((self.text.name, lambda: self.text.create(topic, style, custom_script)))
        elif script_choice == self.codex.name:
            script_providers = [(self.codex.name, lambda: self.codex.create(topic, style, custom_script, model_selection.get("script"), research_data, target_seconds))]
            if self.agy.available:
                script_providers.append((self.agy.name, lambda: self.agy.create(topic, style, custom_script, None, research_data, target_seconds)))
            script_providers.append((self.text.name, lambda: self.text.create(topic, style, custom_script)))
        elif script_choice == self.text.name:
            script_providers = [(self.text.name, lambda: self.text.create(topic, style, custom_script))]
            if self.agy.available:
                script_providers.append((self.agy.name, lambda: self.agy.create(topic, style, custom_script, None, research_data, target_seconds)))
            if self.codex.available:
                script_providers.append((self.codex.name, lambda: self.codex.create(topic, style, custom_script, None, research_data, target_seconds)))
        else:
            raise ProviderError(f"Provider de roteiro '{script_choice}' não está conectado ao pipeline.")
        text_result = self._run_phase("script", script_providers, events)
        script_data = dict(text_result.value)
        script_data["script"] = normalize_script_for_narration(script_data.get("script", ""))
        if not custom_script:
            script_data["script"], trimmed = fit_script_to_target(script_data["script"], target_seconds)
            if trimmed:
                script_data["diagnostic"] = f"Roteiro ajustado para aproximadamente {target_seconds}s."
        script_data["hook"] = script_data["script"].split(".")[0].strip() + "." if script_data["script"] else script_data.get("hook", "")
        score = round((score_virality(topic, script_data["script"]) + float(research_data.get("score", 35.0))) / 2, 1)
        events.append({"phase": "script-preview", "provider": text_result.provider, "status": "success", "message": "rascunho de roteiro pronto"})
        return {
            "title": script_data.get("title", topic),
            "script": script_data.get("script", ""),
            "hook": script_data.get("hook", ""),
            "provider": text_result.provider,
            "virality_score": score,
            "research": research_data,
            "events": events,
            "diagnostics": [script_data["diagnostic"]] if script_data.get("diagnostic") else [],
        }

    def _run_phase(self, phase: str, providers, events: list[dict[str, str]], cancel_callback: Callable[[], bool] | None = None):
        simulated_failures = {
            item.strip().lower()
            for item in os.getenv("SIMULATE_PRIMARY_FAILURES", "").split(",")
            if item.strip()
        }
        selected = []
        if phase in simulated_failures:
            def unavailable():
                raise ProviderError(f"simulated primary {phase} outage")
            selected.append((f"simulated-primary-{phase}", unavailable))
        def guarded(operation):
            if cancel_callback and cancel_callback():
                raise PipelineCancelled("Produção cancelada pelo usuário")
            value = operation()
            if cancel_callback and cancel_callback():
                raise PipelineCancelled("Produção cancelada pelo usuário")
            return value

        selected.extend((name, lambda operation=operation: guarded(operation)) for name, operation in providers)
        chain = FallbackChain(phase, selected)
        result = chain.run()
        events.extend(chain.events)
        return result

    def generate(self, request: GenerateRequest, progress_callback: Callable[[str, str], None] | None = None, artifact_callback: Callable[[str, dict[str, Any]], None] | None = None, cancel_callback: Callable[[], bool] | None = None) -> PipelineOutput:
        project_id = str(uuid.uuid4())
        output_dir = GENERATED_ROOT / project_id
        events: list[dict[str, str]] = []
        diagnostics: list[str] = []
        resolved_providers: dict[str, str] = {}
        resolved_models: dict[str, str] = {}

        fidelity = inspect_sketches(request.sketch_filenames, request.style)
        if request.style_profile_id:
            saved_profile = load_style_profile(request.style_profile_id)
            if not saved_profile:
                return PipelineOutput(
                    project_id=project_id, status="blocked", title=request.topic, script=request.script or "",
                    virality_score=0, render={}, style_fidelity=fidelity,
                    style_profile={"profile_id": request.style_profile_id, "mode": "reference", "quality_gate": "missing"},
                    events=events, diagnostics=["O perfil visual salvo não existe mais; escolha outro perfil ou envie os desenhos novamente."],
                    scenes=[], research={},
                )
            request.sketch_filenames = list(saved_profile.get("reference_files", []))
            request.image_source = "reference"
            fidelity = inspect_sketches(request.sketch_filenames, request.style)
        style_profile = build_style_profile(request.style, fidelity)
        if request.style_profile_id:
            style_profile = {**style_profile, "profile_id": request.style_profile_id, "saved_profile": True, "profile_name": saved_profile.get("name", "Meu traço")}
        if cancel_callback and cancel_callback():
            raise PipelineCancelled("Produção cancelada pelo usuário")
        if progress_callback:
            progress_callback("queued", "Produção aceita; preparando o pipeline.")
        allowed_autonomy = {"autonomous", "manual", "copilot"}
        autonomy = {stage: request.stage_autonomy.get(stage, "autonomous") for stage in ("research", "script", "image", "audio", "sfx", "bgm", "video")}
        selection_errors = validate_provider_selection(request.provider_selection, self, request.video_strategy, request.style, request.model_selection)
        if request.style == "sketch_clone" and request.sketch_filenames and fidelity.get("status") == "needs_upload":
            selection_errors.append("A referência do desenho tem resolução/contraste insuficiente; envie uma foto mais nítida e bem iluminada.")
        if request.image_source == "reference" and not request.sketch_filenames:
            selection_errors.append("A fonte visual está como 'desenho de referência', mas nenhuma imagem foi enviada; escolha geração automática ou envie pelo menos uma foto.")
        selection_errors.extend([f"Modo '{mode}' não é válido para a etapa {stage}." for stage, mode in autonomy.items() if mode not in allowed_autonomy])
        if autonomy["script"] == "manual" and not request.script:
            selection_errors.append("A etapa Roteiro está manual; informe um roteiro próprio antes de gerar.")
        if autonomy["image"] == "manual" and not request.sketch_filenames:
            selection_errors.append("A etapa Imagens está manual; envie pelo menos uma imagem de referência ou mude para Autônomo/Co-piloto.")
        if autonomy["audio"] == "manual" and not request.audio_filename:
            selection_errors.append("A etapa Áudio está manual; envie um arquivo de narração ou mude para Autônomo/Co-piloto.")
        if autonomy["bgm"] == "manual" and not request.bgm_filename:
            selection_errors.append("A etapa BGM está manual; envie uma faixa ou mude para Autônomo/Co-piloto.")
        if autonomy["sfx"] == "manual" and not request.sfx_filenames:
            selection_errors.append("A etapa SFX está manual; envie pelo menos um efeito ou mude para Autônomo/Co-piloto.")
        if selection_errors:
            return PipelineOutput(
                project_id=project_id, status="blocked", title=request.topic, script=request.script or "",
                virality_score=0, render={}, style_fidelity=fidelity, style_profile=style_profile, events=events, diagnostics=selection_errors,
                scenes=[], research={},
            )

        persist_style_profile(output_dir, style_profile)

        strategy = recommended_video_strategy(request.style) if request.video_strategy == "auto" else request.video_strategy
        research_result = self._run_phase(
            "research",
            ([(self.news_research.name, lambda: self.news_research.create(request.topic))] if autonomy["research"] != "manual" and self.news_research.available else [])
            + ([(self.research.name, lambda: self.research.create(request.topic))] if autonomy["research"] != "manual" and self.research.available else [])
            + [(self.local_research.name, lambda: self.local_research.create(request.topic))],
            events,
            cancel_callback,
        )
        research_data = research_result.value
        resolved_providers["research"] = research_result.provider
        if progress_callback:
            progress_callback("research", f"Pesquisa pronta com {research_result.provider}.")
        if artifact_callback:
            artifact_callback("research", research_data)
        script_choice = provider_for_model("script", request.provider_selection.get("script", "auto"), request.model_selection.get("script"))
        if autonomy["script"] == "manual":
            script_providers = [("manual-script-input", lambda: self.text.create(request.topic, request.style, request.script))]
        elif script_choice == "auto":
            script_providers = ([(self.agy.name, lambda: self.agy.create(request.topic, request.style, request.script, request.model_selection.get("script"), research_data, request.target_seconds))] if self.agy.available else []) + ([(self.codex.name, lambda: self.codex.create(request.topic, request.style, request.script, request.model_selection.get("script"), research_data, request.target_seconds))] if self.codex.available else []) + [(self.text.name, lambda: self.text.create(request.topic, request.style, request.script))]
        elif script_choice == self.agy.name:
            script_providers = [(self.agy.name, lambda: self.agy.create(request.topic, request.style, request.script, request.model_selection.get("script"), research_data, request.target_seconds))]
            if self.codex.available:
                script_providers.append((self.codex.name, lambda: self.codex.create(request.topic, request.style, request.script, None, research_data, request.target_seconds)))
            script_providers.append((self.text.name, lambda: self.text.create(request.topic, request.style, request.script)))
        elif script_choice == self.codex.name:
            script_providers = [(self.codex.name, lambda: self.codex.create(request.topic, request.style, request.script, request.model_selection.get("script"), research_data, request.target_seconds))]
            if self.agy.available:
                script_providers.append((self.agy.name, lambda: self.agy.create(request.topic, request.style, request.script, None, research_data, request.target_seconds)))
            script_providers.append((self.text.name, lambda: self.text.create(request.topic, request.style, request.script)))
        elif script_choice == self.text.name:
            script_providers = [(self.text.name, lambda: self.text.create(request.topic, request.style, request.script))]
            if self.agy.available:
                script_providers.append((self.agy.name, lambda: self.agy.create(request.topic, request.style, request.script, None, research_data, request.target_seconds)))
            if self.codex.available:
                script_providers.append((self.codex.name, lambda: self.codex.create(request.topic, request.style, request.script, None, research_data, request.target_seconds)))
        else:
            raise ProviderError(f"Provider de roteiro '{script_choice}' não está conectado ao pipeline.")

        text_result = self._run_phase(
            "script",
            script_providers,
            events,
            cancel_callback,
        )
        if progress_callback:
            progress_callback("script", f"Roteiro pronto com {text_result.provider}.")
        resolved_providers["script"] = text_result.provider
        resolved_models["script"] = resolved_model_label(
            "script", text_result.provider, request.model_selection.get("script")
        )
        def prepare_script_data(value: dict[str, Any]) -> dict[str, Any]:
            data = dict(value)
            data["scene_prompts"] = extract_visual_scene_prompts(data.get("script", ""))
            data["script"] = normalize_script_for_narration(data.get("script", ""))
            if not request.script:
                data["script"], trimmed = fit_script_to_target(data["script"], request.target_seconds)
                if trimmed:
                    diagnostics.append(f"Roteiro automático ajustado para cerca de {request.target_seconds}s.")
            data["hook"] = data["script"].split(".")[0].strip() + "." if data["script"] else data.get("hook", "")
            return data

        script_data = prepare_script_data(text_result.value)
        if artifact_callback:
            artifact_callback("script", {"title": script_data.get("title", request.topic), "hook": script_data.get("hook", ""), "script": script_data.get("script", ""), "provider": text_result.provider})
        score = round((score_virality(request.topic, script_data["script"]) + float(research_data.get("score", 35.0))) / 2, 1)
        if score < 50:
            original_score = score
            rewrite_candidates = []
            requested_script_provider = request.provider_selection.get("script", "auto")
            if self.agy.available and requested_script_provider in {"", "auto", self.agy.name}:
                rewrite_candidates.append((self.agy.name, lambda: self.agy.create(request.topic, request.style, script_data["script"], request.model_selection.get("script"), research_data, request.target_seconds)))
            if self.codex.available and requested_script_provider in {"", "auto", self.codex.name}:
                rewrite_candidates.append((self.codex.name, lambda: self.codex.create(request.topic, request.style, script_data["script"], request.model_selection.get("script"), research_data, request.target_seconds)))
            rewrite_candidates.append((self.text.name, lambda: self.text.rewrite_hook(request.topic, script_data["script"])))
            try:
                rewrite_result = self._run_phase("script-rewrite", rewrite_candidates, events, cancel_callback)
                script_data = prepare_script_data(rewrite_result.value)
                resolved_providers["script"] = rewrite_result.provider
                resolved_models["script"] = resolved_model_label(
                    "script", rewrite_result.provider, request.model_selection.get("script")
                )
                score = round((score_virality(request.topic, script_data["script"]) + float(research_data.get("score", 35.0))) / 2, 1)
                events.append({"phase": "script-rewrite", "provider": rewrite_result.provider, "status": "success", "message": f"hook recuperado de {original_score}% para {score}%"})
                if artifact_callback:
                    artifact_callback("script", {"title": script_data.get("title", request.topic), "hook": script_data.get("hook", ""), "script": script_data.get("script", ""), "provider": rewrite_result.provider})
            except ProviderError as exc:
                diagnostics.append(f"Hook abaixo de 50%; recuperação não disponível: {exc}")
            if score < 50:
                diagnostics.append(f"Virality score permanece baixo após recuperação: {score}%.")

        image_choice = provider_for_model("image", request.provider_selection.get("image", "auto"), request.model_selection.get("image"))
        audio_choice = provider_for_model("audio", request.provider_selection.get("audio", "auto"), request.model_selection.get("audio"))
        video_choice = provider_for_model("video", request.provider_selection.get("video", "auto"), request.model_selection.get("video"))
        image_model = request.model_selection.get("image")
        selected_audio_model = request.model_selection.get("audio", "")
        audio_language = "en_US" if selected_audio_model.startswith("piper-en_US") else "pt_BR" if selected_audio_model.startswith("piper-pt_BR") else request.narration_language
        visual_prompts = request.scene_prompts or script_data.get("scene_prompts", [])
        visual_operation = lambda: self.visual.create(request.topic, request.style, request.sketch_filenames, output_dir, image_model, visual_prompts, request.output_format)
        diffusion_operation = lambda: self.diffusion.create(request.topic, request.style, request.sketch_filenames, output_dir, image_model, visual_prompts, artifact_callback=(lambda value: artifact_callback("images", value)) if artifact_callback else None, output_format=request.output_format)
        comfy_operation = lambda: self.comfy.create(request.topic, request.style, request.sketch_filenames, output_dir, image_model, visual_prompts, artifact_callback=(lambda value: artifact_callback("images", value)) if artifact_callback else None, output_format=request.output_format)
        image_operation = lambda: self.image.create(request.topic, request.style, request.sketch_filenames, output_dir, visual_prompts, request.output_format)
        manual_image_operation = lambda: self.manual_image.create(request.topic, request.style, request.sketch_filenames, output_dir, visual_prompts, request.output_format)
        controlnet_operation = lambda: self.controlnet.create(request.topic, request.style, request.sketch_filenames, output_dir, image_model, visual_prompts, artifact_callback=(lambda value: artifact_callback("images", value)) if artifact_callback else None, output_format=request.output_format)
        # Co-pilot keeps the AI fallback, but an optional uploaded narration wins
        # when the creator supplied one. Manual mode still requires that upload.
        audio_operation = lambda: self.manual_audio.create(request.audio_filename or "", output_dir, audio_language) if (autonomy["audio"] in {"manual", "copilot"} and request.audio_filename) or audio_choice == self.manual_audio.name else self.audio.create(script_data["script"], output_dir, audio_language)
        default_image_candidates = (
            ([(self.comfy.name, comfy_operation)] if self.comfy.available else [])
            + ([(self.controlnet.name, controlnet_operation)] if self.controlnet.available and request.sketch_filenames else [])
            + ([(self.diffusion.name, diffusion_operation)] if self.diffusion.available else [])
            + ([(self.visual.name, visual_operation)] if self.visual.available else [])
            + [(self.image.name, image_operation)]
        )
        if autonomy["image"] == "manual":
            image_candidates = [(self.manual_image.name, manual_image_operation)]
        elif image_choice == self.manual_image.name:
            # An explicit manual provider remains first, but an image generation
            # fallback keeps the job alive if the uploaded asset becomes unreadable.
            image_candidates = [(self.manual_image.name, manual_image_operation)] + default_image_candidates
        elif image_choice == "auto":
            image_candidates = default_image_candidates
        else:
            selected_image = next((item for item in default_image_candidates if item[0] == image_choice), None)
            image_candidates = ([selected_image] if selected_image else []) + [item for item in default_image_candidates if item[0] != image_choice]
            if not image_candidates:
                image_candidates = [(self.image.name, image_operation)]
        image_result = self._run_phase("image", image_candidates, events, cancel_callback)
        resolved_providers["image"] = image_result.provider
        resolved_models["image"] = resolved_model_label(
            "image", image_result.provider, request.model_selection.get("image")
        )
        if image_result.provider == self.controlnet.name:
            fidelity = {
                **fidelity,
                "status": "verified",
                "line_weight_preserved": True,
                "geometry_control": "controlnet_lineart",
                "message": "Frames gerados com ControlNet Lineart local a partir da referência enviada.",
            }
            style_profile = {**style_profile, "conditioning": "controlnet_lineart", "conditioning_provider": image_result.provider, "frames_conditioned": len(image_result.value.get("frames", []))}
        else:
            style_profile = {**style_profile, "conditioning_provider": image_result.provider, "frames_conditioned": 0}
        if image_result.value.get("style_adapter"):
            style_profile = {
                **style_profile,
                "style_adapter": image_result.value["style_adapter"],
                "style_adapter_status": "applied",
            }
        if image_result.value.get("reference_usage"):
            style_profile["reference_usage"] = list(image_result.value["reference_usage"])
        persist_style_profile(output_dir, style_profile)
        if progress_callback:
            progress_callback("image", f"{len(image_result.value.get('frames', []))} cenas preparadas.")
        if artifact_callback:
            artifact_callback("images", {"frames": image_result.value.get("frames", []), "frame_paths": image_result.value.get("frame_paths", []), "provider": image_result.provider})
        narration_captions = [line.strip() for line in re.split(r"[.!?]", script_data["script"]) if line.strip()]
        scene_data = [dict(frame) for frame in image_result.value.get("frames", [])]
        scene_captions = request.scene_captions or distribute_scene_captions(narration_captions, len(scene_data))
        scene_duration = round(max(1.0, float(request.target_seconds) / max(1, len(scene_data))), 2)
        scene_durations = [scene_duration] * len(scene_data)
        for index, scene in enumerate(scene_data):
            scene["caption"] = scene_captions[index] if index < len(scene_captions) else str(scene.get("caption", ""))
            scene["duration_seconds"] = scene_durations[index] if index < len(scene_durations) else scene_duration
        if request.mode == "director" and not request.director_approved:
            events.append({"phase": "director-review", "provider": image_result.provider, "status": "success", "message": "rascunho visual pronto para revisão antes do render final"})
            if progress_callback:
                progress_callback("director_review", "Rascunho visual pronto; aguardando aprovação do diretor.")
            draft_render = {
                "status": "draft",
                "strategy": "image_sequence",
                "frames": len(scene_data),
                "width": output_dimensions(request.output_format)[0],
                "height": output_dimensions(request.output_format)[1],
                "aspect_ratio": output_dimensions(request.output_format)[2],
                "output_format": request.output_format,
                "frame_paths": image_result.value.get("frame_paths", []),
            }
            return PipelineOutput(
                project_id=project_id, status="awaiting_approval", title=script_data["title"], script=script_data["script"],
                virality_score=score, render=draft_render, style_fidelity=fidelity, events=events,
                style_profile=style_profile,
                diagnostics=[*diagnostics, "Director Mode pausado: revise prompts e legendas e aprove para renderizar o MP4."],
                scenes=scene_data, research=research_data,
                resolved_providers=resolved_providers,
                resolved_models=resolved_models,
            )
        manual_audio_requested = (autonomy["audio"] in {"manual", "copilot"} and request.audio_filename) or autonomy["audio"] == "manual" or audio_choice == self.manual_audio.name
        audio_provider_name = self.manual_audio.name if manual_audio_requested else (self.audio.name if audio_choice == "auto" else audio_choice)
        manual_audio_operation = lambda: self.manual_audio.create(request.audio_filename or "", output_dir, audio_language)
        piper_audio_operation = lambda: self.audio.create(script_data["script"], output_dir, audio_language)
        if audio_provider_name == self.manual_audio.name:
            audio_candidates = [(self.manual_audio.name, manual_audio_operation), (self.audio.name, piper_audio_operation)]
        else:
            audio_candidates = [(self.audio.name, piper_audio_operation)]
            if request.audio_filename:
                audio_candidates.append((self.manual_audio.name, manual_audio_operation))
        audio_result = self._run_phase("audio", audio_candidates, events, cancel_callback)
        resolved_providers["audio"] = audio_result.provider
        resolved_models["audio"] = resolved_model_label(
            "audio", audio_result.provider, request.model_selection.get("audio"), audio_language
        )
        audio_data = dict(audio_result.value)
        if progress_callback:
            progress_callback("audio", f"Narração pronta com {audio_result.provider}.")
        if request.bgm_filename:
            bgm_path = uploaded_audio_path(request.bgm_filename, "bgm")
            if bgm_path:
                audio_data["bgm_path"] = str(bgm_path)
                resolved_providers["bgm"] = "manual-bgm-upload"
                events.append({"phase": "bgm", "provider": "manual-bgm-upload", "status": "success", "message": "faixa enviada incorporada"})
        elif autonomy["bgm"] in {"autonomous", "copilot"} and media_enabled():
            audio_data["bgm_path"] = create_procedural_bgm(output_dir, audio_data.get("duration_seconds", 35))
            resolved_providers["bgm"] = "local-ambient-bed"
            events.append({"phase": "bgm", "provider": "local-ambient-bed", "status": "success", "message": "trilha ambiente local criada"})
        if progress_callback:
            progress_callback("bgm", "Trilha de fundo pronta." if audio_data.get("bgm_path") else "Trilha de fundo ignorada.")
        if request.sfx_filenames:
            sfx_paths = [uploaded_audio_path(name, "sfx") for name in request.sfx_filenames]
            audio_data["sfx_paths"] = [str(path) for path in sfx_paths if path]
            if audio_data["sfx_paths"]:
                resolved_providers["sfx"] = "manual-sfx-upload"
                events.append({"phase": "sfx", "provider": "manual-sfx-upload", "status": "success", "message": f"{len(audio_data['sfx_paths'])} efeito(s) incorporado(s)"})
        elif autonomy["sfx"] in {"autonomous", "copilot"} and media_enabled():
            audio_data["sfx_paths"] = [create_procedural_sfx(output_dir)]
            resolved_providers["sfx"] = "local-whoosh"
            events.append({"phase": "sfx", "provider": "local-whoosh", "status": "success", "message": "efeito de transição local criado"})
        if progress_callback:
            progress_callback("sfx", f"{len(audio_data.get('sfx_paths', []) or [])} efeito(s) pronto(s).")
        if artifact_callback:
            artifact_callback("audio", {"provider": audio_result.provider, "voice": audio_data.get("voice"), "duration_seconds": audio_data.get("duration_seconds"), "real_audio": audio_data.get("real_audio", False), "has_bgm": bool(audio_data.get("bgm_path")), "sfx_count": len(audio_data.get("sfx_paths", []) or [])})
        scene_duration = round(max(1.0, float(audio_data.get("duration_seconds", request.target_seconds)) / max(1, len(scene_data))), 2)
        scene_durations = [scene_duration] * len(scene_data)
        for index, scene in enumerate(scene_data):
            scene["caption"] = scene_captions[index] if index < len(scene_captions) else str(scene.get("caption", ""))
            scene["duration_seconds"] = scene_durations[index] if index < len(scene_durations) else scene_duration
        storyboard_for_render = dict(image_result.value)
        storyboard_for_render["frames"] = scene_data
        def local_frame_sequence_operation() -> dict[str, Any]:
            """Reliable frame-by-frame safety net for native video providers."""
            return self.video.create_frame_sequence(
                storyboard_for_render,
                audio_data,
                scene_captions,
                output_dir,
                scene_durations,
                "dissolve",
                request.output_format,
            )

        def local_video_operation() -> dict[str, Any]:
            """Use the requested local strategy when no native provider was chosen."""
            if strategy == "image_sequence":
                return local_frame_sequence_operation()
            return self.video.create(
                storyboard_for_render,
                audio_data,
                scene_captions,
                output_dir,
                scene_durations,
                "dissolve",
                request.output_format,
            )

        native_video_providers = {
            self.wan_video.name: self.wan_video,
            self.ltx_video.name: self.ltx_video,
            self.sadtalker.name: self.sadtalker,
        }
        if video_choice in native_video_providers:
            # Keep the explicitly selected engine first, give one other connected
            # native engine a chance, then always retain the local frame fallback.
            # FallbackChain caps this at three attempts and records each transition.
            video_candidates = [
                (
                    video_choice,
                    lambda provider=native_video_providers[video_choice]: provider.create(
                        storyboard_for_render,
                        audio_data,
                        scene_captions,
                        output_dir,
                        scene_durations,
                        "dissolve",
                        request.output_format,
                    ),
                )
            ]
            for provider_name, provider in native_video_providers.items():
                if provider_name != video_choice and provider.available:
                    video_candidates.append(
                        (
                            provider_name,
                            lambda provider=provider: provider.create(
                                storyboard_for_render,
                                audio_data,
                                scene_captions,
                                output_dir,
                                scene_durations,
                                "dissolve",
                                request.output_format,
                            ),
                        )
                    )
                    break
            video_candidates.append((self.video.name, local_frame_sequence_operation))
        else:
            video_candidates = [(self.video.name, local_video_operation)]
        video_result = self._run_phase(
            "video", video_candidates, events,
            cancel_callback,
        )
        resolved_providers["video"] = video_result.provider
        resolved_models["video"] = resolved_model_label(
            "video", video_result.provider, request.model_selection.get("video")
        )
        render_value = dict(video_result.value)
        render_value["frame_paths"] = image_result.value.get("frame_paths", [])
        render_value["audio_sources"] = {
            "voice_path": audio_data.get("audio_path"),
            "bgm_path": audio_data.get("bgm_path"),
            "sfx_paths": audio_data.get("sfx_paths", []) or [],
        }
        render_value["media_provenance"] = {
            "images": image_result.value.get("generation_mode", "storyboard_manifest"),
            "image_provider": image_result.provider,
            "audio": "real_wav" if audio_data.get("real_audio") else "manifest_only",
            "audio_provider": audio_result.provider,
            "video": "real_mp4" if video_result.value.get("status") == "rendered" else "manifest_only",
            "video_provider": video_result.provider,
        }
        if progress_callback:
            progress_callback("video", "Vídeo finalizado e pronto para preview.")
        publish_pack = build_publish_pack(request.topic, script_data["script"], score)
        output = PipelineOutput(
            project_id=project_id, status="completed", title=script_data["title"], script=script_data["script"],
            virality_score=score, render=render_value, style_fidelity=fidelity, style_profile=style_profile, events=events, diagnostics=diagnostics,
            scenes=scene_data, research=research_data, publish_pack=publish_pack,
            resolved_providers=resolved_providers,
            resolved_models=resolved_models,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "project.json").write_text(json.dumps({"project_id": output.project_id, "mode": request.mode, "status": output.status, "title": output.title, "topic": request.topic, "style": request.style, "image_source": request.image_source, "style_profile_id": request.style_profile_id, "narration_language": request.narration_language, "target_seconds": request.target_seconds, "output_format": request.output_format, "stage_autonomy": autonomy, "provider_selection": request.provider_selection, "model_selection": request.model_selection, "resolved_providers": output.resolved_providers, "resolved_models": output.resolved_models, "video_strategy": request.video_strategy, "research": output.research, "script": output.script, "virality_score": output.virality_score, "publish_pack": output.publish_pack, "render": output.render, "style_fidelity": output.style_fidelity, "style_profile": output.style_profile, "scenes": output.scenes, "events": output.events, "diagnostics": output.diagnostics}, ensure_ascii=False, indent=2), encoding="utf-8")
        return output
