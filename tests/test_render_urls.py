from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from backend.app.main import _decorate_render, _regenerate_scene_frame, list_uploaded_sketches, serve_uploaded_sketch


class RenderUrlTests(unittest.TestCase):
    def test_audio_sources_are_exposed_as_safe_media_urls(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / "project"
            project.mkdir()
            voice = project / "narration_pt_BR.wav"
            bgm = project / "bgm_local_ambient.wav"
            sfx = project / "sfx_local_whoosh.wav"
            frame = project / "frame_001.png"
            for path in (voice, bgm, sfx, frame):
                path.touch()
            with patch("backend.app.main.GENERATED_ROOT", root):
                render = _decorate_render({
                    "path": str(project / "video.mp4"),
                    "frame_paths": [str(frame)],
                    "audio_sources": {
                        "voice_path": str(voice),
                        "bgm_path": str(bgm),
                        "sfx_paths": [str(sfx)],
                    },
                })
            self.assertNotIn("audio_sources", render)
            self.assertEqual(render["audio_urls"]["voice"], "/media/project/narration_pt_BR.wav")
            self.assertEqual(render["audio_urls"]["bgm"], "/media/project/bgm_local_ambient.wav")
            self.assertEqual(render["audio_urls"]["sfx"], ["/media/project/sfx_local_whoosh.wav"])
            self.assertEqual(render["frame_urls"], ["/media/project/frame_001.png"])

    def test_editor_reuses_the_original_real_image_provider(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "edited" / "scene_001"
            fake_pipeline = MagicMock()
            fake_pipeline.diffusion.available = True
            fake_pipeline.diffusion.create.return_value = {
                "generated_image_paths": [str(output / "ai_image_001.png")],
                "generation_mode": "sd_turbo_local_text_to_image",
            }
            with patch("backend.app.main.pipeline", fake_pipeline):
                path, mode = _regenerate_scene_frame(
                    {"topic": "Tema", "style": "dynamic_slideshow", "provider_selection": {"image": "local-sd-turbo"}},
                    {"prompt": "Cena alterada"},
                    output,
                    "vertical",
                )
            self.assertEqual(path, str(output / "ai_image_001.png"))
            self.assertEqual(mode, "sd_turbo_local_text_to_image")
            fake_pipeline.diffusion.create.assert_called_once()

    def test_workspace_sketch_catalog_exposes_existing_reference_safely(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "attached.png").write_bytes(b"png")
            (root / "ignore.txt").write_text("no", encoding="utf-8")
            quality = {"filename": "attached.png", "usable": True, "width": 640, "height": 480}
            with patch("backend.app.main.UPLOADS_ROOT", root), patch("backend.app.main.inspect_reference_quality", return_value=quality):
                catalog = list_uploaded_sketches()
                response = serve_uploaded_sketch("attached.png")
            self.assertEqual(catalog[0]["filename"], "attached.png")
            self.assertEqual(catalog[0]["quality"]["usable"], True)
            self.assertEqual(Path(response.path), root / "attached.png")
            with patch("backend.app.main.UPLOADS_ROOT", root):
                with self.assertRaises(Exception):
                    serve_uploaded_sketch("..\\ignore.txt")


if __name__ == "__main__":
    unittest.main()
