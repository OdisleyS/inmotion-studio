from __future__ import annotations

from typing import Literal

try:
    from pydantic import BaseModel, Field
except ModuleNotFoundError:  # Keeps the core pipeline testable before optional deps are installed.
    class BaseModel:
        def __init__(self, **values):
            annotations = getattr(self.__class__, "__annotations__", {})
            for name in annotations:
                if name in values:
                    value = values[name]
                else:
                    value = getattr(self.__class__, name, None)
                setattr(self, name, value)

    def Field(default=None, **kwargs):
        factory = kwargs.get("default_factory")
        return factory() if factory else default


Mode = Literal["director", "autopilot"]
Style = Literal["avatar_narrator", "couples_fruits_2d", "dynamic_slideshow", "sketch_clone"]
VideoStrategy = Literal["auto", "direct_video", "image_sequence"]
NarrationLanguage = Literal["pt_BR", "en_US"]
ImageSource = Literal["generate", "reference"]
OutputFormat = Literal["vertical", "horizontal", "square"]
MotionStyle = Literal["ken_burns", "static"]


class GenerateRequest(BaseModel):
    mode: Mode = "autopilot"
    style: Style = "dynamic_slideshow"
    topic: str = Field(default="Uma curiosidade surpreendente", min_length=3, max_length=240)
    script: str | None = Field(default=None, max_length=5000)
    sketch_filenames: list[str] = Field(default_factory=list, max_length=10)
    style_profile_id: str | None = None
    target_seconds: int = Field(default=35, ge=10, le=90)
    output_format: OutputFormat = "vertical"
    provider_selection: dict[str, str] = Field(default_factory=dict)
    model_selection: dict[str, str] = Field(default_factory=dict)
    stage_autonomy: dict[str, str] = Field(default_factory=dict)
    audio_filename: str | None = None
    bgm_filename: str | None = None
    sfx_filenames: list[str] = Field(default_factory=list, max_length=10)
    video_strategy: VideoStrategy = "auto"
    narration_language: NarrationLanguage = "pt_BR"
    image_source: ImageSource = "generate"
    # Director Mode can pause after the visual draft so the user can approve
    # scene direction before narration and final rendering.
    scene_prompts: list[str] = Field(default_factory=list, max_length=90)
    scene_captions: list[str] = Field(default_factory=list, max_length=90)
    director_approved: bool = False


class ScriptPreviewRequest(BaseModel):
    """Request used by the studio to draft/revise a script before rendering."""

    topic: str = Field(default="Uma curiosidade surpreendente", min_length=3, max_length=240)
    style: Style = "dynamic_slideshow"
    script: str | None = Field(default=None, max_length=5000)
    target_seconds: int = Field(default=35, ge=10, le=90)
    provider_selection: dict[str, str] = Field(default_factory=dict)
    model_selection: dict[str, str] = Field(default_factory=dict)


class StyleProfileRequest(BaseModel):
    name: str = Field(default="Meu traço", min_length=2, max_length=80)
    sketch_filenames: list[str] = Field(default_factory=list, max_length=10)


class EditProjectRequest(BaseModel):
    scene_order: list[int] = Field(default_factory=list, max_length=90)
    scene_indexes: list[int] = Field(default_factory=list, max_length=90)
    captions: list[str] = Field(default_factory=list, max_length=90)
    scene_prompts: list[str] = Field(default_factory=list, max_length=90)
    scene_durations: list[float] = Field(default_factory=list, max_length=90)
    transition: Literal["cut", "dissolve"] = "cut"
    motion_style: MotionStyle = "ken_burns"
    audio_mix: dict[str, float] = Field(default_factory=dict)


class PhaseEvent(BaseModel):
    phase: str
    provider: str
    status: Literal["success", "failed", "fallback"]
    message: str


class GenerateResponse(BaseModel):
    project_id: str
    mode: Mode
    status: Literal["completed", "blocked", "awaiting_approval"]
    title: str
    script: str
    virality_score: float
    research: dict = Field(default_factory=dict)
    render: dict
    style_fidelity: dict
    style_profile: dict = Field(default_factory=dict)
    publish_pack: dict = Field(default_factory=dict)
    events: list[PhaseEvent]
    diagnostics: list[str]
    scenes: list[dict] = Field(default_factory=list)
    resolved_providers: dict[str, str] = Field(default_factory=dict)
    resolved_models: dict[str, str] = Field(default_factory=dict)
