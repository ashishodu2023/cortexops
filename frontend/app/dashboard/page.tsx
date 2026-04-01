
"use client";
import { useEffect, useState } from "react";
import axios from "axios";

export default function Dashboard() {
  const [metrics, setMetrics] = useState([]);
  const [traces, setTraces] = useState([]);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    axios.get("http://localhost:8000/metrics").then(r => setMetrics(r.data));
    axios.get("http://localhost:8000/traces").then(r => setTraces(r.data));
  }, []);

  return (
    <div style={{display:"flex", height:"100vh"}}>
      <div style={{width:240, background:"#000", color:"#fff", padding:16}}>
        <h2>CortexOps</h2>
      </div>
      <div style={{flex:1, padding:16}}>
        <h3>Metrics</h3>
        <div style={{display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:12}}>
          {metrics.map((m, i) => (
            <div key={i} style={{background:"#111", color:"#fff", padding:12}}>
              {m.metric}: {m.value}
            </div>
          ))}
        </div>

        <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:12, marginTop:20}}>
          <div style={{background:"#222", color:"#fff", padding:12}}>
            <h3>Traces</h3>
            {traces.map((t, i) => (
              <div key={i} onClick={() => setSelected(t)} style={{cursor:"pointer", borderBottom:"1px solid #333", padding:8}}>
                {t.prompt?.slice(0,40)}...
              </div>
            ))}
          </div>
          <div style={{background:"#111", color:"#fff", padding:12}}>
            {selected && (
              <>
                <h3>Prompt</h3>
                <pre>{selected.prompt}</pre>
                <h3>Response</h3>
                <pre>{selected.response}</pre>
                {selected.error && <p style={{color:"red"}}>{selected.error}</p>}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
