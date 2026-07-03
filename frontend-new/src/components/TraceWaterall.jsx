import { useState } from "react";

/**
 * TraceWaterfall — visualizes an agent run as a horizontal timeline
 * of nodes and tool calls, ordered by start time and sized by duration.
 *
 * This is the view that distinguishes agent-execution tracing from
 * flat LLM-call logs: you see the shape of the run, which node was
 * slow, and where a failure happened in the execution path.
 *
 * Drop this into the CortexOps dashboard trace detail page.
 */

// ── Sample trace data (replace with API response from GET /v1/traces/:id) ──
const SAMPLE_TRACE = {
  trace_id: "tr_9f2a1c8b",
  project: "meridian-refund-agent",
  status: "failed",
  total_latency_ms: 4287,
  input: { message: "I want a refund for order #4821" },
  spans: [
    { id: "s1", name: "classify_intent",     type: "node", start_ms: 0,    duration_ms: 1180, status: "ok" },
    { id: "s2", name: "llm: gpt-4o",          type: "llm",  start_ms: 120,  duration_ms: 980,  status: "ok", parent: "s1" },
    { id: "s3", name: "check_refund_policy",  type: "node", start_ms: 1180, duration_ms: 890,  status: "ok" },
    { id: "s4", name: "tool: lookup_order",   type: "tool", start_ms: 1240, duration_ms: 310,  status: "ok", parent: "s3" },
    { id: "s5", name: "tool: check_eligibility", type: "tool", start_ms: 1560, duration_ms: 420, status: "ok", parent: "s3" },
    { id: "s6", name: "process_refund",       type: "node", start_ms: 2070, duration_ms: 2100, status: "failed" },
    { id: "s7", name: "tool: issue_refund",   type: "tool", start_ms: 2130, duration_ms: 2010, status: "failed", parent: "s6", error: "PaymentGatewayTimeout: no response after 2000ms" },
    { id: "s8", name: "respond",              type: "node", start_ms: 4180, duration_ms: 107,  status: "skipped" },
  ],
};

const TYPE_STYLES = {
  node: { label: "Node", bar: "#1565C0", track: "#E3F2FD" },
  tool: { label: "Tool", bar: "#7B4F9E", track: "#F0E9F7" },
  llm:  { label: "LLM",  bar: "#0E8A6D", track: "#E3F5EF" },
};

const STATUS_STYLES = {
  ok:      { dot: "#0E8A6D", label: "OK" },
  failed:  { dot: "#D14343", label: "Failed" },
  skipped: { dot: "#9AA0A6", label: "Skipped" },
};

function fmtMs(ms) {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export default function TraceWaterfall({ trace = SAMPLE_TRACE }) {
  const [selected, setSelected] = useState(null);
  const total = trace.total_latency_ms;

  return (
    <div style={{
      fontFamily: "'Inter', -apple-system, system-ui, sans-serif",
      background: "#FFFFFF",
      border: "1px solid #E4E7EB",
      borderRadius: 12,
      overflow: "hidden",
      maxWidth: 900,
    }}>
      {/* Header */}
      <div style={{
        padding: "16px 20px",
        borderBottom: "1px solid #EEF1F4",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 13, fontWeight: 600, color: "#1A1A2E",
            }}>{trace.trace_id}</span>
            <StatusPill status={trace.status} />
          </div>
          <div style={{ fontSize: 12.5, color: "#6B7280", marginTop: 4 }}>
            {trace.project} · {trace.spans.length} spans · {fmtMs(total)} total
          </div>
        </div>
        <TypeLegend />
      </div>

      {/* Time axis */}
      <div style={{ padding: "12px 20px 0", position: "relative" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <span key={f} style={{ fontSize: 10.5, color: "#9AA0A6", fontFamily: "'JetBrains Mono', monospace" }}>
              {fmtMs(total * f)}
            </span>
          ))}
        </div>
      </div>

      {/* Waterfall rows */}
      <div style={{ padding: "4px 20px 16px" }}>
        {trace.spans.map((span) => {
          const leftPct  = (span.start_ms / total) * 100;
          const widthPct = Math.max((span.duration_ms / total) * 100, 1.5);
          const style    = TYPE_STYLES[span.type] || TYPE_STYLES.node;
          const isChild  = Boolean(span.parent);
          const isSel    = selected === span.id;
          const isError  = span.status === "failed";

          return (
            <div
              key={span.id}
              onClick={() => setSelected(isSel ? null : span.id)}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "6px 8px", margin: "1px -8px",
                borderRadius: 8, cursor: "pointer",
                background: isSel ? "#F7F9FB" : "transparent",
                transition: "background 120ms ease",
              }}
            >
              {/* Label */}
              <div style={{
                width: 200, flexShrink: 0,
                paddingLeft: isChild ? 18 : 0,
                display: "flex", alignItems: "center", gap: 7,
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: STATUS_STYLES[span.status]?.dot || "#9AA0A6",
                  flexShrink: 0,
                }} />
                <span style={{
                  fontSize: 12.5,
                  fontWeight: isChild ? 400 : 500,
                  color: isError ? "#D14343" : "#1A1A2E",
                  fontFamily: span.type === "llm" || span.type === "tool"
                    ? "'JetBrains Mono', monospace" : "inherit",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{span.name}</span>
              </div>

              {/* Timeline track */}
              <div style={{ flex: 1, position: "relative", height: 22 }}>
                <div style={{
                  position: "absolute", inset: 0,
                  background: "#F5F7F9", borderRadius: 5,
                }} />
                <div
                  title={`${span.name} — ${fmtMs(span.duration_ms)}`}
                  style={{
                    position: "absolute",
                    left: `${leftPct}%`, width: `${widthPct}%`,
                    top: 3, bottom: 3,
                    background: isError ? "#D14343" : style.bar,
                    borderRadius: 5,
                    opacity: span.status === "skipped" ? 0.35 : 1,
                    display: "flex", alignItems: "center",
                    paddingLeft: 6, minWidth: 3,
                    boxShadow: isSel ? "0 0 0 2px rgba(21,101,192,0.3)" : "none",
                  }}
                >
                  {widthPct > 12 && (
                    <span style={{
                      fontSize: 10.5, fontWeight: 600, color: "#FFFFFF",
                      fontFamily: "'JetBrains Mono', monospace",
                      whiteSpace: "nowrap",
                    }}>{fmtMs(span.duration_ms)}</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected span detail */}
      {selected && (() => {
        const span = trace.spans.find((s) => s.id === selected);
        return (
          <div style={{
            borderTop: "1px solid #EEF1F4",
            padding: "14px 20px",
            background: "#FAFBFC",
            fontSize: 12.5,
          }}>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              <Detail label="Span" value={span.name} mono />
              <Detail label="Type" value={TYPE_STYLES[span.type]?.label || span.type} />
              <Detail label="Start" value={fmtMs(span.start_ms)} mono />
              <Detail label="Duration" value={fmtMs(span.duration_ms)} mono />
              <Detail label="Status" value={STATUS_STYLES[span.status]?.label || span.status} />
            </div>
            {span.error && (
              <div style={{
                marginTop: 12, padding: "10px 12px",
                background: "#FDECEC", border: "1px solid #F5C6C6",
                borderRadius: 8,
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 12, color: "#B02A2A",
              }}>{span.error}</div>
            )}
          </div>
        );
      })()}
    </div>
  );
}

function StatusPill({ status }) {
  const map = {
    ok:      { bg: "#E3F5EF", fg: "#0E8A6D", label: "Completed" },
    failed:  { bg: "#FDECEC", fg: "#D14343", label: "Failed" },
    running: { bg: "#FFF6E5", fg: "#B8860B", label: "Running" },
  };
  const s = map[status] || map.ok;
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: "2px 9px",
      borderRadius: 20, background: s.bg, color: s.fg,
    }}>{s.label}</span>
  );
}

function TypeLegend() {
  return (
    <div style={{ display: "flex", gap: 14 }}>
      {Object.entries(TYPE_STYLES).map(([key, s]) => (
        <div key={key} style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 3, background: s.bar }} />
          <span style={{ fontSize: 11.5, color: "#6B7280" }}>{s.label}</span>
        </div>
      ))}
    </div>
  );
}

function Detail({ label, value, mono }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: "#9AA0A6", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 2 }}>
        {label}
      </div>
      <div style={{
        fontSize: 12.5, color: "#1A1A2E", fontWeight: 500,
        fontFamily: mono ? "'JetBrains Mono', monospace" : "inherit",
      }}>{value}</div>
    </div>
  );
}