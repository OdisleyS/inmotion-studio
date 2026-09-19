# Architecture plan

## Decision

Use a hybrid stack instead of forcing the whole product into one language:

- **React + TypeScript + Vite** for the current studio UI, editor timeline foundation, provider settings, job progress, asset browser, and video preview. Next.js remains a future option if server-rendered routes or collaboration require it.
- **FastAPI + Python** for model adapters, Piper, image processing, ControlNet/LoRA, FFmpeg, and the production worker.
- **Redis + a durable database** when the team mode is enabled; the current in-memory `JobManager` is the local single-user implementation.
- **Filesystem/object storage** for project assets, frames, WAV files, MP4 exports, and model caches.

Python is the better boundary for the media/ML runtime because Piper, ONNX, Pillow, FFmpeg, ComfyUI and diffusion tooling are Python-first. TypeScript is the better boundary for a responsive editing experience and a maintainable browser application.

## Current vertical slice

```text
concept prompt
  -> Antigravity CLI (script)
  -> Antigravity visual planner (scene directions) -> local PNG scene renderer
  -> Piper pt_BR/en_US (WAV narration)
  -> image-sequence strategy
  -> FFmpeg (H.264/AAC MP4, 1080x1920)
  -> browser preview + local production history
```

The queue is already asynchronous through `JobManager`; the browser polls real phase events instead of faking a completed response.

## Next implementation layers

1. Extend `frontend-ts/` into the full TypeScript editor while keeping the FastAPI contract stable; it now exposes provider + model routing, custom script input, scene thumbnails, and a server-backed project library.
2. Add a persistent project schema: projects, scenes, assets, provider selections, jobs, and exports.
3. Add ComfyUI/ControlNet/LoRA as a real image provider and use uploaded sketches as local references.
4. Add real Piper voice selection, preview, speed, pitch, sentence pauses, and optional speaker profiles.
5. Add native video providers only when their credentials/runtime pass the capability check; otherwise auto-select frame sequencing.
6. Extend the editor endpoint already in place with audio trim and transitions; caption editing, persisted project reopening, drag-and-drop scene reorder, selected-scene inspection, and full-project rerender are now implemented.
7. Add worker concurrency, cancellation, retries, quotas, and durable event logs for group deployment.

## Configuration contract

Provider credentials belong in environment variables or a local secret store. The browser receives capability/status metadata, never API keys. See `.env.example` for the current bridge and Piper configuration.
