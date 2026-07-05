import { useEffect, useMemo, useRef, useState } from "react";

type Mode = "INTELLIGENCE";

type Entity = {
  type: string;
  original_value: string;
  sensitivity: string;
  start: number;
  end: number;
  action: string;
  placeholder?: string | null;
  confidence: number;
};

type PrivacyCounts = {
  total_entities: number;
  identities_detected: number;
  clients_detected: number;
  financial_items_detected: number;
  secrets_detected: number;
  blocked: number;
  pseudonymized: number;
  minimized: number;
};

type PrivacyAnalysis = {
  session_id: string;
  original_text: string;
  safe_content: string;
  entities: Entity[];
  blocked_entities: Entity[];
  pseudonymized_entities: Entity[];
  minimized_entities: Entity[];
  counts: PrivacyCounts;
  risk_level: string;
  external_payload_allowed: boolean;
};

type RememberedTranscript = {
  memory_id: string;
  title: string;
  chunk_count: number;
  summary: string;
  tasks: string[];
  decisions: string[];
  risks: string[];
  areas: EnterpriseArea[];
  task_segments: TaskSegment[];
  analysis: PrivacyAnalysis;
};

type EnterpriseArea = {
  area: string;
  score: number;
  evidence: string[];
};

type TaskSegment = {
  description: string;
  area: string;
  role: string;
  confidence: number;
};

type MemoryDashboardItem = {
  memory_id: string;
  title: string;
  source: string;
  created_at: string;
  updated_at: string;
  summary: string;
  tasks: string[];
  decisions: string[];
  risks: string[];
  areas: EnterpriseArea[];
  task_segments: TaskSegment[];
  risk_level: string;
  entities: number;
  chunks?: number | null;
};

type MemoryDetail = MemoryDashboardItem & {
  transcript: string;
  safe_content: string;
  privacy_report: Record<string, unknown>;
};

type MemorySource = {
  memory_id: string;
  title: string;
  chunk_id: string;
  score: number;
  snippet: string;
  safe_snippet: string;
  summary: string;
  tasks: string[];
  decisions: string[];
  risks: string[];
  areas: EnterpriseArea[];
  task_segments: TaskSegment[];
  created_at: string;
};

type MemoryAnswer = {
  question: string;
  answer: string;
  mode: Mode;
  sources: MemorySource[];
  safe_context: string;
};

type TranscriptionResponse = {
  provider: string;
  model_id: string;
  text: string;
  language_code?: string | null;
  language_probability?: number | null;
  words: unknown[];
};

type RecordingTarget = "meeting" | "request";
type WakeStatus = "off" | "listening" | "awake" | "unsupported" | "error";

type SpeechRecognitionResultLike = {
  isFinal: boolean;
  0: { transcript: string };
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
};

type SpeechRecognitionErrorLike = {
  error?: string;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: SpeechRecognitionErrorLike) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  }
}

const API_BASE = import.meta.env.VITE_SENTINEL_API_BASE ?? "http://127.0.0.1:8000";
const SYSTEM_MODE: Mode = "INTELLIGENCE";

const samples = {
  normal:
    "Weekly ops sync. Ana Lopez confirmed the dashboard copy is ready. We agreed to review the onboarding checklist next Tuesday and keep the meeting notes in the local workspace.",
  confidential:
    "Carlos Hernandez met with cliente Banco Agricola about Proyecto Torre Norte. Budget is USD 85,000 and launch target is 2026-08-15. Maria Gomez will send the revised timeline to finance@example.com.",
  dangerous:
    "Incident review. Sofia Martinez pasted OPENAI_API_KEY=sk-example-not-real-123456789 while discussing cliente Acme Corp. Password: not-real-demo-only. Decision: rotate demo credentials today.",
};

const defaultRequest =
  "Extrae un resumen ejecutivo, decisiones, tareas accionables, riesgos y próximos pasos usando solamente el contenido seguro.";

function App() {
  const [text, setText] = useState(samples.confidential);
  const [specificRequest, setSpecificRequest] = useState(defaultRequest);
  const [analysis, setAnalysis] = useState<PrivacyAnalysis | null>(null);
  const [externalResponse, setExternalResponse] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [rememberTranscript, setRememberTranscript] = useState(true);
  const [memoryStatus, setMemoryStatus] = useState<string | null>(null);
  const [memoryQuestion, setMemoryQuestion] = useState("¿Qué decisiones, tareas o riesgos aparecen en la memoria?");
  const [memoryAnswer, setMemoryAnswer] = useState<MemoryAnswer | null>(null);
  const [memoryAskStatus, setMemoryAskStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [memoryItems, setMemoryItems] = useState<MemoryDashboardItem[]>([]);
  const [selectedMemory, setSelectedMemory] = useState<MemoryDetail | null>(null);
  const [lastRemembered, setLastRemembered] = useState<RememberedTranscript | null>(null);
  const [memoryListStatus, setMemoryListStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [memorySearch, setMemorySearch] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [audioStatus, setAudioStatus] = useState<"idle" | "recording" | "paused" | "transcribing" | "done" | "error">(
    "idle",
  );
  const [audioMessage, setAudioMessage] = useState("Micrófono listo");
  const [recordingTarget, setRecordingTarget] = useState<RecordingTarget>("meeting");
  const [wakeEnabled, setWakeEnabled] = useState(false);
  const [wakeStatus, setWakeStatus] = useState<WakeStatus>("off");
  const [wakeMessage, setWakeMessage] = useState("Di “Hola TEO” para empezar");
  const [lastWakeTranscript, setLastWakeTranscript] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const wakeRestartTimerRef = useRef<number | null>(null);
  const wakeEnabledRef = useRef(false);
  const lastWakeHitAtRef = useRef(0);
  const isRecordingRef = useRef(false);
  const textRef = useRef(text);
  const memoryItemsRef = useRef(memoryItems);

  useEffect(() => {
    void loadMemoryItems();
  }, []);

  useEffect(() => {
    return () => {
      if (wakeRestartTimerRef.current !== null) {
        window.clearTimeout(wakeRestartTimerRef.current);
      }
      recognitionRef.current?.abort();
      stopMediaStream();
    };
  }, []);

  useEffect(() => {
    void bootAlwaysOnMicrophone();
  }, []);

  useEffect(() => {
    isRecordingRef.current = isRecording;
  }, [isRecording]);

  useEffect(() => {
    textRef.current = text;
  }, [text]);

  useEffect(() => {
    memoryItemsRef.current = memoryItems;
  }, [memoryItems]);

  const stats = useMemo(() => {
    const counts = analysis?.counts;
    return [
      ["Identities", counts?.identities_detected ?? 0],
      ["Clients", counts?.clients_detected ?? 0],
      ["Financial", counts?.financial_items_detected ?? 0],
      ["Secrets", counts?.secrets_detected ?? 0],
      ["Blocked", counts?.blocked ?? 0],
      ["Pseudonymized", counts?.pseudonymized ?? 0],
    ];
  }, [analysis]);

  const activeTicketSegments = useMemo(() => {
    if (memoryAnswer) {
      return memoryAnswer.sources.flatMap((source) => source.task_segments);
    }
    if (selectedMemory) {
      return selectedMemory.task_segments;
    }
    if (lastRemembered) {
      return lastRemembered.task_segments;
    }
    return memoryItems.flatMap((item) => item.task_segments);
  }, [lastRemembered, memoryAnswer, memoryItems, selectedMemory]);
  const stageTitle =
    audioStatus === "recording" && recordingTarget === "request"
      ? "Escuchando tu pregunta..."
      : audioStatus === "recording"
      ? "Escuchando reunión en vivo..."
      : audioStatus === "transcribing" && recordingTarget === "request"
        ? "Transcribiendo tu solicitud..."
        : audioStatus === "transcribing"
        ? "Transcribiendo audio con ElevenLabs..."
        : status === "running"
      ? "Escuchando y codificando reunión..."
      : analysis
        ? "Reunión codificada y lista para consultar"
        : "Listo para escuchar y codificar";
  const stageHint =
    audioStatus === "recording" && recordingTarget === "request"
      ? "Di qué necesitas: resumen, tareas, riesgos, próximos pasos o una pregunta específica."
      : audioStatus === "recording"
      ? "Habla normalmente. Al detener, Sentinel enviará el audio a ElevenLabs y traerá el transcript."
      : audioStatus === "transcribing" && recordingTarget === "request"
        ? "La solicitud se convertirá en texto y quedará lista para analizar la reunión."
        : audioStatus === "transcribing"
        ? "El audio sale al proveedor de STT; el texto regresa para privacidad local, memoria y análisis seguro."
        : status === "running"
      ? "Sentinel está preparando el payload seguro para la memoria empresarial."
      : analysis
        ? "El contexto sensible quedó protegido antes de consultar la inteligencia externa."
        : "Pega o recibe aquí la transcripción generada desde audio para analizarla.";
  const safePreview =
    analysis?.safe_content ??
    "El contenido seguro aparecerá aquí con nombres, llaves, fechas y controles sensibles reemplazados antes de cualquier consulta.";

  async function analyze(purposeOverride?: string) {
    setStatus("running");
    setError(null);
    setExternalResponse(null);
    setLastRemembered(null);

    try {
      let privacy: PrivacyAnalysis;
      if (rememberTranscript) {
        const memoryResponse = await fetch(`${API_BASE}/api/memory/remember`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ transcript: text, title: titleFromText(text), source: "web" }),
        });
        if (!memoryResponse.ok) {
          throw new Error(`Memory save failed: ${memoryResponse.status}`);
        }
        const remembered = (await memoryResponse.json()) as RememberedTranscript;
        privacy = remembered.analysis;
        setLastRemembered(remembered);
        setMemoryStatus(`Saved: ${remembered.title} (${remembered.chunk_count})`);
        await loadMemoryItems();
      } else {
        const privacyResponse = await fetch(`${API_BASE}/api/privacy/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (!privacyResponse.ok) {
          throw new Error(`Privacy analysis failed: ${privacyResponse.status}`);
        }
        privacy = (await privacyResponse.json()) as PrivacyAnalysis;
        setMemoryStatus(null);
        setLastRemembered(null);
      }
      setAnalysis(privacy);

      const purpose = (purposeOverride ?? specificRequest).trim() || defaultRequest;
      const aiResponse = await fetch(`${API_BASE}/api/ai/analyze-safe-content`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          safe_content: privacy.safe_content,
          session_id: privacy.session_id,
          purpose,
          mode: SYSTEM_MODE,
        }),
      });
      if (!aiResponse.ok) {
        throw new Error(`External analysis failed: ${aiResponse.status}`);
      }
      const payload = await aiResponse.json();
      setExternalResponse(payload.reconstructed_response);

      setStatus("done");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Analysis failed");
    }
  }

  async function loadMemoryItems() {
    setMemoryListStatus("running");
    try {
      const response = await fetch(`${API_BASE}/api/memory/items?limit=100`);
      if (!response.ok) {
        throw new Error(`Memory list failed: ${response.status}`);
      }
      const payload = (await response.json()) as { items: MemoryDashboardItem[] };
      setMemoryItems(payload.items);
      setMemoryListStatus("done");
      if (selectedMemory && !payload.items.some((item) => item.memory_id === selectedMemory.memory_id)) {
        setSelectedMemory(null);
      }
    } catch (err) {
      setMemoryListStatus("error");
      setError(err instanceof Error ? err.message : "Memory list failed");
    }
  }

  async function openMemoryItem(memoryId: string) {
    setMemoryListStatus("running");
    try {
      const response = await fetch(`${API_BASE}/api/memory/items/${memoryId}`);
      if (!response.ok) {
        throw new Error(`Memory detail failed: ${response.status}`);
      }
      setSelectedMemory((await response.json()) as MemoryDetail);
      setMemoryAnswer(null);
      setMemoryListStatus("done");
    } catch (err) {
      setMemoryListStatus("error");
      setError(err instanceof Error ? err.message : "Memory detail failed");
    }
  }

  async function deleteMemoryItem(memoryId: string) {
    setMemoryListStatus("running");
    try {
      const response = await fetch(`${API_BASE}/api/memory/items/${memoryId}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(`Memory delete failed: ${response.status}`);
      }
      if (selectedMemory?.memory_id === memoryId) {
        setSelectedMemory(null);
      }
      setMemoryStatus("Grabación eliminada");
      await loadMemoryItems();
    } catch (err) {
      setMemoryListStatus("error");
      setError(err instanceof Error ? err.message : "Memory delete failed");
    }
  }

  async function askMemory(questionOverride?: string) {
    const question = (questionOverride ?? memoryQuestion).trim();
    if (!question) {
      return;
    }
    setMemoryQuestion(question);
    setMemoryAskStatus("running");
    setError(null);
    setSelectedMemory(null);
    try {
      const response = await fetch(`${API_BASE}/api/memory/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, mode: SYSTEM_MODE, limit: 6 }),
      });
      if (!response.ok) {
        throw new Error(`Memory question failed: ${response.status}`);
      }
      const payload = (await response.json()) as MemoryAnswer;
      setMemoryAnswer(payload);
      setMemoryAskStatus("done");
    } catch (err) {
      setMemoryAskStatus("error");
      setError(err instanceof Error ? err.message : "Memory question failed");
    }
  }

  async function startRecording(target: RecordingTarget = "meeting") {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setAudioStatus("error");
      setAudioMessage("Este navegador no soporta grabación de audio.");
      return;
    }

    try {
      setError(null);
      if (target === "meeting") {
        setAnalysis(null);
      }
      setExternalResponse(null);
      setRecordingTarget(target);
      audioChunksRef.current = [];
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const options = preferredRecorderOptions();
      const recorder = options ? new MediaRecorder(stream, options) : new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        audioChunksRef.current = [];
        stopMediaStream();
        setIsRecording(false);
        setIsPaused(false);
        if (blob.size > 0) {
          void transcribeAudioBlob(
            blob,
            target === "request" ? "sentinel-request.webm" : "sentinel-recording.webm",
            target,
          );
        }
      };

      recorder.start();
      setIsRecording(true);
      setIsPaused(false);
      setAudioStatus("recording");
      setAudioMessage(target === "request" ? "Grabando solicitud..." : "Grabando reunión...");
    } catch (err) {
      stopMediaStream();
      setIsRecording(false);
      setIsPaused(false);
      setAudioStatus("error");
      setAudioMessage(err instanceof Error ? err.message : "No se pudo acceder al micrófono.");
    }
  }

  function stopRecording() {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      return;
    }
    setAudioMessage(recordingTarget === "request" ? "Procesando solicitud..." : "Procesando audio...");
    recorder.stop();
  }

  function togglePauseRecording() {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      return;
    }
    if (recorder.state === "recording") {
      recorder.pause();
      setIsPaused(true);
      setAudioStatus("paused");
      setAudioMessage("Grabación pausada");
      return;
    }
    recorder.resume();
    setIsPaused(false);
    setAudioStatus("recording");
    setAudioMessage(recordingTarget === "request" ? "Grabando solicitud..." : "Grabando reunión...");
  }

  async function transcribeAudioBlob(blob: Blob, filename: string, target: RecordingTarget = "meeting") {
    setAudioStatus("transcribing");
    setRecordingTarget(target);
    setAudioMessage(target === "request" ? "Transcribiendo solicitud..." : "Transcribiendo con ElevenLabs...");
    try {
      const response = await fetch(`${API_BASE}/api/audio/transcribe?language_code=es&diarize=true`, {
        method: "POST",
        headers: {
          "Content-Type": blob.type || "application/octet-stream",
          "X-Sentinel-Filename": filename,
        },
        body: blob,
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`Audio transcription failed: ${response.status} ${detail}`);
      }
      const payload = (await response.json()) as TranscriptionResponse;
      const transcript = target === "request" ? payload.text.trim() : formatTranscript(payload);
      if (target === "request") {
        setSpecificRequest(transcript || defaultRequest);
      } else {
        setText(transcript);
      }
      setAudioStatus("done");
      setAudioMessage(
        target === "request"
          ? "Solicitud lista para analizar"
          : `Transcripción lista · ${payload.provider} ${payload.model_id}${
              payload.language_code ? ` · ${payload.language_code}` : ""
            }`,
      );
    } catch (err) {
      setAudioStatus("error");
      setAudioMessage(err instanceof Error ? err.message : "Transcription failed");
    }
  }

  async function bootAlwaysOnMicrophone() {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Recognition) {
      setWakeEnabled(false);
      setWakeStatus("unsupported");
      setWakeMessage("Wake word no soportado en este navegador");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setWakeEnabled(false);
      setWakeStatus("unsupported");
      setWakeMessage("Micrófono no disponible en este navegador");
      return;
    }

    setWakeStatus("listening");
    setWakeMessage("Solicitando permiso del micrófono...");
    try {
      const permissionStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      permissionStream.getTracks().forEach((track) => track.stop());
      startWakeListening();
    } catch (err) {
      setWakeEnabled(false);
      setWakeStatus("error");
      setWakeMessage("Permiso de micrófono requerido para activar Hola TEO");
    }
  }

  function startWakeListening() {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Recognition) {
      setWakeEnabled(false);
      setWakeStatus("unsupported");
      setWakeMessage("Wake word no soportado en este navegador");
      return;
    }

    if (wakeRestartTimerRef.current !== null) {
      window.clearTimeout(wakeRestartTimerRef.current);
      wakeRestartTimerRef.current = null;
    }
    recognitionRef.current?.abort();
    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "es-419";
    recognition.onresult = (event) => {
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result?.[0]?.transcript) {
          setLastWakeTranscript(result[0].transcript.trim());
          void handleWakeTranscript(result[0].transcript);
        }
      }
    };
    recognition.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        wakeEnabledRef.current = false;
        setWakeEnabled(false);
        setWakeStatus("error");
        setWakeMessage("Permiso de micrófono requerido para Hola TEO");
        return;
      }
      if (event.error === "audio-capture") {
        setWakeStatus("error");
        setWakeMessage("No encuentro micrófono activo");
        return;
      }
      setWakeStatus("listening");
      setWakeMessage("Escuchando siempre: di “Hola TEO”");
      scheduleWakeRestart(recognition, 220);
    };
    recognition.onend = () => {
      if (!wakeEnabledRef.current) {
        return;
      }
      setWakeStatus("listening");
      setWakeMessage("Escuchando siempre: di “Hola TEO”");
      scheduleWakeRestart(recognition, 180);
    };

    recognitionRef.current = recognition;
    wakeEnabledRef.current = true;
    setWakeEnabled(true);
    setWakeStatus("listening");
    setWakeMessage("Escuchando siempre: di “Hola TEO”");
    try {
      recognition.start();
    } catch {
      scheduleWakeRestart(recognition, 500);
    }
  }

  function scheduleWakeRestart(recognition: SpeechRecognitionLike, delayMs: number) {
    if (wakeRestartTimerRef.current !== null) {
      window.clearTimeout(wakeRestartTimerRef.current);
    }
    wakeRestartTimerRef.current = window.setTimeout(() => {
      wakeRestartTimerRef.current = null;
      if (!wakeEnabledRef.current || recognitionRef.current !== recognition) {
        return;
      }
      try {
        recognition.start();
        setWakeStatus("listening");
        setWakeMessage("Escuchando siempre: di “Hola TEO”");
      } catch {
        scheduleWakeRestart(recognition, Math.min(delayMs + 250, 1600));
      }
    }, delayMs);
  }

  function stopWakeListening() {
    wakeEnabledRef.current = false;
    setWakeEnabled(false);
    setWakeStatus("off");
    setWakeMessage("Wake word desactivado");
    if (wakeRestartTimerRef.current !== null) {
      window.clearTimeout(wakeRestartTimerRef.current);
      wakeRestartTimerRef.current = null;
    }
    recognitionRef.current?.stop();
  }

  async function handleWakeTranscript(transcript: string) {
    const now = Date.now();
    if (now - lastWakeHitAtRef.current < 1800) {
      return;
    }
    const command = extractWakeCommand(transcript);
    if (command === null) {
      return;
    }
    lastWakeHitAtRef.current = now;
    setWakeStatus("awake");
    setWakeMessage(`Detectado: ${transcript.trim()}`);
    if (!command) {
      setWakeMessage("Te escucho. Di: graba reunión, resumen, tareas o riesgos.");
      return;
    }
    await executeWakeCommand(command);
  }

  async function executeWakeCommand(command: string) {
    const normalizedCommand = normalizeSpeech(command);
    if (isStopMeetingCommand(normalizedCommand)) {
      if (isRecordingRef.current) {
        setWakeMessage("Deteniendo grabación");
        stopRecording();
      } else {
        setWakeMessage("No hay grabación activa");
      }
      return;
    }

    if (isStartMeetingCommand(normalizedCommand)) {
      setWakeMessage("Iniciando grabación de reunión");
      await startRecording("meeting");
      return;
    }

    if (isClearCommand(normalizedCommand)) {
      resetCurrentSession();
      setWakeMessage("Sesión actual borrada");
      return;
    }

    const request = voiceCommandToRequest(command);
    setSpecificRequest(request);
    setWakeMessage("Consulta capturada por voz");
    if (textRef.current.trim()) {
      await analyze(request);
      return;
    }
    if (memoryItemsRef.current.length > 0) {
      await askMemory(request);
      return;
    }
    setError("No hay reunión transcrita ni memoria disponible para responder esa solicitud.");
  }

  function stopMediaStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  function resetCurrentSession() {
    if (isRecording) {
      stopRecording();
    }
    setText("");
    setAnalysis(null);
    setExternalResponse(null);
    setLastRemembered(null);
    setMemoryAnswer(null);
    setSelectedMemory(null);
    setStatus("idle");
    setError(null);
    setAudioStatus("idle");
    setAudioMessage("Micrófono listo");
  }

  return (
    <main className="audio-shell">
      <aside className="voice-sidebar">
        <div className="side-logo" aria-label="teo">
          <span>t</span>
        </div>

        <button
          className="new-query"
          onClick={() => {
            setSpecificRequest(defaultRequest);
            setMemoryAnswer(null);
            setSelectedMemory(null);
          }}
        >
          <span>?</span>
          Nueva consulta
        </button>

        <div className="side-section">
          <div className="side-section-head">
            <span>Memoria</span>
            <strong>{memoryItems.length}</strong>
          </div>
          <div className="side-memory-list">
            {memoryItems.slice(0, 7).map((item) => (
              <button
                className={selectedMemory?.memory_id === item.memory_id ? "active" : ""}
                key={item.memory_id}
                onClick={() => void openMemoryItem(item.memory_id)}
              >
                <strong>{item.title}</strong>
                <small>{item.risk_level} · {item.task_segments.length} TO DO</small>
              </button>
            ))}
            {memoryItems.length === 0 && <p>No hay reuniones guardadas.</p>}
          </div>
        </div>

        <div className="company-switch">
          <span />
          Empresa
        </div>
      </aside>

      <section className="voice-main">
        <header className="voice-topbar">
          <div className="brand-lockup">
            <div className="teo-wordmark" aria-label="teo wordmark">
              teo
            </div>
            <div>
              <p className="eyebrow">Tecnología · Entendimiento · Operativo</p>
              <h1>Sentinel Audio</h1>
            </div>
          </div>
          <div className="topbar-actions">
            <span className={`status ${status}`}>{status}</span>
            <button className={`wake-toggle ${wakeEnabled ? "active" : ""}`} onClick={wakeEnabled ? stopWakeListening : startWakeListening}>
              {wakeEnabled ? "Siempre escuchando" : "Reintentar micrófono"}
            </button>
            <button onClick={() => void loadMemoryItems()} disabled={memoryListStatus === "running"}>
              Actualizar memoria
            </button>
          </div>
        </header>

        <section className="audio-stage">
          <div className="listening-hero">
            <WaveGlyph active={status === "running" || audioStatus === "recording" || audioStatus === "transcribing"} />
            <h2>{stageTitle}</h2>
            <p>{stageHint}</p>
            <div className="stage-pills">
              <span>Audio-first</span>
              <span>Regex + ML local</span>
              <span>API protegida</span>
              <span className={audioStatus}>{audioMessage}</span>
              <span className={`wake ${wakeStatus}`}>{wakeMessage}</span>
              {lastWakeTranscript && <span className="heard">Oyó: {lastWakeTranscript}</span>}
            </div>
          </div>

          <div className={`coded-window ${analysis ? "ready" : ""}`}>
            <div className="frame-head">
              <span>Payload seguro</span>
              <strong>{analysis ? `${analysis.counts.total_entities} elementos` : "en espera"}</strong>
            </div>
            <pre>{safePreview}</pre>
          </div>
        </section>

        <section className="source-dock">
          <div className="dock-head">
            <div>
              <span>Buffer de transcripción</span>
              <h2>Entrada generada desde audio</h2>
            </div>
            <div className="sample-row">
              <button onClick={() => setText(samples.normal)}>Normal</button>
              <button onClick={() => setText(samples.confidential)}>Confidencial</button>
              <button onClick={() => setText(samples.dangerous)}>Riesgo</button>
            </div>
          </div>
          <textarea
            className="transcript-input"
            value={text}
            onChange={(event) => setText(event.target.value)}
            spellCheck={false}
          />
        </section>

        <section className="composer-bar" aria-label="Audio and text query composer">
          <input
            ref={fileInputRef}
            className="hidden-file-input"
            type="file"
            accept="audio/*,video/*"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void transcribeAudioBlob(file, file.name);
              }
              event.currentTarget.value = "";
            }}
          />
          <button className="composer-icon" aria-label="Attach source" onClick={() => fileInputRef.current?.click()}>
            +
          </button>
          <textarea
            className="composer-input"
            value={specificRequest}
            onChange={(event) => setSpecificRequest(event.target.value)}
            placeholder="Pregunta lo que quieras..."
            spellCheck={false}
          />
          <div className="composer-controls">
            <button
              className="round-control"
              aria-label="Pause listening"
              onClick={togglePauseRecording}
              disabled={!isRecording}
            >
              {isPaused ? "▶" : "||"}
            </button>
            <button className="round-control" aria-label="Stop listening" onClick={stopRecording} disabled={!isRecording}>
              ■
            </button>
            <button className="wave-control" aria-label="Voice activity">
              <WaveGlyph compact active={isRecording || audioStatus === "transcribing"} />
            </button>
            <button
              className={`mic-control ${isRecording ? "recording" : ""}`}
              aria-label={isRecording ? "Stop microphone recording" : "Start microphone recording"}
              onClick={isRecording ? stopRecording : () => void startRecording("meeting")}
              disabled={audioStatus === "transcribing"}
            >
              mic
            </button>
            <button
              className={`voice-request-control ${isRecording && recordingTarget === "request" ? "recording" : ""}`}
              onClick={
                isRecording && recordingTarget === "request"
                  ? stopRecording
                  : () => void startRecording("request")
              }
              disabled={audioStatus === "transcribing" || (isRecording && recordingTarget !== "request")}
            >
              {isRecording && recordingTarget === "request" ? "Listo" : "Pedir por voz"}
            </button>
            <button className="send-control" onClick={() => void analyze()} disabled={status === "running" || !text.trim()}>
              {status === "running" ? "Codificando" : "Enviar"}
            </button>
          </div>
        </section>

        <div className="memory-options">
          <label className="memory-toggle">
            <input
              type="checkbox"
              checked={rememberTranscript}
              onChange={(event) => setRememberTranscript(event.target.checked)}
            />
            <span>Guardar reunión en memoria empresarial</span>
          </label>
          <button className="lcd-secondary-action" onClick={resetCurrentSession} disabled={!text && !analysis && !externalResponse}>
            Borrar actual
          </button>
          {memoryStatus && <span className="memory-save-status">{memoryStatus}</span>}
          {error && <span className="error">{error}</span>}
        </div>

        <section className="lcd-live-panel">
          <div className="lcd-live-card">
            <span>Transcripción</span>
            <pre>{text || "Presiona el micrófono o sube audio para comenzar."}</pre>
          </div>
          <div className="lcd-live-card accent">
            <span>Respuesta</span>
            <pre>{externalResponse || (analysis ? safePreview : "La respuesta aparecerá aquí después de analizar.")}</pre>
          </div>
        </section>

        <section className="lcd-recordings">
          <div className="lcd-recordings-head">
            <div>
              <span>Memoria empresarial</span>
              <h2>Grabaciones</h2>
            </div>
            <button onClick={() => void loadMemoryItems()} disabled={memoryListStatus === "running"}>
              Actualizar
            </button>
          </div>
          <div className="lcd-recording-list">
            {memoryItems.slice(0, 6).map((item) => (
              <div className="lcd-recording-card" key={item.memory_id}>
                <button className="lcd-recording-open" onClick={() => void openMemoryItem(item.memory_id)}>
                  <strong>{item.title}</strong>
                  <span>
                    {item.risk_level} · {item.task_segments.length} TO DO ·{" "}
                    {new Date(item.created_at).toLocaleDateString()}
                  </span>
                </button>
                <button className="lcd-delete-action" onClick={() => void deleteMemoryItem(item.memory_id)}>
                  Eliminar
                </button>
              </div>
            ))}
            {memoryItems.length === 0 && <p className="empty-state">No hay grabaciones guardadas todavía.</p>}
          </div>
        </section>

        {selectedMemory && (
          <section className="lcd-selected-memory">
            <div>
              <span>Seleccionada</span>
              <h2>{selectedMemory.title}</h2>
              <p>{selectedMemory.summary || "Sin resumen disponible."}</p>
            </div>
            <button className="lcd-delete-action" onClick={() => void deleteMemoryItem(selectedMemory.memory_id)}>
              Eliminar
            </button>
          </section>
        )}

        <section className="operations-grid">
          <aside className="report-panel">
            <div className="report-head">
              <div>
                <span>Privacidad</span>
                <h2>Privacy Report</h2>
              </div>
              <span className={`risk ${(analysis?.risk_level ?? "LOW").toLowerCase()}`}>
                {analysis?.risk_level ?? "LOW"}
              </span>
            </div>
            <div className="metric-grid">
              {stats.map(([label, value]) => (
                <div className="metric" key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
            <div className="flow">
              <span>Audio / Transcript</span>
              <span>Sentinel Privacy Engine</span>
              <span>Safe Payload</span>
              <span>API Intelligence</span>
              <span>Enterprise Memory</span>
            </div>
          </aside>

          <div className="response-panel">
            <div className="frame-head">
              <span>Respuesta del asistente</span>
              <strong>{externalResponse ? "lista" : "sin consulta"}</strong>
            </div>
            {externalResponse ? (
              <pre>{externalResponse}</pre>
            ) : (
              <p className="empty-state">La respuesta de la consulta aparecerá aquí enmarcada.</p>
            )}
          </div>

          <TicketBoard segments={activeTicketSegments} />
        </section>

        <section className="memory-panel">
          <div className="section-title">
            <div>
              <span>Segundo cerebro</span>
              <h2>Enterprise Memory</h2>
            </div>
            <div className="memory-head-actions">
              <span>{memoryItems.length} saved</span>
              <button onClick={() => void loadMemoryItems()} disabled={memoryListStatus === "running"}>
                Refresh
              </button>
              <span className={`status ${memoryAskStatus}`}>{memoryAskStatus}</span>
            </div>
          </div>

          <div className="memory-operating-grid">
            <div className="chat-console">
              <div className="chat-frame request-frame">
                <div className="frame-head">
                  <span>Chat Request</span>
                  <strong>API</strong>
                </div>
                <textarea
                  className="prompt-input chat-input"
                  value={memoryQuestion}
                  onChange={(event) => setMemoryQuestion(event.target.value)}
                  spellCheck={false}
                />
                <div className="chat-actions">
                  <button
                    className="primary"
                  onClick={() => void askMemory()}
                    disabled={memoryAskStatus === "running" || !memoryQuestion.trim()}
                  >
                    {memoryAskStatus === "running" ? "Searching" : "Ask memory"}
                  </button>
                  <span className={`status ${memoryAskStatus}`}>{memoryAskStatus}</span>
                </div>
              </div>

              <div className="chat-frame response-frame">
                <div className="frame-head">
                  <span>Chat Response</span>
                  <strong>{memoryAnswer ? `${memoryAnswer.sources.length} sources` : "waiting"}</strong>
                </div>
                {memoryAnswer ? (
                  <>
                    <pre>{memoryAnswer.answer}</pre>
                    <div className="evidence-strip">
                      {memoryAnswer.sources.map((source) => (
                        <div className="evidence-item" key={source.chunk_id}>
                          <strong>{source.title}</strong>
                          <span>Score {source.score.toFixed(2)}</span>
                          <p>{source.snippet}</p>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="empty-state">Pregunta a la memoria para ver respuesta y fuentes.</p>
                )}
              </div>
            </div>

            <LocalAnalysisPanel remembered={lastRemembered} />
          </div>

          <div className="memory-dashboard">
            <div className="memory-browser">
              <label className="memory-search">
                <span>Saved Meetings</span>
                <input
                  value={memorySearch}
                  onChange={(event) => setMemorySearch(event.target.value)}
                  placeholder="Search title, summary, decisions"
                />
              </label>
              <div className="memory-list">
                {filteredMemoryItems(memoryItems, memorySearch).map((item) => (
                  <button
                    className={`memory-card ${selectedMemory?.memory_id === item.memory_id ? "active" : ""}`}
                    key={item.memory_id}
                    onClick={() => void openMemoryItem(item.memory_id)}
                  >
                    <strong>{item.title}</strong>
                    <span>{item.summary || "No summary available."}</span>
                    <small>
                      {item.tasks.length} tasks · {item.decisions.length} decisions · {item.risks.length} risks
                    </small>
                    {item.areas.length > 0 && <small>{item.areas.map((area) => area.area).join(" · ")}</small>}
                  </button>
                ))}
                {memoryItems.length === 0 && <p className="empty-state">No memories saved yet.</p>}
              </div>
            </div>

            <div className="memory-detail">
              {selectedMemory ? (
                <>
                  <div className="detail-head">
                    <div>
                      <h2>{selectedMemory.title}</h2>
                      <span>
                        {selectedMemory.source} · {new Date(selectedMemory.created_at).toLocaleString()}
                      </span>
                    </div>
                    <button className="danger-button" onClick={() => void deleteMemoryItem(selectedMemory.memory_id)}>
                      Delete
                    </button>
                  </div>
                  <div className="artifact-grid">
                    <Artifact title="Summary" items={[selectedMemory.summary]} />
                    <Artifact title="Areas" items={selectedMemory.areas.map(formatArea)} />
                    <Artifact title="Decisions" items={selectedMemory.decisions} />
                    <Artifact title="Risks" items={selectedMemory.risks} />
                  </div>
                  <div className="memory-transcripts">
                    <div>
                      <h2>Original Transcript</h2>
                      <pre>{selectedMemory.transcript}</pre>
                    </div>
                    <div>
                      <h2>Safe Transcript</h2>
                      <pre>{selectedMemory.safe_content}</pre>
                    </div>
                  </div>
                </>
              ) : (
                <p className="empty-state">Select a saved memory to inspect it.</p>
              )}
            </div>
          </div>
        </section>

        <details className="technical-drawer">
          <summary>Ver análisis técnico y entidades detectadas</summary>
          <section className="comparison">
            <div className="text-column">
              <div className="column-title">
                <h2>Original</h2>
              </div>
              <pre>{analysis?.original_text ?? text}</pre>
            </div>
            <div className="text-column external">
              <div className="column-title">
                <h2>What External AI Sees</h2>
              </div>
              <pre>{analysis?.safe_content ?? "Run local analysis to generate a safe payload."}</pre>
            </div>
          </section>

          <section className="entities">
            <div className="section-title">
              <h2>Detected Elements</h2>
            </div>
            <div className="entity-table">
              <div className="entity-row header">
                <span>Type</span>
                <span>Value</span>
                <span>Sensitivity</span>
                <span>Action</span>
                <span>Placeholder</span>
              </div>
              {(analysis?.entities ?? []).map((entity, index) => (
                <div className="entity-row" key={`${entity.type}-${entity.start}-${index}`}>
                  <span>{entity.type}</span>
                  <span className="mono">{entity.original_value}</span>
                  <span>{entity.sensitivity}</span>
                  <span>{entity.action}</span>
                  <span className="mono">{entity.placeholder ?? ""}</span>
                </div>
              ))}
            </div>
          </section>
        </details>
      </section>
    </main>
  );
}

function WaveGlyph({ active = false, compact = false }: { active?: boolean; compact?: boolean }) {
  const bars = compact ? [18, 30, 42, 26, 36, 20] : [18, 34, 56, 42, 86, 68, 40, 76, 58, 32, 20];
  return (
    <div className={`wave-glyph ${active ? "active" : ""} ${compact ? "compact" : ""}`} aria-hidden="true">
      {bars.map((height, index) => (
        <span key={`${height}-${index}`} style={{ height }} />
      ))}
    </div>
  );
}

function Artifact({ title, items }: { title: string; items: string[] }) {
  const visibleItems = items.filter(Boolean);
  return (
    <div className="artifact">
      <h2>{title}</h2>
      {visibleItems.length ? (
        <ul>
          {visibleItems.map((item, index) => (
            <li key={`${title}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <span>None</span>
      )}
    </div>
  );
}

function LocalAnalysisPanel({ remembered }: { remembered: RememberedTranscript | null }) {
  if (!remembered) {
    return null;
  }

  return (
    <section className="local-analysis-panel">
      <div className="frame-head">
        <span>Local Analysis</span>
        <strong>{remembered.chunk_count} chunks</strong>
      </div>
      <div className="artifact-grid local-artifacts">
        <Artifact title="Summary" items={[remembered.summary]} />
        <Artifact title="Areas" items={remembered.areas.map(formatArea)} />
        <Artifact title="Decisions" items={remembered.decisions} />
        <Artifact title="Risks" items={remembered.risks} />
      </div>
      <TicketBoard segments={remembered.task_segments} emptyText="No routed TO DO detected in this transcript." />
    </section>
  );
}

function TicketBoard({
  segments,
  emptyText = "Select a memory with tasks or ask a question that retrieves task-bearing sources.",
}: {
  segments: TaskSegment[];
  emptyText?: string;
}) {
  const groups = ticketGroupsFromSegments(segments);
  const totalTodos = groups.reduce(
    (total, group) => total + group.divisions.reduce((subtotal, division) => subtotal + division.todos.length, 0),
    0,
  );

  return (
    <section className="ticket-board">
      <div className="ticket-head">
        <div>
          <span>Ticket Routing</span>
          <h2>Areas, Divisions & TO DO</h2>
        </div>
        <strong>{totalTodos} TO DO</strong>
      </div>
      {groups.length ? (
        <div className="ticket-area-grid">
          {groups.map((group) => (
            <div className="ticket-area" key={group.area}>
              <div className="ticket-area-head">
                <strong>{group.area}</strong>
                <span>{group.divisions.length} divisions</span>
              </div>
              {group.divisions.map((division) => (
                <div className="ticket-division" key={`${group.area}-${division.role}`}>
                  <h3>{division.role}</h3>
                  <ol>
                    {division.todos.map((todo) => (
                      <li key={todo.id}>
                        <span>{todo.id}</span>
                        <p>{todo.description}</p>
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-state">{emptyText}</p>
      )}
    </section>
  );
}

function filteredMemoryItems(items: MemoryDashboardItem[], query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return items;
  }
  return items.filter((item) =>
    [
      item.title,
      item.summary,
      ...item.tasks,
      ...item.decisions,
      ...item.risks,
      ...item.areas.map((area) => area.area),
      ...item.task_segments.map((segment) => `${segment.role} ${segment.area} ${segment.description}`),
    ]
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
}

function ticketGroupsFromSegments(segments: TaskSegment[]) {
  const seen = new Set<string>();
  const groups = new Map<string, Map<string, { id: string; description: string; confidence: number }[]>>();

  segments.forEach((segment) => {
    const area = segment.area || "General";
    const role = segment.role || "General / Sin asignar";
    const description = segment.description.trim();
    if (!description) {
      return;
    }
    const key = `${area}|${role}|${description}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    if (!groups.has(area)) {
      groups.set(area, new Map());
    }
    const divisions = groups.get(area)!;
    if (!divisions.has(role)) {
      divisions.set(role, []);
    }
    const todoIndex = seen.size.toString().padStart(2, "0");
    divisions.get(role)!.push({
      id: `T-${todoIndex}`,
      description,
      confidence: segment.confidence,
    });
  });

  return Array.from(groups.entries()).map(([area, divisions]) => ({
    area,
    divisions: Array.from(divisions.entries()).map(([role, todos]) => ({ role, todos })),
  }));
}

function formatArea(area: EnterpriseArea) {
  const evidence = area.evidence.length ? ` · ${area.evidence.slice(0, 4).join(", ")}` : "";
  return `${area.area} (${Math.round(area.score * 100)}%)${evidence}`;
}

function titleFromText(value: string) {
  const line = value
    .split("\n")
    .map((item) => item.replace(/^[#*\-\s:]+/, "").trim())
    .find(Boolean);
  return (line || "Meeting transcript").slice(0, 90);
}

function normalizeSpeech(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[¿?¡!.,;:]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function extractWakeCommand(transcript: string) {
  const normalized = normalizeSpeech(transcript);
  const wakeMatch = normalized.match(
    /\b(?:(?:hola|ola|oye|hey|ei|ok|okay)\s+)?(?:teo|theo|tio|ceo|seo|te\s*o|t\s*e\s*o|te\s+veo)\b/,
  );
  if (!wakeMatch || wakeMatch.index === undefined) {
    return null;
  }
  return normalized.slice(wakeMatch.index + wakeMatch[0].length).trim();
}

function isStartMeetingCommand(command: string) {
  return (
    /\b(graba|grabar|inicia|iniciar|empieza|empezar|comienza|comenzar|registra|registrar|captura|capturar)\b/.test(
      command,
    ) && /\b(reunion|junta|meeting|sesion)\b/.test(command)
  );
}

function isStopMeetingCommand(command: string) {
  return (
    /\b(detente|deten|detener|para|parar|termina|terminar|finaliza|finalizar)\b/.test(command) &&
    /\b(grabacion|reunion|junta|meeting|sesion)\b/.test(command)
  );
}

function isClearCommand(command: string) {
  return /\b(borra|borrar|limpia|limpiar|reinicia|reiniciar)\b/.test(command) && /\b(actual|sesion|pantalla)\b/.test(command);
}

function voiceCommandToRequest(command: string) {
  const normalized = normalizeSpeech(command);
  if (/\b(resumen|resume|resumir)\b/.test(normalized)) {
    return "Extrae un resumen ejecutivo de la reunión usando solamente el contenido seguro.";
  }
  if (/\b(tareas|pendientes|to do|acciones|accionables)\b/.test(normalized)) {
    return "Extrae las tareas accionables, responsables sugeridos y próximos pasos usando solamente el contenido seguro.";
  }
  if (/\b(riesgos|riesgo|alertas|problemas)\b/.test(normalized)) {
    return "Identifica los riesgos, alertas y puntos críticos mencionados usando solamente el contenido seguro.";
  }
  if (/\b(decisiones|acuerdos|decision)\b/.test(normalized)) {
    return "Extrae las decisiones y acuerdos tomados usando solamente el contenido seguro.";
  }
  return command.trim() || defaultRequest;
}

function preferredRecorderOptions(): MediaRecorderOptions | undefined {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  const mimeType = candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate));
  return mimeType ? { mimeType } : undefined;
}

function formatTranscript(payload: TranscriptionResponse) {
  const diarized = diarizedTranscript(payload.words);
  return diarized || payload.text;
}

function diarizedTranscript(words: unknown[]) {
  const wordItems = words.filter(isTranscriptWord);
  const speakers = new Set(wordItems.map((word) => word.speaker_id).filter(Boolean));
  if (wordItems.length === 0 || speakers.size < 2) {
    return "";
  }

  const lines: string[] = [];
  let currentSpeaker = "";
  let currentText = "";
  for (const word of wordItems) {
    const speaker = word.speaker_id || "speaker";
    if (speaker !== currentSpeaker) {
      if (currentText.trim()) {
        lines.push(`${currentSpeaker}: ${currentText.trim()}`);
      }
      currentSpeaker = speaker;
      currentText = "";
    }
    currentText = appendToken(currentText, word.text);
  }
  if (currentText.trim()) {
    lines.push(`${currentSpeaker}: ${currentText.trim()}`);
  }
  return lines.join("\n\n");
}

function isTranscriptWord(value: unknown): value is { text: string; speaker_id?: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "text" in value &&
    typeof (value as { text?: unknown }).text === "string"
  );
}

function appendToken(current: string, token: string) {
  const cleanToken = token.trim();
  if (!cleanToken) {
    return current;
  }
  if (!current || /^[.,;:!?)]$/.test(cleanToken)) {
    return `${current}${cleanToken}`;
  }
  if (/^['"]/.test(cleanToken)) {
    return `${current} ${cleanToken}`;
  }
  return `${current} ${cleanToken}`;
}

export default App;
