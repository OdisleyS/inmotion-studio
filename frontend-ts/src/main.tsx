import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AudioLines,
  Check,
  ChevronDown,
  Copy,
  Film,
  FolderOpen,
  Gauge,
  Image as ImageIcon,
  Layers3,
  LoaderCircle,
  Mic2,
  Play,
  Plus,
  Save,
  Settings2,
  Sparkles,
  Square,
  WandSparkles,
  Workflow,
} from "lucide-react";
import "./styles.css";
import "./views.css";
import "./editor.css";
import "./upload.css";
import "./stage-controls.css";
import "./production.css";

const API = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
type Phase = "script" | "image" | "audio" | "video";
type ProductionPhase = "research" | "sfx" | "bgm" | Phase;
type StageKey =
  "research" | "script" | "image" | "audio" | "sfx" | "bgm" | "video";
type Autonomy = "autonomous" | "manual" | "copilot";
type Catalog = Record<Phase, Provider[]>;
type Provider = {
  name: string;
  label: string;
  status: string;
  capabilities: string[];
};
type ModelOption = {
  name: string;
  label: string;
  provider: string;
  status: string;
  capabilities: string[];
};
type ModelCatalog = Record<Phase, ModelOption[]>;
type ProjectRef = { project_id: string; title: string; url: string };
type StyleProfile = {
  profile_id: string;
  name: string;
  style?: string;
  reference_count: number;
  reference_files: string[];
  quality_gate?: string;
  conditioning?: string;
  conditioning_provider?: string;
};
type AvailableSketch = {
  filename: string;
  preview_url?: string;
  quality?: { usable?: boolean; width?: number; height?: number };
};
type JobEvent = {
  phase: string;
  message: string;
  progress?: number;
  provider?: string;
  status?: string;
};
type JobArtifacts = {
  research?: Result["research"];
  script?: {
    title?: string;
    hook?: string;
    script?: string;
    provider?: string;
  };
  images?: {
    frames?: Scene[];
    frame_urls?: string[];
    provider?: string;
    completed?: number;
    total?: number;
  };
  audio?: {
    provider?: string;
    voice?: string;
    duration_seconds?: number;
    real_audio?: boolean;
    has_bgm?: boolean;
    sfx_count?: number;
  };
};
type Job = {
  job_id: string;
  status: string;
  phase: string;
  progress: number;
  events: JobEvent[];
  artifacts?: JobArtifacts;
  result?: Result;
  error?: string;
  cancel_requested?: boolean;
};
type QueueJob = {
  job_id: string;
  project_id?: string | null;
  title?: string;
  status: string;
  phase: string;
  progress: number;
  created_at?: string;
  cancel_requested?: boolean;
  render?: { url?: string };
};
type Scene = {
  index?: number;
  prompt?: string;
  subject?: string;
  action?: string;
  caption?: string;
  duration_seconds?: number;
  sketch_inputs?: string[];
};
type AudioMix = { voice: number; bgm: number; sfx: number };
type OutputFormat = "vertical" | "horizontal" | "square";
type Result = {
  project_id: string;
  status: string;
  title: string;
  script: string;
  virality_score: number;
  style?: string;
  target_seconds?: number;
  output_format?: OutputFormat;
  image_source?: "generate" | "reference";
  research?: {
    status?: string;
    score?: number;
    sources?: {
      title: string;
      url: string;
      snippet?: string;
      published_at?: string;
      relevance?: number;
      recency?: number;
      matched_terms?: string[];
    }[];
    grounding?: string;
    query?: string;
    message?: string;
    quality?: string;
  };
  render: {
    url?: string;
    frame_urls?: string[];
    audio_urls?: { voice?: string; bgm?: string; sfx?: string[] };
    media_provenance?: {
      images?: string;
      image_provider?: string;
      audio?: string;
      audio_provider?: string;
      video?: string;
      video_provider?: string;
    };
    status?: string;
    strategy?: string;
    frames?: number;
    width?: number;
    height?: number;
    aspect_ratio?: string;
    output_format?: OutputFormat;
    transition?: string;
    motion_style?: "ken_burns" | "static";
    scene_durations?: number[];
    audio_mix?: AudioMix;
    regenerated_scene_indexes?: number[];
    reused_scene_indexes?: number[];
    validation?: { status?: string; video?: string; audio?: string };
  };
  transition?: string;
  style_fidelity: { status: string; inputs: number };
  style_profile?: {
    profile_id?: string;
    style?: string;
    mode?: string;
    reference_count?: number;
    quality_gate?: string;
    conditioning?: string;
    conditioning_provider?: string;
    reference_files?: string[];
    reference_usage?: string[];
  };
  events: JobEvent[];
  diagnostics: string[];
  scenes?: Scene[];
  resolved_providers?: Record<string, string>;
  resolved_models?: Record<string, string>;
  provider_selection?: Record<string, string>;
  model_selection?: Record<string, string>;
  stage_autonomy?: Record<string, string>;
  video_strategy?: string;
};
type ScriptPreview = {
  script?: string;
  hook?: string;
  provider?: string;
  virality_score?: number;
  diagnostics?: string[];
};
type PublishPack = {
  title?: string;
  description?: string;
  hashtags?: string[];
  virality_score?: number;
  editable?: boolean;
};
type HealthResponse = {
  antigravity_cli?: { available?: boolean; enabled?: boolean };
  codex_cli?: { available?: boolean; enabled?: boolean; model?: string };
  hardware?: {
    available?: boolean;
    name?: string | null;
    memory_mb?: number | null;
    driver?: string | null;
    native_video_guidance?: string;
  };
  integrations?: {
    piper?: { pt_BR?: boolean; en_US?: boolean };
    ffmpeg?: { available?: boolean };
    sd_turbo?: { available?: boolean };
    controlnet_lineart?: { available?: boolean; enabled?: boolean };
    comfyui?: {
      available?: boolean;
      workflow_configured?: boolean;
      url?: string;
    };
  };
};
type WorkspaceSettings = {
  provider_selection: Record<Phase, string>;
  model_selection: Record<Phase, string>;
  stage_autonomy: Record<StageKey, Autonomy>;
  image_source: "generate" | "reference";
  video_strategy: string;
  narration_language: string;
  target_seconds: number;
  output_format: OutputFormat;
};
type IntegrationKey = "codex" | "antigravity" | "controlnet" | "comfyui";
type ProbeResult = {
  status: string;
  model?: string;
  url?: string;
  message?: string;
};
type RuntimePath = {
  path?: string | null;
  exists?: boolean;
  size_bytes?: number;
  size_mb?: number;
  config?: RuntimePath;
};
type LoraAdapter = {
  name?: string;
  path?: string;
  available?: boolean;
  size_bytes?: number;
  selected?: boolean;
};
type RuntimeConfig = {
  project_root?: string;
  hardware?: {
    available?: boolean;
    name?: string | null;
    memory_mb?: number | null;
    driver?: string | null;
    native_video_guidance?: string;
  };
  bridges?: {
    antigravity?: {
      command?: string;
      available?: boolean;
      enabled?: boolean;
      timeout_seconds?: string;
    };
    codex?: {
      command?: string;
      available?: boolean;
      enabled?: boolean;
      model?: string;
      timeout_seconds?: string;
    };
  };
  media?: {
    piper?: {
      executable?: string | null;
      pt_BR?: RuntimePath;
      en_US?: RuntimePath;
    };
    ffmpeg?: { executable?: string | null; available?: boolean };
  };
  image?: {
    sd_turbo?: RuntimePath & {
      enabled?: boolean;
      available?: boolean;
      lora?: {
        configured?: boolean;
        available?: boolean;
        path?: string | null;
        size_bytes?: number;
        error?: string | null;
        adapters?: LoraAdapter[];
      };
    };
    controlnet?: {
      base?: RuntimePath;
      lineart?: RuntimePath;
      enabled?: boolean;
      available?: boolean;
    };
    comfyui?: { url?: string; workflow?: RuntimePath; available?: boolean };
  };
  video?: {
    comfyui?: {
      wan?: RuntimePath;
      ltx?: RuntimePath;
      sadtalker?: RuntimePath & {
        available?: boolean;
        inference?: RuntimePath;
        checkpoints?: RuntimePath;
        python?: string;
      };
    };
  };
  research?: { enabled?: boolean; provider?: string };
  editable?: Record<string, string>;
};

const phaseLabels: Record<Phase, string> = {
  script: "Roteiro",
  image: "Imagens",
  audio: "Áudio",
  video: "Vídeo",
};
const productionLabels: Record<ProductionPhase, string> = {
  research: "Pesquisa",
  script: "Roteiro",
  image: "Imagens",
  audio: "Áudio",
  sfx: "SFX",
  bgm: "BGM",
  video: "Vídeo",
};
const productionPhases: ProductionPhase[] = [
  "research",
  "script",
  "image",
  "audio",
  "video",
];
const liveProductionStages: ProductionPhase[] = [
  "research",
  "script",
  "image",
  "audio",
  "sfx",
  "bgm",
  "video",
];
const stageLabels: Record<StageKey, string> = {
  research: "Pesquisa / virality",
  script: "Roteiro",
  image: "Arte / imagens",
  audio: "Narração",
  sfx: "Efeitos (SFX)",
  bgm: "Trilha (BGM)",
  video: "Montagem / edição",
};
const stageKeys: StageKey[] = [
  "research",
  "script",
  "image",
  "audio",
  "sfx",
  "bgm",
  "video",
];
const styles = [
  { value: "dynamic_slideshow", label: "Slideshow dinâmico" },
  { value: "sketch_clone", label: "Meu traço / sketch" },
  { value: "couples_fruits_2d", label: "Casais / frutas 2D" },
  { value: "avatar_narrator", label: "Avatar narrador" },
];
const capabilityLabels: Record<string, string> = {
  text: "texto",
  image_generation: "geração de imagem",
  audio: "áudio",
  image_sequence: "frames → vídeo",
  video_generation: "vídeo nativo",
  lip_sync: "lip-sync de avatar",
};
const outputFormats: {
  value: OutputFormat;
  label: string;
  detail: string;
  dimensions: string;
}[] = [
  {
    value: "vertical",
    label: "Shorts / TikTok",
    detail: "vertical",
    dimensions: "1080×1920 · 9:16",
  },
  {
    value: "horizontal",
    label: "YouTube normal",
    detail: "horizontal",
    dimensions: "1920×1080 · 16:9",
  },
  {
    value: "square",
    label: "Quadrado",
    detail: "feed",
    dimensions: "1080×1080 · 1:1",
  },
];
const formatSourceDate = (value?: string) => {
  if (!value) return "data recente";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "data recente"
    : parsed.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
};
const formatMediaDuration = (seconds?: number | null) => {
  if (!seconds || !Number.isFinite(seconds)) return "duração não lida";
  const rounded = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(rounded / 60);
  const remainder = String(rounded % 60).padStart(2, "0");
  return `${minutes}:${remainder}`;
};

const normalizeScenePrompt = (value: string) => {
  const seen = new Set<string>();
  return value
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .filter((part) => {
      const key = part.toLocaleLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .join("; ");
};

function requiredCapabilityForPhase(
  phase: Phase,
  strategy: string,
  provider = "",
): string {
  if (phase === "script") return "text";
  if (phase === "image")
    return provider === "manual-image-reference"
      ? "image_sequence"
      : "image_generation";
  if (phase === "audio") return "audio";
  return strategy === "direct_video" ? "video_generation" : "image_sequence";
}

function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [modelCatalog, setModelCatalog] = useState<ModelCatalog | null>(null);
  const [topic, setTopic] = useState(
    "História do Japão: da formação até a era moderna",
  );
  const [script, setScript] = useState("");
  const [style, setStyle] = useState("dynamic_slideshow");
  const [mode, setMode] = useState("autopilot");
  const [imageSource, setImageSource] = useState<"generate" | "reference">(
    "generate",
  );
  const [language, setLanguage] = useState("pt_BR");
  const [strategy, setStrategy] = useState("auto");
  const [targetSeconds, setTargetSeconds] = useState(35);
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("vertical");
  const [providers, setProviders] = useState<Record<Phase, string>>({
    script: "auto",
    image: "auto",
    audio: "auto",
    video: "auto",
  });
  const [modelSelection, setModelSelection] = useState<Record<Phase, string>>({
    script: "auto",
    image: "auto",
    audio: "auto",
    video: "auto",
  });
  const [stageAutonomy, setStageAutonomy] = useState<
    Record<StageKey, Autonomy>
  >({
    research: "autonomous",
    script: "autonomous",
    image: "autonomous",
    audio: "autonomous",
    sfx: "autonomous",
    bgm: "autonomous",
    video: "autonomous",
  });
  const [files, setFiles] = useState<File[]>([]);
  const [storedSketchFilenames, setStoredSketchFilenames] = useState<string[]>([]);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioDuration, setAudioDuration] = useState<number | null>(null);
  const [bgmFile, setBgmFile] = useState<File | null>(null);
  const [sfxFiles, setSfxFiles] = useState<File[]>([]);
  const [sketchPreviews, setSketchPreviews] = useState<string[]>([]);
  const [availableSketches, setAvailableSketches] = useState<AvailableSketch[]>([]);
  const [styleProfiles, setStyleProfiles] = useState<StyleProfile[]>([]);
  const [selectedStyleProfile, setSelectedStyleProfile] = useState("");
  const [profileName, setProfileName] = useState("Meu traço");
  const [profileMessage, setProfileMessage] = useState("");
  const [loraTrainingBusy, setLoraTrainingBusy] = useState(false);
  const [loraTrainingStatus, setLoraTrainingStatus] = useState("");
  const selectedProfileData = styleProfiles.find(
    (profile) => profile.profile_id === selectedStyleProfile,
  );
  const selectedProfileReferenceCount = selectedProfileData?.reference_count ?? files.length;
  const loraReferencesReady = selectedProfileReferenceCount >= 3;
  const [job, setJob] = useState<Job | null>(null);
  const [queue, setQueue] = useState<QueueJob[]>([]);
  const [sceneCaptions, setSceneCaptions] = useState<string[]>([]);
  const [scenePrompts, setScenePrompts] = useState<string[]>([]);
  const [sceneDurations, setSceneDurations] = useState<number[]>([]);
  const [audioMix, setAudioMix] = useState<AudioMix>({
    voice: 1,
    bgm: 0.16,
    sfx: 0.28,
  });
  const [editorMessage, setEditorMessage] = useState("");
  const [transitionStyle, setTransitionStyle] = useState<"cut" | "dissolve">(
    "dissolve",
  );
  const [motionStyle, setMotionStyle] = useState<"ken_burns" | "static">(
    "ken_burns",
  );
  const [sceneOrder, setSceneOrder] = useState<number[]>([]);
  const [selectedScene, setSelectedScene] = useState(0);
  const [draggedScene, setDraggedScene] = useState<number | null>(null);
  const [history, setHistory] = useState<ProjectRef[]>(() =>
    JSON.parse(localStorage.getItem("studio-history") || "[]"),
  );
  const [health, setHealth] = useState("connecting");
  const [healthDetails, setHealthDetails] = useState<HealthResponse | null>(
    null,
  );
  const [scriptPreviewBusy, setScriptPreviewBusy] = useState(false);
  const [scriptPreviewMessage, setScriptPreviewMessage] = useState("");
  const [probeMessage, setProbeMessage] = useState("");
  const [probeBusy, setProbeBusy] = useState<IntegrationKey | "">("");
  const [probeResults, setProbeResults] = useState<
    Partial<Record<IntegrationKey, ProbeResult>>
  >({});
  const [workspaceSettings, setWorkspaceSettings] =
    useState<WorkspaceSettings | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(
    null,
  );
  const [settingsMessage, setSettingsMessage] = useState("");
  const [activeTab, setActiveTab] = useState("studio");
  const timer = useRef<number | undefined>(undefined);
  const autoAttachedJob = useRef("");
  const autoOpenedLatestProject = useRef(false);
  const projectLoadRequest = useRef(0);
  const jobPollRequest = useRef(0);
  const audioMetadataUrl = useRef<string | null>(null);

  const inspectAudioFile = (file: File | null) => {
    if (audioMetadataUrl.current) {
      URL.revokeObjectURL(audioMetadataUrl.current);
      audioMetadataUrl.current = null;
    }
    setAudioDuration(null);
    if (!file) return;

    const url = URL.createObjectURL(file);
    audioMetadataUrl.current = url;
    const probe = new Audio();
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      if (audioMetadataUrl.current !== url) return;
      setAudioDuration(
        Number.isFinite(probe.duration) && probe.duration > 0
          ? probe.duration
          : null,
      );
      URL.revokeObjectURL(url);
      audioMetadataUrl.current = null;
    };
    probe.onerror = () => {
      if (audioMetadataUrl.current !== url) return;
      URL.revokeObjectURL(url);
      audioMetadataUrl.current = null;
    };
    probe.src = url;
  };

  const refreshQueue = async () => {
    try {
      const response = await fetch(`${API}/api/jobs`);
      if (!response.ok) return;
      const records: QueueJob[] = await response.json();
      setQueue(records);
      const active = records.find((item) =>
        ["running", "queued", "cancelling"].includes(item.status),
      );
      if (active && autoAttachedJob.current !== active.job_id) {
        autoAttachedJob.current = active.job_id;
        void poll(active.job_id);
      }
      if (!active) autoAttachedJob.current = "";
    } catch {
      /* backend may be restarting; the next poll will recover automatically */
    }
  };
  const saveWorkspaceDefaults = async () => {
    const response = await fetch(`${API}/api/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider_selection: providers,
        model_selection: modelSelection,
        stage_autonomy: stageAutonomy,
        image_source: imageSource,
        video_strategy: strategy,
        narration_language: language,
        target_seconds: targetSeconds,
        output_format: outputFormat,
      }),
    });
    if (response.ok) {
      setWorkspaceSettings(await response.json());
      setSettingsMessage("padrões salvos neste workspace");
    } else setSettingsMessage("não foi possível salvar os padrões");
  };
  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then((response) => (response.ok ? response.json() : null))
      .then((value) => {
        if (!value) return;
        setWorkspaceSettings(value);
        if (!job) {
          if (value.provider_selection)
            setProviders((current) => ({
              ...current,
              ...value.provider_selection,
            }));
          if (value.model_selection)
            setModelSelection((current) => ({
              ...current,
              ...value.model_selection,
            }));
          if (value.stage_autonomy)
            setStageAutonomy((current) => ({
              ...current,
              ...value.stage_autonomy,
            }));
          if (value.image_source) setImageSource(value.image_source);
          if (value.video_strategy) setStrategy(value.video_strategy);
          if (value.narration_language) setLanguage(value.narration_language);
          if (value.target_seconds) setTargetSeconds(value.target_seconds);
          if (
            value.output_format === "vertical" ||
            value.output_format === "horizontal" ||
            value.output_format === "square"
          )
            setOutputFormat(value.output_format);
        }
      })
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    Promise.all([
      fetch(`${API}/api/providers`).then((r) => r.json()),
      fetch(`${API}/api/models`).then((r) => r.json()),
      fetch(`${API}/api/health`).then((r) => r.json()),
      fetch(`${API}/api/projects`).then((r) => r.json()),
      fetch(`${API}/api/jobs`).then((r) => r.json()),
      fetch(`${API}/api/uploads/sketches`).then((r) => r.json()),
    ])
      .then(
        ([
          providersResponse,
          modelsResponse,
          healthResponse,
          projectsResponse,
          queueResponse,
          sketchesResponse,
        ]) => {
          setCatalog(providersResponse);
          setModelCatalog(modelsResponse);
          setHealthDetails(healthResponse);
          if (Array.isArray(queueResponse)) setQueue(queueResponse);
          if (Array.isArray(sketchesResponse)) setAvailableSketches(sketchesResponse);
          const bridges = [
            healthResponse.antigravity_cli?.enabled
              ? "agy connected"
              : "local mode",
            healthResponse.codex_cli?.enabled
              ? `codex ${healthResponse.codex_cli.model || "connected"}`
              : "codex off",
          ];
          setHealth(
            `${bridges.join(" · ")} · ${healthResponse.integrations?.piper?.pt_BR && healthResponse.integrations?.piper?.en_US && healthResponse.integrations?.ffmpeg?.available ? "media ready" : "media partial"}`,
          );
          if (Array.isArray(projectsResponse)) {
            const serverHistory = projectsResponse
              .filter(
                (item: { project_id?: string; render?: { url?: string } }) =>
                  item.project_id && item.render?.url,
              )
              .map(
                (item: {
                  project_id: string;
                  title: string;
                  render: { url: string };
                }) => ({
                  project_id: item.project_id,
                  title: item.title,
                  url: item.render.url,
                }),
              );
            if (serverHistory.length) {
              setHistory(serverHistory);
              localStorage.setItem(
                "studio-history",
                JSON.stringify(serverHistory),
              );
            }
          }
        },
      )
      .catch(() => setHealth("backend reconectando"));
    return () => window.clearTimeout(timer.current);
  }, []);
  useEffect(() => {
    const interval = window.setInterval(() => {
      void refreshQueue();
    }, 1800);
    return () => window.clearInterval(interval);
  }, []);
  useEffect(() => {
    const refreshHealth = async () => {
      try {
        const response = await fetch(`${API}/api/health`);
        if (!response.ok) throw new Error("health check failed");
        const healthResponse: HealthResponse = await response.json();
        setHealthDetails(healthResponse);
        const bridges = [
          healthResponse.antigravity_cli?.enabled
            ? "agy connected"
            : "local mode",
          healthResponse.codex_cli?.enabled
            ? `codex ${healthResponse.codex_cli.model || "connected"}`
            : "codex off",
        ];
        setHealth(
          `${bridges.join(" · ")} · ${healthResponse.integrations?.piper?.pt_BR && healthResponse.integrations?.piper?.en_US && healthResponse.integrations?.ffmpeg?.available ? "media ready" : "media partial"}`,
        );
      } catch {
        setHealth("backend reconectando");
      }
    };
    const interval = window.setInterval(() => {
      void refreshHealth();
    }, 5000);
    return () => window.clearInterval(interval);
  }, []);
  useEffect(() => {
    fetch(`${API}/api/styles/profiles`)
      .then((response) => (response.ok ? response.json() : []))
      .then((value) => {
        if (Array.isArray(value)) setStyleProfiles(value);
      })
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    fetch(`${API}/api/runtime-config`)
      .then((response) => (response.ok ? response.json() : null))
      .then((value) => {
        if (value) setRuntimeConfig(value);
      })
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (imageSource === "generate" && selectedStyleProfile)
      setSelectedStyleProfile("");
  }, [imageSource, selectedStyleProfile]);
  useEffect(() => {
    if (autoOpenedLatestProject.current || job || !history.length) return;
    autoOpenedLatestProject.current = true;
    void loadProject(history[0].project_id);
  }, [history.length, job?.job_id]);
  useEffect(() => {
    const project = job?.result;
    if (!project?.project_id) return;
    if (project.provider_selection)
      setProviders((current) => ({
        ...current,
        ...project.provider_selection,
      }));
    if (project.model_selection)
      setModelSelection((current) => ({
        ...current,
        ...project.model_selection,
      }));
    if (project.stage_autonomy)
      setStageAutonomy((current) => ({
        ...current,
        ...project.stage_autonomy,
      }));
    if (project.video_strategy) setStrategy(project.video_strategy);
    if (
      project.image_source === "reference" ||
      project.image_source === "generate"
    )
      setImageSource(project.image_source);
    if (project.target_seconds) setTargetSeconds(project.target_seconds);
    if (
      project.output_format === "vertical" ||
      project.output_format === "horizontal" ||
      project.output_format === "square"
    )
      setOutputFormat(project.output_format);
  }, [job?.result?.project_id]);

  const selectedProviders = useMemo(
    () =>
      phases.map(
        (phase) =>
          `${phaseLabels[phase]}: ${providers[phase]} / ${modelSelection[phase]}`,
      ),
    [modelSelection, providers],
  );
  const selectedImageEngine = useMemo(() => {
    const selectedModel = modelCatalog?.image?.find(
      (item) => item.name === modelSelection.image && item.name !== "auto",
    );
    if (selectedModel) return selectedModel.label;
    const selectedProvider = catalog?.image?.find(
      (item) => item.name === providers.image && item.name !== "auto",
    );
    if (selectedProvider) return selectedProvider.label;
    return job?.result?.resolved_models?.image || "SD-Turbo local";
  }, [catalog, job?.result?.resolved_models, modelCatalog, modelSelection.image, providers.image]);
  const resolvedProviderSummary = useMemo(() => {
    const resolved = job?.result?.resolved_providers || {};
    return Object.entries(resolved)
      .map(
        ([phase, provider]) =>
          `${productionLabels[phase as ProductionPhase] || phase}: ${provider}`,
      )
      .join(" · ");
  }, [job?.result?.project_id, job?.result?.resolved_providers]);
  const resolvedModelSummary = useMemo(() => {
    const resolved = job?.result?.resolved_models || {};
    return Object.entries(resolved)
      .map(
        ([phase, model]) =>
          `${productionLabels[phase as ProductionPhase] || phase}: ${model}`,
      )
      .join(" · ");
  }, [job?.result?.project_id, job?.result?.resolved_models]);
  const selectedOutputFormat =
    outputFormats.find((item) => item.value === outputFormat) ||
    outputFormats[0];
  const latestMessage =
    job?.events?.at(-1)?.message || "Pronto para começar uma produção";
  const activePhaseIndex =
    job?.phase === "queued"
      ? -1
      : productionPhases.indexOf(job?.phase as ProductionPhase);
  const activityEvents = job?.result?.events?.length
    ? job.result.events
    : job?.events || [];
  const orderedScenes = useMemo(() => {
    const scenes = job?.result?.scenes || [];
    const order =
      sceneOrder.length === scenes.length
        ? sceneOrder
        : scenes.map((_, index) => index);
    return order.map((index) => ({
      scene: scenes[index]
        ? {
            ...scenes[index],
            prompt: normalizeScenePrompt(scenes[index].prompt || ""),
          }
        : scenes[index],
      originalIndex: index,
    }));
  }, [job?.result?.scenes, sceneOrder]);

  const setProvider = (phase: Phase, value: string) => {
    setProviders((current) => ({ ...current, [phase]: value }));
    setModelSelection((current) => {
      const selected = modelCatalog?.[phase]?.find(
        (item) => item.name === current[phase],
      );
      if (
        !selected ||
        selected.name === "auto" ||
        value === "auto" ||
        selected.provider === value
      )
        return current;
      return { ...current, [phase]: "auto" };
    });
  };
  const setModel = (phase: Phase, value: string) =>
    setModelSelection((current) => ({ ...current, [phase]: value }));
  const setStageMode = (stage: StageKey, value: Autonomy) => {
    setStageAutonomy((current) => ({ ...current, [stage]: value }));
    if (stage === "image" && value === "manual") {
      setImageSource("reference");
      setProviders((current) => ({ ...current, image: "manual-image-reference" }));
      setModelSelection((current) => ({ ...current, image: "auto" }));
    } else if (
      stage === "image" &&
      value !== "manual" &&
      providers.image === "manual-image-reference"
    ) {
      setProviders((current) => ({ ...current, image: "auto" }));
    }
  };
  const activateAutomaticFlow = () => {
    setMode("autopilot");
    setImageSource("generate");
    setSelectedStyleProfile("");
    selectSketches([]);
    setScript("");
    setProviders({
      script: "auto",
      image: "auto",
      audio: "auto",
      video: "auto",
    });
    setModelSelection({
      script: "auto",
      image: "auto",
      audio: "auto",
      video: "auto",
    });
    setStageAutonomy({
      research: "autonomous",
      script: "autonomous",
      image: "autonomous",
      audio: "autonomous",
      sfx: "autonomous",
      bgm: "autonomous",
      video: "autonomous",
    });
    setStrategy("auto");
    setScriptPreviewMessage(
      "Fluxo automático pronto: conceito → roteiro → imagens → Piper → MP4.",
    );
  };
  const modelCompatible = (phase: Phase, item: ModelOption) => {
    if (item.name === "auto") return true;
    if (!["ready", "ready-manifest"].includes(item.status)) return false;
    if (providers[phase] !== "auto" && item.provider !== providers[phase])
      return false;
    const capability = requiredCapabilityForPhase(phase, strategy, providers[phase]);
    return item.capabilities.includes(capability);
  };
  const routingPreflight = useMemo(
    () =>
      phases.map((phase) => {
        const provider = catalog?.[phase]?.find(
          (item) => item.name === providers[phase],
        );
        const model = modelCatalog?.[phase]?.find(
          (item) => item.name === modelSelection[phase],
        );
        const required = requiredCapabilityForPhase(phase, strategy, providers[phase]);
        const providerReady =
          !provider || ["ready", "ready-manifest"].includes(provider.status);
        const providerCapabilityReady =
          !provider ||
          provider.name === "auto" ||
          provider.capabilities.includes(required) ||
          (phase === "video" &&
            required === "image_sequence" &&
            provider.capabilities.includes("video_render"));
        const modelReady =
          !model || model.name === "auto" || modelCompatible(phase, model);
        const nativeVideoMissing =
          phase === "video" &&
          strategy === "direct_video" &&
          !(modelCatalog?.video || []).some(
            (item) =>
              item.name !== "auto" &&
              item.status === "ready" &&
              item.capabilities.includes("video_generation"),
          );
        return {
          phase,
          required,
          provider,
          model,
          providerCapabilityReady,
          ready:
            providerReady &&
            providerCapabilityReady &&
            modelReady &&
            !nativeVideoMissing,
        };
      }),
    [catalog, modelCatalog, modelSelection, providers, strategy],
  );
  const imageSourceReady =
    imageSource === "generate" ||
    files.length > 0 ||
    storedSketchFilenames.length > 0 ||
    Boolean(selectedStyleProfile);
  const manualInputIssue = useMemo(() => {
    if (stageAutonomy.script === "manual" && !script.trim())
      return "A etapa Roteiro está manual; escreva ou cole o roteiro acima.";
    if (
      stageAutonomy.image === "manual" &&
      !files.length &&
      !storedSketchFilenames.length &&
      !selectedStyleProfile
    )
      return "A etapa Imagens está manual; envie uma imagem ou selecione um perfil visual.";
    if (stageAutonomy.audio === "manual" && !audioFile)
      return "A etapa Narração está manual; envie um arquivo de voz.";
    if (stageAutonomy.bgm === "manual" && !bgmFile)
      return "A etapa BGM está manual; envie uma faixa de fundo.";
    if (stageAutonomy.sfx === "manual" && !sfxFiles.length)
      return "A etapa SFX está manual; envie pelo menos um efeito.";
    return "";
  }, [
    audioFile,
    bgmFile,
    files.length,
    storedSketchFilenames.length,
    script,
    selectedStyleProfile,
    sfxFiles.length,
    stageAutonomy,
  ]);
  const preflightReady =
    routingPreflight.every((item) => item.ready) &&
    imageSourceReady &&
    !manualInputIssue;

  const selectSketches = (selected: File[]) => {
    sketchPreviews.forEach((preview) => URL.revokeObjectURL(preview));
    setFiles(selected);
    setStoredSketchFilenames([]);
    setSelectedStyleProfile("");
    setSketchPreviews(selected.map((file) => URL.createObjectURL(file)));
  };
 const selectStoredSketch = (sketch: AvailableSketch) => {
   sketchPreviews.forEach((preview) => URL.revokeObjectURL(preview));
   setFiles([]);
   setStoredSketchFilenames([sketch.filename]);
   setSelectedStyleProfile("");
   setSketchPreviews([
     `${API}/api/uploads/sketches/${encodeURIComponent(sketch.filename)}`,
   ]);
   setImageSource("reference");
   setProfileMessage(`referência do workspace selecionada · ${sketch.filename}`);
 };
  const selectStoredSketches = (sketches: AvailableSketch[]) => {
    sketchPreviews.forEach((preview) => URL.revokeObjectURL(preview));
    const filenames = sketches.map((sketch) => sketch.filename);
    setFiles([]);
    setStoredSketchFilenames(filenames);
    setSelectedStyleProfile("");
    setSketchPreviews(
      filenames.map(
        (filename) =>
          API + "/api/uploads/sketches/" + encodeURIComponent(filename),
      ),
    );
    setImageSource("reference");
    setProfileMessage(
      filenames.length
        ? String(filenames.length) + " referência(s) do workspace selecionada(s)"
        : "referências do workspace removidas",
    );
  };
 const toggleStoredSketch = (sketch: AvailableSketch) => {
   const selected = storedSketchFilenames.includes(sketch.filename);
    if (!selected && storedSketchFilenames.length >= 10) {
      setProfileMessage("limite de 10 referências atingido");
      return;
    }
   const nextFilenames = selected
      ? storedSketchFilenames.filter((filename) => filename !== sketch.filename)
      : [...storedSketchFilenames, sketch.filename];
    selectStoredSketches(
      nextFilenames
        .map((filename) => availableSketches.find((item) => item.filename === filename))
        .filter((item): item is AvailableSketch => Boolean(item)),
    );
  };
  useEffect(() => {
    if (imageSource !== "reference") return;
    const dropzone = document.querySelector<HTMLElement>(".reference-drop");
    if (!dropzone) return;
    const onDragEnter = (event: DragEvent) => {
      event.preventDefault();
      dropzone.classList.add("dragging");
    };
    const onDragOver = (event: DragEvent) => {
      event.preventDefault();
      dropzone.classList.add("dragging");
    };
    const onDragLeave = (event: DragEvent) => {
      event.preventDefault();
      if (!dropzone.contains(event.relatedTarget as Node | null))
        dropzone.classList.remove("dragging");
    };
    const onDrop = (event: DragEvent) => {
      event.preventDefault();
      dropzone.classList.remove("dragging");
      const selected = Array.from(event.dataTransfer?.files || []).filter(
        (file) => file.type.startsWith("image/"),
      );
      if (selected.length) {
        selectSketches(selected);
        setImageSource("reference");
      }
    };
    dropzone.addEventListener("dragenter", onDragEnter);
    dropzone.addEventListener("dragover", onDragOver);
    dropzone.addEventListener("dragleave", onDragLeave);
    dropzone.addEventListener("drop", onDrop);
    return () => {
      dropzone.removeEventListener("dragenter", onDragEnter);
      dropzone.removeEventListener("dragover", onDragOver);
      dropzone.removeEventListener("dragleave", onDragLeave);
      dropzone.removeEventListener("drop", onDrop);
    };
  }, [imageSource]);

  const moveScene = (from: number, to: number) => {
    if (
      from === to ||
      from < 0 ||
      to < 0 ||
      from >= orderedScenes.length ||
      to >= orderedScenes.length
    )
      return;
    const next = [...orderedScenes.map((item) => item.originalIndex)];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setSceneOrder(next);
    setSceneCaptions((current) => {
      const captions = [...current];
      const [caption] = captions.splice(from, 1);
      captions.splice(to, 0, caption || "");
      return captions;
    });
    setScenePrompts((current) => {
      const prompts = [...current];
      const [prompt] = prompts.splice(from, 1);
      prompts.splice(to, 0, prompt || "");
      return prompts;
    });
    setSceneDurations((current) => {
      const durations = [...current];
      const [duration] = durations.splice(from, 1);
      durations.splice(to, 0, duration || 4);
      return durations;
    });
    setSelectedScene(to);
  };

  const uploadSketches = async () => {
    if (!files.length) return [];
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    const response = await fetch(`${API}/api/uploads/sketches`, {
      method: "POST",
      body: form,
    });
    const data = await response.json();
    return (data.accepted || [])
      .filter((item: { status: string }) => item.status === "accepted")
      .map((item: { filename: string }) => item.filename);
  };

  const uploadAssets = async (endpoint: string, selected: File[]) => {
    if (!selected.length) return [];
    const form = new FormData();
    selected.forEach((file) => form.append("files", file));
    const response = await fetch(`${API}/api/uploads/${endpoint}`, {
      method: "POST",
      body: form,
    });
    if (!response.ok)
      throw new Error(`Não foi possível enviar o arquivo de ${endpoint}`);
    const data = await response.json();
    return (data.accepted || [])
      .filter((item: { status: string }) => item.status === "accepted")
      .map((item: { filename: string }) => item.filename);
  };

 const saveStyleProfile = async () => {
    if (!files.length && !storedSketchFilenames.length) {
     setProfileMessage("selecione pelo menos um desenho antes de salvar");
     return;
   }
   setProfileMessage("validando referências…");
   try {
      const sketchFilenames = files.length
        ? await uploadSketches()
        : storedSketchFilenames;
      const response = await fetch(`${API}/api/styles/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: profileName,
          sketch_filenames: sketchFilenames,
        }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail || "não foi possível salvar o perfil");
      setStyleProfiles((current) => [
        data,
        ...current.filter((item) => item.profile_id !== data.profile_id),
      ]);
      setSelectedStyleProfile(data.profile_id);
      setImageSource("reference");
      setProfileMessage(`perfil salvo · ${data.reference_count} referência(s)`);
    } catch (error) {
      setProfileMessage(String(error).replace(/^Error:\s*/, ""));
    }
  };

  const prepareLoraDataset = async () => {
    if (!selectedStyleProfile) {
      setProfileMessage("salve ou selecione um perfil visual primeiro");
      return;
    }
    setLoraTrainingBusy(true);
    setProfileMessage("preparando dataset LoRA local…");
    try {
      const response = await fetch(
        `${API}/api/styles/profiles/${selectedStyleProfile}/lora-dataset`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ trigger_word: "studio_sketch", resolution: 512 }),
        },
      );
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail || "não foi possível preparar o dataset");
      setProfileMessage(
        `dataset LoRA pronto · ${data.reference_count} fotos · treinamento ainda não iniciado`,
      );
      setLoraTrainingStatus(data.training_status || data.status || "dataset_ready");
    } catch (error) {
      setProfileMessage(String(error).replace(/^Error:\s*/, ""));
    } finally {
      setLoraTrainingBusy(false);
    }
  };

  const pollLoraTraining = async (profileId: string) => {
    try {
      const response = await fetch(
        `${API}/api/styles/profiles/${profileId}/lora-dataset`,
      );
      const data = await response.json();
      if (!response.ok) return;
      const status = data.training_status || data.status || "unknown";
      setLoraTrainingStatus(status);
      if (status === "running") {
        window.setTimeout(() => void pollLoraTraining(profileId), 1500);
      } else if (status === "completed") {
        setProfileMessage(`LoRA treinado localmente · ${data.adapter_output || "adaptador pronto"}`);
      } else if (status === "failed") {
        setProfileMessage(`treinamento LoRA falhou · ${data.error || "consulte o log local"}`);
      }
    } catch {
      setProfileMessage("não foi possível consultar o treinamento LoRA");
    }
  };

  const trainLora = async () => {
    if (!selectedStyleProfile) {
      setProfileMessage("selecione um perfil visual primeiro");
      return;
    }
    setLoraTrainingBusy(true);
    setProfileMessage("iniciando treinamento LoRA local…");
    try {
      const response = await fetch(
        `${API}/api/styles/profiles/${selectedStyleProfile}/lora-train`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ steps: 40 }),
        },
      );
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail || "não foi possível iniciar o treinamento");
      setLoraTrainingStatus(data.training_status || "running");
      setProfileMessage(
        `treinamento local iniciado · ${data.steps || 40} passos · acompanhe o status aqui`,
      );
      void pollLoraTraining(selectedStyleProfile);
    } catch (error) {
      setProfileMessage(String(error).replace(/^Error:\s*/, ""));
    } finally {
      setLoraTrainingBusy(false);
    }
  };

  const poll = async (id: string, requestId = ++jobPollRequest.current) => {
    const current: Job = await fetch(`${API}/api/jobs/${id}`).then((r) =>
      r.json(),
    );
    if (requestId !== jobPollRequest.current) return;
    setJob(current);
    if (current.result?.scenes) {
      const persistedReferences = Array.from(
        new Set(
          current.result.scenes.flatMap((scene) => scene.sketch_inputs || []),
        ),
      ).filter(Boolean);
      setStoredSketchFilenames(persistedReferences);
      setSceneCaptions(
        current.result.scenes.map((scene) => scene.caption || ""),
      );
      setScenePrompts(
        current.result.scenes.map((scene) =>
          normalizeScenePrompt(scene.prompt || ""),
        ),
      );
      setSceneDurations(
        current.result.scenes.map((scene) => scene.duration_seconds || 4),
      );
      setSceneOrder(current.result.scenes.map((_, index) => index));
      setSelectedScene(0);
    }
    if (current.result?.provider_selection)
      setProviders(current.result.provider_selection as Record<Phase, string>);
    if (current.result?.model_selection)
      setModelSelection(
        current.result.model_selection as Record<Phase, string>,
      );
    if (current.result?.video_strategy)
      setStrategy(current.result.video_strategy);
    if (
      current.result?.style &&
      styles.some((item) => item.value === current.result?.style)
    )
      setStyle(current.result.style);
    if (current.result?.target_seconds)
      setTargetSeconds(current.result.target_seconds);
    if (current.result?.output_format)
      setOutputFormat(current.result.output_format);
    if (current.result?.stage_autonomy)
      setStageAutonomy(
        current.result.stage_autonomy as Record<StageKey, Autonomy>,
      );
    if (current.result?.render.audio_mix)
      setAudioMix(current.result.render.audio_mix);
    if (
      ![
        "completed",
        "awaiting_approval",
        "blocked",
        "failed",
        "cancelled",
      ].includes(current.status)
    )
      timer.current = window.setTimeout(() => void poll(id, requestId), 700);
    if (current.result?.render.url) {
      const next = [
        {
          project_id: current.result.project_id,
          title: current.result.title,
          url: current.result.render.url,
        },
        ...history.filter((item) => item.url !== current.result?.render.url),
      ].slice(0, 8);
      setHistory(next);
      localStorage.setItem("studio-history", JSON.stringify(next));
    }
  };

  const copyScript = async () => {
    if (job?.result?.script && navigator.clipboard)
      await navigator.clipboard.writeText(job.result.script);
  };
  const copyPublishPack = async () => {
    const pack = (
      job?.result as (Result & { publish_pack?: PublishPack }) | undefined
    )?.publish_pack;
    if (!pack || !navigator.clipboard) return;
    await navigator.clipboard.writeText(
      [pack.title, pack.description, (pack.hashtags || []).join(" ")]
        .filter(Boolean)
        .join("\n\n"),
    );
  };

  const draftScript = async () => {
    if (!topic.trim() || scriptPreviewBusy) return;
    setScriptPreviewBusy(true);
    setScriptPreviewMessage("gerando roteiro com pesquisa e fallback…");
    try {
      const response = await fetch(`${API}/api/script/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic,
          style,
          script: script.trim() || null,
          target_seconds: targetSeconds,
          provider_selection: { script: providers.script },
          model_selection: { script: modelSelection.script },
        }),
      });
      const data: ScriptPreview = await response.json();
      if (!response.ok)
        throw new Error(
          (data as { detail?: string }).detail ||
            "não foi possível gerar o roteiro",
        );
      setScript(data.script || "");
      setScriptPreviewMessage(
        `rascunho pronto · ${data.provider || "fallback"} · virality ${data.virality_score ?? "—"}%`,
      );
    } catch (error) {
      setScriptPreviewMessage(String(error).replace(/^Error:\s*/, ""));
    } finally {
      setScriptPreviewBusy(false);
    }
  };

  const probeIntegration = async (integration: IntegrationKey) => {
    setProbeBusy(integration);
    setProbeMessage(`testando ${integration}…`);
    try {
      const response = await fetch(`${API}/api/integrations/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ integration }),
      });
      const data = await response.json();
      setProbeResults((current) => ({ ...current, [integration]: data }));
      setProbeMessage(
        `${integration}: ${data.status}${data.model ? ` · ${data.model}` : ""} · ${data.message || "sem detalhes"}`,
      );
      const [healthResponse, providersResponse, modelsResponse] =
        await Promise.all([
          fetch(`${API}/api/health`),
          fetch(`${API}/api/providers`),
          fetch(`${API}/api/models`),
        ]);
      if (healthResponse.ok) setHealthDetails(await healthResponse.json());
      if (providersResponse.ok) setCatalog(await providersResponse.json());
      if (modelsResponse.ok) setModelCatalog(await modelsResponse.json());
    } catch (error) {
      setProbeMessage(
        `falha no diagnóstico: ${String(error).replace(/^Error:\s*/, "")}`,
      );
    } finally {
      setProbeBusy("");
    }
  };

  const cancelJob = async () => {
    if (
      !job?.job_id ||
      job.job_id === "local" ||
      ["completed", "blocked", "failed", "cancelled"].includes(job.status)
    )
      return;
    const response = await fetch(`${API}/api/jobs/${job.job_id}/cancel`, {
      method: "POST",
    });
    const updated: Job = await response.json();
    if (response.ok) setJob(updated);
  };

  const retryJob = async () => {
    if (!job?.job_id || job.job_id === "local") return;
    const response = await fetch(`${API}/api/jobs/${job.job_id}/retry`, {
      method: "POST",
    });
    const updated: Job = await response.json();
    if (!response.ok) {
      setJob((current) =>
        current
          ? {
              ...current,
              error: updated.error || "Não foi possível repetir a produção",
            }
          : current,
      );
      return;
    }
    setJob(updated);
    void refreshQueue();
    await poll(updated.job_id);
  };

  const cancelQueueJob = async (jobId: string) => {
    const response = await fetch(`${API}/api/jobs/${jobId}/cancel`, {
      method: "POST",
    });
    if (!response.ok) return;
    const updated: Job = await response.json();
    if (job?.job_id === jobId) setJob(updated);
    await refreshQueue();
  };

  const retryQueueJob = async (jobId: string) => {
    const response = await fetch(`${API}/api/jobs/${jobId}/retry`, {
      method: "POST",
    });
    if (!response.ok) return;
    const updated: Job = await response.json();
    setJob(updated);
    await refreshQueue();
    await poll(updated.job_id);
  };

  const approveJob = async () => {
    if (!job?.job_id || job.status !== "awaiting_approval") return;
    const response = await fetch(`${API}/api/jobs/${job.job_id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        script: script.trim() || job.result?.script || "",
        scene_prompts: scenePrompts,
        scene_captions: sceneCaptions,
      }),
    });
    const updated: Job = await response.json();
    if (!response.ok) {
      setJob((current) =>
        current
          ? {
              ...current,
              status: "failed",
              error: updated.error || "Não foi possível aprovar o plano",
            }
          : current,
      );
      return;
    }
    setJob(updated);
    void refreshQueue();
    await poll(updated.job_id);
  };

  const saveEdits = async (selectedOnly = false) => {
    if (!job?.result?.project_id || !job.result.scenes?.length) return;
    const order =
      sceneOrder.length === job.result.scenes.length
        ? sceneOrder
        : job.result.scenes.map((_, index) => index);
    const response = await fetch(
      `${API}/api/projects/${job.result.project_id}/edit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scene_order: order,
          ...(selectedOnly ? { scene_indexes: [selectedScene] } : {}),
          captions: sceneCaptions,
          scene_prompts: scenePrompts,
          scene_durations: sceneDurations,
          transition: transitionStyle,
          motion_style: motionStyle,
          audio_mix: audioMix,
        }),
      },
    );
    const edited = await response.json();
    if (!response.ok) {
      setJob((current) =>
        current
          ? {
              ...current,
              status: "failed",
              error: edited.detail || "Não foi possível rerenderizar",
            }
          : current,
      );
      return;
    }
    setJob((current) =>
      current?.result
        ? {
            ...current,
            result: {
              ...current.result,
              scenes: edited.scenes,
              render: edited.render,
              transition: edited.transition,
              motion_style: edited.motion_style,
            },
          }
        : current,
    );
    setEditorMessage(
      `${edited.render.regenerated_scene_indexes?.length || 0} cena(s) regenerada(s) · ${edited.render.reused_scene_indexes?.length || 0} reutilizada(s)${selectedOnly ? " · escopo: cena selecionada" : ""}`,
    );
    setSceneDurations(
      edited.scenes.map((scene: Scene) => scene.duration_seconds || 4),
    );
    setScenePrompts(edited.scenes.map((scene: Scene) => scene.prompt || ""));
    setTransitionStyle(edited.transition || transitionStyle);
    setMotionStyle(edited.motion_style || motionStyle);
    if (edited.render.audio_mix) setAudioMix(edited.render.audio_mix);
    setSceneOrder(edited.scenes.map((_: Scene, index: number) => index));
    setSelectedScene(0);
    setHistory((current) =>
      [
        {
          project_id: edited.project_id,
          title: edited.title,
          url: edited.render.url,
        },
        ...current.filter((item) => item.url !== edited.render.url),
      ].slice(0, 8),
    );
  };

  const loadProject = async (projectId: string) => {
    const requestId = ++projectLoadRequest.current;
    const response = await fetch(`${API}/api/projects/${projectId}`);
    if (!response.ok) return;
    const project = await response.json();
    if (requestId !== projectLoadRequest.current) return;
    const scenes: Scene[] = project.scenes || [];
    const persistedReferences = Array.from(
      new Set([
        ...((project.style_profile?.reference_files || []) as string[]),
        ...scenes.flatMap((scene) => scene.sketch_inputs || []),
      ]),
    ).filter(Boolean);
    setStoredSketchFilenames(persistedReferences);
    setJob({
      job_id: `project-${projectId}`,
      status: "completed",
      phase: "completed",
      progress: 100,
      events: project.events || [],
      result: project,
    });
    if (project.topic || project.title)
      setTopic(project.topic || project.title || "");
    if (typeof project.script === "string") setScript(project.script);
    if (styles.some((item) => item.value === project.style))
      setStyle(project.style);
    setSceneCaptions(scenes.map((scene) => scene.caption || ""));
    setScenePrompts(
      scenes.map((scene) => normalizeScenePrompt(scene.prompt || "")),
    );
    setSceneDurations(scenes.map((scene) => scene.duration_seconds || 4));
    setSceneOrder(scenes.map((_: Scene, index: number) => index));
    setSelectedScene(0);
    setTransitionStyle(
      project.transition || project.render?.transition || "dissolve",
    );
    setMotionStyle(
      project.motion_style || project.render?.motion_style || "ken_burns",
    );
    if (project.render?.audio_mix) setAudioMix(project.render.audio_mix);
    if (project.stage_autonomy)
      setStageAutonomy((current) => ({
        ...current,
        ...project.stage_autonomy,
      }));
    if (project.provider_selection)
      setProviders((current) => ({
        ...current,
        ...project.provider_selection,
      }));
    if (project.model_selection)
      setModelSelection((current) => ({
        ...current,
        ...project.model_selection,
      }));
    if (project.video_strategy) setStrategy(project.video_strategy);
    if (project.target_seconds) setTargetSeconds(project.target_seconds);
    if (
      project.output_format === "vertical" ||
      project.output_format === "horizontal" ||
      project.output_format === "square"
    )
      setOutputFormat(project.output_format);
    if (project.style_profile_id)
      setSelectedStyleProfile(project.style_profile_id);
    setActiveTab("studio");
  };

  const generate = async (event: FormEvent) => {
    event.preventDefault();
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = undefined;
    setSelectedScene(0);
    try {
      const preflightResponse = await fetch(`${API}/api/providers/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style,
          video_strategy: strategy,
          provider_selection: providers,
          model_selection: modelSelection,
        }),
      });
      const preflight = await preflightResponse.json();
      if (!preflightResponse.ok || !preflight.valid) {
        setScriptPreviewMessage(
          (
            preflight.errors || [
              "A configuração atual não passou no preflight do backend.",
            ]
          ).join(" · "),
        );
        return;
      }
      setJob({
        job_id: "local",
        status: "running",
        phase: "queued",
        progress: 3,
        events: [
          {
            phase: "queued",
            message: "Preflight confirmado; criando job…",
            progress: 3,
          },
        ],
      });
      setSceneOrder([]);
      const uploadedSketchFilenames = selectedStyleProfile
        ? []
        : await uploadSketches();
      const sketchFilenames =
        imageSource === "reference" && !uploadedSketchFilenames.length
          ? storedSketchFilenames
          : uploadedSketchFilenames;
      const audioFilenames = await uploadAssets(
        "audio",
        audioFile ? [audioFile] : [],
      );
      const bgmFilenames = await uploadAssets("bgm", bgmFile ? [bgmFile] : []);
      const sfxFilenames = await uploadAssets("sfx", sfxFiles);
      const response = await fetch(`${API}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          style,
          topic,
          script: script || null,
          target_seconds: targetSeconds,
          output_format: outputFormat,
          image_source: imageSource,
          style_profile_id: selectedStyleProfile || null,
          sketch_filenames: sketchFilenames,
          audio_filename: audioFilenames[0] || null,
          bgm_filename: bgmFilenames[0] || null,
          sfx_filenames: sfxFilenames,
          stage_autonomy: stageAutonomy,
          video_strategy: strategy,
          narration_language: language,
          provider_selection: providers,
          model_selection: modelSelection,
        }),
      });
      const created: Job = await response.json();
      if (!response.ok)
        throw new Error(created.error || "Não foi possível criar o job");
      void refreshQueue();
      await poll(created.job_id);
    } catch (error) {
      setJob({
        job_id: "error",
        status: "failed",
        phase: "failed",
        progress: 0,
        events: [],
        error: String(error),
      });
    }
  };

  return (
    <div className="studio-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Sparkles size={17} />
          </div>
          <div>
            <strong>IN-HOUSE</strong>
            <span>VIDEO STUDIO / BETA</span>
          </div>
        </div>
        <div className="top-status">
          <span className="status-dot" />
          {health}
          <span className="divider" />
          local workspace <ChevronDown size={14} />
        </div>
      </header>
      <div className="workspace">
        {activeTab === "settings" ? (
          <>
            <RuntimeDiagnostics
              config={runtimeConfig}
              onSaved={setRuntimeConfig}
            />
            <PiperRuntimeCard config={runtimeConfig} />
            <ImageRuntimeCard config={runtimeConfig} />
            <AvatarRuntimeCard
              config={runtimeConfig}
              onSaved={setRuntimeConfig}
            />
          </>
        ) : null}
        {job?.status === "running" ? (
          <LiveProductionBanner job={job} api={API} />
        ) : null}
        {job && ["failed", "blocked", "cancelled"].includes(job.status) ? (
          <RetryBanner job={job} onRetry={() => void retryJob()} />
        ) : null}
        <aside className="rail">
          <button
            className={`rail-button ${activeTab === "studio" ? "selected" : ""}`}
            onClick={() => setActiveTab("studio")}
          >
            <WandSparkles size={18} />
            <span>Studio</span>
          </button>
          <button
            className={`rail-button ${activeTab === "library" ? "selected" : ""}`}
            onClick={() => setActiveTab("library")}
          >
            <FolderOpen size={18} />
            <span>Biblioteca</span>
          </button>
          <button
            className={`rail-button ${activeTab === "providers" ? "selected" : ""}`}
            onClick={() => setActiveTab("providers")}
          >
            <Workflow size={18} />
            <span>Providers</span>
          </button>
          <button
            className={`rail-button ${activeTab === "settings" ? "selected" : ""}`}
            onClick={() => setActiveTab("settings")}
          >
            <Settings2 size={18} />
            <span>Config</span>
          </button>
          <div className="rail-spacer" />
          <div className="quota">
            <Gauge size={15} />
            <span>LOCAL</span>
            <strong>∞</strong>
          </div>
        </aside>
        <main className="content">
          <div className="page-heading">
            <div>
              <p className="kicker">DIRECTOR WORKSPACE</p>
              <h1>Crie uma produção completa.</h1>
              <p className="subhead">
                Um conceito entra. Roteiro, cenas, voz e vídeo saem.
              </p>
            </div>
            <button
              className="new-button"
              onClick={() => {
                projectLoadRequest.current += 1;
                jobPollRequest.current += 1;
                if (timer.current) window.clearTimeout(timer.current);
                timer.current = undefined;
                autoAttachedJob.current = "";
                autoOpenedLatestProject.current = true;
                setTopic("");
                setScript("");
                setTargetSeconds(35);
                setOutputFormat("vertical");
                setSceneCaptions([]);
                setScenePrompts([]);
                setSceneDurations([]);
                setTransitionStyle("dissolve");
                setSceneOrder([]);
                setSelectedScene(0);
                setFiles([]);
                setStoredSketchFilenames([]);
                setImageSource("generate");
                setAudioFile(null);
                setBgmFile(null);
                setSfxFiles([]);
                selectSketches([]);
                setJob(null);
              }}
            >
              <Plus size={16} /> novo projeto
            </button>
          </div>
          {activeTab === "studio" ? (
            <>
              {job?.result?.style_profile ? (
                <div className="style-profile-strip">
                  <div>
                    <span className="field-label">Perfil visual</span>
                    <strong>
                      {job.result.style_profile.mode === "reference"
                        ? "Referência preservada"
                        : "Geração automática"}
                    </strong>
                  </div>
                  <small>
                    {job.result.style_profile.reference_count || 0}{" "}
                    referência(s) ·{" "}
                    {job.result.style_profile.conditioning_provider ||
                      "aguardando provider"}{" "}
                    · gate {job.result.style_profile.quality_gate || "n/a"}
                    {job.result.style_profile.reference_usage?.length ? (
                      <> · cenas: {job.result.style_profile.reference_usage.join(" → ")}</>
                    ) : null}
                  </small>
                </div>
              ) : null}
              <div className="studio-grid">
                <section className="panel brief-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">01</span>
                      <h2>Briefing da produção</h2>
                    </div>
                    <span className="live-badge">
                      <Activity size={13} />{" "}
                      {mode === "autopilot" ? "AUTOPILOT" : "DIRECTOR"}
                    </span>
                  </div>
                  <form onSubmit={generate}>
                    <label className="field-label">
                      Conceito{" "}
                      <span>obrigatório · descreva o tema em uma frase</span>
                    </label>
                    <textarea
                      className="concept"
                      value={topic}
                      onChange={(event) => setTopic(event.target.value)}
                      placeholder="Ex.: História do Japão: como ele evoluiu até a era moderna…"
                    />
                    <label className="field-label script-label">
                      Roteiro próprio <span>opcional · vazio = IA escreve</span>
                    </label>
                    <textarea
                      className="concept script-input"
                      value={script}
                      onChange={(event) => {
                        setScript(event.target.value);
                        setScriptPreviewMessage("");
                      }}
                      placeholder="Deixe vazio para gerar a partir do conceito, ou cole seu roteiro aqui…"
                    />
                    <div className="script-tools">
                      <button
                        type="button"
                        className="text-button"
                        disabled={!topic.trim() || scriptPreviewBusy}
                        onClick={() => void draftScript()}
                      >
                        <WandSparkles size={14} />
                        {scriptPreviewBusy
                          ? "gerando roteiro…"
                          : "gerar roteiro a partir do conceito"}
                      </button>
                      {scriptPreviewMessage ? (
                        <span>{scriptPreviewMessage}</span>
                      ) : null}
                    </div>
                    <div className="one-click-guide">
                      <div className="one-click-head">
                        <div>
                          <strong>
                            Fluxo automático de produção · sem upload
                            obrigatório
                          </strong>
                          <span>
                            Você só precisa escrever o conceito; o Studio cria o
                            roteiro, as imagens, a voz e o MP4.
                          </span>
                        </div>
                        <button
                          type="button"
                          className="text-button"
                          onClick={activateAutomaticFlow}
                        >
                          <Sparkles size={13} /> usar fluxo automático
                        </button>
                      </div>
                      <div className="one-click-steps">
                        <span>
                          <b>01</b> IA escreve
                        </span>
                        <span>
                          <b>02</b> 3 imagens locais
                        </span>
                        <span>
                          <b>03</b> Piper narra
                        </span>
                        <span>
                          <b>04</b> MP4{" "}
                          {selectedOutputFormat.dimensions.split(" · ")[1]}
                        </span>
                      </div>
                    </div>
                    <div className="field-row">
                      <label>
                        <span className="field-label">Modo</span>
                        <select
                          value={mode}
                          onChange={(event) => setMode(event.target.value)}
                        >
                          <option value="autopilot">Autopilot</option>
                          <option value="director">Director</option>
                        </select>
                      </label>
                      <label>
                        <span className="field-label">Estilo</span>
                        <select
                          value={style}
                          onChange={(event) => setStyle(event.target.value)}
                        >
                          {styles.map((item) => (
                            <option key={item.value} value={item.value}>
                              {item.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="visual-source-card">
                      <div className="visual-source-head">
                        <div>
                          <strong>Fonte das imagens</strong>
                          <span>
                            Desenho é opcional: o padrão é a IA criar os frames
                            localmente.
                          </span>
                        </div>
                        <ImageIcon size={18} />
                      </div>
                      <div className="visual-source-options">
                        <button
                          type="button"
                          className={
                            imageSource === "generate"
                              ? "visual-source-option selected"
                              : "visual-source-option"
                          }
                          onClick={() => {
                            setImageSource("generate");
                            if (files.length || storedSketchFilenames.length)
                              selectSketches([]);
                            setProviders((current) => ({
                              ...current,
                              image: "auto",
                            }));
                            setModelSelection((current) => ({
                              ...current,
                              image: "auto",
                            }));
                            setStageAutonomy((current) => ({
                              ...current,
                              image: "autonomous",
                            }));
                          }}
                        >
                          <span className="visual-source-radio" />
                          <div>
                            <strong>
                              Gerar imagens automaticamente{" "}
                              <em>recomendado · sem upload</em>
                            </strong>
                            <small>
                              {(imageSource === "generate"
                                ? selectedImageEngine
                                : "SD-Turbo local")} prepara 3 imagens locais a
                              partir do conceito e do roteiro.
                            </small>
                          </div>
                        </button>
                        <button
                          type="button"
                          className={
                            imageSource === "reference"
                              ? "visual-source-option selected"
                              : "visual-source-option"
                          }
                          onClick={() => setImageSource("reference")}
                        >
                          <span className="visual-source-radio" />
                          <div>
                            <strong>Usar meu desenho como referência</strong>
                            <small>
                              Só escolha esta opção se quiser enviar fotos do
                              papel para orientar traço, composição e
                              personagens.
                            </small>
                          </div>
                        </button>
                      </div>
                      {imageSource === "reference" ? (
                        <div className="reference-drop">
                          <ImageIcon size={18} />
                          <div>
                            <strong>
                              {files.length || storedSketchFilenames.length
                                ? `${files.length || storedSketchFilenames.length} desenho(s) selecionado(s)`
                                : "Envie pelo menos 1 foto do desenho"}
                            </strong>
                            <span>
                              {files.length
                                ? "O traço será incorporado aos frames desta produção."
                                : storedSketchFilenames.length
                                  ? "Referências salvas neste projeto; elas serão reutilizadas na próxima geração."
                                : "Uma foto já basta · PNG, JPG ou WEBP · até 10 referências."}
                            </span>
                            <small className="reference-tip">
                              Clique em “adicionar desenho” ou arraste a foto
                              para esta área. Dica: fotografe de cima, com boa
                              luz e o papel inteiro visível.
                            </small>
                            {!files.length && availableSketches.length ? (
                             <div className="workspace-sketches">
                                <small>Referências já encontradas neste workspace · selecione até 10</small>
                               <div className="workspace-sketch-list">
                                 {availableSketches.slice(0, 6).map((sketch) => (
                                   <button
                                     type="button"
                                      className={`workspace-sketch ${storedSketchFilenames.includes(sketch.filename) ? "selected" : ""}`}
                                     key={sketch.filename}
                                      onClick={() => toggleStoredSketch(sketch)}
                                      title={`${storedSketchFilenames.includes(sketch.filename) ? "Remover" : "Adicionar"} ${sketch.filename}`}
                                   >
                                     <img
                                       src={`${API}/api/uploads/sketches/${encodeURIComponent(sketch.filename)}`}
                                       alt={`Referência ${sketch.filename}`}
                                     />
                                      <span>
                                        {storedSketchFilenames.includes(sketch.filename)
                                          ? "selecionada · remover"
                                          : "adicionar"}
                                      </span>
                                   </button>
                                 ))}
                               </div>
                             </div>
                           ) : null}
                          </div>
                          <label className="upload-button">
                            {files.length || storedSketchFilenames.length
                              ? "trocar desenho"
                              : "adicionar desenho"}
                            <input
                              type="file"
                              accept="image/png,image/jpeg,image/webp"
                              multiple
                              onChange={(event) =>
                                selectSketches(
                                  Array.from(event.target.files || []),
                                )
                              }
                            />
                          </label>
                          {files.length || storedSketchFilenames.length ? (
                            <button
                              type="button"
                              className="clear-upload"
                              onClick={() => {
                                selectSketches([]);
                                setImageSource("generate");
                              }}
                            >
                              usar geração automática
                            </button>
                          ) : null}
                        </div>
                      ) : (
                        <div className="visual-source-confirm">
                          <span className="status-dot" /> sem desenho enviado ·
                          o {selectedImageEngine} criará os 3 frames
                          automaticamente a partir do seu conceito
                        </div>
                      )}
                      {sketchPreviews.length ? (
                        <div className="sketch-preview-strip">
                          {sketchPreviews.map((preview, index) => (
                            <img
                              key={preview}
                              src={preview}
                              alt={`Desenho de referência ${index + 1}`}
                            />
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <div className="stage-controls">
                      <div className="stage-controls-head">
                        <div>
                          <strong>Autonomia por etapa</strong>
                          <span>
                            misture IA, entrada manual e Co-piloto no mesmo
                            vídeo
                          </span>
                        </div>
                        <span className="muted-label">7 nós</span>
                      </div>
                      {stageKeys.map((stage) => (
                        <div
                          className={`stage-control stage-${stage}`}
                          key={stage}
                        >
                          <div className="stage-control-copy">
                            <strong>{stageLabels[stage]}</strong>
                            <span>
                              {stage === "research"
                                ? "busca e contexto"
                                : stage === "image"
                                  ? "arte, sketch ou SD-Turbo"
                                  : stage === "audio"
                                    ? "voz narrada"
                                    : stage === "sfx"
                                      ? "efeitos de transição"
                                      : stage === "bgm"
                                        ? "trilha de fundo"
                                        : stage === "video"
                                          ? "timeline e montagem"
                                          : "hook e roteiro"}
                            </span>
                          </div>
                          <select
                            aria-label={`Autonomia ${stageLabels[stage]}`}
                            value={stageAutonomy[stage]}
                            onChange={(event) =>
                              setStageMode(
                                stage,
                                event.target.value as Autonomy,
                              )
                            }
                          >
                            <option value="autonomous">Autônomo · IA</option>
                            <option value="copilot">Co-piloto</option>
                            <option value="manual">Manual</option>
                          </select>
                          {stage === "audio" &&
                          ["manual", "copilot"].includes(
                            stageAutonomy.audio,
                          ) ? (
                            <div className="stage-file-wrap">
                              <label className="stage-file">
                                {audioFile
                                  ? audioFile.name
                                  : stageAutonomy.audio === "copilot"
                                    ? "voz opcional · IA faz fallback"
                                    : "enviar voz obrigatória"}
                                <input
                                  type="file"
                                  accept="audio/*"
                                  onChange={(event) => {
                                    const file = event.target.files?.[0] || null;
                                    setAudioFile(file);
                                    inspectAudioFile(file);
                                  }}
                                />
                              </label>
                              {audioFile ? (
                                <small className="stage-file-meta">
                                  {audioDuration
                                    ? `duração local · ${formatMediaDuration(audioDuration)}`
                                    : "duração será validada ao carregar no backend"}
                                </small>
                              ) : null}
                            </div>
                          ) : null}
                          {stage === "bgm" &&
                          ["manual", "copilot"].includes(stageAutonomy.bgm) ? (
                            <label className="stage-file">
                              {bgmFile
                                ? bgmFile.name
                                : stageAutonomy.bgm === "copilot"
                                  ? "BGM opcional · IA faz fallback"
                                  : "enviar BGM obrigatório"}
                              <input
                                type="file"
                                accept="audio/*"
                                onChange={(event) =>
                                  setBgmFile(event.target.files?.[0] || null)
                                }
                              />
                            </label>
                          ) : null}
                          {stage === "sfx" &&
                          ["manual", "copilot"].includes(stageAutonomy.sfx) ? (
                            <label className="stage-file">
                              {sfxFiles.length
                                ? `${sfxFiles.length} SFX`
                                : stageAutonomy.sfx === "copilot"
                                  ? "SFX opcional · IA faz fallback"
                                  : "enviar SFX obrigatório"}
                              <input
                                type="file"
                                accept="audio/*"
                                multiple
                                onChange={(event) =>
                                  setSfxFiles(
                                    Array.from(event.target.files || []),
                                  )
                                }
                              />
                            </label>
                          ) : null}
                        </div>
                      ))}
                    </div>
                    <div className="field-row">
                      <label>
                        <span className="field-label">Idioma</span>
                        <select
                          value={language}
                          onChange={(event) => setLanguage(event.target.value)}
                        >
                          <option value="pt_BR">Português · Piper Faber</option>
                          <option value="en_US">English · Piper Amy</option>
                        </select>
                      </label>
                      <label>
                        <span className="field-label">Vídeo</span>
                        <select
                          value={strategy}
                          onChange={(event) => setStrategy(event.target.value)}
                        >
                          <option value="auto">Automático por estilo</option>
                          <option value="image_sequence">
                            Frame por frame
                          </option>
                          <option value="direct_video">Vídeo nativo</option>
                        </select>
                      </label>
                      <label>
                        <span className="field-label">Duração alvo</span>
                        <input
                          type="number"
                          min="10"
                          max="90"
                          step="5"
                          value={targetSeconds}
                          onChange={(event) =>
                            setTargetSeconds(
                              Math.min(
                                90,
                                Math.max(10, Number(event.target.value) || 35),
                              ),
                            )
                          }
                        />
                      </label>
                    </div>
                    <div className="output-format-card">
                      <div>
                        <strong>Formato de saída</strong>
                        <span>Escolha onde o vídeo vai ser publicado.</span>
                        <small className="format-selection-summary">
                          Prévia ativa: {selectedOutputFormat.dimensions}
                        </small>
                      </div>
                      <div className="output-format-options">
                        {outputFormats.map((item) => (
                          <button
                            type="button"
                            key={item.value}
                            className={
                              outputFormat === item.value ? "selected" : ""
                            }
                            onClick={() => setOutputFormat(item.value)}
                          >
                            <strong>{item.label}</strong>
                            <small>{item.dimensions}</small>
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="saved-style-profiles">
                      <div>
                        <strong>Perfil visual reutilizável</strong>
                        <span>
                          Salve seu traço uma vez e use em novas produções.
                        </span>
                      </div>
                      <select
                        aria-label="Perfil visual salvo"
                        value={selectedStyleProfile}
                        onChange={(event) => {
                          setSelectedStyleProfile(event.target.value);
                          if (event.target.value) {
                            setImageSource("reference");
                            setStyle("sketch_clone");
                          }
                        }}
                      >
                        <option value="">Nenhum · usar upload atual</option>
                        {styleProfiles.map((profile) => (
                          <option
                            key={profile.profile_id}
                            value={profile.profile_id}
                          >
                            {profile.name} · {profile.reference_count}{" "}
                            referência(s)
                          </option>
                        ))}
                      </select>
                      <div className="saved-style-actions">
                        <input
                          aria-label="Nome do novo perfil visual"
                          value={profileName}
                          onChange={(event) =>
                            setProfileName(event.target.value)
                          }
                          placeholder="Nome do perfil"
                        />
                        <button
                          type="button"
                          className="text-button"
                          disabled={!files.length && !storedSketchFilenames.length}
                          onClick={() => void saveStyleProfile()}
                        >
                          salvar perfil
                        </button>
                        {selectedStyleProfile ? (
                          <>
                            <button
                              type="button"
                              className="text-button"
                              disabled={loraTrainingBusy || !loraReferencesReady}
                              onClick={() => void prepareLoraDataset()}
                              title={
                                loraReferencesReady
                                  ? "Prepara as referências aprovadas para o treinamento LoRA"
                                  : "LoRA exige pelo menos três referências aprovadas"
                              }
                            >
                              {loraTrainingBusy
                                ? "preparando dataset…"
                                : loraReferencesReady
                                  ? "preparar dataset LoRA"
                                  : `LoRA: ${selectedProfileReferenceCount}/3 referências`}
                            </button>
                            <button
                              type="button"
                              className="text-button"
                              disabled={loraTrainingBusy || !loraReferencesReady}
                              onClick={() => void trainLora()}
                              title={
                                loraReferencesReady
                                  ? "Executa 40 passos locais; exige dataset preparado e pode consumir GPU"
                                  : "LoRA exige pelo menos três referências aprovadas"
                              }
                            >
                              {loraReferencesReady ? "treinar LoRA local" : "treinar LoRA · aguardando 3 fotos"}
                            </button>
                          </>
                        ) : null}
                      </div>
                      {loraTrainingStatus ? (
                        <small className="profile-message">
                          status LoRA · {loraTrainingStatus}
                        </small>
                      ) : null}
                      {selectedStyleProfile && !loraReferencesReady ? (
                        <small className="profile-message">
                          Uma foto já é suficiente para usar ControlNet na produção; o treinamento LoRA precisa de pelo menos 3 fotos nítidas do mesmo traço.
                        </small>
                      ) : null}
                      {profileMessage ? (
                        <small className="profile-message">
                          {profileMessage}
                        </small>
                      ) : null}
                    </div>
                    <p className="hint">
                      <Sparkles size={14} />{" "}
                      {style === "avatar_narrator"
                        ? "Avatar: o sistema usa frames locais até um provider de lip-sync ser conectado."
                        : "Este estilo será composto frame por frame para preservar controle visual."}
                    </p>
                    {!preflightReady ? (
                      <p className="preflight-warning">
                        <span className="status-dot" />{" "}
                        {manualInputIssue ||
                          (!imageSourceReady
                            ? "Você escolheu usar desenho como referência; envie pelo menos uma foto ou volte para geração automática."
                            : "A configuração atual pede uma capability ainda não conectada. Troque para uma opção marcada como ready para liberar a produção.")}
                      </p>
                    ) : null}
                    <button
                      className="primary-button"
                      disabled={
                        !topic.trim() ||
                        !preflightReady ||
                        job?.status === "cancelling"
                      }
                    >
                      <span>
                        {job?.status === "running"
                          ? "enfileirar produção"
                          : job?.status === "cancelling"
                            ? "cancelando…"
                            : "gerar produção"}
                      </span>
                      {job?.status === "cancelling" ? (
                        <LoaderCircle className="spin" size={17} />
                      ) : (
                        <Play size={17} fill="currentColor" />
                      )}
                    </button>
                  </form>
                </section>
                <section className="panel preview-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">02</span>
                      <h2>Preview / Canvas</h2>
                    </div>
                    <span className="format-badge">9:16 · 1080 × 1920</span>
                  </div>
                  <div className="preview-stage">
                    {job?.result?.render.url ? (
                      <video
                        className="video-preview"
                        controls
                        playsInline
                        src={`${API}${job.result.render.url}`}
                      />
                    ) : (
                      <div className="canvas-empty">
                        <div className="canvas-orbit">
                          <Sparkles size={25} />
                        </div>
                        <strong>
                          {job?.status === "awaiting_approval"
                            ? "Revisão do diretor"
                            : job?.status === "running" ||
                                job?.status === "cancelling"
                              ? `${job.phase === "queued" ? "Na fila" : productionLabels[job.phase as ProductionPhase] || job.phase}`
                              : job?.status === "cancelled"
                                ? "Produção cancelada"
                                : job?.result?.status === "blocked"
                                  ? "Produção bloqueada"
                                  : "Pronto para produzir"}
                        </strong>
                        <span>
                          {job?.status === "awaiting_approval"
                            ? "O storyboard está pronto. Revise cada cena abaixo e aprove para gerar voz e MP4."
                            : job?.status === "running" ||
                                job?.status === "cancelling"
                              ? latestMessage
                              : job?.status === "cancelled"
                                ? "O job foi interrompido e nenhum MP4 foi publicado."
                                : job?.result?.status === "blocked"
                                  ? job.result.diagnostics?.[0] ||
                                    "Revise as configurações antes de tentar novamente."
                                  : "O vídeo final aparecerá aqui com preview e controles."}
                        </span>
                        {(job?.status === "running" ||
                          job?.status === "cancelling") && (
                          <>
                            <div className="progress-track">
                              <i style={{ width: `${job.progress}%` }} />
                            </div>
                            <div className="production-stepper">
                              {productionPhases.map((phase, index) => (
                                <div
                                  className={`production-step ${index < activePhaseIndex ? "done" : index === activePhaseIndex ? "active" : "pending"}`}
                                  key={phase}
                                >
                                  <span>
                                    {index < activePhaseIndex
                                      ? "✓"
                                      : String(index + 1).padStart(2, "0")}
                                  </span>
                                  <small>{productionLabels[phase]}</small>
                                </div>
                              ))}
                            </div>
                            <button
                              type="button"
                              className="cancel-button"
                              disabled={job.status === "cancelling"}
                              onClick={() => void cancelJob()}
                            >
                              <Square size={14} />
                              {job.status === "cancelling"
                                ? "cancelando…"
                                : "cancelar produção"}
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="timeline-head">
                    <span>
                      <Layers3 size={14} /> timeline · arraste para ordenar
                    </span>
                    <span>
                      {job?.result?.render.frames || 0} cenas{" "}
                      <span className="muted-separator">/</span>{" "}
                      {job?.result?.render.strategy || "auto"}
                    </span>
                  </div>
                  <div className="timeline">
                    {orderedScenes.length
                      ? orderedScenes.map(({ originalIndex }, index) => (
                          <div
                            className={`scene-card ${selectedScene === index ? "active" : ""}`}
                            key={`${job?.result?.project_id || "draft"}-timeline-${originalIndex}`}
                            draggable
                            onClick={() => setSelectedScene(index)}
                            onDragStart={() => setDraggedScene(index)}
                            onDragOver={(event) => event.preventDefault()}
                            onDrop={() => {
                              if (draggedScene !== null)
                                moveScene(draggedScene, index);
                              setDraggedScene(null);
                            }}
                          >
                            <div className="scene-thumb">
                              {job?.result?.render.frame_urls?.[
                                originalIndex
                              ] ? (
                                <img
                                  src={`${API}${job.result.render.frame_urls[originalIndex]}`}
                                  alt={`Cena ${index + 1}`}
                                />
                              ) : (
                                <ImageIcon size={16} />
                              )}
                              <span className="scene-number">
                                {String(index + 1).padStart(2, "0")}
                              </span>
                            </div>
                            <small>
                              CENA {String(index + 1).padStart(2, "0")}
                            </small>
                          </div>
                        ))
                      : Array.from({ length: 3 }).map((_, index) => (
                          <div className="scene-card" key={index}>
                            <div className="scene-thumb">
                              <ImageIcon size={16} />
                              <span className="scene-number">
                                {String(index + 1).padStart(2, "0")}
                              </span>
                            </div>
                            <small>
                              CENA {String(index + 1).padStart(2, "0")}
                            </small>
                          </div>
                        ))}
                  </div>
                </section>
              </div>
              {queue.length ? (
                <section className="panel queue-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">QUEUE</span>
                      <h2>Fila de produção</h2>
                    </div>
                    <span className="muted-label">
                      {
                        queue.filter(
                          (item) =>
                            item.status === "running" ||
                            item.status === "queued" ||
                            item.status === "cancelling",
                        ).length
                      }{" "}
                      ativa(s) · 2 workers
                    </span>
                  </div>
                  <div className="queue-list">
                    {queue.slice(0, 6).map((item) => (
                      <article
                        className={`queue-row ${item.status}`}
                        key={item.job_id}
                      >
                        <div className="queue-row-main">
                          <span className={`queue-state ${item.status}`}>
                            {item.status === "completed"
                              ? "pronto"
                              : item.status === "awaiting_approval"
                                ? "revisão"
                                : item.status === "running"
                                  ? "produzindo"
                                  : item.status === "queued"
                                    ? "na fila"
                                    : item.status === "cancelling"
                                      ? "cancelando"
                                      : item.status}
                          </span>
                          <strong>{item.title || "Produção sem título"}</strong>
                          <small>
                            {item.phase === "director_review"
                              ? "Revisão do diretor"
                              : productionLabels[
                                  item.phase as ProductionPhase
                                ] || item.phase}{" "}
                            · {item.progress}%
                          </small>
                        </div>
                        <div className="queue-row-side">
                          <div className="queue-progress">
                            <i style={{ width: `${item.progress}%` }} />
                          </div>
                          {item.project_id && item.status === "completed" ? (
                            <button
                              type="button"
                              className="queue-open"
                              onClick={() => void loadProject(item.project_id!)}
                            >
                              abrir editor
                            </button>
                          ) : item.status === "awaiting_approval" ? (
                            <button
                              type="button"
                              className="queue-open"
                              onClick={() => void poll(item.job_id)}
                            >
                              abrir revisão
                            </button>
                          ) : ["running", "queued"].includes(item.status) ? (
                            <button
                              type="button"
                              className="queue-action queue-cancel"
                              onClick={() => void cancelQueueJob(item.job_id)}
                            >
                              cancelar
                            </button>
                          ) : ["failed", "blocked", "cancelled"].includes(
                              item.status,
                            ) ? (
                            <button
                              type="button"
                              className="queue-action queue-retry"
                              onClick={() => void retryQueueJob(item.job_id)}
                            >
                              repetir
                            </button>
                          ) : (
                            <span className="queue-percent">
                              {item.progress}%
                            </span>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}
              {job?.status === "awaiting_approval" &&
              job.result?.scenes?.length ? (
                <section className="panel director-review-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">REVIEW</span>
                      <h2>Plano pronto para aprovação</h2>
                    </div>
                    <span className="live-badge">
                      <Check size={13} /> DIRECTOR GATE
                    </span>
                  </div>
                  <p>
                    O roteiro e os frames já foram preparados. Edite o texto,
                    prompts, legendas e ordem; a voz e o MP4 só serão gerados
                    depois da sua aprovação.
                  </p>
                  <label className="review-script-label">
                    <span className="field-label">
                      Roteiro final da narração
                    </span>
                    <textarea
                      className="review-script"
                      value={script || job.result.script}
                      onChange={(event) => setScript(event.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    className="primary-button review-approve"
                    onClick={() => void approveJob()}
                  >
                    <span>aprovar e renderizar MP4</span>
                    <Play size={17} fill="currentColor" />
                  </button>
                </section>
              ) : null}
              {job?.result?.render.validation?.status === "passed" ? (
                <section className="panel render-check-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">PASS</span>
                      <h2>Render validado</h2>
                    </div>
                    <span className="healthy">
                      <span className="status-dot" /> pronto para preview
                    </span>
                  </div>
                  <div className="render-check-grid">
                    <div>
                      <span>Vídeo</span>
                      <strong>
                        {job.result.render.validation.video || "validado"}
                      </strong>
                    </div>
                    <div>
                      <span>Áudio</span>
                      <strong>
                        {job.result.render.validation.audio || "validado"}
                      </strong>
                    </div>
                    <div>
                      <span>Estratégia</span>
                      <strong>
                        {job.result.render.strategy || "image_sequence"}
                      </strong>
                    </div>
                    <div>
                      <span>Cenas</span>
                      <strong>{job.result.render.frames || 0}</strong>
                    </div>
                    <div>
                      <span>Origem das imagens</span>
                      <strong
                        title={
                          job.result.render.media_provenance?.images ||
                          "não informado"
                        }
                      >
                        {job.result.render.media_provenance?.images ||
                          "não informado"}
                      </strong>
                    </div>
                    <div>
                      <span>Áudio</span>
                      <strong>
                        {job.result.render.media_provenance?.audio ===
                        "real_wav"
                          ? "WAV real"
                          : "manifest"}
                      </strong>
                    </div>
                  </div>
                </section>
              ) : null}
              {job?.status === "running" &&
              (job.artifacts?.script ||
                job.artifacts?.images?.frame_urls?.length) ? (
                <section className="panel live-artifacts">
                  <div className="panel-head">
                    <div>
                      <span className="index">LIVE</span>
                      <h2>Materiais em produção</h2>
                    </div>
                    <span className="muted-label">
                      {job.artifacts.images?.completed
                        ? `frames ${job.artifacts.images.completed}/${job.artifacts.images.total || 3}`
                        : "não precisa esperar o MP4"}
                    </span>
                  </div>
                  {job.artifacts.script ? (
                    <div className="live-script">
                      <span className="field-label">
                        Roteiro pronto · {job.artifacts.script.provider}
                      </span>
                      <strong>
                        {job.artifacts.script.hook ||
                          job.artifacts.script.title}
                      </strong>
                      <p>{job.artifacts.script.script}</p>
                    </div>
                  ) : null}
                  {job.artifacts.images?.frame_urls?.length ? (
                    <div className="live-frame-grid">
                      {job.artifacts.images.frame_urls.map((url, index) => (
                        <img
                          key={`${url}-${job.artifacts?.images?.completed || 0}`}
                          src={`${API}${url}${url.includes("?") ? "&" : "?"}live=${job.artifacts?.images?.completed || 0}`}
                          alt={`Frame gerado ${index + 1}`}
                        />
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}
              {job?.result?.diagnostics?.length ? (
                <section className="panel diagnostics-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">CHECK</span>
                      <h2>Precisa de atenção</h2>
                    </div>
                    <span className="muted-label">validação do pipeline</span>
                  </div>
                  <div className="diagnostics-list">
                    {job.result.diagnostics.map((diagnostic, index) => (
                      <p key={`${diagnostic}-${index}`}>{diagnostic}</p>
                    ))}
                  </div>
                </section>
              ) : null}
              {job?.result ? (
                <section className="virality-strip">
                  <div>
                    <span className="field-label">
                      Virality score · heurística
                    </span>
                    <strong>{job.result.virality_score}%</strong>
                  </div>
                  <div>
                    <span className="field-label">Pesquisa</span>
                    <small>
                      {job.result.research?.status === "live"
                        ? "fontes ao vivo"
                        : "fallback local"}{" "}
                      · {(job.result.research?.sources || []).length} fonte(s)
                    </small>
                  </div>
                  <div>
                    <span className="field-label">Grounding</span>
                    <small>
                      {job.result.research?.grounding === "news_rss"
                        ? "Google News RSS"
                        : job.result.research?.grounding === "web_search"
                          ? "web search"
                          : "hipótese local"}
                    </small>
                  </div>
                </section>
              ) : null}
              {job?.result?.scenes?.length ? (
                <section className="panel scene-editor-wide">
                  <div className="panel-head">
                    <div>
                      <span className="index">03</span>
                      <h2>Editor de cenas</h2>
                    </div>
                    <label className="transition-control">
                      Transição{" "}
                      <select
                        value={transitionStyle}
                        onChange={(event) =>
                          setTransitionStyle(
                            event.target.value as "cut" | "dissolve",
                          )
                        }
                      >
                        <option value="dissolve">Dissolve</option>
                        <option value="cut">Corte seco</option>
                      </select>
                    </label>
                    <label className="transition-control">
                      Movimento{" "}
                      <select
                        value={motionStyle}
                        onChange={(event) =>
                          setMotionStyle(
                            event.target.value as "ken_burns" | "static",
                          )
                        }
                      >
                        <option value="ken_burns">Ken Burns · dinâmico</option>
                        <option value="static">Estático · preservar desenho</option>
                      </select>
                    </label>
                  </div>
                  <div className="audio-mixer">
                    <div>
                      <strong>Mixer da timeline</strong>
                      <span>ajuste cada trilha sem regenerar os assets</span>
                    </div>
                    <label>
                      Voz <output>{Math.round(audioMix.voice * 100)}%</output>
                      <input
                        type="range"
                        min="0"
                        max="1.5"
                        step="0.01"
                        value={audioMix.voice}
                        onChange={(event) =>
                          setAudioMix((current) => ({
                            ...current,
                            voice: Number(event.target.value),
                          }))
                        }
                      />
                    </label>
                    <label>
                      BGM <output>{Math.round(audioMix.bgm * 100)}%</output>
                      <input
                        type="range"
                        min="0"
                        max="1.5"
                        step="0.01"
                        value={audioMix.bgm}
                        onChange={(event) =>
                          setAudioMix((current) => ({
                            ...current,
                            bgm: Number(event.target.value),
                          }))
                        }
                      />
                    </label>
                    <label>
                      SFX <output>{Math.round(audioMix.sfx * 100)}%</output>
                      <input
                        type="range"
                        min="0"
                        max="1.5"
                        step="0.01"
                        value={audioMix.sfx}
                        onChange={(event) =>
                          setAudioMix((current) => ({
                            ...current,
                            sfx: Number(event.target.value),
                          }))
                        }
                      />
                    </label>
                  </div>
                  {job.result.render.audio_urls ? (
                    <div className="audio-preview-strip">
                      <span className="field-label">
                        Pré-escuta das trilhas
                      </span>
                      {job.result.render.audio_urls.voice ? (
                        <label>
                          Voz
                          <audio
                            controls
                            preload="metadata"
                            src={`${API}${job.result.render.audio_urls.voice}`}
                          />
                        </label>
                      ) : null}
                      {job.result.render.audio_urls.bgm ? (
                        <label>
                          BGM
                          <audio
                            controls
                            preload="metadata"
                            src={`${API}${job.result.render.audio_urls.bgm}`}
                          />
                        </label>
                      ) : null}
                      {job.result.render.audio_urls.sfx?.map((url, index) => (
                        <label key={url}>
                          SFX {index + 1}
                          <audio
                            controls
                            preload="metadata"
                            src={`${API}${url}`}
                          />
                        </label>
                      ))}
                    </div>
                  ) : null}
                  <div className="scene-editor-layout">
                    <div className="scene-editor-grid">
                      {orderedScenes.map(({ scene, originalIndex }, index) => (
                        <label
                          className={
                            selectedScene === index ? "selected-scene" : ""
                          }
                          draggable
                          key={`${job.result?.project_id}-editor-${originalIndex}`}
                          onClick={() => setSelectedScene(index)}
                          onDragStart={() => setDraggedScene(index)}
                          onDragOver={(event) => event.preventDefault()}
                          onDrop={() => {
                            if (draggedScene !== null)
                              moveScene(draggedScene, index);
                            setDraggedScene(null);
                          }}
                        >
                          <span>
                            CENA {String(index + 1).padStart(2, "0")} · arraste
                          </span>
                          <textarea
                            className="scene-prompt-input"
                            value={scenePrompts[index] ?? scene?.prompt ?? ""}
                            aria-label={`Prompt visual da cena ${index + 1}`}
                            placeholder="Direção visual desta cena"
                            onChange={(event) =>
                              setScenePrompts((current) =>
                                current.map((prompt, itemIndex) =>
                                  itemIndex === index
                                    ? event.target.value
                                    : prompt,
                                ),
                              )
                            }
                          />
                          <input
                            value={sceneCaptions[index] ?? scene?.caption ?? ""}
                            placeholder="Legenda desta cena (opcional)"
                            onChange={(event) =>
                              setSceneCaptions((current) =>
                                current.map((caption, itemIndex) =>
                                  itemIndex === index
                                    ? event.target.value
                                    : caption,
                                ),
                              )
                            }
                          />
                          <input
                            className="scene-duration-input"
                            type="number"
                            min="0.5"
                            max="30"
                            step="0.5"
                            aria-label={`Duração da cena ${index + 1} em segundos`}
                            value={
                              sceneDurations[index] ??
                              scene?.duration_seconds ??
                              4
                            }
                            onChange={(event) =>
                              setSceneDurations((current) => {
                                const next = [...current];
                                next[index] = Number(event.target.value) || 1;
                                return next;
                              })
                            }
                          />
                          <div className="scene-move-actions">
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                moveScene(index, index - 1);
                              }}
                              disabled={index === 0}
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                moveScene(index, index + 1);
                              }}
                              disabled={index === orderedScenes.length - 1}
                            >
                              ↓
                            </button>
                          </div>
                        </label>
                      ))}
                    </div>
                    <aside className="scene-inspector">
                      {orderedScenes[selectedScene] ? (
                        <>
                          <span className="field-label">Cena selecionada</span>
                          {job.result.render.frame_urls?.[
                            orderedScenes[selectedScene].originalIndex
                          ] ? (
                            <img
                              src={`${API}${job.result.render.frame_urls[orderedScenes[selectedScene].originalIndex]}`}
                              alt="Preview da cena selecionada"
                            />
                          ) : null}
                          <strong>
                            {orderedScenes[selectedScene].scene?.subject ||
                              "Direção visual"}
                          </strong>
                          <p>
                            {orderedScenes[selectedScene].scene?.prompt ||
                              "Cena pronta para edição."}
                          </p>
                        </>
                      ) : (
                        <span>Selecione uma cena na timeline.</span>
                      )}
                    </aside>
                  </div>
                  {job.status === "awaiting_approval" ? (
                    <span className="review-hint">
                      Aprovação pendente: suas alterações serão enviadas ao
                      pipeline no botão acima.
                    </span>
                  ) : (
                    <>
                      <button
                        className="text-button editor-save"
                        onClick={() => void saveEdits()}
                      >
                        <Save size={14} /> salvar ordem, prompts, legendas e
                        rerenderizar MP4
                      </button>
                      <button
                        className="text-button editor-save editor-save-local"
                        onClick={() => void saveEdits(true)}
                      >
                        <Save size={14} /> rerenderizar somente cena {selectedScene + 1}
                      </button>
                      {editorMessage ? (
                        <span className="editor-feedback">{editorMessage}</span>
                      ) : null}
                    </>
                  )}
                </section>
              ) : null}
              <section className="panel routing-panel">
                <div className="panel-head">
                  <div>
                    <span className="index">04</span>
                    <h2>Roteamento por etapa</h2>
                  </div>
                  <span className="muted-label">
                    provider + modelo + capability
                  </span>
                </div>
                <div className="routing-grid">
                  {(Object.keys(phaseLabels) as Phase[]).map((phase) => (
                    <div className="route-card" key={phase}>
                      <div className="route-icon">
                        {phase === "script" ? (
                          <WandSparkles size={15} />
                        ) : phase === "image" ? (
                          <ImageIcon size={15} />
                        ) : phase === "audio" ? (
                          <AudioLines size={15} />
                        ) : (
                          <Film size={15} />
                        )}
                      </div>
                      <div>
                        <strong>{phaseLabels[phase]}</strong>
                        <span>
                          {catalog?.[phase]?.find(
                            (item) => item.name === providers[phase],
                          )?.label || providers[phase]}
                        </span>
                      </div>
                      <select
                        aria-label={`Provider ${phaseLabels[phase]}`}
                        value={providers[phase]}
                        onChange={(event) =>
                          setProvider(phase, event.target.value)
                        }
                      >
                        {(catalog?.[phase] || []).map((item) => (
                          <option
                            key={item.name}
                            value={item.name}
                            disabled={
                              !["ready", "ready-manifest"].includes(item.status)
                            }
                          >
                            {item.label} · {item.status}
                          </option>
                        ))}
                      </select>
                      <select
                        aria-label={`Modelo IA ${phaseLabels[phase]}`}
                        value={modelSelection[phase]}
                        onChange={(event) =>
                          setModel(phase, event.target.value)
                        }
                      >
                        {(modelCatalog?.[phase] || []).map((item) => (
                          <option
                            key={item.name}
                            value={item.name}
                            disabled={!modelCompatible(phase, item)}
                          >
                            {item.label} · {item.status}
                            {!modelCompatible(phase, item) &&
                            item.status === "ready"
                              ? " · capability/provider incompatível"
                              : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
                <div className="routing-preflight">
                  <div className="routing-preflight-head">
                    <strong>
                      <Check size={14} /> Capability preflight
                    </strong>
                    <span>
                      {preflightReady
                        ? "todas as etapas prontas"
                        : "revise a capacidade destacada antes de gerar"}
                    </span>
                  </div>
                  <div className="preflight-items">
                    {routingPreflight.map((item) => (
                      <div
                        className={`preflight-item ${item.ready ? "ready" : "attention"}`}
                        key={item.phase}
                      >
                        <span>{phaseLabels[item.phase]}</span>
                        <strong>{item.ready ? "OK" : "revisar"}</strong>
                        <small>
                          {item.providerCapabilityReady
                            ? capabilityLabels[item.required]
                            : `provider sem ${capabilityLabels[item.required]}`}
                        </small>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="routing-footer">
                  <span>
                    <Check size={14} /> {selectedProviders.join(" · ")}
                  </span>
                  {resolvedProviderSummary ? (
                    <span
                      className="resolved-provider-summary"
                      title={resolvedProviderSummary}
                    >
                      <Activity size={13} /> usado: {resolvedProviderSummary}
                    </span>
                  ) : null}
                  {resolvedModelSummary ? (
                    <span
                      className="resolved-model-summary"
                      title={resolvedModelSummary}
                    >
                      modelo: {resolvedModelSummary}
                    </span>
                  ) : null}
                  <span>
                    {job?.status === "completed"
                      ? "produção concluída"
                      : job?.status === "failed"
                        ? job.error
                        : "pronto para o próximo job"}
                  </span>
                </div>
              </section>
              <section className="bottom-grid">
                <div className="panel history-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">04</span>
                      <h2>Biblioteca recente</h2>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => setActiveTab("library")}
                    >
                      ver tudo <ChevronDown size={13} />
                    </button>
                  </div>
                  {history.length ? (
                    history.slice(0, 3).map((item) => (
                      <div className="history-row" key={item.project_id}>
                        <button
                          className="mini-thumb"
                          onClick={() => void loadProject(item.project_id)}
                          title="Abrir no editor"
                        >
                          <Film size={16} />
                        </button>
                        <span>{item.title}</span>
                        <a href={`${API}${item.url}`} target="_blank">
                          <small>abrir MP4 ↗</small>
                        </a>
                      </div>
                    ))
                  ) : (
                    <div className="empty-row">
                      <FolderOpen size={18} /> suas produções aparecerão aqui
                    </div>
                  )}
                </div>
                <div className="panel health-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">05</span>
                      <h2>Pipeline health</h2>
                    </div>
                    <span className="healthy">
                      <span className="status-dot" /> healthy
                    </span>
                  </div>
                  <div className="health-list">
                    <div>
                      <span>Antigravity / script</span>
                      <strong
                        className={
                          healthDetails?.antigravity_cli?.enabled &&
                          healthDetails.antigravity_cli.available
                            ? "green"
                            : "muted"
                        }
                      >
                        {healthDetails?.antigravity_cli?.enabled
                          ? healthDetails.antigravity_cli.available
                            ? "connected"
                            : "unavailable"
                          : "disabled"}
                      </strong>
                    </div>
                    <div>
                      <span>
                        Codex / {healthDetails?.codex_cli?.model || "script"}
                      </span>
                      <strong
                        className={
                          healthDetails?.codex_cli?.enabled &&
                          healthDetails.codex_cli.available
                            ? "green"
                            : "muted"
                        }
                      >
                        {healthDetails?.codex_cli?.enabled
                          ? healthDetails.codex_cli.available
                            ? "connected"
                            : "unavailable"
                          : "disabled"}
                      </strong>
                    </div>
                    <div>
                      <span>Piper / narration</span>
                      <strong
                        className={
                          healthDetails?.integrations?.piper?.pt_BR &&
                          healthDetails.integrations.piper.en_US
                            ? "green"
                            : "muted"
                        }
                      >
                        {healthDetails?.integrations?.piper?.pt_BR &&
                        healthDetails.integrations.piper.en_US
                          ? "pt-BR · en-US"
                          : "incomplete"}
                      </strong>
                    </div>
                    <div>
                      <span>SD-Turbo / imagens</span>
                      <strong
                        className={
                          healthDetails?.integrations?.sd_turbo?.available
                            ? "green"
                            : "muted"
                        }
                      >
                        {healthDetails?.integrations?.sd_turbo?.available
                          ? "ready · local"
                          : "unavailable"}
                      </strong>
                    </div>
                    <div>
                      <span>FFmpeg / render</span>
                      <strong
                        className={
                          healthDetails?.integrations?.ffmpeg?.available
                            ? "green"
                            : "muted"
                        }
                      >
                        {healthDetails?.integrations?.ffmpeg?.available
                          ? "ready · 1080×1920"
                          : "unavailable"}
                      </strong>
                    </div>
                    <div>
                      <span>Job queue</span>
                      <strong>2 workers</strong>
                    </div>
                  </div>
                </div>
              </section>
              {job?.result?.script ? (
                <section className="panel script-result-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">06</span>
                      <h2>Roteiro gerado</h2>
                    </div>
                    <button
                      className="text-button"
                      type="button"
                      onClick={() => void copyScript()}
                    >
                      copiar roteiro
                    </button>
                  </div>
                  <p className="script-hook">
                    {job.result.script.split(".")[0]}.
                  </p>
                  <pre>{job.result.script}</pre>
                </section>
              ) : null}
              {(
                job?.result as
                  (Result & { publish_pack?: PublishPack }) | undefined
              )?.publish_pack ? (
                <section className="panel publish-pack-panel">
                  <div className="panel-head">
                    <div>
                      <span className="index">08</span>
                      <h2>Pacote de publicação</h2>
                    </div>
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => void copyPublishPack()}
                    >
                      copiar título, descrição e hashtags
                    </button>
                  </div>
                  <div className="publish-pack-grid">
                    <div>
                      <span className="field-label">Título sugerido</span>
                      <strong>
                        {
                          (
                            job?.result as
                              | (Result & { publish_pack?: PublishPack })
                              | undefined
                          )?.publish_pack?.title
                        }
                      </strong>
                    </div>
                    <div>
                      <span className="field-label">Hashtags</span>
                      <p>
                        {(
                          (
                            job?.result as
                              | (Result & { publish_pack?: PublishPack })
                              | undefined
                          )?.publish_pack?.hashtags || []
                        ).join(" ")}
                      </p>
                    </div>
                  </div>
                  <label className="publish-description">
                    <span className="field-label">Descrição</span>
                    <textarea
                      readOnly
                      value={
                        (
                          job?.result as
                            | (Result & { publish_pack?: PublishPack })
                            | undefined
                        )?.publish_pack?.description || ""
                      }
                    />
                  </label>
                </section>
              ) : null}
              {activityEvents.length ? (
                <section className="panel production-log">
                  <div className="panel-head">
                    <div>
                      <span className="index">07</span>
                      <h2>Produção ao vivo</h2>
                    </div>
                    <span className="muted-label">
                      {job?.status === "running"
                        ? "acompanhando agora"
                        : "histórico do job"}
                    </span>
                  </div>
                  <div className="activity-list">
                    {activityEvents.map((event, index) => (
                      <div
                        className={`activity-row ${event.status || (job?.status === "running" ? "running" : "success")}`}
                        key={`${event.phase}-${index}`}
                      >
                        <span className="activity-dot" />
                        <div>
                          <strong>
                            {productionLabels[event.phase as ProductionPhase] ||
                              event.phase}
                          </strong>
                          <span>{event.provider || event.message}</span>
                        </div>
                        <small>{event.status || event.message}</small>
                      </div>
                    ))}
                  </div>
                  {job?.result?.research?.sources?.length ? (
                    <div className="source-list">
                      <div className="source-list-head">
                        <span className="field-label">
                          Fontes usadas na pesquisa
                        </span>
                        <small>
                          {job.result.research.quality === "filtered_live"
                            ? `relevância média ${Math.round(job.result.research.sources.reduce((sum, source) => sum + (source.relevance || 0), 0) / job.result.research.sources.length)}%`
                            : "fontes sem ranking local"}
                        </small>
                      </div>
                      {job.result.research.sources.slice(0, 4).map((source) => (
                        <article className="source-card" key={source.url}>
                          <div className="source-card-head">
                            <a
                              href={source.url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {source.title} ↗
                            </a>
                            <span>
                              {source.relevance
                                ? `${Math.round(source.relevance)}% match`
                                : "fonte"}
                            </span>
                          </div>
                          {source.snippet ? <p>{source.snippet}</p> : null}
                          <div className="source-meta">
                            <span>{formatSourceDate(source.published_at)}</span>
                            {source.matched_terms?.slice(0, 3).map((term) => (
                              <i key={term}>{term}</i>
                            ))}
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}
            </>
          ) : activeTab === "library" ? (
            <section className="panel full-view">
              <div className="panel-head">
                <div>
                  <p className="kicker">MEDIA LIBRARY</p>
                  <h2>Suas produções</h2>
                </div>
                <span className="muted-label">
                  {history.length} projetos persistidos
                </span>
              </div>
              <div className="library-grid">
                {history.length ? (
                  history.map((item) => (
                    <article className="library-card" key={item.project_id}>
                      <video
                        controls
                        preload="metadata"
                        src={`${API}${item.url}`}
                      />
                      <div className="library-card-foot">
                        <strong>{item.title}</strong>
                        <a href={`${API}${item.url}`} target="_blank">
                          abrir MP4 ↗
                        </a>
                        <button
                          className="text-button"
                          onClick={() => void loadProject(item.project_id)}
                        >
                          abrir no editor
                        </button>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="empty-row">
                    <FolderOpen size={18} /> nenhuma produção concluída ainda
                  </div>
                )}
              </div>
            </section>
          ) : activeTab === "providers" ? (
            <section className="panel full-view">
              <div className="panel-head">
                <div>
                  <p className="kicker">MODEL ROUTER</p>
                  <h2>Providers e modelos disponíveis</h2>
                  <p className="view-subtitle">
                    Escolha por etapa e valide a capacidade antes de produzir.
                  </p>
                </div>
                <span className="muted-label">capability-aware</span>
              </div>
              <div className="integration-grid">
                {(
                  [
                    "antigravity",
                    "codex",
                    "controlnet",
                    "comfyui",
                  ] as IntegrationKey[]
                ).map((integration) => {
                  const probe = probeResults[integration];
                  const connected =
                    probe?.status === "ready" ||
                    (!probe &&
                      (integration === "comfyui"
                        ? Boolean(
                            healthDetails?.integrations?.comfyui?.available,
                          )
                        : integration === "controlnet"
                          ? Boolean(
                              healthDetails?.integrations?.controlnet_lineart
                                ?.available,
                            )
                          : integration === "antigravity"
                            ? Boolean(
                                healthDetails?.antigravity_cli?.available &&
                                healthDetails?.antigravity_cli?.enabled,
                              )
                            : Boolean(
                                healthDetails?.codex_cli?.available &&
                                healthDetails?.codex_cli?.enabled,
                              )));
                  const title =
                    integration === "antigravity"
                      ? "Antigravity CLI"
                      : integration === "codex"
                        ? "Codex CLI"
                        : integration === "controlnet"
                          ? "ControlNet Lineart"
                          : "ComfyUI";
                  const detail =
                    integration === "antigravity"
                      ? "roteiro e direção visual"
                      : integration === "codex"
                        ? `roteiro · ${healthDetails?.codex_cli?.model || "modelo configurado"}`
                        : integration === "controlnet"
                          ? "referência de desenho · geometria local"
                          : "ControlNet / LoRA / workflows locais";
                  return (
                    <article
                      className={`integration-card ${connected ? "connected" : probe?.status === "error" ? "error" : "offline"}`}
                      key={integration}
                    >
                      <div className="integration-card-head">
                        <div>
                          <strong>{title}</strong>
                          <span>{detail}</span>
                        </div>
                        <span className="integration-state">
                          {connected
                            ? "conectado"
                            : probe?.status === "unavailable"
                              ? "indisponível"
                              : "não verificado"}
                        </span>
                      </div>
                      <small>
                        {probe?.message ||
                          (integration === "comfyui" &&
                          healthDetails?.integrations?.comfyui?.url
                            ? healthDetails.integrations.comfyui.url
                            : integration === "controlnet"
                              ? "checkpoint SD1.5 + lineart local"
                              : "check local ainda não executado")}
                      </small>
                      <button
                        type="button"
                        className="text-button"
                        disabled={probeBusy === integration}
                        onClick={() => void probeIntegration(integration)}
                      >
                        <Activity size={13} />
                        {probeBusy === integration
                          ? "testando…"
                          : "testar conexão real"}
                      </button>
                    </article>
                  );
                })}
              </div>
              {probeMessage ? (
                <p className="probe-feedback">
                  <Check size={14} /> {probeMessage}
                </p>
              ) : null}
              <div className="status-legend">
                <span>
                  <i className="legend-dot ready" /> ready = executável
                </span>
                <span>
                  <i className="legend-dot manifest" /> ready-manifest =
                  catálogo sem runtime completo
                </span>
                <span>
                  <i className="legend-dot planned" /> planned/unavailable =
                  ainda não conectado
                </span>
              </div>
              <div className="provider-table">
                {phases.map((phase) => (
                  <div className="provider-row" key={phase}>
                    <div>
                      <strong>{phaseLabels[phase]}</strong>
                      <span>
                        Provider: {providers[phase]} · Modelo:{" "}
                        {modelSelection[phase]}
                      </span>
                    </div>
                    <div className="provider-chips">
                      {(catalog?.[phase] || []).map((item) => (
                        <span
                          className={`provider-chip ${item.status}`}
                          key={item.name}
                        >
                          {item.label}
                          <small>
                            {item.status} ·{" "}
                            {(item.capabilities || []).join(" · ")}
                          </small>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : (
            <section className="panel full-view">
              <div className="panel-head">
                <div>
                  <p className="kicker">WORKSPACE CONFIG</p>
                  <h2>Configuração local</h2>
                </div>
                <span className="healthy">
                  <span className="status-dot" /> {health}
                </span>
              </div>
              <div className="settings-grid">
                <div>
                  <strong>Backend</strong>
                  <span>FastAPI em http://127.0.0.1:8000</span>
                </div>
                <div>
                  <strong>Frontend</strong>
                  <span>
                    React + TypeScript + Vite em http://127.0.0.1:4174
                  </span>
                </div>
                <div>
                  <strong>Narração</strong>
                  <span>Piper Faber pt-BR · Piper Amy en-US</span>
                </div>
                <div>
                  <strong>Render</strong>
                  <span>FFmpeg · MP4 H.264/AAC · 1080×1920</span>
                </div>
                <div>
                  <strong>Fallback</strong>
                  <span>
                    Até 3 tentativas por etapa; providers planejados ficam
                    bloqueados
                  </span>
                </div>
                <div>
                  <strong>Sketch</strong>
                  <span>
                    Upload opcional; geração automática por SD-Turbo quando
                    disponível
                  </span>
                </div>
              </div>
              <div className="workspace-defaults">
                <div className="panel-head">
                  <div>
                    <span className="index">DEFAULTS</span>
                    <h2>Padrões do workspace</h2>
                  </div>
                  <span className="muted-label">
                    sem credenciais no frontend
                  </span>
                </div>
                <div className="defaults-grid">
                  <div>
                    <span className="field-label">Roteiro</span>
                    <strong>
                      {providers.script} · {modelSelection.script}
                    </strong>
                  </div>
                  <div>
                    <span className="field-label">Imagens</span>
                    <strong>
                      {providers.image} · {modelSelection.image}
                    </strong>
                  </div>
                  <div>
                    <span className="field-label">Áudio</span>
                    <strong>
                      {providers.audio} · {modelSelection.audio}
                    </strong>
                  </div>
                  <div>
                    <span className="field-label">Vídeo</span>
                    <strong>
                      {providers.video} · {modelSelection.video}
                    </strong>
                  </div>
                  <div>
                    <span className="field-label">Fonte visual</span>
                    <strong>
                      {imageSource === "generate"
                        ? "geração automática"
                        : "desenho de referência"}
                    </strong>
                  </div>
                  <div>
                    <span className="field-label">Duração / idioma</span>
                    <strong>
                      {targetSeconds}s · {language}
                    </strong>
                  </div>
                </div>
                <button
                  type="button"
                  className="text-button settings-save"
                  onClick={() => void saveWorkspaceDefaults()}
                >
                  <Save size={14} /> salvar seleção atual como padrão
                </button>
                {settingsMessage ? (
                  <span className="settings-message">{settingsMessage}</span>
                ) : null}
                {workspaceSettings ? (
                  <span className="settings-message">
                    padrões carregados do arquivo local
                  </span>
                ) : null}
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function LiveProductionBanner({ job, api }: { job: Job; api: string }) {
  const frames = job.artifacts?.images?.frame_urls || [];
  const phase = productionLabels[job.phase as ProductionPhase] || job.phase;
  const recentEvents = job.events.slice(-6).reverse();
  const currentStageIndex = liveProductionStages.indexOf(
    job.phase as ProductionPhase,
  );
  const stageState = (stage: ProductionPhase) => {
    if (job.status === "completed") return "done";
    if (["failed", "cancelled", "blocked"].includes(job.status)) {
      return stage === job.phase ? "failed" : "pending";
    }
    const stageIndex = liveProductionStages.indexOf(stage);
    if (stage === job.phase) return "current";
    return currentStageIndex >= 0 && stageIndex < currentStageIndex
      ? "done"
      : "pending";
  };
  return (
    <section className="live-production-banner">
      <div className="live-production-head">
        <div>
          <span className="index">LIVE PREVIEW</span>
          <h2>Produzindo agora · {phase}</h2>
          <p>
            {job.artifacts?.script?.hook ||
              job.events.at(-1)?.message ||
              "Preparando os próximos assets…"}
          </p>
        </div>
        <div className="live-production-status">
          <LoaderCircle className="spin" size={16} />
          <strong>{job.progress}%</strong>
          <span>
            {frames.length
              ? `${frames.length} frame(s) prontos`
              : "gerando assets"}
          </span>
        </div>
      </div>
      <div className="live-stage-strip" aria-label="Etapas da produção">
        {liveProductionStages.map((stage, index) => {
          const state = stageState(stage);
          return (
            <div className={`live-stage ${state}`} key={stage}>
              <span>{state === "done" ? "✓" : String(index + 1).padStart(2, "0")}</span>
              <strong>{productionLabels[stage]}</strong>
              {state === "current" ? <small>{job.progress}%</small> : null}
            </div>
          );
        })}
      </div>
      {frames.length ? (
        <div className="live-production-frames">
          {frames.map((url, index) => (
            <figure key={url}>
              <img
                src={`${api}${url}${url.includes("?") ? "&" : "?"}live=${job.artifacts?.images?.completed || 0}`}
                alt={`Frame ao vivo ${index + 1}`}
              />
              <figcaption>CENA {String(index + 1).padStart(2, "0")}</figcaption>
            </figure>
          ))}
        </div>
      ) : (
        <div className="live-production-empty">
          <Sparkles size={16} />
          <span>
            A primeira imagem está sendo preparada; o preview aparecerá aqui sem
            esperar o MP4 final.
          </span>
        </div>
      )}
      {job.artifacts?.script?.script ? (
        <div className="live-production-script">
          <span className="field-label">
            Roteiro já disponível ·{" "}
            {job.artifacts.script.provider || "provider"}
          </span>
          <p>{job.artifacts.script.script}</p>
        </div>
      ) : null}
      <div className="live-production-events">
        <div className="live-production-events-head">
          <span className="field-label">Atividade do pipeline</span>
          <small>últimas mensagens</small>
        </div>
        <div className="live-production-event-list">
          {recentEvents.map((event, index) => (
            <div
              className={`live-production-event ${event.status || ""}`}
              key={`${event.phase}-${event.message}-${index}`}
            >
              <span>
                {productionLabels[event.phase as ProductionPhase] ||
                  event.phase}
              </span>
              <p>{event.message}</p>
              {event.progress !== undefined ? (
                <strong>{event.progress}%</strong>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function RetryBanner({ job, onRetry }: { job: Job; onRetry: () => void }) {
  const detail =
    job.error ||
    job.result?.diagnostics?.[0] ||
    "O pipeline não conseguiu concluir esta tentativa.";
  return (
    <section className="retry-banner">
      <div>
        <span className="index">RECOVERY</span>
        <h2>Esta produção precisa de uma nova tentativa</h2>
        <p>{detail}</p>
      </div>
      <button type="button" className="text-button" onClick={onRetry}>
        <Activity size={14} /> tentar novamente
      </button>
    </section>
  );
}

function AvatarRuntimeCard({
  config,
  onSaved,
}: {
  config: RuntimeConfig | null;
  onSaved?: (value: RuntimeConfig) => void;
}) {
  const [message, setMessage] = useState("");
  const [draft, setDraft] = useState({
    SADTALKER_ROOT: "",
    SADTALKER_PYTHON: "",
    SADTALKER_CHECKPOINT_DIR: "",
  });
  useEffect(() => {
    if (!config) return;
    setDraft((current) => ({
      ...current,
      SADTALKER_ROOT:
        config.editable?.SADTALKER_ROOT ||
        config.video?.comfyui?.sadtalker?.inference?.path?.replace(
          /\\inference\.py$/,
          "",
        ) ||
        "",
      SADTALKER_PYTHON:
        config.editable?.SADTALKER_PYTHON ||
        config.video?.comfyui?.sadtalker?.python ||
        "",
      SADTALKER_CHECKPOINT_DIR:
        config.editable?.SADTALKER_CHECKPOINT_DIR ||
        config.video?.comfyui?.sadtalker?.checkpoints?.path ||
        "",
    }));
  }, [config]);
  const save = async () => {
    const response = await fetch(`${API}/api/runtime-config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
    const data = await response.json();
    if (!response.ok) {
      setMessage(data.detail || "não foi possível salvar");
      return;
    }
    onSaved?.(data);
    setMessage(
      data.video?.comfyui?.sadtalker?.available
        ? "SadTalker conectado e pronto para lip-sync"
        : "caminhos salvos · SadTalker ainda não está completo",
    );
  };
  if (!config) return null;
  const avatar = config.video?.comfyui?.sadtalker;
  return (
    <section className="panel avatar-runtime-card">
      <div className="panel-head">
        <div>
          <span className="index">AVATAR</span>
          <h2>Avatar e lip-sync local</h2>
          <p className="view-subtitle">
            SadTalker só será liberado quando entrypoint, Python e checkpoints
            forem encontrados.
          </p>
        </div>
        <span
          className={`runtime-avatar-state ${avatar?.available ? "ready" : "planned"}`}
        >
          {avatar?.available ? "ready" : "planned"}
        </span>
      </div>
      <div className="avatar-runtime-grid">
        <label>
          <span>Diretório SadTalker</span>
          <input
            value={draft.SADTALKER_ROOT}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                SADTALKER_ROOT: event.target.value,
              }))
            }
            placeholder="third_party\\SadTalker"
          />
        </label>
        <label>
          <span>Python do ambiente</span>
          <input
            value={draft.SADTALKER_PYTHON}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                SADTALKER_PYTHON: event.target.value,
              }))
            }
            placeholder="python.exe · vazio = ambiente atual"
          />
        </label>
        <label>
          <span>Diretório de checkpoints</span>
          <input
            value={draft.SADTALKER_CHECKPOINT_DIR}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                SADTALKER_CHECKPOINT_DIR: event.target.value,
              }))
            }
            placeholder="third_party\\SadTalker\\checkpoints"
          />
        </label>
      </div>
      <div className="avatar-runtime-foot">
        <span>
          inference.py: {avatar?.inference?.exists ? "encontrado" : "ausente"} ·
          checkpoints:{" "}
          {avatar?.checkpoints?.exists ? "encontrados" : "ausentes"}
        </span>
        <button
          type="button"
          className="text-button"
          onClick={() => void save()}
        >
          <Save size={14} /> salvar avatar
        </button>
      </div>
      {message ? <small className="settings-message">{message}</small> : null}
    </section>
  );
}

function PiperRuntimeCard({ config }: { config: RuntimeConfig | null }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [copied, setCopied] = useState(false);
  const test = async () => {
    setBusy(true);
    setResult({ status: "testing", message: "executando síntese WAV real…" });
    try {
      const response = await fetch(`${API}/api/integrations/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ integration: "piper" }),
      });
      setResult(await response.json());
    } catch (error) {
      setResult({ status: "error", message: String(error) });
    } finally {
      setBusy(false);
    }
  };
  const ptReady = Boolean(config?.media?.piper?.pt_BR?.exists);
  const enReady = Boolean(config?.media?.piper?.en_US?.exists);
  const repairCommand = ".\\scripts\\ensure-piper-voices.ps1";
  const copyRepairCommand = async () => {
    try {
      await navigator.clipboard.writeText(repairCommand);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };
  const baseline =
    ptReady && enReady
      ? "ready · modelos locais pt-BR e en-US encontrados"
      : "atenção · confira os dois modelos locais";
  return (
    <section className="panel piper-runtime-card">
      <div className="panel-head">
        <div>
          <span className="index">VOICE</span>
          <h2>Piper · vozes locais</h2>
          <p className="view-subtitle">
            Teste os dois modelos reais antes de iniciar uma produção.
          </p>
        </div>
        <span
          className={`runtime-avatar-state ${ptReady && enReady ? "ready" : "planned"}`}
        >
          {ptReady && enReady ? "ready" : "revisar"}
        </span>
      </div>
      <div className="piper-runtime-body">
        <div>
          <strong>Português Faber + English Amy</strong>
          <span>
            O teste sintetiza uma frase curta e descarta os WAV temporários
            depois da validação.
          </span>
          <span className="piper-file-proof">
            pt-BR: {ptReady ? `${config?.media?.piper?.pt_BR?.size_mb || "?"} MB` : "ausente"}
            {" · "}
            en-US: {enReady ? `${config?.media?.piper?.en_US?.size_mb || "?"} MB` : "ausente"}
          </span>
        </div>
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void test()}
        >
          <Activity size={14} />
          {busy ? "testando vozes…" : "testar síntese real"}
        </button>
      </div>
      <small
        aria-live="polite"
        className={`piper-runtime-result ${result?.status || (ptReady && enReady ? "ready" : "unavailable")}`}
      >
        {result
          ? `${result.status} · ${result.message || "sem detalhes"}`
          : baseline}
      </small>
      <div className="piper-repair-row">
        <code>{repairCommand}</code>
        <button
          type="button"
          className="text-button"
          onClick={() => void copyRepairCommand()}
        >
          <Copy size={13} /> {copied ? "copiado" : "copiar reparo"}
        </button>
      </div>
    </section>
  );
}

function ImageRuntimeCard({ config }: { config: RuntimeConfig | null }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProbeResult | null>(null);
  const test = async () => {
    setBusy(true);
    setResult({ status: "testing", message: "gerando PNG real com SD-Turbo…" });
    try {
      const response = await fetch(`${API}/api/integrations/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ integration: "sd_turbo" }),
      });
      setResult(await response.json());
    } catch (error) {
      setResult({ status: "error", message: String(error) });
    } finally {
      setBusy(false);
    }
  };
  const ready = Boolean(config?.image?.sd_turbo?.available);
  return (
    <section className="panel image-runtime-card">
      <div className="panel-head">
        <div>
          <span className="index">IMAGE</span>
          <h2>SD-Turbo · geração local</h2>
          <p className="view-subtitle">
            Valide uma imagem PNG real antes de iniciar uma produção.
          </p>
        </div>
        <span className={`runtime-avatar-state ${ready ? "ready" : "planned"}`}>
          {ready ? "ready" : "revisar"}
        </span>
      </div>
      <div className="piper-runtime-body">
        <div>
          <strong>Text-to-image sem upload</strong>
          <span>
            O teste cria um frame temporário e o remove depois; a produção usa o
            mesmo adapter local.
          </span>
        </div>
        <button
          type="button"
          className="text-button"
          disabled={busy || !ready}
          onClick={() => void test()}
        >
          <Activity size={14} />
          {busy ? "gerando imagem…" : "testar geração real"}
        </button>
      </div>
      <small
        aria-live="polite"
        className={`piper-runtime-result ${result?.status || (ready ? "ready" : "unavailable")}`}
      >
        {result
          ? `${result.status} · ${result.message || "sem detalhes"}`
          : ready
            ? "ready · SD-Turbo local disponível para criar imagens automaticamente"
            : "atenção · modelo local não encontrado"}
      </small>
    </section>
  );
}

function RuntimeDiagnostics({
  config,
  onSaved,
}: {
  config: RuntimeConfig | null;
  onSaved?: (value: RuntimeConfig) => void;
}) {
  const [message, setMessage] = useState("");
  const [probeBusy, setProbeBusy] = useState("");
  const [probeState, setProbeState] = useState<
    Record<string, { status: string; message: string }>
  >({});
  const [draft, setDraft] = useState({
    ENABLE_AGY_BRIDGE: "0",
    AGY_COMMAND: "agy",
    AGY_TIMEOUT_SECONDS: "90",
    AGY_SKIP_PERMISSIONS: "1",
    ENABLE_CODEX_BRIDGE: "0",
    CODEX_COMMAND: "codex",
    CODEX_TIMEOUT_SECONDS: "120",
    CODEX_MODEL: "",
    COMFYUI_URL: "",
    COMFYUI_WORKFLOW: "",
    COMFYUI_WAN_WORKFLOW: "",
    COMFYUI_LTX_WORKFLOW: "",
    COMFYUI_VIDEO_TIMEOUT_SECONDS: "600",
    SADTALKER_ROOT: "",
    SADTALKER_PYTHON: "",
    SADTALKER_CHECKPOINT_DIR: "",
    LOCAL_DIFFUSION_MODEL: "",
    LOCAL_LORA_ADAPTER: "",
    LOCAL_LORA_WEIGHT: "0.8",
  });
  useEffect(() => {
    if (config)
      setDraft((current) => ({
        ...current,
        ENABLE_AGY_BRIDGE:
          config.editable?.ENABLE_AGY_BRIDGE ||
          (config.bridges?.antigravity?.enabled ? "1" : "0"),
        AGY_COMMAND:
          config.editable?.AGY_COMMAND ||
          config.bridges?.antigravity?.command ||
          "agy",
        AGY_TIMEOUT_SECONDS:
          config.editable?.AGY_TIMEOUT_SECONDS ||
          config.bridges?.antigravity?.timeout_seconds ||
          "90",
        AGY_SKIP_PERMISSIONS: config.editable?.AGY_SKIP_PERMISSIONS || "1",
        ENABLE_CODEX_BRIDGE:
          config.editable?.ENABLE_CODEX_BRIDGE ||
          (config.bridges?.codex?.enabled ? "1" : "0"),
        CODEX_COMMAND:
          config.editable?.CODEX_COMMAND ||
          config.bridges?.codex?.command ||
          "codex",
        CODEX_TIMEOUT_SECONDS:
          config.editable?.CODEX_TIMEOUT_SECONDS ||
          config.bridges?.codex?.timeout_seconds ||
          "120",
        CODEX_MODEL:
          config.editable?.CODEX_MODEL || config.bridges?.codex?.model || "",
        COMFYUI_URL:
          config.editable?.COMFYUI_URL || config.image?.comfyui?.url || "",
        COMFYUI_WORKFLOW:
          config.editable?.COMFYUI_WORKFLOW ||
          config.image?.comfyui?.workflow?.path ||
          "",
        COMFYUI_WAN_WORKFLOW: config.editable?.COMFYUI_WAN_WORKFLOW || "",
        COMFYUI_LTX_WORKFLOW: config.editable?.COMFYUI_LTX_WORKFLOW || "",
        COMFYUI_VIDEO_TIMEOUT_SECONDS:
          config.editable?.COMFYUI_VIDEO_TIMEOUT_SECONDS || "600",
        SADTALKER_ROOT:
          config.editable?.SADTALKER_ROOT ||
          config.video?.comfyui?.sadtalker?.inference?.path?.replace(
            /\\inference\.py$/,
            "",
          ) ||
          "",
        SADTALKER_PYTHON:
          config.editable?.SADTALKER_PYTHON ||
          config.video?.comfyui?.sadtalker?.python ||
          "",
        SADTALKER_CHECKPOINT_DIR:
          config.editable?.SADTALKER_CHECKPOINT_DIR ||
          config.video?.comfyui?.sadtalker?.checkpoints?.path ||
          "",
        LOCAL_DIFFUSION_MODEL:
          config.editable?.LOCAL_DIFFUSION_MODEL ||
          config.image?.sd_turbo?.path ||
          "",
        LOCAL_LORA_ADAPTER:
          config.editable?.LOCAL_LORA_ADAPTER ||
          config.image?.sd_turbo?.lora?.path ||
          "",
        LOCAL_LORA_WEIGHT: config.editable?.LOCAL_LORA_WEIGHT || "0.8",
      }));
  }, [config]);
  const pathLabel = (value?: RuntimePath) => value?.path || "não configurado";
  const pathState = (value?: RuntimePath) =>
    value?.exists ? "ready" : "ausente";
  const copy = async () => {
    if (!config) return;
    await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
    setMessage("diagnóstico copiado");
  };
  const save = async () => {
    const response = await fetch(`${API}/api/runtime-config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
    const data = await response.json();
    if (!response.ok) {
      setMessage(data.detail || "não foi possível salvar");
      return;
    }
    onSaved?.(data);
    setMessage("configurações locais salvas");
  };
  const probe = async (integration: "codex" | "antigravity") => {
    setProbeBusy(integration);
    try {
      const response = await fetch(`${API}/api/integrations/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ integration }),
      });
      const data = await response.json();
      setProbeState((current) => ({
        ...current,
        [integration]: {
          status: data.status || "error",
          message: data.message || "sem diagnóstico",
        },
      }));
    } catch (error) {
      setProbeState((current) => ({
        ...current,
        [integration]: { status: "error", message: String(error) },
      }));
    } finally {
      setProbeBusy("");
    }
  };
  if (!config)
    return (
      <section className="panel runtime-diagnostics loading">
        <div className="panel-head">
          <div>
            <span className="index">RUNTIME</span>
            <h2>Detectando configurações locais…</h2>
          </div>
          <LoaderCircle className="spin" size={17} />
        </div>
      </section>
    );
  return (
    <section className="panel runtime-diagnostics">
      <div className="panel-head">
        <div>
          <span className="index">RUNTIME</span>
          <h2>Configuração efetiva do PC</h2>
          <p className="view-subtitle">
            Valores detectados pelo backend. Nenhuma credencial é exibida.
          </p>
        </div>
        <button
          type="button"
          className="text-button"
          onClick={() => void copy()}
        >
          copiar diagnóstico
        </button>
      </div>
      <div className="runtime-grid">
        <article>
          <strong>GPU local</strong>
          <span>
            {config.hardware?.available
              ? `${config.hardware.name || "NVIDIA"} · ${config.hardware.memory_mb || "?"} MB VRAM`
              : "não detectada"}
          </span>
          <small>
            {config.hardware?.native_video_guidance ||
              "frame a frame local disponível"}
          </small>
        </article>
        <article>
          <strong>Antigravity CLI</strong>
          <span>
            {config.bridges?.antigravity?.enabled &&
            config.bridges.antigravity.available
              ? "conectado"
              : "indisponível"}{" "}
            · comando{" "}
            <code>{config.bridges?.antigravity?.command || "agy"}</code> ·{" "}
            {config.bridges?.antigravity?.timeout_seconds || "90"}s
          </span>
        </article>
        <article>
          <strong>Codex CLI</strong>
          <span>
            {config.bridges?.codex?.enabled && config.bridges.codex.available
              ? "conectado"
              : "indisponível"}{" "}
            ·{" "}
            <code>
              {config.bridges?.codex?.model || "modelo não informado"}
            </code>{" "}
            · {config.bridges?.codex?.timeout_seconds || "120"}s
          </span>
        </article>
        <article>
          <strong>Piper · pt-BR</strong>
          <span>
            {pathState(config.media?.piper?.pt_BR)} ·{" "}
            <code>{pathLabel(config.media?.piper?.pt_BR)}</code>
          </span>
        </article>
        <article>
          <strong>Piper · en-US</strong>
          <span>
            {pathState(config.media?.piper?.en_US)} ·{" "}
            <code>{pathLabel(config.media?.piper?.en_US)}</code>
          </span>
        </article>
        <article>
          <strong>FFmpeg</strong>
          <span>
            {config.media?.ffmpeg?.available ? "ready" : "ausente"} ·{" "}
            <code>{config.media?.ffmpeg?.executable || "não encontrado"}</code>
          </span>
        </article>
        <article>
          <strong>SD-Turbo</strong>
          <span>
            {config.image?.sd_turbo?.available
              ? "ready"
              : config.image?.sd_turbo?.enabled
                ? "habilitado, mas incompleto"
                : "desabilitado"}{" "}
            · <code>{pathLabel(config.image?.sd_turbo)}</code>
          </span>
        </article>
        <article>
          <strong>Adaptador LoRA</strong>
          <span>
            {config.image?.sd_turbo?.lora?.available
              ? "ready · aplicado nas imagens SD-Turbo"
              : config.image?.sd_turbo?.lora?.configured
                ? "configurado, mas ausente/inválido"
                : "opcional · nenhum configurado"}
          </span>
          <small>
            {config.image?.sd_turbo?.lora?.adapters?.length
              ? `catálogo local · ${config.image.sd_turbo.lora.adapters.map((item) => item.name).join(", ")}`
              : config.image?.sd_turbo?.lora?.path ||
                "Use um .safetensors local para reforçar um estilo treinado."}
          </small>
        </article>
        <article>
          <strong>ControlNet Lineart</strong>
          <span>
            {config.image?.controlnet?.available ? "ready" : "incompleto"} ·
            base <code>{pathLabel(config.image?.controlnet?.base)}</code>
          </span>
        </article>
        <article>
          <strong>ComfyUI</strong>
          <span>
            {config.image?.comfyui?.available ? "ready" : "não conectado"} ·{" "}
            <code>{config.image?.comfyui?.url || "url não configurada"}</code>
          </span>
          <small>workflow: {pathState(config.image?.comfyui?.workflow)}</small>
        </article>
      </div>
      <div className="runtime-probes">
        <div>
          <strong>Teste real dos bridges</strong>
          <span>
            Executa uma chamada curta usando a sessão local já autenticada;
            nenhuma credencial sai do PC.
          </span>
        </div>
        <div className="runtime-probe-actions">
          <div>
            <button
              type="button"
              className="text-button"
              disabled={probeBusy === "antigravity"}
              onClick={() => void probe("antigravity")}
            >
              {probeBusy === "antigravity"
                ? "testando Agy…"
                : "testar Antigravity"}
            </button>
            {probeState.antigravity ? (
              <small
                className={`runtime-probe-result ${probeState.antigravity.status}`}
              >
                {probeState.antigravity.status} ·{" "}
                {probeState.antigravity.message}
              </small>
            ) : null}
          </div>
          <div>
            <button
              type="button"
              className="text-button"
              disabled={probeBusy === "codex"}
              onClick={() => void probe("codex")}
            >
              {probeBusy === "codex" ? "testando Codex…" : "testar Codex"}
            </button>
            {probeState.codex ? (
              <small
                className={`runtime-probe-result ${probeState.codex.status}`}
              >
                {probeState.codex.status} · {probeState.codex.message}
              </small>
            ) : null}
          </div>
        </div>
      </div>
      <div className="runtime-edit">
        <div>
          <strong>Configurar runtimes locais</strong>
          <span>
            Altere apenas valores não secretos; o Studio salva no workspace.
            Credenciais continuam somente no ambiente local.
          </span>
        </div>
        <div className="runtime-bridge-controls">
          <label className="runtime-toggle">
            <input
              type="checkbox"
              checked={draft.ENABLE_AGY_BRIDGE === "1"}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  ENABLE_AGY_BRIDGE: event.target.checked ? "1" : "0",
                }))
              }
            />
            <span>habilitar Antigravity bridge</span>
          </label>
          <label className="runtime-toggle">
            <input
              type="checkbox"
              checked={draft.AGY_SKIP_PERMISSIONS === "1"}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  AGY_SKIP_PERMISSIONS: event.target.checked ? "1" : "0",
                }))
              }
            />
            <span>autorizar Agy em modo headless</span>
          </label>
          <label className="runtime-toggle">
            <input
              type="checkbox"
              checked={draft.ENABLE_CODEX_BRIDGE === "1"}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  ENABLE_CODEX_BRIDGE: event.target.checked ? "1" : "0",
                }))
              }
            />
            <span>habilitar Codex bridge</span>
          </label>
        </div>
        <div className="runtime-edit-grid">
          <label>
            <span>Comando Antigravity</span>
            <input
              value={draft.AGY_COMMAND}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  AGY_COMMAND: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>Timeout Agy (s)</span>
            <input
              value={draft.AGY_TIMEOUT_SECONDS}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  AGY_TIMEOUT_SECONDS: event.target.value,
                }))
              }
              inputMode="numeric"
            />
          </label>
          <label>
            <span>Comando Codex</span>
            <input
              value={draft.CODEX_COMMAND}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  CODEX_COMMAND: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>Timeout Codex (s)</span>
            <input
              value={draft.CODEX_TIMEOUT_SECONDS}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  CODEX_TIMEOUT_SECONDS: event.target.value,
                }))
              }
              inputMode="numeric"
            />
          </label>
          <label>
            <span>Modelo Codex</span>
            <input
              value={draft.CODEX_MODEL}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  CODEX_MODEL: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>URL ComfyUI</span>
            <input
              value={draft.COMFYUI_URL}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  COMFYUI_URL: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>Workflow ComfyUI</span>
            <input
              value={draft.COMFYUI_WORKFLOW}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  COMFYUI_WORKFLOW: event.target.value,
                }))
              }
              placeholder="caminho opcional para workflow_api.json"
            />
          </label>
          <label>
            <span>Workflow Wan nativo</span>
            <input
              value={draft.COMFYUI_WAN_WORKFLOW}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  COMFYUI_WAN_WORKFLOW: event.target.value,
                }))
              }
              placeholder="workflow Wan via ComfyUI"
            />
          </label>
          <label>
            <span>Workflow LTX nativo</span>
            <input
              value={draft.COMFYUI_LTX_WORKFLOW}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  COMFYUI_LTX_WORKFLOW: event.target.value,
                }))
              }
              placeholder="workflow LTX via ComfyUI"
            />
          </label>
          <label>
            <span>Timeout vídeo nativo (s)</span>
            <input
              value={draft.COMFYUI_VIDEO_TIMEOUT_SECONDS}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  COMFYUI_VIDEO_TIMEOUT_SECONDS: event.target.value,
                }))
              }
              inputMode="numeric"
            />
          </label>
          <label>
            <span>Modelo SD-Turbo</span>
            <input
              value={draft.LOCAL_DIFFUSION_MODEL}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  LOCAL_DIFFUSION_MODEL: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>Adaptador LoRA opcional</span>
            {config.image?.sd_turbo?.lora?.adapters?.length ? (
              <select
                aria-label="Catálogo de adaptadores LoRA"
                value={draft.LOCAL_LORA_ADAPTER}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    LOCAL_LORA_ADAPTER: event.target.value,
                  }))
                }
              >
                <option value="">Nenhum · usar SD-Turbo base</option>
                {config.image.sd_turbo.lora.adapters.map((adapter) => (
                  <option
                    key={adapter.path || adapter.name}
                    value={adapter.path || ""}
                    disabled={adapter.available === false}
                  >
                    {adapter.name || adapter.path} ·{" "}
                    {adapter.available ? "ready" : "ausente/inválido"}
                  </option>
                ))}
              </select>
            ) : null}
            <input
              value={draft.LOCAL_LORA_ADAPTER}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  LOCAL_LORA_ADAPTER: event.target.value,
                }))
              }
              placeholder="assets/models/lora/meu-traco.safetensors"
            />
          </label>
          <label>
            <span>Peso do LoRA (0–2)</span>
            <input
              value={draft.LOCAL_LORA_WEIGHT}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  LOCAL_LORA_WEIGHT: event.target.value,
                }))
              }
              inputMode="decimal"
            />
          </label>
        </div>
        <button
          type="button"
          className="text-button"
          onClick={() => void save()}
        >
          <Save size={14} /> salvar configurações locais
        </button>
      </div>
      {message ? <span className="settings-message">{message}</span> : null}
    </section>
  );
}

const phases: Phase[] = ["script", "image", "audio", "video"];
createRoot(document.getElementById("root")!).render(<App />);
