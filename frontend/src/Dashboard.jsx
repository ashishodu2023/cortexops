import { useState, useEffect } from "react";

const API = "http://localhost:8000";
const API_KEY = "dev_internal_key";

const headers = { "X-API-Key": API_KEY, "Content-Type": "application/json" };

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
    <span style={{ ...cfg, fontSize: 10, fontWeight: 500, padding: "2px 8px", borderRadius: 99 }}>
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

function NavBar({ project, setProject }) {
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
          placeholder="payments-agent"
        />
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [project, setProject] = useState("payments-agent");
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState("overview");

  useEffect(() => {
    if (!project) return;
    setLoading(true);
    fetch(`${API}/v1/evals?project=${encodeURIComponent(project)}&limit=20`, { headers })
      .then(r => r.json())
      .then(data => { setRuns(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [project]);

  const latest = runs[0];
  const prev = runs[1];

  const tcDelta = latest && prev
    ? `${Math.abs((latest.task_completion_rate - prev.task_completion_rate) * 100).toFixed(1)}%`
    : undefined;
  const tcUp = latest && prev && latest.task_completion_rate >= prev.task_completion_rate;

  return (
    <div style={{ minHeight: "100vh", background: "#F4F3FB", fontFamily: "system-ui, sans-serif" }}>
      <NavBar project={project} setProject={setProject} />

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px" }}>

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
        </div>

        {view === "overview" && (
          <>
            {latest && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 10, marginBottom: 20 }}>
                <MetricCard
                  label="Task completion"
                  value={`${(latest.task_completion_rate * 100).toFixed(1)}%`}
                  delta={tcDelta} deltaUp={tcUp}
                />
                <MetricCard label="Tool accuracy" value={`${latest.tool_accuracy.toFixed(1)}`} />
                <MetricCard label="Latency p95" value={`${Math.round(latest.latency_p95_ms)}ms`} />
                <MetricCard
                  label="Regressions"
                  value={latest.regressions}
                  delta={latest.regressions > 0 ? `${latest.regressions} new` : undefined}
                  deltaUp={false}
                />
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
                  No runs found. Run <code>cortexops eval run --project {project}</code> to get started.
                </div>
              )}
              {runs.map((run, i) => (
                <div
                  key={run.run_id}
                  onClick={() => setSelected(selected?.run_id === run.run_id ? null : run)}
                  style={{
                    padding: "12px 18px", borderBottom: "0.5px solid #F0EFF8", cursor: "pointer",
                    background: selected?.run_id === run.run_id ? "#F8F8FF" : i === 0 ? "#FDFCFF" : "white",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <code style={{ fontSize: 11, color: GRAY, minWidth: 72 }}>{run.run_id.slice(0, 8)}</code>
                    <StatusBadge status={run.status} />
                    <div style={{ flex: 1 }}>
                      <ScoreBar score={run.task_completion_rate * 100} />
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
                          <div style={{ width: 120 }}><ScoreBar score={cr.score} /></div>
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
          <div style={{ background: "white", borderRadius: 12, border: "0.5px solid #E0DFF0", padding: 20 }}>
            <p style={{ color: GRAY, fontSize: 13, margin: 0 }}>
              Trace viewer coming soon. Traces are ingested via <code>POST /v1/traces</code> from the SDK and stored per-project.
            </p>
          </div>
        )}

        {view === "prompts" && (
          <div style={{ background: "white", borderRadius: 12, border: "0.5px solid #E0DFF0", padding: 20 }}>
            <p style={{ color: GRAY, fontSize: 13, margin: 0 }}>
              Prompt version history available at <code>GET /v1/prompts?project={project}&prompt_name=system_prompt</code>.
              Diffs available at <code>GET /v1/prompts/diff</code>.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
