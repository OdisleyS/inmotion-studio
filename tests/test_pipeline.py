import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, PropertyMock
import subprocess
import wave

from PIL import Image, ImageDraw

os.environ.setdefault("ENABLE_REAL_MEDIA", "0")

from backend.app.models import GenerateRequest
from backend.app.pipeline import PipelineCancelled, ProductionPipeline, build_publish_pack, build_style_profile, extract_visual_scene_prompts, fit_script_to_target, inspect_sketches, normalize_script_for_narration, score_virality, validate_provider_selection
from backend.app.media import create_storyboard_frames
from backend.app.providers import AntigravityTextProvider, CodexTextProvider, LocalControlNetImageProvider, LocalDiffusionImageProvider, ManualAudioProvider, ManualImageProvider, ProviderError, get_model_catalog, sadtalker_available


class PipelineTests(unittest.TestCase):
    def test_director_script_keeps_only_voice_for_narration(self):
        raw = """Slide 1
Visual: um samurai diante de Tóquio.
Texto na tela: Da tradição ao futuro.
Voz: O Japão mudou profundamente em pouco mais de um século.

Slide 2
Visual: trem-bala cruzando a cidade.
Texto na tela: Inovação.
Voz: A modernização combinou disciplina, indústria e tecnologia."""
        self.assertEqual(
            normalize_script_for_narration(raw),
            "O Japão mudou profundamente em pouco mais de um século. A modernização combinou disciplina, indústria e tecnologia.",
        )
        inline = "[Cena 1] Navios no porto. Texto: A virada. Locução: O Japão estava isolado. [Cena 2] Trem-bala. Locução: Então veio a modernização."
        self.assertEqual(normalize_script_for_narration(inline), "O Japão estava isolado. Então veio a modernização.")
        visual = "[Cena 1] Visual: navios negros chegando ao porto. Locução: O Japão estava isolado. [Cena 2] Visual: trem-bala atravessando Tóquio. Locução: Então veio a modernização."
        self.assertEqual(extract_visual_scene_prompts(visual), ["navios negros chegando ao porto", "trem-bala atravessando Tóquio"])
        bracketed = "Hook sobre o Japão. [ O país vivia isolado. [ A modernização trouxe ferrovias. [ Hoje, Tóquio é futurista."
        self.assertEqual(extract_visual_scene_prompts(bracketed), ["O país vivia isolado", "A modernização trouxe ferrovias", "Hoje, Tóquio é futurista"])
        prose = "O Japão começou com comunidades antigas. Por séculos, samurais e xoguns moldaram o arquipélago. Na Era Meiji, ferrovias e indústrias aceleraram a modernização. Hoje, Tóquio combina tradição e tecnologia."
        prose_prompts = extract_visual_scene_prompts(prose)
        self.assertEqual(len(prose_prompts), 3)
        self.assertIn("comunidades antigas", prose_prompts[0])
        self.assertIn("Era Meiji", prose_prompts[1])
        self.assertIn("Tóquio", prose_prompts[2])
        self.assertNotIn("[", normalize_script_for_narration(bracketed))
        self.assertEqual(normalize_script_for_narration("Corte visual de uma katana. Áudio: O Japão estava isolado."), "O Japão estava isolado.")
        malformed_inline = "Você sabia? 00:04 - 00:11] Visual: arcades em pixel art. Texto na tela: A era de ouro. Nos primeiros arcades, cada pixel precisava ser genial. 00:11 - 00:18] Visual: polígonos e consoles."
        normalized_inline = normalize_script_for_narration(malformed_inline)
        self.assertNotIn("Visual:", normalized_inline)
        self.assertNotIn("Texto na tela:", normalized_inline)
        self.assertNotIn("00:04", normalized_inline)
        self.assertNotIn("A era de ouro", normalized_inline)
        self.assertIn("Nos primeiros arcades", normalized_inline)
        shortened, trimmed = fit_script_to_target("Primeira frase com contexto histórico suficiente para testar o limite. Segunda frase com mais detalhes sobre a transformação social e econômica. Terceira frase explicando o impacto cultural. Quarta frase encerrando a história com uma pergunta.", 10)
        self.assertTrue(trimmed)
        self.assertTrue(shortened.endswith("."))

    def test_autopilot_generates_vertical_output(self):
        result = ProductionPipeline().generate(GenerateRequest(topic="O segredo das frutas vermelhas"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.render["aspect_ratio"], "9:16")
        self.assertEqual(result.render["audio_channels"], 2)
        self.assertIn(result.render["media_provenance"]["video"], {"real_mp4", "manifest_only"})
        self.assertIn(result.render["media_provenance"]["audio"], {"real_wav", "manifest_only"})
        self.assertGreaterEqual(result.virality_score, 50)

    def test_director_mode_pauses_after_visual_draft(self):
        result = ProductionPipeline().generate(
            GenerateRequest(
                mode="director",
                topic="Rascunho para revisão",
                provider_selection={"script": "local-template-text", "image": "local-storyboard"},
            )
        )
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(result.render["status"], "draft")
        self.assertEqual(len(result.scenes), 3)
        self.assertTrue(result.scenes[0]["caption"])
        self.assertFalse(any(event["phase"] == "audio" for event in result.events))

    def test_automatic_image_source_needs_no_sketch_upload(self):
        result = ProductionPipeline().generate(GenerateRequest(topic="Imagem automática", image_source="generate"))
        self.assertEqual(result.status, "completed")

    def test_reference_image_source_requires_upload(self):
        result = ProductionPipeline().generate(GenerateRequest(topic="Imagem por referência", image_source="reference"))
        self.assertEqual(result.status, "blocked")
        self.assertIn("nenhuma imagem foi enviada", result.diagnostics[0])

    def test_manual_image_stage_uses_uploaded_reference_frames(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uploads = root / "uploads"
            output = root / "output"
            uploads.mkdir()
            Image.new("RGB", (640, 480), "white").save(uploads / "drawing.png")
            with patch.dict("os.environ", {"ENABLE_REAL_MEDIA": "1"}, clear=False), patch("backend.app.media.UPLOADS_ROOT", uploads):
                result = ManualImageProvider().create("Desenho manual", "sketch_clone", ["drawing.png"], output, ["cena um"], "vertical")
            self.assertEqual(result["generation_mode"], "manual_uploaded_reference")
            self.assertEqual(len(result["frame_paths"]), 3)
            self.assertTrue(all(Path(path).exists() for path in result["frame_paths"]))
            self.assertEqual(result["reference_usage"], ["drawing.png", "drawing.png", "drawing.png"])

    def test_copilot_audio_tracks_allow_ai_fallback_without_uploads(self):
        result = ProductionPipeline().generate(
            GenerateRequest(
                topic="Mix híbrido sem arquivos",
                stage_autonomy={"audio": "copilot", "bgm": "copilot", "sfx": "copilot"},
            )
        )
        self.assertEqual(result.status, "completed")

    def test_stage_level_hybrid_gate_composes_manual_art_voice_and_ai_tracks(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sketch_root = root / "sketches"
            audio_root = root / "audio"
            bgm_root = root / "bgm"
            sfx_root = root / "sfx"
            generated_root = root / "generated"
            for folder in (sketch_root, audio_root, bgm_root, sfx_root, generated_root):
                folder.mkdir()
            sketch = Image.new("RGB", (640, 640), "white")
            sketch_draw = ImageDraw.Draw(sketch)
            sketch_draw.line((80, 520, 320, 80, 560, 520, 80, 520), fill="black", width=14)
            sketch.save(sketch_root / "character.png")
            with wave.open(str(audio_root / "voice.wav"), "wb") as voice:
                voice.setnchannels(1)
                voice.setsampwidth(2)
                voice.setframerate(16000)
                voice.writeframes(b"\x00\x00" * 16000)
            request = GenerateRequest(
                topic="Gate híbrido de produção",
                style="sketch_clone",
                image_source="reference",
                sketch_filenames=["character.png"],
                audio_filename="voice.wav",
                target_seconds=10,
                stage_autonomy={
                    "research": "autonomous", "script": "autonomous", "image": "autonomous",
                    "audio": "manual", "sfx": "autonomous", "bgm": "copilot", "video": "autonomous",
                },
                provider_selection={"script": "local-template-text", "image": "manual-image-reference", "audio": "manual-audio-upload", "video": "local-ffmpeg-renderer"},
            )
            progress = []
            with patch.dict("os.environ", {"ENABLE_REAL_MEDIA": "1", "ENABLE_AGY_BRIDGE": "0", "ENABLE_CODEX_BRIDGE": "0"}, clear=False), \
                    patch("backend.app.media.UPLOADS_ROOT", sketch_root), \
                    patch("backend.app.media.AUDIO_UPLOADS_ROOT", audio_root), \
                    patch("backend.app.media.BGM_UPLOADS_ROOT", bgm_root), \
                    patch("backend.app.media.SFX_UPLOADS_ROOT", sfx_root), \
                    patch("backend.app.pipeline.GENERATED_ROOT", generated_root):
                result = ProductionPipeline().generate(request, progress_callback=lambda phase, message: progress.append((phase, message)))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.render["aspect_ratio"], "9:16")
        self.assertEqual(result.render["media_provenance"]["audio_provider"], "manual-audio-upload")
        self.assertEqual(result.render["media_provenance"]["audio"], "real_wav")
        self.assertEqual(result.render["media_provenance"]["image_provider"], "manual-image-reference")
        self.assertEqual(result.render["media_provenance"]["images"], "manual_uploaded_reference")
        self.assertTrue(any(event["phase"] == "bgm" and event["provider"] == "local-ambient-bed" for event in result.events))
        self.assertTrue(any(event["phase"] == "sfx" and event["provider"] == "local-whoosh" for event in result.events))
        progress_phases = [phase for phase, _ in progress]
        self.assertIn("audio", progress_phases)
        self.assertIn("bgm", progress_phases)
        self.assertIn("sfx", progress_phases)
        self.assertIn("video", progress_phases)

    def test_manual_audio_track_requires_upload_before_generation(self):
        result = ProductionPipeline().generate(
            GenerateRequest(topic="Mix manual sem arquivo", stage_autonomy={"audio": "manual"})
        )
        self.assertEqual(result.status, "blocked")
        self.assertIn("etapa Áudio está manual", result.diagnostics[0])

    def test_manual_audio_provider_reports_real_duration(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            root.mkdir(exist_ok=True)
            with wave.open(str(root / "voice.wav"), "wb") as voice:
                voice.setnchannels(1)
                voice.setsampwidth(2)
                voice.setframerate(16000)
                voice.writeframes(b"\x00\x00" * (16000 * 4))
            with patch("backend.app.media.AUDIO_UPLOADS_ROOT", root):
                result = ManualAudioProvider().create("voice.wav")
            self.assertEqual(result["duration_seconds"], 4.0)

    def test_diffusion_provider_passes_sketch_to_image_conditioning(self):
        seen_references = []

        def fake_generate(prompt, output_path, seed=0, reference_path=None):
            seen_references.append(reference_path)
            return str(output_path)

        with patch("backend.app.providers.diffusion_available", return_value=True), \
             patch("backend.app.providers.media_enabled", return_value=True), \
             patch("backend.app.providers.uploaded_sketch_path", return_value=Path("reference.png")), \
             patch("backend.app.providers.generate_diffusion_image", side_effect=fake_generate), \
             patch("backend.app.providers.create_storyboard_frames", return_value=["frame.png"]):
            result = LocalDiffusionImageProvider().create("Tema", "sketch_clone", ["reference.png"], Path("output"))
        self.assertEqual(result["generation_mode"], "sd_turbo_local_img2img")
        self.assertEqual(len(seen_references), 3)
        self.assertTrue(all(reference == Path("reference.png") for reference in seen_references))

    def test_controlnet_uses_three_uploaded_references_across_scene_frames(self):
        references = {
            "one.png": Path("one.png"),
            "two.jpg": Path("two.jpg"),
            "three.webp": Path("three.webp"),
        }
        seen_references = []

        def fake_generate(prompt, output_path, reference_path, seed=0):
            seen_references.append(Path(reference_path))
            return str(output_path)

        with patch("backend.app.providers.controlnet_available", return_value=True), \
             patch("backend.app.providers.media_enabled", return_value=True), \
             patch("backend.app.providers.uploaded_sketch_path", side_effect=lambda filename: references.get(filename)), \
             patch("backend.app.providers.generate_controlnet_image", side_effect=fake_generate), \
             patch("backend.app.providers.create_storyboard_frames", return_value=["frame.png"]):
            result = LocalControlNetImageProvider().create(
                "Tema",
                "sketch_clone",
                list(references),
                Path("output"),
            )
            self.assertEqual(seen_references, list(references.values()))
            self.assertEqual(result["reference_strategy"], "scene_cycle")
            self.assertEqual(result["reference_usage"], list(references))
            rerun = LocalControlNetImageProvider().create(
                "Tema",
                "sketch_clone",
                list(references),
                Path("output"),
                scene_prompts=[result["frames"][0]["prompt"]],
            )
            prompt = rerun["frames"][0]["prompt"].casefold()
            self.assertEqual(prompt.count("hand-drawn lineart animation, preserve the reference character and geometry"), 1)

    def test_sketch_fidelity_gate_accepts_three_images(self):
        fidelity = inspect_sketches(["one.png", "two.jpg", "three.webp"], "sketch_clone")
        self.assertEqual(fidelity["status"], "verified")
        self.assertEqual(fidelity["inputs"], 3)
        self.assertTrue(fidelity["line_weight_preserved"])
        self.assertEqual(fidelity["geometry_control"], "ControlNet-ready")

    def test_style_profile_persists_reference_provenance(self):
        profile = build_style_profile(
            "sketch_clone",
            {
                "status": "verified",
                "inputs": 3,
                "style_reference_id": "abc123",
                "quality": [
                    {"filename": "one.png", "width": 1200, "height": 900, "contrast": 42.0, "usable": True},
                    {"filename": "two.jpg", "width": 900, "height": 900, "contrast": 35.0, "usable": True},
                    {"filename": "three.webp", "width": 700, "height": 1000, "contrast": 28.0, "usable": True},
                ],
            },
        )
        self.assertEqual(profile["profile_id"], "abc123")
        self.assertEqual(profile["mode"], "reference")
        self.assertEqual(profile["reference_count"], 3)
        self.assertEqual(profile["conditioning"], "controlnet_lineart")
        self.assertEqual(profile["preservation_targets"], ["geometry", "line_weight", "character_traits"])

    def test_sketch_mode_generates_without_upload(self):
        result = ProductionPipeline().generate(GenerateRequest(style="sketch_clone", topic="Teste"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.style_fidelity["status"], "generated_without_reference")

    def test_virality_score_is_bounded(self):
        self.assertGreaterEqual(score_virality("tema", "Você sabia? segredo? Fique até o final."), 0)
        self.assertLessEqual(score_virality("tema", "x" * 10000), 100)

    def test_publish_pack_contains_editable_metadata(self):
        pack = build_publish_pack("História do Japão", "Você sabia? O Japão mudou profundamente.", 72.5)
        self.assertTrue(pack["title"])
        self.assertIn("#japao", pack["hashtags"])
        self.assertIn("#shorts", pack["hashtags"])
        self.assertEqual(pack["virality_score"], 72.5)

    def test_pipeline_publishes_intermediate_artifacts(self):
        artifacts = {}
        result = ProductionPipeline().generate(
            GenerateRequest(topic="Artefatos intermediários"),
            artifact_callback=lambda kind, value: artifacts.__setitem__(kind, value),
        )
        self.assertEqual(result.status, "completed")
        self.assertTrue({"research", "script", "images", "audio"}.issubset(artifacts))
        self.assertEqual(len(artifacts["images"]["frames"]), 3)
        self.assertTrue(artifacts["script"]["script"])

    def test_video_phase_recovers_from_simulated_primary_outage(self):
        with patch.dict("os.environ", {"SIMULATE_PRIMARY_FAILURES": "video"}):
            result = ProductionPipeline().generate(GenerateRequest(topic="Fallback demonstrável"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.render["aspect_ratio"], "9:16")
        self.assertEqual(result.events[-2]["status"], "failed")
        self.assertEqual(result.events[-1]["status"], "fallback")

    def test_explicit_script_provider_failure_uses_local_fallback(self):
        pipeline = ProductionPipeline()
        catalog = {
            "script": [
                {"name": "codex-cli", "status": "ready", "capabilities": ["text"]},
                {"name": "local-template-text", "status": "ready", "capabilities": ["text"]},
            ],
            "image": [{"name": "local-storyboard", "status": "ready", "capabilities": ["image_generation", "image_sequence"]}],
            "audio": [], "video": [],
        }
        with patch("backend.app.pipeline.get_provider_catalog", return_value=catalog), \
             patch.object(type(pipeline.codex), "available", new_callable=PropertyMock, return_value=True), \
             patch.object(type(pipeline.agy), "available", new_callable=PropertyMock, return_value=False), \
             patch.object(pipeline.codex, "create", side_effect=ProviderError("Codex caiu")):
            result = pipeline.generate(
                GenerateRequest(
                    topic="Fallback explícito de roteiro",
                    provider_selection={"script": "codex-cli", "image": "local-storyboard"},
                )
            )
        self.assertEqual(result.status, "completed")
        script_events = [event for event in result.events if event["phase"] == "script"]
        self.assertEqual(script_events[0]["status"], "failed")
        self.assertEqual(script_events[-1]["provider"], "local-template-text")
        self.assertEqual(script_events[-1]["status"], "fallback")

    def test_explicit_image_provider_failure_uses_storyboard_fallback(self):
        pipeline = ProductionPipeline()
        catalog = {
            "script": [{"name": "local-template-text", "status": "ready", "capabilities": ["text"]}],
            "image": [
                {"name": "local-sd-turbo", "status": "ready", "capabilities": ["image_generation", "image_sequence"]},
                {"name": "local-storyboard", "status": "ready", "capabilities": ["image_generation", "image_sequence"]},
            ],
            "audio": [], "video": [],
        }
        with patch("backend.app.pipeline.get_provider_catalog", return_value=catalog), \
             patch.object(type(pipeline.diffusion), "available", new_callable=PropertyMock, return_value=True), \
             patch.object(pipeline.diffusion, "create", side_effect=ProviderError("SD-Turbo caiu")):
            result = pipeline.generate(
                GenerateRequest(
                    topic="Fallback explícito de imagem",
                    provider_selection={"script": "local-template-text", "image": "local-sd-turbo"},
                )
            )
        self.assertEqual(result.status, "completed")
        image_events = [event for event in result.events if event["phase"] == "image"]
        self.assertEqual(image_events[0]["status"], "failed")
        self.assertEqual(image_events[-1]["provider"], "local-storyboard")
        self.assertEqual(image_events[-1]["status"], "fallback")

    def test_connected_native_video_falls_back_to_local_frame_sequence(self):
        pipeline = ProductionPipeline()
        local_result = {
            "status": "rendered",
            "aspect_ratio": "9:16",
            "strategy": "image_sequence",
            "frames": 3,
        }
        with patch("backend.app.providers.comfyui_native_video_available", return_value=True), \
            patch.object(type(pipeline.wan_video), "available", new_callable=PropertyMock, return_value=True), \
            patch.object(pipeline.wan_video, "create", side_effect=ProviderError("workflow caiu")), \
            patch.object(pipeline.video, "create_frame_sequence", return_value=local_result):
            result = pipeline.generate(
                GenerateRequest(
                    topic="Fallback nativo",
                    provider_selection={"video": "wan-video"},
                    video_strategy="direct_video",
                )
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.render["media_provenance"]["video_provider"], "local-ffmpeg-renderer")
        video_events = [event for event in result.events if event["phase"] == "video"]
        self.assertEqual(video_events[0]["provider"], "wan-video")
        self.assertEqual(video_events[0]["status"], "failed")
        self.assertEqual(video_events[-1]["provider"], "local-ffmpeg-renderer")
        self.assertEqual(video_events[-1]["status"], "fallback")

    def test_sketch_auto_selects_image_sequence_strategy(self):
        request = GenerateRequest(
            style="sketch_clone", topic="Desenho frame a frame", sketch_filenames=["character.png"],
            provider_selection={"script": "local-template-text", "image": "local-storyboard", "audio": "piper-local", "video": "local-ffmpeg-renderer"},
        )
        result = ProductionPipeline().generate(request)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.render["strategy"], "image_sequence")

    def test_unavailable_selected_provider_is_blocked_before_generation(self):
        request = GenerateRequest(topic="Provider indisponível", provider_selection={"video": "wan-video"})
        result = ProductionPipeline().generate(request)
        self.assertEqual(result.status, "blocked")
        self.assertIn("ainda não pode ser usado", result.diagnostics[0])

    def test_sadtalker_is_planned_without_local_engine(self):
        self.assertFalse(sadtalker_available())
        model = next(item for item in get_model_catalog()["video"] if item["name"] == "sadtalker-lipsync")
        self.assertEqual(model["status"], "planned")
        self.assertIn("lip_sync", model["capabilities"])

    def test_unavailable_sadtalker_selection_is_blocked_before_generation(self):
        result = ProductionPipeline().generate(GenerateRequest(topic="Avatar", provider_selection={"video": "sadtalker-lipsync"}))
        self.assertEqual(result.status, "blocked")
        self.assertIn("sadtalker-lipsync", result.diagnostics[0])

    def test_native_video_requires_a_connected_video_generation_capability(self):
        result = ProductionPipeline().generate(GenerateRequest(topic="Vídeo nativo", video_strategy="direct_video"))
        self.assertEqual(result.status, "blocked")
        self.assertIn("video_generation", result.diagnostics[0])

    def test_provider_capability_is_checked_for_image_stage(self):
        catalog = {
            "image": [{"name": "local-sd-turbo", "status": "ready", "capabilities": ["audio"]}],
            "script": [],
            "audio": [],
            "video": [],
        }
        with patch("backend.app.pipeline.get_provider_catalog", return_value=catalog):
            errors = validate_provider_selection({"image": "local-sd-turbo"}, ProductionPipeline())
        self.assertTrue(any("image_generation" in error for error in errors))

    def test_codex_cli_bridge_parses_json_agent_message(self):
        output = '\n'.join([
            '{"type":"thread.started","thread_id":"test"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"O Japão evoluiu de um arquipélago feudal para uma potência moderna."}}',
        ])
        completed = subprocess.CompletedProcess(["codex"], 0, stdout=output, stderr="")
        with patch.dict("os.environ", {"ENABLE_CODEX_BRIDGE": "1", "CODEX_COMMAND": "codex", "CODEX_MODEL": "gpt-5.6-luna"}, clear=False), patch("backend.app.providers.shutil.which", return_value="codex.exe"), patch("backend.app.providers.subprocess.run", return_value=completed) as run:
            result = CodexTextProvider().create("História do Japão", "dynamic_slideshow", None)
        self.assertIn("arquipélago feudal", result["script"])
        self.assertIn("--sandbox", run.call_args.args[0])

    def test_antigravity_headless_bridge_approves_configured_permissions(self):
        completed = subprocess.CompletedProcess(["agy"], 0, stdout="Roteiro real.", stderr="")
        with patch.dict("os.environ", {"ENABLE_AGY_BRIDGE": "1", "AGY_COMMAND": "agy", "AGY_SKIP_PERMISSIONS": "1"}, clear=False), patch("backend.app.providers.shutil.which", return_value="agy.exe"), patch("backend.app.providers.subprocess.run", return_value=completed) as run:
            result = AntigravityTextProvider().create("Tema", "dynamic_slideshow", None)
        self.assertEqual(result["script"], "Roteiro real.")
        self.assertIn("--dangerously-skip-permissions", run.call_args.args[0])

    def test_selected_model_routes_automatic_provider(self):
        request = GenerateRequest(
            topic="Modelo escolhido pelo usuário",
            model_selection={"script": "local-template-text", "image": "local-storyboard"},
        )
        result = ProductionPipeline().generate(request)
        self.assertEqual(result.status, "completed")
        self.assertTrue(any(event["phase"] == "script" and event["provider"] == "local-template-text" for event in result.events))
        self.assertTrue(any(event["phase"] == "image" and event["provider"] == "local-storyboard" for event in result.events))
        self.assertEqual(result.resolved_models["script"], "local-template-text")
        self.assertEqual(result.resolved_models["image"], "local-storyboard")

    def test_codex_runtime_model_name_is_accepted_as_catalog_alias(self):
        pipeline = ProductionPipeline()
        provider_catalog = {
            "script": [{"name": "codex-cli", "status": "ready", "capabilities": ["text"]}],
            "image": [],
            "audio": [],
            "video": [],
        }
        model_catalog = {
            "script": [{
                "name": "codex-gpt-5.6-luna",
                "aliases": ["gpt-5.6-luna"],
                "provider": "codex-cli",
                "status": "ready",
                "capabilities": ["text"],
            }],
            "image": [],
            "audio": [],
            "video": [],
        }
        with patch("backend.app.pipeline.get_provider_catalog", return_value=provider_catalog), patch("backend.app.pipeline.get_model_catalog", return_value=model_catalog):
            errors = validate_provider_selection(
                {"script": "codex-cli"},
                pipeline,
                model_selection={"script": "gpt-5.6-luna"},
            )
        self.assertEqual(errors, [])

    def test_pipeline_honors_cancellation_before_generation(self):
        with self.assertRaises(PipelineCancelled):
            ProductionPipeline().generate(GenerateRequest(topic="Cancelamento"), cancel_callback=lambda: True)

    def test_low_score_triggers_hook_recovery(self):
        with patch("backend.app.pipeline.score_virality", side_effect=[20.0, 82.0]):
            result = ProductionPipeline().generate(
                GenerateRequest(topic="Recuperação de hook", provider_selection={"script": "local-template-text"})
            )
        self.assertEqual(result.status, "completed")
        self.assertTrue(any(event["phase"] == "script-rewrite" and event["status"] == "success" for event in result.events))

    def test_uploaded_sketch_is_composited_into_generated_frame(self):
        with TemporaryDirectory() as temp_dir:
            upload_root = Path(temp_dir) / "uploads"
            output_root = Path(temp_dir) / "output"
            upload_root.mkdir()
            Image.new("RGBA", (80, 80), (255, 0, 0, 255)).save(upload_root / "reference.png")
            with patch("backend.app.media.UPLOADS_ROOT", upload_root):
                paths = create_storyboard_frames("Teste", "sketch_clone", [{"index": 1, "prompt": "Cena", "sketch_inputs": ["reference.png"]}], output_root)
            rendered = Image.open(paths[0]).convert("RGB")
            red_pixel = rendered.getpixel((540, 420))
            self.assertGreater(red_pixel[0], 200)
            self.assertLess(red_pixel[1], 80)

    def test_low_quality_sketch_is_rejected_with_reupload_diagnostic(self):
        with TemporaryDirectory() as temp_dir:
            upload_root = Path(temp_dir) / "uploads"
            upload_root.mkdir()
            Image.new("L", (64, 64), 200).save(upload_root / "blurry.png")
            with patch("backend.app.media.UPLOADS_ROOT", upload_root):
                fidelity = inspect_sketches(["blurry.png"], "sketch_clone")
            self.assertEqual(fidelity["status"], "needs_upload")
            self.assertFalse(fidelity["quality"][0]["usable"])
