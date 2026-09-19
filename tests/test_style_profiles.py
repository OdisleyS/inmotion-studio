from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.style_profiles import create_style_profile, load_style_profile, list_style_profiles


class StyleProfileTests(unittest.TestCase):
    def test_profile_persists_multiple_workspace_references(self):
        quality = [
            {"filename": name, "usable": True, "width": 640, "height": 420}
            for name in ("one.png", "two.png", "three.png")
        ]
        with tempfile.TemporaryDirectory() as folder:
            profile_root = Path(folder) / "profiles"
            with patch("backend.app.style_profiles.STYLE_PROFILES_ROOT", profile_root), patch(
                "backend.app.style_profiles.inspect_reference_quality",
                side_effect=quality,
            ):
                profile = create_style_profile(
                    "Meu traço",
                    ["one.png", "two.png", "three.png"],
                    {"status": "verified", "style_reference_id": "multi-ref"},
                )
                loaded = load_style_profile(profile["profile_id"])
                listed = list_style_profiles()

            self.assertEqual(profile["reference_count"], 3)
            self.assertEqual(profile["reference_files"], ["one.png", "two.png", "three.png"])
            self.assertEqual(loaded["conditioning"], "controlnet_lineart")
            self.assertEqual(loaded["style_reference_id"], "multi-ref")
            self.assertEqual(len(listed), 1)


if __name__ == "__main__":
    unittest.main()
