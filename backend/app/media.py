from __future__ import annotations

import os
import math
import random
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from textwrap import wrap
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageStat


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPER_ROOT = PROJECT_ROOT / "assets" / "models" / "piper"
GENERATED_ROOT = PROJECT_ROOT / "generated"
UPLOADS_ROOT = PROJECT_ROOT / "assets" / "uploads" / "sketches"
AUDIO_UPLOADS_ROOT = PROJECT_ROOT / "assets" / "uploads" / "audio"
BGM_UPLOADS_ROOT = PROJECT_ROOT / "assets" / "uploads" / "bgm"
SFX_UPLOADS_ROOT = PROJECT_ROOT / "assets" / "uploads" / "sfx"
VOICE_MODELS = {
    "pt_BR": (PIPER_ROOT / "pt_BR-faber-medium.onnx", PIPER_ROOT / "pt_BR-faber-medium.onnx.json"),
    "en_US": (PIPER_ROOT / "en_US-amy-medium.onnx", PIPER_ROOT / "en_US-amy-medium.onnx.json"),
}
OUTPUT_FORMATS: dict[str, tuple[int, int, str]] = {
    "vertical": (1080, 1920, "9:16"),
    "horizontal": (1920, 1080, "16:9"),
    "square": (1080, 1080, "1:1"),
}


def output_dimensions(output_format: str = "vertical") -> tuple[int, int, str]:
    return OUTPUT_FORMATS.get(output_format, OUTPUT_FORMATS["vertical"])


def voice_model_paths(language: str) -> tuple[Path, Path]:
    default_model, default_config = VOICE_MODELS.get(language, VOICE_MODELS["pt_BR"])
    prefix = "PIPER_PT" if language == "pt_BR" else "PIPER_EN"
    model = Path(os.getenv(f"{prefix}_MODEL", str(default_model)))
    config = Path(os.getenv(f"{prefix}_CONFIG", str(default_config)))
    if not model.is_absolute():
        model = PROJECT_ROOT / model
    if not config.is_absolute():
        config = PROJECT_ROOT / config
    return model, config


class MediaError(RuntimeError):
    pass


def media_enabled() -> bool:
    return os.getenv("ENABLE_REAL_MEDIA", "1") == "1"


def piper_executable() -> str | None:
    candidate = Path(sys.executable).with_name("piper.exe")
    if candidate.exists():
        return str(candidate)
    return shutil.which("piper")


def piper_voice_available(language: str = "pt_BR") -> bool:
    model, config = voice_model_paths(language)
    return piper_executable() is not None and model.exists() and config.exists()


def uploaded_audio_path(filename: str | None, kind: str = "audio") -> Path | None:
    """Resolve only files previously stored in the managed local upload folders."""
    if not filename:
        return None
    roots = {"audio": AUDIO_UPLOADS_ROOT, "bgm": BGM_UPLOADS_ROOT, "sfx": SFX_UPLOADS_ROOT}
    root = roots.get(kind, AUDIO_UPLOADS_ROOT)
    candidate = root / Path(filename).name
    return candidate if candidate.exists() and candidate.is_file() else None


def audio_duration_seconds(path: Path) -> float:
    """Read duration for uploaded WAV/audio files without trusting filename metadata."""
    if not path.exists() or not path.is_file():
        return 0.0
    try:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as audio:
                return round(audio.getnframes() / max(1, audio.getframerate()), 2)
    except (OSError, wave.Error):
        pass
    ffmpeg = ffmpeg_executable()
    if not ffmpeg:
        return 0.0
    try:
        probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", f"{probe.stdout}\n{probe.stderr}")
        if match:
            hours, minutes, seconds = match.groups()
            return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 2)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return 0.0


def uploaded_sketch_path(filename: str | None) -> Path | None:
    """Resolve a managed drawing reference without allowing path traversal."""
    if not filename:
        return None
    candidate = UPLOADS_ROOT / Path(filename).name
    return candidate if candidate.exists() and candidate.is_file() else None


def ffmpeg_executable() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _draw_wrapped(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], width: int, font, fill) -> int:
    lines = wrap(text or "", width=max(20, width // max(1, int(font.size * 0.55))))
    y = xy[1]
    for line in lines[:8]:
        draw.text((xy[0], y), line, font=font, fill=fill)
        y += int(font.size * 1.25)
    return y


def _reference_image(filename: str) -> Image.Image | None:
    """Load only a basename from the managed upload directory."""
    safe_name = Path(filename).name
    path = UPLOADS_ROOT / safe_name
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except (OSError, ValueError):
        return None


def _generated_image(filename: str) -> Image.Image | None:
    path = Path(filename)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_absolute() or not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except (OSError, ValueError):
        return None


def inspect_reference_quality(filename: str) -> dict[str, Any] | None:
    """Measure basic photo quality before a sketch enters the style pipeline."""
    safe_name = Path(filename).name
    path = UPLOADS_ROOT / safe_name
    if not path.exists():
        return None
    try:
        with Image.open(path) as source:
            image = source.convert("L")
            width, height = image.size
            contrast = round(float(ImageStat.Stat(image).stddev[0]), 2)
            usable = min(width, height) >= 128 and contrast >= 8.0
            return {"filename": safe_name, "width": width, "height": height, "contrast": contrast, "usable": usable}
    except (OSError, ValueError):
        return {"filename": safe_name, "usable": False, "message": "arquivo de imagem inválido"}


def _line_art_overlay(reference: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Extract a restrained transparent ink layer from a photographed sketch."""
    gray = ImageOps.contain(reference.convert("L"), size)
    gray = ImageOps.autocontrast(gray)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    alpha = edges.point(lambda value: 255 if value > 35 else 0)
    overlay = Image.new("RGBA", gray.size, (22, 19, 18, 0))
    overlay.putalpha(alpha)
    return overlay


def create_storyboard_frames(topic: str, style: str, frames: list[dict[str, Any]], output_dir: Path, output_format: str = "vertical") -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height, aspect_ratio = output_dimensions(output_format)
    palettes = {
        "sketch_clone": ((32, 29, 25), (245, 224, 174), (226, 122, 78)),
        "couples_fruits_2d": ((61, 25, 46), (255, 219, 122), (255, 119, 151)),
        "avatar_narrator": ((14, 34, 53), (198, 235, 255), (93, 196, 255)),
        "dynamic_slideshow": ((24, 38, 31), (226, 248, 189), (184, 230, 96)),
    }
    dark, light, accent = palettes.get(style, palettes["dynamic_slideshow"])
    paths: list[str] = []
    title_font, body_font, meta_font = _font(72), _font(35), _font(22)
    for index, frame in enumerate(frames or [{"index": 1, "prompt": topic}], start=1):
        generated_references = [
            image
            for image in (
                _generated_image(str(name))
                for name in frame.get("generated_image_paths", [])
            )
            if image is not None
        ]
        sketches = [
            image
            for image in (
                _reference_image(str(name))
                for name in frame.get("sketch_inputs", [])
            )
            if image is not None
        ]
        full_generated = bool(generated_references)
        if full_generated:
            # AI-generated scenes should be usable as actual video shots, not
            # displayed as a small card inside a diagnostic storyboard.
            image = ImageOps.fit(
                generated_references[0].convert("RGB"),
                (width, height),
                method=Image.Resampling.LANCZOS,
            ).convert("RGBA")
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            overlay_draw.rectangle(
                (0, int(height * 0.65), width, height),
                fill=(0, 0, 0, 172),
            )
            image = Image.alpha_composite(image, overlay).convert("RGB")
            draw = ImageDraw.Draw(image)
        else:
            image = Image.new("RGB", (width, height), dark)
            draw = ImageDraw.Draw(image)
            for y in range(height):
                ratio = y / max(1, height - 1)
                color = tuple(int(dark[i] * (1 - ratio) + accent[i] * ratio * 0.35) for i in range(3))
                draw.line((0, y, width, y), fill=color)
            draw.ellipse((int(width * 0.64), int(height * 0.08), int(width * 1.12), int(height * 0.36)), fill=accent)
            draw.ellipse((int(-width * 0.17), int(height * 0.73), int(width * 0.38), int(height * 1.04)), outline=light, width=8)
            if sketches:
                reference = ImageOps.contain(sketches[0], (int(width * 0.76), int(height * 0.23)))
                left = (width - reference.width) // 2
                top = int(height * 0.11)
                image.paste(reference, (left, top), reference)
                if style == "sketch_clone":
                    ink = _line_art_overlay(sketches[0], reference.size)
                    image.paste(ink, (left, top), ink)
                draw.rounded_rectangle((left - 8, top - 8, left + reference.width + 8, top + reference.height + 8), radius=12, outline=light, width=4)
                draw.text((left, top + reference.height + 18), "SKETCH REFERENCE · LINE-ART PRESERVADO", font=meta_font, fill=light)
        badge_left, badge_top = int(width * 0.063), int(height * 0.039)
        badge_right, badge_bottom = int(width * 0.325), int(height * 0.066)
        draw.rounded_rectangle((badge_left, badge_top, badge_right, badge_bottom), radius=20, fill=light)
        draw.text((int(width * 0.085), int(height * 0.046)), f"FRAME {index:02d} · {aspect_ratio}", font=meta_font, fill=dark)
        title_y = int(
            height * (0.58 if full_generated else (0.44 if aspect_ratio == "9:16" else 0.43))
        )
        content_width = int(width * 0.83)
        y = _draw_wrapped(draw, topic, (int(width * 0.063), title_y), content_width, title_font, light)
        draw.line((int(width * 0.063), y + 24, int(width * 0.935), y + 24), fill=accent, width=5)
        visual_detail = (
            str(frame.get("action", "Cena gerada automaticamente"))
            if full_generated
            else " · ".join(
                filter(
                    None,
                    [
                        str(frame.get("prompt", "Cena gerada localmente")),
                        str(frame.get("subject", "")),
                        str(frame.get("action", "")),
                    ],
                )
            )
        )
        _draw_wrapped(draw, visual_detail, (int(width * 0.063), y + 75), content_width, body_font, light)
        footer = "AI FRAME · SD-TURBO LOCAL" if full_generated else "IN-HOUSE VIDEO STUDIO · LOCAL FRAME GENERATOR"
        draw.text((int(width * 0.063), int(height * 0.94)), footer, font=meta_font, fill=light)
        path = output_dir / f"frame_{index:03d}.png"
        image.save(path, "PNG", optimize=True)
        paths.append(str(path))
    return paths


def create_reference_frames(topic: str, style: str, frames: list[dict[str, Any]], output_dir: Path, output_format: str = "vertical") -> list[str]:
    """Turn uploaded drawings into real scene frames for the manual image stage.

    The drawing is kept as the visual source and only contained inside the
    requested canvas; no synthetic storyboard art is substituted.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height, _ = output_dimensions(output_format)
    paths: list[str] = []
    for index, frame in enumerate(frames, start=1):
        reference = _reference_image(str(frame.get("manual_reference", "")))
        if reference is None:
            raise MediaError(f"Referência manual não encontrada: {frame.get('manual_reference', '')}")
        canvas = Image.new("RGB", (width, height), (246, 242, 230) if style == "sketch_clone" else (18, 22, 20))
        contained = ImageOps.contain(reference.convert("RGB"), (width - 96, height - 180))
        left = (width - contained.width) // 2
        top = (height - contained.height) // 2
        canvas.paste(contained, (left, top))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((left - 10, top - 10, left + contained.width + 10, top + contained.height + 10), radius=12, outline=(110, 134, 92), width=4)
        draw.text((48, 42), f"REFERÊNCIA MANUAL · CENA {index:02d}", font=_font(24), fill=(44, 56, 42) if style == "sketch_clone" else (220, 238, 204))
        path = output_dir / f"manual_reference_frame_{index:03d}.png"
        canvas.save(path, "PNG", optimize=True)
        paths.append(str(path))
    return paths


def synthesize_piper(script: str, output_dir: Path, language: str = "pt_BR") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    model, config = voice_model_paths(language)
    executable = piper_executable()
    output_path = output_dir / f"narration_{language}.wav"
    if not executable or not model.exists() or not config.exists():
        return {"duration_seconds": max(10, round(len(script.split()) / 2.6, 1)), "voice": f"{language}-manifest", "stereo": True, "real_audio": False}
    safe_script = script.encode("utf-8", "replace").decode("utf-8")
    safe_script = "".join(char for char in safe_script if not 0xD800 <= ord(char) <= 0xDFFF)
    completed = subprocess.run(
        [executable, "--model", str(model), "--config", str(config), "--output_file", str(output_path), "--sentence_silence", "0.18"],
        input=safe_script, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
    )
    if completed.returncode != 0 or not output_path.exists():
        raise MediaError(completed.stderr.strip() or "Piper não conseguiu sintetizar o áudio")
    with wave.open(str(output_path), "rb") as audio:
        duration = audio.getnframes() / float(audio.getframerate())
    return {"duration_seconds": round(duration, 2), "voice": f"piper-{language}", "stereo": False, "real_audio": True, "audio_path": str(output_path)}


def create_procedural_bgm(output_dir: Path, duration_seconds: float = 35.0) -> str:
    """Create a quiet local fallback bed when no licensed music file is supplied."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "bgm_local_ambient.wav"
    rate = 44100
    frames = int(rate * max(5.0, duration_seconds))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        for index in range(frames):
            time_position = index / rate
            envelope = min(1.0, time_position / 1.5, (duration_seconds - time_position) / 1.5)
            value = 0.045 * envelope * (math.sin(2 * math.pi * 196 * time_position) + 0.35 * math.sin(2 * math.pi * 247 * time_position))
            sample = int(max(-1.0, min(1.0, value)) * 32767)
            output.writeframesraw(sample.to_bytes(2, "little", signed=True) * 2)
    return str(path)


def create_procedural_sfx(output_dir: Path, duration_seconds: float = 1.2) -> str:
    """Create a short local whoosh fallback for the SFX track."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "sfx_local_whoosh.wav"
    rate = 44100
    frames = int(rate * duration_seconds)
    noise = random.Random(17)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        for index in range(frames):
            progress = index / max(1, frames - 1)
            envelope = math.sin(math.pi * progress) ** 0.7
            tone = math.sin(2 * math.pi * (280 + 820 * progress) * index / rate)
            value = 0.12 * envelope * (0.7 * tone + 0.3 * (noise.random() * 2 - 1))
            sample = int(max(-1.0, min(1.0, value)) * 32767)
            output.writeframesraw(sample.to_bytes(2, "little", signed=True) * 2)
    return str(path)


def _prepare_render_frames(frame_paths: list[str], captions: list[str] | None, scene_durations: list[float] | None, transition: str, output_dir: Path, motion_style: str = "ken_burns") -> tuple[list[str], list[float]]:
    """Create a render-only frame set with captions, motion and optional dissolves."""
    render_dir = output_dir / "render_frames"
    render_dir.mkdir(parents=True, exist_ok=True)
    base_durations = [max(1.0, float(value)) for value in (scene_durations or [])[:len(frame_paths)]]
    if len(base_durations) < len(frame_paths):
        default_duration = max(1.0, 35.0 / max(1, len(frame_paths)))
        base_durations.extend([default_duration] * (len(frame_paths) - len(base_durations)))
    caption_font = _font(42)
    output_paths: list[str] = []
    output_durations: list[float] = []
    for index, source_name in enumerate(frame_paths):
        source = Path(source_name)
        if not source.exists():
            continue
        try:
            image = Image.open(source).convert("RGB")
        except (OSError, ValueError):
            continue
        caption = str((captions or [""])[index] if index < len(captions or []) else "").strip()
        if caption:
            draw = ImageDraw.Draw(image, "RGBA")
            lines = wrap(caption, width=38)[:4]
            line_height = int(caption_font.size * 1.2)
            box_height = line_height * len(lines) + 34
            top = image.height - box_height - 90
            draw.rounded_rectangle((54, top, image.width - 54, top + box_height), radius=18, fill=(8, 13, 10, 215), outline=(226, 248, 189, 230), width=2)
            for line_index, line in enumerate(lines):
                draw.text((78, top + 16 + line_index * line_height), line, font=caption_font, fill=(242, 249, 229, 255))
        if motion_style == "static":
            path = render_dir / f"scene_{len(output_paths) + 1:04d}.png"
            image.save(path, "PNG", optimize=True)
            output_paths.append(str(path))
            output_durations.append(base_durations[index])
        else:
            # A local image-sequence video should still feel animated. Generate a
            # small Ken Burns path per scene so drawings/slideshows have gentle
            # motion even when no native video model is connected.
            motion_frames = max(4, min(12, int(round(base_durations[index] * 3))))
            for motion_index in range(motion_frames):
                progress = motion_index / max(1, motion_frames - 1)
                scale = 1.0 + 0.055 * progress
                resized = image.resize((max(image.width, round(image.width * scale)), max(image.height, round(image.height * scale))), Image.Resampling.LANCZOS)
                available_x = max(0, resized.width - image.width)
                available_y = max(0, resized.height - image.height)
                pan = 0.5 + 0.35 * math.sin(progress * math.pi)
                left = round(available_x * pan)
                top = round(available_y * (1.0 - 0.4 * progress))
                motion_image = resized.crop((left, top, left + image.width, top + image.height))
                path = render_dir / f"scene_{len(output_paths) + 1:04d}.png"
                motion_image.save(path, "PNG", optimize=True)
                output_paths.append(str(path))
                output_durations.append(base_durations[index] / motion_frames)
        if transition == "dissolve" and index < len(frame_paths) - 1:
            next_source = Path(frame_paths[index + 1])
            try:
                next_image = Image.open(next_source).convert("RGB").resize(image.size)
                for blend_index, alpha in enumerate((0.25, 0.5, 0.75), start=1):
                    blend = Image.blend(image, next_image, alpha)
                    blend_path = render_dir / f"scene_{len(output_paths) + 1:04d}_dissolve.png"
                    blend.save(blend_path, "PNG", optimize=True)
                    output_paths.append(str(blend_path))
                    output_durations.append(0.12)
            except (OSError, ValueError):
                pass
    return output_paths, output_durations


def _verify_render_output(ffmpeg: str, output_path: Path, expected_width: int = 1080, expected_height: int = 1920) -> dict[str, Any]:
    """Inspect the actual MP4 stream layout instead of trusting render metadata."""
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(output_path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
    report = f"{probe.stdout}\n{probe.stderr}"
    video_match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", report, re.IGNORECASE)
    audio_match = re.search(r"Audio:.*?(stereo|2 channels)", report, re.IGNORECASE)
    width = int(video_match.group(1)) if video_match else 0
    height = int(video_match.group(2)) if video_match else 0
    stereo = bool(audio_match)
    if (width, height) != (expected_width, expected_height) or not stereo:
        raise MediaError(f"Validação do MP4 falhou: {width}x{height}, esperado={expected_width}x{expected_height}, áudio={'stereo' if stereo else 'ausente/mono'}")
    return {"status": "passed", "video": f"{expected_width}x{expected_height}", "audio": "stereo"}


def render_frame_video(frame_paths: list[str], audio: dict[str, Any], output_dir: Path, captions: list[str] | None = None, scene_durations: list[float] | None = None, transition: str = "cut", output_format: str = "vertical", motion_style: str = "ken_burns") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height, aspect_ratio = output_dimensions(output_format)
    safe_motion_style = motion_style if motion_style in {"ken_burns", "static"} else "ken_burns"
    ffmpeg = ffmpeg_executable()
    output_path = output_dir / "video.mp4"
    if not ffmpeg or not frame_paths or not audio.get("audio_path"):
        return {"format": "mp4", "status": "manifest", "width": width, "height": height, "aspect_ratio": aspect_ratio, "output_format": output_format, "strategy": "image_sequence", "frames": len(frame_paths), "audio_channels": 1 if audio.get("audio_path") else 0, "motion_style": safe_motion_style}
    render_frames, render_durations = _prepare_render_frames(frame_paths, captions, scene_durations, transition if transition in {"cut", "dissolve"} else "cut", output_dir, safe_motion_style)
    if not render_frames:
        raise MediaError("Nenhum frame válido para renderização")
    concat_path = output_dir / "render_frames.txt"
    concat_lines = []
    for path, duration in zip(render_frames, render_durations):
        concat_lines.extend([f"file '{Path(path).as_posix()}'", f"duration {duration:.3f}"])
    concat_lines.append(f"file '{Path(render_frames[-1]).as_posix()}'")
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-i", audio["audio_path"]]
    extra_audio = []
    if audio.get("bgm_path"):
        command += ["-stream_loop", "-1", "-i", audio["bgm_path"]]
        extra_audio.append("bgm")
    for sfx_path in audio.get("sfx_paths", []) or []:
        command += ["-i", sfx_path]
        extra_audio.append("sfx")
    def mix_level(name: str, fallback: float) -> float:
        try:
            return max(0.0, min(1.5, float(audio.get(name, fallback))))
        except (TypeError, ValueError):
            return fallback

    voice_volume = mix_level("voice_volume", 1.0)
    bgm_volume = mix_level("bgm_volume", 0.16)
    sfx_volume = mix_level("sfx_volume", 0.28)
    filter_parts = [f"[1:a]volume={voice_volume:.3f}[voice]"]
    mix_inputs = ["[voice]"]
    next_index = 2
    if audio.get("bgm_path"):
        filter_parts.append(f"[{next_index}:a]volume={bgm_volume:.3f}[bgm]")
        mix_inputs.append("[bgm]")
        next_index += 1
    for sfx_index, _ in enumerate(audio.get("sfx_paths", []) or [], start=next_index):
        filter_parts.append(f"[{sfx_index}:a]volume={sfx_volume:.3f}[sfx{sfx_index}]")
        mix_inputs.append(f"[sfx{sfx_index}]")
    if len(mix_inputs) > 1:
        filter_parts.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=2[aout]")
        audio_map = "[aout]"
    else:
        audio_map = "[voice]"
    command += ["-filter_complex", ";".join(filter_parts), "-map", "0:v:0", "-map", audio_map, "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(output_path)]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
    if completed.returncode != 0 or not output_path.exists():
        raise MediaError(completed.stderr[-1000:] or "FFmpeg não conseguiu montar o vídeo")
    validation = _verify_render_output(ffmpeg, output_path, width, height)
    base_scene_durations = [max(1.0, float(value)) for value in (scene_durations or [])[:len(frame_paths)]]
    if len(base_scene_durations) < len(frame_paths):
        base_scene_durations.extend([max(1.0, 35.0 / max(1, len(frame_paths)))] * (len(frame_paths) - len(base_scene_durations)))
    return {"format": "mp4", "status": "rendered", "path": str(output_path), "width": width, "height": height, "aspect_ratio": aspect_ratio, "output_format": output_format, "strategy": "image_sequence", "frames": len(frame_paths), "audio_channels": 2, "caption_count": len([caption for caption in (captions or []) if str(caption).strip()]), "scene_durations": base_scene_durations, "transition": transition, "motion_style": safe_motion_style, "validation": validation, "audio_mix": {"voice": voice_volume, "bgm": bgm_volume, "sfx": sfx_volume}, "mixed_tracks": {"voice": True, "bgm": bool(audio.get("bgm_path")), "sfx": len(audio.get("sfx_paths", []) or [])}}


def mux_native_video(video_path: str | Path, audio: dict[str, Any], output_dir: Path, output_format: str = "vertical") -> dict[str, Any]:
    """Attach the local narration/mix to a native video engine output."""
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height, aspect_ratio = output_dimensions(output_format)
    ffmpeg = ffmpeg_executable()
    source = Path(video_path)
    output_path = output_dir / "video.mp4"
    if not ffmpeg or not source.exists() or not audio.get("audio_path"):
        return {"format": "mp4", "status": "manifest", "width": width, "height": height, "aspect_ratio": aspect_ratio, "output_format": output_format, "strategy": "native_video", "frames": 0, "audio_channels": 1 if audio.get("audio_path") else 0}

    def mix_level(name: str, fallback: float) -> float:
        try:
            return max(0.0, min(1.5, float(audio.get(name, fallback))))
        except (TypeError, ValueError):
            return fallback

    voice_volume = mix_level("voice_volume", 1.0)
    bgm_volume = mix_level("bgm_volume", 0.16)
    sfx_volume = mix_level("sfx_volume", 0.28)
    command = [ffmpeg, "-y", "-i", str(source), "-i", str(audio["audio_path"])]
    filter_parts = [f"[1:a]volume={voice_volume:.3f}[voice]"]
    mix_inputs = ["[voice]"]
    next_index = 2
    if audio.get("bgm_path"):
        command[1:1] = ["-stream_loop", "-1"]
        command += ["-i", str(audio["bgm_path"])]
        filter_parts.append(f"[{next_index}:a]volume={bgm_volume:.3f}[bgm]")
        mix_inputs.append("[bgm]")
        next_index += 1
    for sfx_index, sfx_path in enumerate(audio.get("sfx_paths", []) or [], start=next_index):
        command += ["-i", str(sfx_path)]
        filter_parts.append(f"[{sfx_index}:a]volume={sfx_volume:.3f}[sfx{sfx_index}]")
        mix_inputs.append(f"[sfx{sfx_index}]")
    if len(mix_inputs) > 1:
        filter_parts.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=2[aout]")
        audio_map = "[aout]"
    else:
        audio_map = "[voice]"
    command += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "0:v:0", "-map", audio_map,
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False)
    if completed.returncode != 0 or not output_path.exists():
        raise MediaError(completed.stderr[-1200:] or "FFmpeg não conseguiu anexar o áudio ao vídeo nativo")
    validation = _verify_render_output(ffmpeg, output_path, width, height)
    return {"format": "mp4", "status": "rendered", "path": str(output_path), "width": width, "height": height, "aspect_ratio": aspect_ratio, "output_format": output_format, "strategy": "native_video", "frames": 0, "audio_channels": 2, "validation": validation, "audio_mix": {"voice": voice_volume, "bgm": bgm_volume, "sfx": sfx_volume}, "mixed_tracks": {"voice": True, "bgm": bool(audio.get("bgm_path")), "sfx": len(audio.get("sfx_paths", []) or [])}}
