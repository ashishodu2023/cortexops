import { useState, useEffect, useRef, useCallback } from "react";

const API = import.meta.env?.VITE_API_URL || "https://api.getcortexops.com";

const C = {
  bg: "#0A0A12", surface: "#11111F", card: "#161628", border: "#1E1E3A",
  purple: "#6C63FF", purpleDim: "#2A2650", teal: "#00D4A8", tealDim: "#00342A",
  red: "#FF4D6A", redDim: "#3A0F18", amber: "#FFB547", amberDim: "#3A2800",
  blue: "#4D9FFF", text: "#E8E8F0", textMuted: "#6B6B8A", textDim: "#3A3A5C",
  mono: "'JetBrains Mono', 'Fira Code', monospace",
};

const G = `
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Syne:wght@400;500;600;700&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{background:${C.bg};color:${C.text};font-family:'Syne',sans-serif}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:${C.surface}}
::-webkit-scrollbar-thumb{background:${C.border};border-radius:2px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
@keyframes slideIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
`;

function useFetch(apiKey, path) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const fetch_ = useCallback(async () => {
    if (!apiKey || !path) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}${path}`, { headers: { "X-API-Key": apiKey } });
      if (r.ok) setData(await r.json());
    } finally { setLoading(false); }
  }, [apiKey, path]);
  useEffect(() => { fetch_(); }, [fetch_]);
  return { data, loading, refetch: fetch_ };
}

function Sparkline({ values = [], color, h = 32 }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1), min = Math.min(...values), range = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 120},${h - ((v - min) / range) * (h - 4) - 2}`).join(" ");
  const last = pts.split(" ").pop().split(",");
  return (
    <svg width="120" height={h} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="2.5" fill={color} />
    </svg>
  );
}

function Tile({ label, value, unit, delta, deltaUp, spark, color, loading }) {
  return (
    <div style={{ background: C.card, border: `0.5px solid ${C.border}`, borderRadius: 12, padding: "14px 16px", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: color, opacity: .4 }} />
      <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 6 }}>{label}</div>
      {loading
        ? <div style={{ width: 60, height: 26, background: C.border, borderRadius: 4, animation: "pulse 1.5s infinite" }} />
        : <div style={{ fontSize: 26, fontWeight: 700, color, letterSpacing: "-.03em", marginBottom: 6 }}>{value ?? "—"}<span style={{ fontSize: 12, color: C.textMuted, fontWeight: 400, marginLeft: 2 }}>{unit}</span></div>
      }
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        {delta !== undefined && <span style={{ fontSize: 11, color: deltaUp ? C.teal : C.red }}>{deltaUp ? "↑" : "↓"} {delta}</span>}
        <Sparkline values={spark} color={color} />
      </div>
    </div>
  );
}

function Dot({ status }) {
  const c = { completed: C.teal, failed: C.red, running: C.amber }[status] || C.textMuted;
  return <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: c, animation: status === "running" ? "pulse 1s infinite" : "none" }} />;
}

function WaterfallPanel({ trace, onClose }) {
  const raw = trace.raw_trace || {};
  const nodes = raw.nodes || [];
  const maxMs = Math.max(...nodes.map(n => n.latency_ms || 0), trace.total_latency_ms || 1);
  return (
    <div style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: 540, background: C.card, borderLeft: `1px solid ${C.border}`, zIndex: 100, display: "flex", flexDirection: "column", animation: "slideIn .2s ease" }}>
      <div style={{ padding: "14px 18px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Trace detail</div>
          <div style={{ fontSize: 10, fontFamily: C.mono, color: C.textMuted, marginTop: 2 }}>{trace.trace_id}</div>
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", color: C.textMuted, cursor: "pointer", fontSize: 20 }}>×</button>
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: "14px 18px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 18 }}>
          {[
            ["Status", trace.status, trace.status === "completed" ? C.teal : C.red],
            ["Latency", `${Math.round(trace.total_latency_ms || 0)}ms`, C.amber],
            ["Environment", trace.environment || "—", C.blue],
            ["Failure", trace.failure_kind || "none", trace.failure_kind ? C.red : C.textMuted],
          ].map(([l, v, c]) => (
            <div key={l} style={{ background: C.surface, borderRadius: 8, padding: "10px 12px", border: `0.5px solid ${C.border}` }}>
              <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 4 }}>{l}</div>
              <div style={{ fontSize: 13, fontFamily: C.mono, color: c }}>{v}</div>
            </div>
          ))}
        </div>
        {nodes.length > 0 && (
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 10 }}>Node waterfall</div>
            {nodes.map((n, i) => {
              const w = Math.max(2, (n.latency_ms / maxMs) * 100);
              const c = n.latency_ms > 1000 ? C.red : n.latency_ms > 500 ? C.amber : C.teal;
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0", borderBottom: `0.5px solid ${C.border}`, animation: `slideIn .2s ease ${i * .04}s both` }}>
                  <div style={{ width: 130, fontSize: 11, color: C.textMuted, fontFamily: C.mono, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{n.node_name || n.name || "node"}</div>
                  <div style={{ flex: 1, height: 18, background: C.surface, borderRadius: 3, overflow: "hidden" }}>
                    <div style={{ width: `${w}%`, height: "100%", background: c, borderRadius: 3, opacity: .8 }} />
                  </div>
                  <div style={{ width: 55, fontSize: 11, fontFamily: C.mono, color: c, textAlign: "right" }}>{Math.round(n.latency_ms)}ms</div>
                  {n.tool_calls?.slice(0, 2).map((tc, j) => (
                    <span key={j} style={{ fontSize: 9, background: tc.status === "success" ? C.tealDim : C.redDim, color: tc.status === "success" ? C.teal : C.red, padding: "1px 5px", borderRadius: 3, fontFamily: C.mono }}>{tc.name?.slice(0, 8)}</span>
                  ))}
                </div>
              );
            })}
          </div>
        )}
        {raw.output && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 8 }}>Output</div>
            <div style={{ background: C.surface, borderRadius: 8, padding: 12, border: `0.5px solid ${C.border}`, fontFamily: C.mono, fontSize: 11, color: C.teal, whiteSpace: "pre-wrap", wordBreak: "break-all", maxHeight: 180, overflow: "auto" }}>
              {JSON.stringify(raw.output, null, 2)}
            </div>
          </div>
        )}
        {trace.failure_detail && (
          <div>
            <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 8 }}>Failure</div>
            <div style={{ background: C.redDim, borderRadius: 8, padding: 12, border: `0.5px solid ${C.red}40`, fontFamily: C.mono, fontSize: 11, color: C.red }}>{trace.failure_detail}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function LoginScreen({ onLogin }) {
  const [key, setKey] = useState(""); const [proj, setProj] = useState("payments-agent");
  const [err, setErr] = useState(""); const [loading, setLoading] = useState(false);
  const submit = async () => {
    if (!key.startsWith("cxo-")) { setErr("Key must start with cxo-"); return; }
    setLoading(true);
    try { const r = await fetch(`${API}/health`); if (!r.ok) throw 0; onLogin(key, proj); }
    catch { setErr("Cannot reach api.getcortexops.com"); }
    finally { setLoading(false); }
  };
  return (
    <div style={{ minHeight: "100vh", background: C.bg, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 370, background: C.card, border: `1px solid ${C.border}`, borderRadius: 16, padding: "34px 36px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 28 }}>
          <svg width="34" height="34" viewBox="0 0 34 34"><rect width="34" height="34" rx="8" fill={C.purple} />
            <path d="M17 5 Q24 17 17 29" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
            <path d="M10 5 Q20 17 10 29" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" opacity=".35" />
            <circle cx="17" cy="5" r="2.2" fill="white" /><circle cx="17" cy="29" r="2.2" fill="white" />
          </svg>
          <div><div style={{ fontSize: 17, fontWeight: 700 }}>CortexOps</div><div style={{ fontSize: 11, color: C.textMuted }}>Agent observability</div></div>
        </div>
        {[["API Key", key, setKey, "cxo-...", "password"], ["Project", proj, setProj, "my-agent", "text"]].map(([l, v, s, p, t]) => (
          <div key={l} style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 10, color: C.textMuted, marginBottom: 5, textTransform: "uppercase", letterSpacing: ".06em" }}>{l}</label>
            <input value={v} onChange={e => s(e.target.value)} placeholder={p} type={t} onKeyDown={e => e.key === "Enter" && submit()}
              style={{ width: "100%", background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text, fontSize: 13, padding: "9px 11px", outline: "none", fontFamily: t === "password" ? C.mono : "inherit" }} />
          </div>
        ))}
        {err && <div style={{ background: C.redDim, color: C.red, fontSize: 12, padding: "7px 11px", borderRadius: 7, marginBottom: 12 }}>{err}</div>}
        <button onClick={submit} disabled={loading || !key}
          style={{ width: "100%", background: C.purple, color: "white", border: "none", borderRadius: 8, padding: 11, fontSize: 14, fontWeight: 600, cursor: "pointer", opacity: loading || !key ? .5 : 1 }}>
          {loading ? "Connecting..." : "Open dashboard →"}
        </button>
        <p style={{ color: C.textDim, fontSize: 11, marginTop: 12, textAlign: "center" }}>
          <a href="https://getcortexops.com" style={{ color: C.purple }}>getcortexops.com</a>
        </p>
      </div>
    </div>
  );
}

export default function App() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("cxo_key") || "");
  const [project, setProject] = useState(() => localStorage.getItem("cxo_project") || "payments-agent");
  const [tab, setTab] = useState("traces");
  const [filter, setFilter] = useState("all");
  const [live, setLive] = useState(true);
  const [selected, setSelected] = useState(null);
  const ref = useRef(null);

  const tPath = apiKey ? `/v1/traces?project=${encodeURIComponent(project)}&limit=100${filter !== "all" ? `&status=${filter}` : ""}` : null;
  const ePath = apiKey ? `/v1/evals?project=${encodeURIComponent(project)}&limit=20` : null;

  const { data: rawTraces, loading: tLoad, refetch: rT } = useFetch(apiKey, tPath);
  const { data: rawEvals, loading: eLoad, refetch: rE } = useFetch(apiKey, ePath);

  useEffect(() => {
    if (live && apiKey) { ref.current = setInterval(() => { rT(); rE(); }, 5000); }
    return () => clearInterval(ref.current);
  }, [live, apiKey, rT, rE]);

  useEffect(() => { if (project) localStorage.setItem("cxo_project", project); }, [project]);

  const login = (k, p) => { setApiKey(k); setProject(p); localStorage.setItem("cxo_key", k); localStorage.setItem("cxo_project", p); };

  if (!apiKey) return <><style>{G}</style><LoginScreen onLogin={login} /></>;

  const traces = Array.isArray(rawTraces) ? rawTraces : [];
  const evals = Array.isArray(rawEvals) ? rawEvals : [];
  const latest = evals[0]; const prev = evals[1];
  const failed = traces.filter(t => t.status === "failed").length;
  const errRate = traces.length > 0 ? ((failed / traces.length) * 100).toFixed(1) : "0.0";
  const avgLat = traces.length > 0 ? Math.round(traces.reduce((s, t) => s + (t.total_latency_ms || 0), 0) / traces.length) : 0;
  const sorted = [...traces].sort((a, b) => b.total_latency_ms - a.total_latency_ms);
  const p95 = sorted.length > 0 ? Math.round(sorted[Math.floor(sorted.length * 0.05)]?.total_latency_ms || 0) : 0;

  return (
    <>
      <style>{G}</style>
      <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>

        {/* Topbar */}
        <div style={{ display: "flex", alignItems: "center", padding: "0 18px", height: 50, borderBottom: `1px solid ${C.border}`, background: C.surface, gap: 14, flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <svg width="22" height="22" viewBox="0 0 22 22"><rect width="22" height="22" rx="5" fill={C.purple} />
              <path d="M11 3 Q16 11 11 19" fill="none" stroke="white" strokeWidth="1.4" strokeLinecap="round" />
              <path d="M7 3 Q13 11 7 19" fill="none" stroke="white" strokeWidth="1.4" strokeLinecap="round" opacity=".35" />
              <circle cx="11" cy="3" r="1.6" fill="white" /><circle cx="11" cy="19" r="1.6" fill="white" />
            </svg>
            <span style={{ fontSize: 14, fontWeight: 700 }}>CortexOps</span>
            <span style={{ fontSize: 11, color: C.textDim }}>Observability</span>
          </div>
          <div style={{ width: 1, height: 18, background: C.border }} />
          <span style={{ fontSize: 11, color: C.textMuted }}>project</span>
          <input value={project} onChange={e => setProject(e.target.value)}
            style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, color: C.text, fontSize: 12, padding: "3px 9px", width: 150, fontFamily: C.mono, outline: "none" }} />
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
            <div onClick={() => setLive(l => !l)} style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: live ? C.teal : C.textMuted, animation: live ? "pulse 1s infinite" : "none" }} />
              <span style={{ fontSize: 11, color: live ? C.teal : C.textMuted }}>{live ? "Live · 5s" : "Paused"}</span>
            </div>
            <button onClick={() => { rT(); rE(); }} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 5, color: C.textMuted, fontSize: 11, padding: "3px 9px", cursor: "pointer" }}>↻</button>
            <button onClick={() => { setApiKey(""); localStorage.removeItem("cxo_key"); }} style={{ background: "none", border: "none", color: C.textDim, fontSize: 11, cursor: "pointer" }}>Sign out</button>
          </div>
        </div>

        {/* Metric tiles */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5,minmax(0,1fr))", gap: 10, padding: "12px 18px", flexShrink: 0 }}>
          <Tile label="Task completion" value={latest ? `${(latest.task_completion_rate * 100).toFixed(1)}` : "—"} unit="%" color={C.teal}
            spark={evals.slice(0, 10).reverse().map(e => (e.task_completion_rate || 0) * 100)} loading={eLoad}
            delta={prev ? `${Math.abs((latest.task_completion_rate - prev.task_completion_rate) * 100).toFixed(1)}%` : undefined}
            deltaUp={prev && latest.task_completion_rate >= prev.task_completion_rate} />
          <Tile label="Error rate" value={errRate} unit="%" color={parseFloat(errRate) > 5 ? C.red : C.teal} spark={traces.slice(0, 20).reverse().map(t => t.status === "failed" ? 100 : 0)} loading={tLoad} />
          <Tile label="Avg latency" value={avgLat} unit="ms" color={avgLat > 1000 ? C.red : avgLat > 500 ? C.amber : C.teal} spark={traces.slice(0, 20).reverse().map(t => t.total_latency_ms || 0)} loading={tLoad} />
          <Tile label="P95 latency" value={p95} unit="ms" color={p95 > 2000 ? C.red : p95 > 1000 ? C.amber : C.blue} spark={traces.slice(0, 20).reverse().map(t => t.total_latency_ms || 0)} loading={tLoad} />
          <Tile label="Total traces" value={traces.length} color={C.purple} spark={traces.slice(0, 20).map(() => 1)} loading={tLoad} />
        </div>

        {/* Main content */}
        <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

            {/* Tabs */}
            <div style={{ display: "flex", alignItems: "center", padding: "0 18px", height: 38, borderBottom: `1px solid ${C.border}`, gap: 4, flexShrink: 0 }}>
              {["traces", "evals", "errors"].map(t => (
                <button key={t} onClick={() => setTab(t)}
                  style={{ background: tab === t ? C.purpleDim : "none", color: tab === t ? C.purple : C.textMuted, border: `1px solid ${tab === t ? C.purple + "50" : "transparent"}`, borderRadius: 5, padding: "3px 12px", fontSize: 12, cursor: "pointer", fontWeight: tab === t ? 600 : 400 }}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                  {t === "errors" && failed > 0 && <span style={{ marginLeft: 5, background: C.red, color: "white", borderRadius: 99, fontSize: 9, padding: "1px 5px" }}>{failed}</span>}
                </button>
              ))}
              {tab === "traces" && (
                <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                  {["all", "completed", "failed"].map(s => (
                    <button key={s} onClick={() => setFilter(s)}
                      style={{ background: filter === s ? C.card : "none", border: `1px solid ${filter === s ? C.border : "transparent"}`, borderRadius: 4, color: filter === s ? C.text : C.textMuted, fontSize: 10, padding: "2px 9px", cursor: "pointer" }}>{s}</button>
                  ))}
                </div>
              )}
            </div>

            {/* List headers */}
            {tab === "traces" && (
              <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "5px 16px", borderBottom: `0.5px solid ${C.border}`, flexShrink: 0 }}>
                {["", "ID", "Case", "Latency", "Failure", "Time"].map((h, i) => (
                  <span key={i} style={{ fontSize: 10, color: C.textDim, textTransform: "uppercase", letterSpacing: ".07em", minWidth: i === 0 ? 6 : i === 1 ? 64 : i === 3 ? 58 : i === 4 ? 100 : i === 5 ? 80 : undefined, flex: i === 2 ? 1 : undefined }}>{h}</span>
                ))}
              </div>
            )}

            <div style={{ flex: 1, overflow: "auto" }}>
              {tab === "traces" && (
                <>
                  {traces.length === 0 && !tLoad && (
                    <div style={{ padding: "40px 20px", textAlign: "center", color: C.textMuted, fontSize: 13 }}>
                      No traces yet.<div style={{ fontFamily: C.mono, fontSize: 11, color: C.textDim, marginTop: 6 }}>pip install cortexops</div>
                    </div>
                  )}
                  {traces.map((t, i) => (
                    <div key={t.trace_id} onClick={() => setSelected(t)}
                      style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 16px", borderBottom: `0.5px solid ${C.border}`, cursor: "pointer", animation: `slideIn .2s ease ${Math.min(i, 8) * .03}s both`, transition: "background .1s" }}
                      onMouseEnter={e => e.currentTarget.style.background = C.surface}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <Dot status={t.status} />
                      <span style={{ fontFamily: C.mono, fontSize: 11, color: C.textMuted, minWidth: 64 }}>{t.trace_id?.slice(0, 8)}</span>
                      <span style={{ flex: 1, fontSize: 12, color: C.text }}>{t.case_id || "live trace"}</span>
                      <span style={{ fontSize: 11, fontFamily: C.mono, minWidth: 58, textAlign: "right", color: t.total_latency_ms > 1000 ? C.red : t.total_latency_ms > 500 ? C.amber : C.teal }}>{Math.round(t.total_latency_ms || 0)}ms</span>
                      <span style={{ minWidth: 100, fontSize: 10 }}>
                        {t.failure_kind ? <span style={{ background: C.redDim, color: C.red, padding: "2px 6px", borderRadius: 3, fontFamily: C.mono }}>{t.failure_kind.replace("FailureKind.", "")}</span> : <span style={{ color: C.textDim }}>—</span>}
                      </span>
                      <span style={{ fontSize: 10, color: C.textMuted, minWidth: 80, textAlign: "right" }}>{t.created_at ? new Date(t.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}</span>
                    </div>
                  ))}
                </>
              )}

              {tab === "evals" && (
                <>
                  {evals.length === 0 && !eLoad && (
                    <div style={{ padding: "40px 20px", textAlign: "center", color: C.textMuted, fontSize: 13 }}>
                      No eval runs yet.<div style={{ fontFamily: C.mono, fontSize: 11, color: C.textDim, marginTop: 6 }}>cortexops eval run --dataset golden_v1.yaml</div>
                    </div>
                  )}
                  {evals.map((run, i) => (
                    <div key={run.run_id} style={{ padding: "12px 16px", borderBottom: `0.5px solid ${C.border}`, animation: `slideIn .2s ease ${i * .04}s both` }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                        <Dot status={run.status || "completed"} />
                        <span style={{ fontFamily: C.mono, fontSize: 11, color: C.textMuted }}>{run.run_id?.slice(0, 8)}</span>
                        <div style={{ flex: 1, height: 6, background: C.surface, borderRadius: 3, overflow: "hidden" }}>
                          <div style={{ width: `${(run.task_completion_rate || 0) * 100}%`, height: "100%", background: run.task_completion_rate >= .9 ? C.teal : run.task_completion_rate >= .7 ? C.amber : C.red, borderRadius: 3 }} />
                        </div>
                        <span style={{ fontFamily: C.mono, fontSize: 12, color: C.teal }}>{((run.task_completion_rate || 0) * 100).toFixed(0)}%</span>
                        <span style={{ fontSize: 11, color: C.textMuted }}>{run.passed}/{run.total_cases} pass</span>
                        {run.regressions > 0 && <span style={{ fontSize: 9, background: C.redDim, color: C.red, padding: "2px 6px", borderRadius: 3, fontFamily: C.mono }}>{run.regressions} regression</span>}
                      </div>
                      <div style={{ display: "flex", gap: 16, paddingLeft: 16 }}>
                        {[["Tool accuracy", `${(run.tool_accuracy || 0).toFixed(0)}/100`], ["P95", `${Math.round(run.latency_p95_ms || 0)}ms`], ["Cases", `${run.total_cases}`]].map(([l, v]) => (
                          <span key={l} style={{ fontSize: 11, color: C.textMuted }}>{l}: <span style={{ color: C.text, fontFamily: C.mono }}>{v}</span></span>
                        ))}
                      </div>
                    </div>
                  ))}
                </>
              )}

              {tab === "errors" && (
                <>
                  {traces.filter(t => t.status === "failed").length === 0 && (
                    <div style={{ padding: "40px 20px", textAlign: "center" }}>
                      <div style={{ color: C.teal, fontSize: 14, fontWeight: 600, marginBottom: 4 }}>No errors</div>
                      <div style={{ color: C.textMuted, fontSize: 12 }}>All traces healthy</div>
                    </div>
                  )}
                  {traces.filter(t => t.status === "failed").map((t, i) => (
                    <div key={t.trace_id} onClick={() => setSelected(t)}
                      style={{ padding: "11px 16px", borderBottom: `0.5px solid ${C.border}`, borderLeft: `3px solid ${C.red}`, cursor: "pointer", animation: `slideIn .2s ease ${i * .04}s both`, transition: "background .1s" }}
                      onMouseEnter={e => e.currentTarget.style.background = C.surface}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                        <span style={{ fontFamily: C.mono, fontSize: 11, color: C.textMuted }}>{t.trace_id?.slice(0, 8)}</span>
                        <span style={{ flex: 1, fontSize: 12, color: C.text }}>{t.case_id || "live trace"}</span>
                        <span style={{ fontSize: 9, background: C.redDim, color: C.red, padding: "2px 6px", borderRadius: 3, fontFamily: C.mono }}>{t.failure_kind?.replace("FailureKind.", "") || "UNKNOWN"}</span>
                      </div>
                      {t.failure_detail && <div style={{ fontSize: 11, color: C.textMuted, fontFamily: C.mono, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", paddingLeft: 0 }}>{t.failure_detail}</div>}
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Right stats panel */}
          <div style={{ width: 210, borderLeft: `1px solid ${C.border}`, background: C.surface, padding: "14px 12px", flexShrink: 0, overflow: "auto", display: "flex", flexDirection: "column", gap: 18 }}>
            <div>
              <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 8 }}>Health</div>
              {[
                ["Success rate", traces.length > 0 ? `${(((traces.length - failed) / traces.length) * 100).toFixed(1)}%` : "—", failed / traces.length < .05],
                ["Eval gate", latest ? (latest.task_completion_rate >= .9 ? "Passing" : "Failing") : "—", latest?.task_completion_rate >= .9],
                ["Regressions", latest?.regressions ?? "—", !latest?.regressions],
              ].map(([l, v, ok]) => (
                <div key={l} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "5px 0", borderBottom: `0.5px solid ${C.border}` }}>
                  <span style={{ fontSize: 11, color: C.textMuted }}>{l}</span>
                  <span style={{ fontSize: 12, fontFamily: C.mono, color: ok ? C.teal : C.red, fontWeight: 500 }}>{String(v)}</span>
                </div>
              ))}
            </div>

            <div>
              <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 8 }}>Failures</div>
              {["TIMEOUT", "HALLUCINATION", "TOOL_CALL_MISMATCH", "OUTPUT_FORMAT", "UNKNOWN"].map(k => {
                const n = traces.filter(t => t.failure_kind?.includes(k)).length;
                if (!n) return null;
                return (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
                    <span style={{ fontSize: 10, color: C.textMuted, fontFamily: C.mono }}>{k.slice(0, 13)}</span>
                    <span style={{ fontSize: 11, color: C.red, fontWeight: 600 }}>{n}</span>
                  </div>
                );
              })}
              {!traces.some(t => t.failure_kind) && <div style={{ fontSize: 11, color: C.textDim }}>No failures</div>}
            </div>

            <div>
              <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 8 }}>Latency dist.</div>
              {[["< 200ms", t => t.total_latency_ms < 200], ["200–500ms", t => t.total_latency_ms >= 200 && t.total_latency_ms < 500], ["500ms–1s", t => t.total_latency_ms >= 500 && t.total_latency_ms < 1000], ["> 1s", t => t.total_latency_ms >= 1000]].map(([l, fn]) => {
                const n = traces.filter(fn).length;
                const pct = traces.length > 0 ? (n / traces.length) * 100 : 0;
                const c = l === "> 1s" ? C.red : l === "500ms–1s" ? C.amber : C.teal;
                return (
                  <div key={l} style={{ marginBottom: 7 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                      <span style={{ fontSize: 10, color: C.textMuted }}>{l}</span>
                      <span style={{ fontSize: 10, fontFamily: C.mono, color: C.textMuted }}>{n}</span>
                    </div>
                    <div style={{ height: 4, background: C.border, borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ width: `${pct}%`, height: "100%", background: c, borderRadius: 2 }} />
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ marginTop: "auto", paddingTop: 10, borderTop: `0.5px solid ${C.border}` }}>
              <div style={{ fontSize: 10, color: C.textDim, fontFamily: C.mono }}>{API.replace("https://", "")}</div>
              <div style={{ fontSize: 10, color: C.textDim, marginTop: 2 }}>{project}</div>
            </div>
          </div>
        </div>
      </div>
      {selected && <WaterfallPanel trace={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
