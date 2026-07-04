import { useEffect, useMemo, useState } from "react";

type Mode = "VAULT" | "INTELLIGENCE";

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
  analysis: PrivacyAnalysis;
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
  created_at: string;
};

type MemoryAnswer = {
  question: string;
  answer: string;
  mode: Mode;
  sources: MemorySource[];
  safe_context: string;
};

const API_BASE = import.meta.env.VITE_SENTINEL_API_BASE ?? "http://127.0.0.1:8000";

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
  const [mode, setMode] = useState<Mode>("VAULT");
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
  const [memoryListStatus, setMemoryListStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [memorySearch, setMemorySearch] = useState("");

  useEffect(() => {
    void loadMemoryItems();
  }, []);

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

  async function analyze() {
    setStatus("running");
    setError(null);
    setExternalResponse(null);

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
      }
      setAnalysis(privacy);

      if (mode === "INTELLIGENCE") {
        const purpose = specificRequest.trim() || defaultRequest;
        const aiResponse = await fetch(`${API_BASE}/api/ai/analyze-safe-content`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            safe_content: privacy.safe_content,
            session_id: privacy.session_id,
            purpose,
            mode,
          }),
        });
        if (!aiResponse.ok) {
          throw new Error(`External analysis failed: ${aiResponse.status}`);
        }
        const payload = await aiResponse.json();
        setExternalResponse(payload.reconstructed_response);
      }

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
      await loadMemoryItems();
    } catch (err) {
      setMemoryListStatus("error");
      setError(err instanceof Error ? err.message : "Memory delete failed");
    }
  }

  async function askMemory() {
    if (!memoryQuestion.trim()) {
      return;
    }
    setMemoryAskStatus("running");
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/memory/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: memoryQuestion, mode, limit: 6 }),
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

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">NVIDIA Jetson Orin Nano privacy gateway</p>
          <h1>Sentinel</h1>
        </div>
        <div className="mode-switch" role="tablist" aria-label="System mode">
          {(["VAULT", "INTELLIGENCE"] as Mode[]).map((item) => (
            <button
              key={item}
              className={mode === item ? "active" : ""}
              onClick={() => setMode(item)}
              role="tab"
              aria-selected={mode === item}
            >
              {item === "VAULT" ? "Vault Mode" : "Intelligence Mode"}
            </button>
          ))}
        </div>
      </header>

      <section className="workspace">
        <div className="input-panel">
          <div className="panel-heading">
            <h2>Meeting Transcript</h2>
            <div className="sample-row">
              <button onClick={() => setText(samples.normal)}>Normal</button>
              <button onClick={() => setText(samples.confidential)}>Confidential</button>
              <button onClick={() => setText(samples.dangerous)}>Dangerous</button>
            </div>
          </div>
          <textarea value={text} onChange={(event) => setText(event.target.value)} spellCheck={false} />
          <label className="prompt-block">
            <span>External Analysis Request</span>
            <textarea
              className="prompt-input"
              value={specificRequest}
              onChange={(event) => setSpecificRequest(event.target.value)}
              spellCheck={false}
            />
          </label>
          <div className="action-row">
            <button className="primary" onClick={analyze} disabled={status === "running" || !text.trim()}>
              {status === "running" ? "Analyzing" : "Analyze locally"}
            </button>
            <span className={`status ${status}`}>{status}</span>
            {memoryStatus && <span className="memory-save-status">{memoryStatus}</span>}
          </div>
          <label className="memory-toggle">
            <input
              type="checkbox"
              checked={rememberTranscript}
              onChange={(event) => setRememberTranscript(event.target.checked)}
            />
            <span>Remember transcript</span>
          </label>
          {error && <p className="error">{error}</p>}
        </div>

        <aside className="report-panel">
          <div className="report-head">
            <h2>Privacy Report</h2>
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
            <span>Original Data</span>
            <span>Sentinel Privacy Engine</span>
            <span>Safe Payload</span>
            <span>Optional External AI</span>
            <span>Local Reconstruction</span>
          </div>
        </aside>
      </section>

      <section className="memory-panel">
        <div className="section-title">
          <h2>Enterprise Memory</h2>
          <div className="memory-head-actions">
            <span>{memoryItems.length} saved</span>
            <button onClick={() => void loadMemoryItems()} disabled={memoryListStatus === "running"}>
              Refresh
            </button>
            <span className={`status ${memoryAskStatus}`}>{memoryAskStatus}</span>
          </div>
        </div>
        <div className="memory-grid">
          <label className="prompt-block memory-question">
            <span>Memory Question</span>
            <textarea
              className="prompt-input"
              value={memoryQuestion}
              onChange={(event) => setMemoryQuestion(event.target.value)}
              spellCheck={false}
            />
          </label>
          <div className="memory-actions">
            <button className="primary" onClick={askMemory} disabled={memoryAskStatus === "running" || !memoryQuestion.trim()}>
              {memoryAskStatus === "running" ? "Searching" : "Ask memory"}
            </button>
          </div>
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
                  <Artifact title="Tasks" items={selectedMemory.tasks} />
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
        {memoryAnswer && (
          <div className="memory-output">
            <div>
              <h2>Memory Answer</h2>
              <pre>{memoryAnswer.answer}</pre>
            </div>
            <div className="source-list">
              {memoryAnswer.sources.map((source) => (
                <div className="source-item" key={source.chunk_id}>
                  <strong>{source.title}</strong>
                  <span>Score {source.score.toFixed(1)}</span>
                  <pre>{source.snippet}</pre>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

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

      {externalResponse && (
        <section className="external-response">
          <h2>External Result</h2>
          <pre>{externalResponse}</pre>
        </section>
      )}
    </main>
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

function filteredMemoryItems(items: MemoryDashboardItem[], query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return items;
  }
  return items.filter((item) =>
    [item.title, item.summary, ...item.tasks, ...item.decisions, ...item.risks]
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
}

function titleFromText(value: string) {
  const line = value
    .split("\n")
    .map((item) => item.replace(/^[#*\-\s:]+/, "").trim())
    .find(Boolean);
  return (line || "Meeting transcript").slice(0, 90);
}

export default App;
