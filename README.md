# In-House Video Studio

Private-first short-form video production studio for YouTube Shorts and TikTok.

The current build implements the production foundation described in the goal:

- Director Mode and Autopilot Mode
- concept-to-video duration target (10–90 seconds) persisted per project
- pre-production script drafting from a concept, with provider/model routing and a virality estimate before rendering
- provider fallback cascades for script, image, audio, and video phases
- per-stage provider and model selection with capability/status preflight checks
- persistent local workspace defaults for provider/model routing, image source, language, and target duration (credentials remain environment-only)
- per-stage autonomy controls (Autonomous, Co-Pilot, or Manual) for research, script, visuals, voice, SFX, BGM, and editing
- automatic image-sequence mode for sketch, 2D, and slideshow styles
- automatic visual scene planning from the concept through the authenticated Antigravity bridge, with local image fallback
- deterministic local providers for offline development
- optional real local SD-Turbo image generation on the RTX 3050, with fallback to Antigravity/local storyboard
- optional local SD1.5 + ControlNet Lineart provider for preserving geometry from uploaded drawings; it is separate from the automatic SD-Turbo path
- explicit visual-source choice: generate all images automatically or use uploaded drawings as references
- real local Piper TTS voices for Brazilian Portuguese and English
- real local PNG frame generation and MP4 assembly through bundled FFmpeg
- live trend research through public Google News RSS and DuckDuckGo Lite with local heuristic fallback and a transparent virality score
- bounded live-research timeout so an unavailable search service does not hold the production queue
- sketch-upload validation with line-art fidelity metadata
- persisted visual style profiles (`style_profile.json`) with reference count, quality gate, conditioning provider, and preservation targets
- uploaded sketch previews, local image-to-image conditioning when the SD-Turbo checkpoint supports it, and line-art/reference compositing fallback in every generated scene frame
- 9:16 render manifest generation and optional FFmpeg MP4 rendering
- persisted project library with reopen-in-editor support, scene drag/reorder, visual prompt editing, caption/duration editing, transition and motion control, independent voice/BGM/SFX mixer with in-editor audio preview, and rerender endpoint
- cancellable production jobs with live intermediate artifacts and terminal cancellation state
- live multi-job queue panel with progress, worker count, and reopen-in-editor actions
- live preview banner that attaches to running jobs and displays generated frames and the available script before the final MP4 exists
- durable queue state in `assets/jobs-state.json`, with unfinished jobs recovered and requeued after a backend restart
- retry action for failed, blocked, or cancelled jobs, preserving the original request while creating a fresh queue entry
- real Director approval gate: visual draft pauses before narration/render, with editable narration script, scene prompts, captions, ordering, and an approval endpoint
- low-retention hook recovery: scores below 50% trigger one rewrite through Agy or the local recovery writer
- configurable Antigravity CLI timeout for slower authenticated sessions
- optional authenticated Codex CLI bridge for script generation, using a read-only sandbox with Agy/local fallback
- Agy director-script normalization: visual/text direction is removed from narration, while visual directions can seed image prompts
- a lightweight browser studio UI
- automated failover and style-fidelity tests

## Run locally

Para iniciar os dois serviços sem abrir duplicatas, use no PowerShell:

```powershell
.\scripts\start-studio.ps1
```

O script verifica as portas `8000` e `4174` e só inicia o processo que estiver ausente.

```powershell
cd C:\Users\odisl\Documents\Codex\2026-09-18\new-chat\outputs\inhouse-video-studio
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --env-file .env
```

Open `frontend/index.html` directly for the compatibility UI, or serve the folder with any static server. Set `VITE_API_BASE`/`API_BASE` if the API is not on `http://127.0.0.1:8000`.

When the concept is filled and the custom-script field is empty, the script provider writes the roteiro automatically. With the authenticated Antigravity bridge enabled, its roteiro is the primary source; director-style labels such as `Visual`, `Texto na tela`, `Voz`, and `Locução` are normalized so Piper narrates only spoken text. Visual directions are reused as prompts when available. The image phase then generates local PNG scene assets through SD-Turbo (when enabled), with Antigravity/local storyboard fallback. A drawing upload is optional: when present, its preview is shown in the UI and the reference image is composited into every generated frame. If a ComfyUI API workflow is configured, the ControlNet/LoRA adapter becomes a real selectable provider; otherwise the UI marks it unavailable.

The research phase stores its query, source links, grounding mode, and score in `project.json`. Public Google News RSS is tried first when `ENABLE_GOOGLE_NEWS_RSS=1`, followed by DuckDuckGo Lite and then the local heuristic. Live results are labeled `news_rss` or `web_search`; when every network/search provider is unavailable, the pipeline records `local_heuristic` and lowers the research contribution instead of presenting an ungrounded result as current data.

The visual source defaults to `generate`: no drawing upload is required. In the studio, SD-Turbo creates three local frames automatically when available — including for the `sketch_clone` style. The `reference` option is the separate manual mode and makes a drawing upload mandatory. In that mode, the `manual-image-reference` provider uses the uploaded files as the actual three scene frames (cycling multiple references), rather than substituting synthetic storyboard art.

Each production also records a visual provenance profile. Automatic productions are marked as `automatic` with zero references; reference productions record the accepted filenames and local quality measurements, then update the profile with the actual conditioning provider (`ControlNet Lineart`, SD-Turbo, or storyboard fallback). This metadata is an audit trail, not a claim that a LoRA was trained.

The Studio can save a validated set of drawings as a reusable profile through `POST /api/styles/profiles` and list it with `GET /api/styles/profiles`. Selecting a saved profile automatically switches the visual style to `sketch_clone`, restores its references, and sends only the profile id with the next job.

Autonomy modes can be mixed in one production. Manual narration, BGM, and SFX accept uploaded audio files; autonomous BGM/SFX use local generated tracks and FFmpeg mixes them with the voice track. The UI also shows which media capabilities are actually ready for each selected provider/model.

The production-oriented React/TypeScript studio UI is in `frontend-ts/`:

```powershell
cd frontend-ts
npm install
npm run dev:host
```

Then open `http://127.0.0.1:4174/`. The static MVP remains available on port 4173.

Completed projects can be reopened from the Biblioteca and edited through the studio timeline or `POST /api/projects/{project_id}/edit` with `scene_order`, optional `scene_indexes` (rerender only selected scene positions), `scene_prompts`, `captions`, `scene_durations`, `transition`, `motion_style` (`ken_burns` or `static`), and `audio_mix` (`voice`, `bgm`, `sfx`). The editor is localized: unchanged scenes reuse their existing image files, while only scenes whose prompt changed receive a replacement frame; prompt changes outside `scene_indexes` remain pending for a later rerender. The MP4 rerender keeps the registered voice, BGM, and SFX sources and only reapplies the requested mix. Running jobs can be cancelled with `POST /api/jobs/{job_id}/cancel`.

The Studio polls `GET /api/jobs` for a lightweight newest-first queue snapshot. A new production can be enqueued while another is running; the interface follows the latest job while the queue keeps both workers visible. Completed media remains available through the persistent Biblioteca even after the backend process restarts; active jobs belong to the current worker process.

Completed productions also persist an editable `publish_pack` in `project.json` with a suggested title, description, hashtags, and the same heuristic virality score. The browser exposes it as a copyable publishing panel for Shorts/TikTok metadata; it does not publish automatically.

Director Mode stops after the visual storyboard with job status `awaiting_approval`. Review the draft in the scene editor, then call `POST /api/jobs/{job_id}/approve` with `scene_prompts` and `scene_captions` (or use the browser button) to resume narration and final MP4 rendering. Autopilot continues directly through the full pipeline.

## Test

```powershell
python -m unittest discover -s tests -v
```

To exercise the failover gate through the pipeline, simulate a primary outage before starting the API:

```powershell
$env:SIMULATE_PRIMARY_FAILURES = "video"
uvicorn backend.app.main:app --reload
```

## Provider configuration

The local provider is always available. Real providers can be added behind the same interfaces and configured through environment variables; the fallback chain never exposes provider-specific details to the pipeline.

Suggested future adapters:

1. Gemini/OpenAI-compatible text adapter
2. local ComfyUI/ControlNet + LoRA image adapter
3. Piper/XTTS audio adapter
4. Wan/LTX-Video/fal.ai video adapter

### Antigravity CLI bridge

If `agy` is installed and already authenticated for the Windows user, enable it for script generation:

```powershell
$env:ENABLE_AGY_BRIDGE = "1"
$env:AGY_TIMEOUT_SECONDS = "90"
$env:AGY_SKIP_PERMISSIONS = "1"
uvicorn backend.app.main:app --reload
```

The backend invokes `agy --print` as the primary script provider and automatically falls back to the local template provider on timeout, CLI failure, or empty output. In the default headless mode, `AGY_SKIP_PERMISSIONS=1` adds Agy's explicit `--dangerously-skip-permissions` flag so a background server cannot hang waiting for a terminal prompt; set it to `0` if the Agy process is being run in an already-approved interactive sandbox. `AGY_TIMEOUT_SECONDS` can be increased up to 300 for slower local sessions. No token is read or stored by this project.

### Codex CLI bridge

If the local `codex` command is authenticated, enable it as an optional roteiro provider:

```powershell
$env:ENABLE_CODEX_BRIDGE = "1"
$env:CODEX_COMMAND = "codex"
$env:CODEX_MODEL = "gpt-5.6-luna"
$env:CODEX_TIMEOUT_SECONDS = "120"
uvicorn backend.app.main:app --reload
```

The bridge calls `codex exec` with `--ephemeral`, `--sandbox read-only`, and JSON output parsing. It is available as a selectable text-capability provider and as fallback after Agy; it does not read or store authentication tokens.

### Piper local: vozes gratuitas

O Studio usa Piper local, sem API paga, com as vozes Faber em português brasileiro e Amy em inglês. Para conferir ou completar uma instalação em outra máquina, execute:

```powershell
.\scripts\ensure-piper-voices.ps1
```

O script é idempotente: mantém os arquivos existentes e baixa somente o modelo/config ausente para `assets/models/piper`. Use `-Force` apenas quando quiser substituir os arquivos locais. Depois, valide em Config > Piper com o botão de síntese real.

### Capability-aware video strategy

The UI lets you select a provider and model independently for script, image, audio, and video. The backend checks model capabilities (`text`, `image_generation`, `audio`, `video_generation`, and `image_sequence`) before starting and rejects incompatible or unavailable choices. For animation styles without a native video engine, the recommended path is real image generation frame by frame followed by FFmpeg assembly.

The script panel also has a pre-production action that calls `/api/script/preview`: it researches the concept, uses the selected roteiro provider/model, applies the same fallback cascade, and puts the draft back into the editable field before any media is rendered. `/api/integrations/probe` provides explicit local checks for Codex, Antigravity, Piper, SD-Turbo, ControlNet, and ComfyUI without accepting or exposing credentials.

### Local SD-Turbo image generation

The project can use the downloaded `stabilityai/sd-turbo` checkpoint locally. After the checkpoint is present in `assets/models/sd-turbo`, enable it before starting the backend:

```powershell
$env:ENABLE_LOCAL_DIFFUSION = "1"
$env:LOCAL_DIFFUSION_MODEL = "assets/models/sd-turbo"
```

The `local-sd-turbo` provider then becomes available for the image phase. Automatic routing tries it first, then Antigravity visual planning, then the local storyboard fallback. The first generation loads the model into memory and can take longer on a 4 GB GPU.

### Local ControlNet Lineart provider

The style-control path can run locally through Diffusers without requiring the ComfyUI UI. It uses the public `stable-diffusion-v1-5/stable-diffusion-v1-5` base plus `lllyasviel/control_v11p_sd15_lineart`, cycles the uploaded references across the three scene frames, and emits the same three-frame storyboard contract as the automatic provider. The generated manifest records the filename used for each conditioned frame. It is only exposed as `ready` after both safetensors checkpoints pass the local file check. Set `ENABLE_LOCAL_CONTROLNET=0` to disable it. The provider is selected automatically before SD-Turbo only when a reference drawing is actually present, so a concept-only production never asks for an upload.

The Studio also lists existing local sketch uploads at `/api/uploads/sketches`, with a safe preview endpoint and multi-select actions. Up to ten existing references can be added or removed individually, reused in a production, or saved as a new visual profile without finding each file again in the Windows file picker. Automatic text-to-image remains the default when no reference is selected.

### Optional ComfyUI / ControlNet / LoRA adapter

The local SD-Turbo adapter also accepts an optional pre-trained LoRA directly, without making the base generator depend on it. Set `LOCAL_LORA_ADAPTER` to a local `.safetensors`, `.bin`, or `.pt` file and optionally set `LOCAL_LORA_WEIGHT` between `0` and `2`. If that setting is empty, the runtime automatically discovers the newest adapter whose training manifest says `training_status=completed`; unfinished or failed training is never loaded. The Config screen exposes its detected state and lists local adapters when present. A saved visual profile with at least three approved references can use `POST /api/styles/profiles/{profile_id}/lora-dataset` (or the Studio button) to create a normalized 512px training dataset with captions and a manifest under `assets/models/lora/training`. `POST /api/styles/profiles/{profile_id}/lora-train` starts the local Diffusers + PEFT trainer, persists PID/log/progress, and writes a safetensors adapter when training completes. This is intentionally an explicit, GPU-consuming action; ControlNet remains the verified geometry-preserving path while the profile has fewer than three references or LoRA training has not completed.

The Config tab reads `/api/runtime-config` to show the effective local commands, model paths, voice files, FFmpeg binary, ControlNet assets, and ComfyUI workflow status. It also persists a whitelist of safe, non-secret runtime overrides (for example `CODEX_MODEL`, `COMFYUI_URL`, `COMFYUI_WORKFLOW`, and local model paths) in `assets/runtime-settings.json`; credentials and arbitrary shell commands are never accepted from the browser.

The image catalog exposes `comfyui-controlnet-lora` only as `unavailable` until a real ComfyUI API and workflow are present. To activate it, run ComfyUI with its HTTP API enabled and set `COMFYUI_URL` (default `http://127.0.0.1:8188`) plus `COMFYUI_WORKFLOW` to a JSON API workflow file. The workflow is responsible for its ControlNet and LoRA nodes; the adapter injects the scene prompt and seed, waits for the generated image, and then feeds the resulting frames into the same 9:16 storyboard/video path. If either the server or workflow is missing, the studio keeps the local SD-Turbo/fallback chain and reports the unavailable capability honestly in `/api/health` and `/api/providers`.

`video_strategy=auto` selects `image_sequence` for sketch cloning, 2D scenes, and dynamic slideshows, then assembles frames with captions and stereo audio. Avatar narration defaults to `direct_video`.

When the downloaded Piper voices and `imageio-ffmpeg` runtime are available, the local pipeline emits real WAV, PNG, and MP4 files under `generated/<project-id>/`. If a component is unavailable, the response is explicitly marked `manifest` and includes diagnostics rather than pretending a media file exists.

Keep API keys in a secret manager or local environment, never in the frontend.

## Safety and monetization note

The virality score is a heuristic prioritization signal, not a prediction or guarantee. Trend inputs should respect source terms, platform policies, copyright, and privacy requirements. The renderer produces original assets and metadata; publishing automation is intentionally out of scope for this MVP.
The Config tab also allows the local team to enable/disable each CLI bridge, change the executable path, model, and bounded timeout (30–300 seconds). This is only runtime wiring: authentication remains in the already logged-in local CLI and is never accepted by the browser or written to the workspace settings.
### Native video through ComfyUI

Wan 2.1 and LTX-Video now have real adapter slots in the same capability router. Configure a ComfyUI API workflow in `COMFYUI_WAN_WORKFLOW` or `COMFYUI_LTX_WORKFLOW`; the provider remains unavailable until the server and workflow exist. The adapter submits the workflow, waits for a video/gif output, converts it to MP4 when necessary, scales it to the selected format, and muxes the local Piper/BGM/SFX tracks. Without those settings, `image_sequence` remains the ready path and native video is blocked instead of simulated.

When a connected native engine is selected, video rendering uses a bounded cascade: selected engine, one other connected native engine when available, then the local FFmpeg frame sequence. Each failed attempt is kept in the job event log, and the final `media_provenance.video_provider` identifies the provider that actually produced the MP4. This keeps a transient ComfyUI/Wan/LTX/SadTalker failure from losing an otherwise valid production.

## Avatar lip-sync (optional)

SadTalker now has an honest local adapter slot. Set `SADTALKER_ROOT`, `SADTALKER_PYTHON`, and `SADTALKER_CHECKPOINT_DIR` when a local SadTalker checkout and checkpoints are available. The adapter runs `inference.py` with the first generated portrait and the real local narration, then validates/muxes the final MP4. If the checkout or checkpoints are missing, the capability remains `planned` and the selection is blocked; the reliable frame-sequence path is never silently replaced by a mock avatar.
