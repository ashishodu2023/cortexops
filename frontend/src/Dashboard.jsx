import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "https://api.getcortexops.com";

const PURPLE = "#534AB7";
const TEAL = "#1D9E75";
const RED = "#E24B4A";
const AMBER = "#EF9F27";
const GRAY = "#888780";

function MetricCard({ label, value, delta, deltaUp }) {
  return (
    <div style={{ background: "#F8F8FF", borderRadius: 10, padding: "14px 16px", border: "0.5px solid #E0DFF8" }}>
      <div style={{ fontSize: 11, color: GRAY, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 500, color: "#1A1830" }}>{value}</div>
      {delta !== undefined && (
        <div style={{ fontSize: 11, marginTop: 4, color: deltaUp ? TEAL : RED }}>
          {deltaUp ? "▲" : "▼"} {delta}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  const cfg = {
    completed: { bg: "#E1F5EE", color: "#085041" },
    failed: { bg: "#FCEBEB", color: "#791F1F" },
    pending: { bg: "#FAEEDA", color: "#633806" },
    running: { bg: "#E6F1FB", color: "#0C447C" },
  }[status] || { bg: "#F1EFE8", color: "#5F5E5A" };
  return (
    <span style={{ background: cfg.bg, color: cfg.color, fontSize: 10, fontWeight: 500, padding: "2px 8px", borderRadius: 99 }}>
      {status}
    </span>
  );
}

function ScoreBar({ score }) {
  const color = score >= 80 ? TEAL : score >= 60 ? AMBER : RED;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: "#EEEDFE", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${score}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 500, color, minWidth: 28, textAlign: "right" }}>
        {Math.round(score)}
      </span>
    </div>
  );
}

function NavBar({ project, setProject, apiKey, onSignOut }) {
  return (
    <div style={{ background: "#0F0D2A", padding: "12px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <svg width="28" height="28" viewBox="0 0 28 28">
          <rect width="28" height="28" rx="7" fill={PURPLE} />
          <path d="M14 4 Q20 14 14 24" fill="none" stroke="white" strokeWidth="1.6" strokeLinecap="round" />
          <path d="M9 4 Q17 14 9 24" fill="none" stroke="white" strokeWidth="1.6" strokeLinecap="round" opacity=".4" />
          <circle cx="14" cy="4" r="2" fill="white" />
          <circle cx="14" cy="24" r="2" fill="white" />
        </svg>
        <span style={{ color: "#EEEDFE", fontWeight: 500, fontSize: 15 }}>Cortex<span style={{ color: "#7F77DD", fontWeight: 400 }}>Ops</span></span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ color: "#6B6A9A", fontSize: 12 }}>Project:</span>
        <input
          value={project}
          onChange={e => setProject(e.target.value)}
          style={{ background: "#1A1830", border: "0.5px solid #2A2850", borderRadius: 6, color: "#EEEDFE", fontSize: 12, padding: "4px 10px", width: 160 }}
          placeholder="my-agent"
        />
        <span style={{ color: "#6B6A9A", fontSize: 11, marginLeft: 4 }}>
          {apiKey.slice(0, 12)}...
        </span>
        <button
          onClick={onSignOut}
          style={{ background: "none", border: "0.5px solid #2A2850", borderRadius: 6, color: "#6B6A9A", fontSize: 11, padding: "4px 10px", cursor: "pointer" }}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}

function LoginScreen({ onLogin }) {
  const [key, setKey] = useState("");
  const [project, setProject] = useState("payments-agent");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    if (!key.startsWith("cxo-")) {
      setError("API key must start with cxo-");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${API}/health`);
      if (!r.ok) throw new Error("API unreachable");
      onLogin(key, project);
    } catch {
      setError("Could not reach api.getcortexops.com — check your connection.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#0F0D2A", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "#1A1830", border: "0.5px solid #2A2850", borderRadius: 16, padding: "36px 40px", width: 380 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 28 }}>
          <svg width="32" height="32" viewBox="0 0 32 32">
            <rect width="32" height="32" rx="8" fill={PURPLE} />
            <path d="M16 5 Q23 16 16 27" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
            <path d="M10 5 Q19 16 10 27" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" opacity=".4" />
            <circle cx="16" cy="5" r="2.2" fill="white" />
            <circle cx="16" cy="27" r="2.2" fill="white" />
          </svg>
          <span style={{ color: "#EEEDFE", fontWeight: 500, fontSize: 18 }}>Cortex<span style={{ color: "#7F77DD", fontWeight: 300 }}>Ops</span></span>
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: 12, color: "#6B6A9A", marginBottom: 6 }}>API Key</label>
          <input
            value={key}
            onChange={e => setKey(e.target.value)}
            placeholder="cxo-..."
            type="password"
            onKeyDown={e => e.key === "Enter" && handleLogin()}
            style={{ width: "100%", background: "#0F0D2A", border: "0.5px solid #2A2850", borderRadius: 8, color: "#EEEDFE", fontSize: 13, padding: "10px 12px", outline: "none" }}
          />
        </div>

        <div style={{ marginBottom: 24 }}>
          <label style={{ display: "block", fontSize: 12, color: "#6B6A9A", marginBottom: 6 }}>Project name</label>
          <input
            value={project}
            onChange={e => setProject(e.target.value)}
            placeholder="payments-agent"
            onKeyDown={e => e.key === "Enter" && handleLogin()}
            style={{ width: "100%", background: "#0F0D2A", border: "0.5px solid #2A2850", borderRadius: 8, color: "#EEEDFE", fontSize: 13, padding: "10px 12px", outline: "none" }}
          />
        </div>

        {error && (
          <div style={{ background: "#FCEBEB", color: "#791F1F", fontSize: 12, padding: "8px 12px", borderRadius: 8, marginBottom: 16 }}>
            {error}
          </div>
        )}

        <button
          onClick={handleLogin}
          disabled={loading || !key}
          style={{ width: "100%", background: PURPLE, color: "#EEEDFE", border: "none", borderRadius: 8, padding: "11px", fontSize: 14, fontWeight: 500, cursor: loading || !key ? "not-allowed" : "pointer", opacity: loading || !key ? 0.6 : 1 }}
        >
          {loading ? "Connecting..." : "Open dashboard"}
        </button>

        <p style={{ color: "#3A3756", fontSize: 11, marginTop: 16, textAlign: "center" }}>
          Get an API key at <a href="https://getcortexops.com" style={{ color: "#7F77DD" }}>getcortexops.com</a>
        </p>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("cxo_key") || "");
  const [project, setProject] = useState(() => localStorage.getItem("cxo_project") || "payments-agent");
  const [runs, setRuns] = useState([]);
  const [traces, setTraces] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState("overview");
  const [error, setError] = useState("");

  const headers = { "X-API-Key": apiKey, "Content-Type": "application/json" };

  const handleLogin = (key, proj) => {
    setApiKey(key);
    setProject(proj);
    localStorage.setItem("cxo_key", key);
    localStorage.setItem("cxo_project", proj);
  };

  const handleSignOut = () => {
    setApiKey("");
    localStorage.removeItem("cxo_key");
    setRuns([]);
    setTraces([]);
  };

  useEffect(() => {
    if (!apiKey || !project) return;
    setLoading(true);
    setError("");

    const fetchData = async () => {
      try {
        const [evalsRes, tracesRes] = await Promise.all([
          fetch(`${API}/v1/evals?project=${encodeURIComponent(project)}&limit=20`, { headers }),
          fetch(`${API}/v1/traces?project=${encodeURIComponent(project)}&limit=50`, { headers }),
        ]);

        if (evalsRes.status === 401 || evalsRes.status === 403) {
          setError("Invalid API key — check your credentials.");
          setApiKey("");
          localStorage.removeItem("cxo_key");
          return;
        }

        const evalsData = await evalsRes.json();
        const tracesData = await tracesRes.json();

        setRuns(Array.isArray(evalsData) ? evalsData : []);
        setTraces(Array.isArray(tracesData) ? tracesData : []);
      } catch {
        setError("Failed to fetch data — check your connection.");
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [apiKey, project]);

  useEffect(() => {
    if (project) localStorage.setItem("cxo_project", project);
  }, [project]);

  if (!apiKey) return <LoginScreen onLogin={handleLogin} />;

  const latest = runs[0];
  const prev = runs[1];
  const tcDelta = latest && prev
    ? `${Math.abs((latest.task_completion_rate - prev.task_completion_rate) * 100).toFixed(1)}%`
    : undefined;
  const tcUp = latest && prev && latest.task_completion_rate >= prev.task_completion_rate;

  return (
    <div style={{ minHeight: "100vh", background: "#F4F3FB", fontFamily: "system-ui, sans-serif" }}>
      <NavBar project={project} setProject={setProject} apiKey={apiKey} onSignOut={handleSignOut} />

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px" }}>

        {error && (
          <div style={{ background: "#FCEBEB", color: "#791F1F", fontSize: 13, padding: "10px 14px", borderRadius: 8, marginBottom: 16 }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
          {["overview", "traces", "prompts"].map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              background: view === v ? PURPLE : "white",
              color: view === v ? "white" : "#5F5E5A",
              border: `0.5px solid ${view === v ? PURPLE : "#D3D1C7"}`,
              borderRadius: 7, padding: "6px 14px", fontSize: 13, cursor: "pointer", fontWeight: view === v ? 500 : 400,
            }}>
              {v.charAt(0).toUpperCase() + v.slice(1)}
            </button>
          ))}
          <div style={{ marginLeft: "auto", fontSize: 11, color: GRAY, display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: TEAL }} />
            Live · refreshes every 30s
          </div>
        </div>

        {view === "overview" && (
          <>
            {latest ? (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 10, marginBottom: 20 }}>
                <MetricCard label="Task completion" value={`${(latest.task_completion_rate * 100).toFixed(1)}%`} delta={tcDelta} deltaUp={tcUp} />
                <MetricCard label="Tool accuracy" value={`${(latest.tool_accuracy || 0).toFixed(1)}`} />
                <MetricCard label="Latency p95" value={`${Math.round(latest.latency_p95_ms || 0)}ms`} />
                <MetricCard label="Regressions" value={latest.regressions || 0} delta={latest.regressions > 0 ? `${latest.regressions} new` : undefined} deltaUp={false} />
              </div>
            ) : !loading && (
              <div style={{ background: "#EEEDFE", border: "0.5px solid #AFA9EC", borderRadius: 10, padding: "16px 20px", marginBottom: 20 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: "#3C3489", marginBottom: 4 }}>No eval runs yet</div>
                <div style={{ fontSize: 12, color: "#534AB7", fontFamily: "monospace" }}>
                  cortexops eval run --dataset golden_v1.yaml --project {project}
                </div>
              </div>
            )}

            <div style={{ background: "white", borderRadius: 12, border: "0.5px solid #E0DFF0", overflow: "hidden", marginBottom: 20 }}>
              <div style={{ padding: "14px 18px", borderBottom: "0.5px solid #E0DFF0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 500, fontSize: 14, color: "#1A1830" }}>Eval runs</span>
                <span style={{ fontSize: 12, color: GRAY }}>{runs.length} total</span>
              </div>
              {loading && <div style={{ padding: 20, color: GRAY, fontSize: 13 }}>Loading...</div>}
              {!loading && runs.length === 0 && (
                <div style={{ padding: 20, color: GRAY, fontSize: 13 }}>
                  No runs found for project <strong>{project}</strong>.
                </div>
              )}
              {runs.map((run, i) => (
                <div
                  key={run.run_id}
                  onClick={() => setSelected(selected?.run_id === run.run_id ? null : run)}
                  style={{
                    padding: "12px 18px", borderBottom: "0.5px solid #F0EFF8", cursor: "pointer",
                    background: selected?.run_id === run.run_id ? "#F8F8FF" : i === 0 ? "#FDFCFF" : "white",
                    transition: "background 0.1s",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <code style={{ fontSize: 11, color: GRAY, minWidth: 72 }}>{run.run_id?.slice(0, 8)}</code>
                    <StatusBadge status={run.status || "completed"} />
                    <div style={{ flex: 1 }}>
                      <ScoreBar score={(run.task_completion_rate || 0) * 100} />
                    </div>
                    <span style={{ fontSize: 12, color: GRAY, minWidth: 60, textAlign: "right" }}>
                      {run.passed}/{run.total_cases} pass
                    </span>
                    {run.regressions > 0 && (
                      <span style={{ fontSize: 10, background: "#FCEBEB", color: "#791F1F", padding: "2px 7px", borderRadius: 99 }}>
                        {run.regressions} regression{run.regressions > 1 ? "s" : ""}
                      </span>
                    )}
                  </div>

                  {selected?.run_id === run.run_id && run.case_results?.length > 0 && (
                    <div style={{ marginTop: 12, paddingTop: 12, borderTop: "0.5px solid #E0DFF0" }}>
                      <div style={{ fontSize: 11, color: GRAY, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>Case results</div>
                      {run.case_results.map(cr => (
                        <div key={cr.case_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0", borderBottom: "0.5px solid #F4F3FB" }}>
                          <code style={{ fontSize: 11, flex: 1, color: "#1A1830" }}>{cr.case_id}</code>
                          <div style={{ width: 120 }}><ScoreBar score={cr.score || 0} /></div>
                          {cr.failure_kind && (
                            <span style={{ fontSize: 10, color: RED, fontFamily: "monospace" }}>{cr.failure_kind}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {view === "traces" && (
          <div style={{ background: "white", borderRadius: 12, border: "0.5px solid #E0DFF0", overflow: "hidden" }}>
            <div style={{ padding: "14px 18px", borderBottom: "0.5px solid #E0DFF0", display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontWeight: 500, fontSize: 14, color: "#1A1830" }}>Traces</span>
              <span style={{ fontSize: 12, color: GRAY }}>{traces.length} total</span>
            </div>
            {loading && <div style={{ padding: 20, color: GRAY, fontSize: 13 }}>Loading...</div>}
            {!loading && traces.length === 0 && (
              <div style={{ padding: 20, color: GRAY, fontSize: 13 }}>
                No traces yet. Instrument your agent with <code style={{ background: "#F4F3FB", padding: "1px 5px", borderRadius: 4 }}>CortexTracer</code> to start collecting traces.
              </div>
            )}
            {traces.map((t, i) => (
              <div key={t.trace_id} style={{ padding: "11px 18px", borderBottom: "0.5px solid #F0EFF8", display: "flex", alignItems: "center", gap: 12, background: i % 2 === 0 ? "white" : "#FDFCFF" }}>
                <code style={{ fontSize: 11, color: GRAY, minWidth: 72 }}>{t.trace_id?.slice(0, 8)}</code>
                <StatusBadge status={t.status || "completed"} />
                <span style={{ fontSize: 12, color: "#1A1830", flex: 1 }}>{t.case_id || "—"}</span>
                <span style={{ fontSize: 12, color: GRAY }}>{Math.round(t.total_latency_ms || 0)}ms</span>
                {t.failure_kind && <span style={{ fontSize: 10, color: RED, fontFamily: "monospace" }}>{t.failure_kind}</span>}
                <span style={{ fontSize: 11, color: GRAY }}>{t.created_at ? new Date(t.created_at).toLocaleTimeString() : ""}</span>
              </div>
            ))}
          </div>
        )}

        {view === "prompts" && (
          <div style={{ background: "white", borderRadius: 12, border: "0.5px solid #E0DFF0", padding: 20 }}>
            <p style={{ color: GRAY, fontSize: 13, margin: 0, lineHeight: 1.7 }}>
              Prompt version history is available via the API.<br />
              <code style={{ background: "#F4F3FB", padding: "2px 6px", borderRadius: 4, fontSize: 12 }}>
                GET {API}/v1/prompts?project={project}&prompt_name=system_prompt
              </code>
              <br /><br />
              Diffs between versions:<br />
              <code style={{ background: "#F4F3FB", padding: "2px 6px", borderRadius: 4, fontSize: 12 }}>
                GET {API}/v1/prompts/diff?project={project}&prompt_name=system_prompt&version_a=1&version_b=2
              </code>
            </p>
          </div>
        )}

      </div>
    </div>
  );
}
