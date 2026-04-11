import { useState, useEffect, useRef, useCallback } from "react";

const API = import.meta.env?.VITE_API_URL || "https://api.getcortexops.com";

const M = {
  blue:"#1A73E8",blueDark:"#1557B0",blueLight:"#E8F0FE",
  green:"#137333",greenLight:"#E6F4EA",
  red:"#C5221F",redLight:"#FCE8E6",
  amber:"#B06000",amberLight:"#FEF3CD",
  gray50:"#FAFAFA",gray100:"#F1F3F4",gray200:"#E8EAED",
  gray300:"#DADCE0",gray400:"#BDC1C6",gray500:"#9AA0A6",
  gray600:"#80868B",gray700:"#5F6368",gray800:"#3C4043",gray900:"#202124",
  white:"#FFFFFF",
  shadow1:"0 1px 2px rgba(60,64,67,.3),0 1px 3px rgba(60,64,67,.15)",
  shadow2:"0 1px 2px rgba(60,64,67,.3),0 2px 6px rgba(60,64,67,.15)",
  mono:"'Roboto Mono','Courier New',monospace",
  sans:"'Google Sans','Segoe UI',Roboto,sans-serif",
};

const G=`
@import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;600;700&family=Roboto+Mono:wght@400;500&family=Roboto:wght@300;400;500&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{background:${M.gray50};color:${M.gray900};font-family:${M.sans};-webkit-font-smoothing:antialiased}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:${M.gray100}}
::-webkit-scrollbar-thumb{background:${M.gray300};border-radius:2px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes slideIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
`;

function useFetch(apiKey,path){
  const[data,setData]=useState(null);const[loading,setLoading]=useState(false);
  const fetch_=useCallback(async()=>{
    if(!apiKey||!path)return;setLoading(true);
    try{const r=await fetch(`${API}${path}`,{headers:{"X-API-Key":apiKey}});if(r.ok)setData(await r.json());}
    finally{setLoading(false);}
  },[apiKey,path]);
  useEffect(()=>{fetch_();},[fetch_]);
  return{data,loading,refetch:fetch_};
}

function Sparkline({values=[],color,h=28}){
  if(values.length<2)return null;
  const max=Math.max(...values,1),min=Math.min(...values),range=max-min||1;
  const pts=values.map((v,i)=>`${(i/(values.length-1))*100},${h-((v-min)/range)*(h-4)-2}`).join(" ");
  const last=pts.split(" ").pop().split(",");
  return(<svg width="100" height={h} style={{display:"block"}}><polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><circle cx={last[0]} cy={last[1]} r="2.5" fill={color}/></svg>);
}

function Tile({label,value,unit,delta,deltaUp,spark,color,loading}){
  return(
    <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:8,padding:"14px 16px",borderTop:`3px solid ${color}`,boxShadow:M.shadow1}}>
      <div style={{fontSize:11,color:M.gray600,fontWeight:500,marginBottom:6,textTransform:"uppercase",letterSpacing:".05em"}}>{label}</div>
      {loading?<div style={{width:60,height:26,background:M.gray100,borderRadius:4}}/>
        :<div style={{fontSize:26,fontWeight:600,color:M.gray900,letterSpacing:"-.02em",marginBottom:4}}>{value??"—"}<span style={{fontSize:12,color:M.gray500,fontWeight:400,marginLeft:2}}>{unit}</span></div>}
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        {delta!==undefined&&<span style={{fontSize:11,color:deltaUp?M.green:M.red,fontWeight:500}}>{deltaUp?"↑":"↓"} {delta}</span>}
        <Sparkline values={spark} color={color}/>
      </div>
    </div>
  );
}

function StatusDot({status}){
  const color={completed:M.green,failed:M.red,running:M.amber}[status]||M.gray500;
  return<span style={{display:"inline-block",width:8,height:8,borderRadius:"50%",background:color,animation:status==="running"?"pulse 1s infinite":"none",flexShrink:0}}/>;
}

function LatencyChip({ms}){
  const c=ms>1000?M.red:ms>500?M.amber:M.green;
  const bg=ms>1000?M.redLight:ms>500?M.amberLight:M.greenLight;
  return<span style={{background:bg,color:c,fontSize:11,fontFamily:M.mono,padding:"2px 7px",borderRadius:4,fontWeight:500}}>{Math.round(ms)}ms</span>;
}

function WaterfallPanel({trace,onClose}){
  const raw=trace.raw_trace||{};const nodes=raw.nodes||[];
  const maxMs=Math.max(...nodes.map(n=>n.latency_ms||0),trace.total_latency_ms||1);
  return(
    <div style={{position:"fixed",top:0,right:0,bottom:0,width:520,background:M.white,borderLeft:`1px solid ${M.gray200}`,zIndex:100,display:"flex",flexDirection:"column",boxShadow:"-2px 0 8px rgba(60,64,67,.15)",animation:"slideIn .2s ease"}}>
      <div style={{padding:"14px 20px",borderBottom:`1px solid ${M.gray200}`,display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div>
          <div style={{fontSize:15,fontWeight:500,color:M.gray900}}>Trace detail</div>
          <div style={{fontSize:11,fontFamily:M.mono,color:M.gray500,marginTop:2}}>{trace.trace_id}</div>
        </div>
        <button onClick={onClose} style={{background:M.gray100,border:"none",borderRadius:"50%",width:32,height:32,cursor:"pointer",fontSize:18,color:M.gray600,display:"flex",alignItems:"center",justifyContent:"center"}}>×</button>
      </div>
      <div style={{flex:1,overflow:"auto",padding:"16px 20px"}}>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:20}}>
          {[["Status",trace.status,trace.status==="completed"?M.green:M.red,trace.status==="completed"?M.greenLight:M.redLight],
            ["Latency",`${Math.round(trace.total_latency_ms||0)}ms`,M.amber,M.amberLight],
            ["Environment",trace.environment||"—",M.blue,M.blueLight],
            ["Failure",trace.failure_kind||"none",trace.failure_kind?M.red:M.gray600,trace.failure_kind?M.redLight:M.gray100]
          ].map(([l,v,c,bg])=>(
            <div key={l} style={{background:bg,borderRadius:8,padding:"10px 12px",border:`1px solid ${M.gray200}`}}>
              <div style={{fontSize:10,color:M.gray600,textTransform:"uppercase",letterSpacing:".06em",marginBottom:3,fontWeight:500}}>{l}</div>
              <div style={{fontSize:13,fontFamily:M.mono,color:c,fontWeight:500}}>{v}</div>
            </div>
          ))}
        </div>
        {nodes.length>0&&(
          <div style={{marginBottom:20}}>
            <div style={{fontSize:11,color:M.gray600,textTransform:"uppercase",letterSpacing:".07em",marginBottom:10,fontWeight:600}}>Node waterfall</div>
            {nodes.map((n,i)=>{
              const w=Math.max(2,(n.latency_ms/maxMs)*100);
              const c=n.latency_ms>1000?M.red:n.latency_ms>500?M.amber:M.blue;
              const bg=n.latency_ms>1000?M.redLight:n.latency_ms>500?M.amberLight:M.blueLight;
              return(
                <div key={i} style={{display:"flex",alignItems:"center",gap:10,padding:"6px 0",borderBottom:`1px solid ${M.gray200}`}}>
                  <div style={{width:130,fontSize:12,color:M.gray700,fontFamily:M.mono,whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis"}}>{n.node_name||"node"}</div>
                  <div style={{flex:1,height:18,background:M.gray100,borderRadius:4,overflow:"hidden"}}>
                    <div style={{width:`${w}%`,height:"100%",background:c,borderRadius:4,opacity:.7}}/>
                  </div>
                  <div style={{width:55,fontSize:12,fontFamily:M.mono,color:c,textAlign:"right",fontWeight:500}}>{Math.round(n.latency_ms)}ms</div>
                  {n.tool_calls?.slice(0,2).map((tc,j)=>(
                    <span key={j} style={{fontSize:10,background:bg,color:c,padding:"2px 6px",borderRadius:4,fontFamily:M.mono}}>{tc.name?.slice(0,8)}</span>
                  ))}
                </div>
              );
            })}
          </div>
        )}
        {raw.output&&(
          <div style={{marginBottom:16}}>
            <div style={{fontSize:11,color:M.gray600,textTransform:"uppercase",letterSpacing:".07em",marginBottom:8,fontWeight:600}}>Output</div>
            <div style={{background:M.gray50,borderRadius:8,padding:12,border:`1px solid ${M.gray200}`,borderLeft:`4px solid ${M.blue}`,fontFamily:M.mono,fontSize:12,color:M.gray900,whiteSpace:"pre-wrap",wordBreak:"break-all",maxHeight:180,overflow:"auto"}}>
              {JSON.stringify(raw.output,null,2)}
            </div>
          </div>
        )}
        {trace.failure_detail&&(
          <div>
            <div style={{fontSize:11,color:M.gray600,textTransform:"uppercase",letterSpacing:".07em",marginBottom:8,fontWeight:600}}>Failure detail</div>
            <div style={{background:M.redLight,borderRadius:8,padding:12,border:"1px solid rgba(197,34,31,.2)",fontFamily:M.mono,fontSize:12,color:M.red}}>{trace.failure_detail}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function LoginScreen({onLogin}){
  const[key,setKey]=useState("");const[proj,setProj]=useState("payments-agent");
  const[err,setErr]=useState("");const[loading,setLoading]=useState(false);
  const submit=async()=>{
    if(!key.startsWith("cxo-")){setErr("Key must start with cxo-");return;}
    setLoading(true);
    try{const r=await fetch(`${API}/health`);if(!r.ok)throw new Error();onLogin(key,proj);}
    catch{setErr("Cannot reach api.getcortexops.com");}
    finally{setLoading(false);}
  };
  return(
    <div style={{minHeight:"100vh",background:M.gray50,display:"flex",alignItems:"center",justifyContent:"center",padding:20}}>
      <div style={{background:M.white,borderRadius:8,padding:"36px 40px",width:"100%",maxWidth:420,boxShadow:M.shadow2}}>
        <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:32}}>
          <div style={{width:36,height:36,background:M.blue,borderRadius:8,display:"flex",alignItems:"center",justifyContent:"center"}}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M10 2.5 Q14 10 10 17.5" stroke="white" strokeWidth="1.8" strokeLinecap="round"/>
              <path d="M6 2.5 Q10.5 10 6 17.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" opacity=".4"/>
              <circle cx="10" cy="2.5" r="1.8" fill="white"/>
              <circle cx="10" cy="17.5" r="1.8" fill="white"/>
            </svg>
          </div>
          <div>
            <div style={{fontSize:18,fontWeight:600,color:M.gray900}}>CortexOps</div>
            <div style={{fontSize:12,color:M.gray600}}>Agent observability</div>
          </div>
        </div>
        {[["API Key",key,setKey,"cxo-...","password"],["Project",proj,setProj,"payments-agent","text"]].map(([l,v,s,p,t])=>(
          <div key={l} style={{marginBottom:16}}>
            <label style={{display:"block",fontSize:12,fontWeight:500,color:M.gray700,marginBottom:6}}>{l}</label>
            <input value={v} onChange={e=>s(e.target.value)} placeholder={p} type={t}
              onKeyDown={e=>e.key==="Enter"&&submit()}
              style={{width:"100%",background:M.white,border:`1px solid ${M.gray300}`,borderRadius:4,color:M.gray900,fontSize:14,padding:"10px 12px",outline:"none",fontFamily:t==="password"?M.mono:"inherit",transition:"border-color .15s"}}
              onFocus={e=>e.target.style.borderColor=M.blue}
              onBlur={e=>e.target.style.borderColor=M.gray300}
            />
          </div>
        ))}
        {err&&<div style={{background:M.redLight,color:M.red,fontSize:13,padding:"8px 12px",borderRadius:4,marginBottom:16,border:"1px solid rgba(197,34,31,.2)"}}>{err}</div>}
        <button onClick={submit} disabled={loading||!key}
          style={{width:"100%",background:M.blue,color:"white",border:"none",borderRadius:4,padding:12,fontSize:15,fontWeight:500,cursor:loading||!key?"not-allowed":"pointer",opacity:loading||!key?.5:1,boxShadow:M.shadow1}}>
          {loading?"Connecting…":"Open dashboard →"}
        </button>
        <p style={{color:M.gray500,fontSize:12,marginTop:16,textAlign:"center"}}>
          <a href="https://getcortexops.com" style={{color:M.blue}}>getcortexops.com</a>
          {" · "}
          <a href="https://getcortexops.com/?trial=1" style={{color:M.blue}}>Get Pro key</a>
        </p>
      </div>
    </div>
  );
}

export default function App(){
  const[apiKey,setApiKey]=useState(()=>localStorage.getItem("cxo_key")||"");
  const[project,setProject]=useState(()=>localStorage.getItem("cxo_project")||"payments-agent");
  const[tab,setTab]=useState("traces");
  const[filter,setFilter]=useState("all");
  const[live,setLive]=useState(true);
  const[selected,setSelected]=useState(null);
  const ref=useRef(null);

  const tPath=apiKey?`/v1/traces?project=${encodeURIComponent(project)}&limit=100${filter!=="all"?`&status=${filter}`:""}`:null;
  const ePath=apiKey?`/v1/evals?project=${encodeURIComponent(project)}&limit=20`:null;

  const{data:rawTraces,loading:tLoad,refetch:rT}=useFetch(apiKey,tPath);
  const{data:rawEvals,loading:eLoad,refetch:rE}=useFetch(apiKey,ePath);

  useEffect(()=>{
    if(live&&apiKey){ref.current=setInterval(()=>{rT();rE();},5000);}
    return()=>clearInterval(ref.current);
  },[live,apiKey,rT,rE]);

  useEffect(()=>{if(project)localStorage.setItem("cxo_project",project);},[project]);

  const login=(k,p)=>{setApiKey(k);setProject(p);localStorage.setItem("cxo_key",k);localStorage.setItem("cxo_project",p);};
  const logout=()=>{setApiKey("");localStorage.removeItem("cxo_key");};

  if(!apiKey)return<><style>{G}</style><LoginScreen onLogin={login}/></>;

  const traces=Array.isArray(rawTraces)?rawTraces:[];
  const evals=Array.isArray(rawEvals)?rawEvals:[];
  const latest=evals[0];const prev=evals[1];
  const failed=traces.filter(t=>t.status==="failed").length;
  const errRate=traces.length>0?((failed/traces.length)*100).toFixed(1):"0.0";
  const avgLat=traces.length>0?Math.round(traces.reduce((s,t)=>s+(t.total_latency_ms||0),0)/traces.length):0;
  const sorted=[...traces].sort((a,b)=>b.total_latency_ms-a.total_latency_ms);
  const p95=sorted.length>0?Math.round(sorted[Math.floor(sorted.length*0.05)]?.total_latency_ms||0):0;
  const tcColor=avgLat>1000?M.red:avgLat>500?M.amber:M.green;

  return(
    <>
      <style>{G}</style>
      <div style={{display:"flex",flexDirection:"column",height:"100vh",background:M.gray50}}>
        {/* Top app bar */}
        <div style={{background:M.blue,height:56,display:"flex",alignItems:"center",padding:"0 20px",gap:14,flexShrink:0,boxShadow:"0 2px 4px rgba(0,0,0,.2)"}}>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <div style={{width:24,height:24,background:"white",borderRadius:5,display:"flex",alignItems:"center",justifyContent:"center"}}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 1.5 Q10.5 7 7 12.5" stroke={M.blue} strokeWidth="1.5" strokeLinecap="round"/>
                <path d="M4 1.5 Q8 7 4 12.5" stroke={M.blue} strokeWidth="1.5" strokeLinecap="round" opacity=".4"/>
                <circle cx="7" cy="1.5" r="1.3" fill={M.blue}/><circle cx="7" cy="12.5" r="1.3" fill={M.blue}/>
              </svg>
            </div>
            <span style={{fontSize:16,fontWeight:500,color:"white"}}>CortexOps</span>
          </div>
          <div style={{width:1,height:20,background:"rgba(255,255,255,.3)"}}/>
          <input value={project} onChange={e=>setProject(e.target.value)}
            style={{background:"rgba(255,255,255,.15)",border:"1px solid rgba(255,255,255,.25)",borderRadius:4,color:"white",fontSize:13,padding:"4px 10px",width:150,fontFamily:M.mono,outline:"none"}}/>
          <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:12}}>
            <div onClick={()=>setLive(l=>!l)} style={{display:"flex",alignItems:"center",gap:6,cursor:"pointer"}}>
              <div style={{width:8,height:8,borderRadius:"50%",background:live?"#34A853":"rgba(255,255,255,.4)",animation:live?"pulse 1.5s infinite":"none"}}/>
              <span style={{fontSize:12,color:live?"#34A853":"rgba(255,255,255,.6)",fontWeight:500}}>{live?"Live · 5s":"Paused"}</span>
            </div>
            <button onClick={()=>{rT();rE();}} style={{background:"rgba(255,255,255,.15)",border:"1px solid rgba(255,255,255,.25)",borderRadius:4,color:"white",fontSize:13,padding:"4px 10px",cursor:"pointer"}}>↻</button>
            <button onClick={logout} style={{background:"none",border:"none",color:"rgba(255,255,255,.7)",fontSize:13,cursor:"pointer"}}>Sign out</button>
          </div>
        </div>

        {/* Metric tiles */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(5,minmax(0,1fr))",gap:12,padding:"16px 20px",flexShrink:0}}>
          <Tile label="Task completion" value={latest?`${(latest.task_completion_rate*100).toFixed(1)}`:"—"} unit="%" color={M.green}
            spark={evals.slice(0,10).reverse().map(e=>(e.task_completion_rate||0)*100)} loading={eLoad}
            delta={prev?`${Math.abs((latest.task_completion_rate-prev.task_completion_rate)*100).toFixed(1)}%`:undefined}
            deltaUp={prev&&latest.task_completion_rate>=prev.task_completion_rate}/>
          <Tile label="Error rate" value={errRate} unit="%" color={parseFloat(errRate)>5?M.red:M.green} spark={traces.slice(0,20).reverse().map(t=>t.status==="failed"?100:0)} loading={tLoad}/>
          <Tile label="Avg latency" value={avgLat} unit="ms" color={tcColor} spark={traces.slice(0,20).reverse().map(t=>t.total_latency_ms||0)} loading={tLoad}/>
          <Tile label="P95 latency" value={p95} unit="ms" color={p95>2000?M.red:p95>1000?M.amber:M.blue} spark={traces.slice(0,20).reverse().map(t=>t.total_latency_ms||0)} loading={tLoad}/>
          <Tile label="Total traces" value={traces.length} color={M.blue} spark={traces.slice(0,20).map(()=>1)} loading={tLoad}/>
        </div>

        <div style={{display:"flex",flex:1,overflow:"hidden"}}>
          <div style={{flex:1,display:"flex",flexDirection:"column",overflow:"hidden",background:M.white,borderTop:`1px solid ${M.gray200}`}}>
            {/* Tabs */}
            <div style={{display:"flex",alignItems:"center",padding:"0 20px",height:48,borderBottom:`1px solid ${M.gray200}`,gap:4}}>
              {["traces","evals","errors"].map(t=>(
                <button key={t} onClick={()=>setTab(t)}
                  style={{background:tab===t?M.blueLight:"transparent",color:tab===t?M.blue:M.gray600,border:"none",borderRadius:4,padding:"6px 16px",fontSize:14,fontWeight:tab===t?600:400,cursor:"pointer",fontFamily:M.sans}}>
                  {t.charAt(0).toUpperCase()+t.slice(1)}
                  {t==="errors"&&failed>0&&<span style={{marginLeft:6,background:M.red,color:"white",borderRadius:99,fontSize:10,padding:"1px 6px",fontWeight:600}}>{failed}</span>}
                </button>
              ))}
              {tab==="traces"&&(
                <div style={{marginLeft:"auto",display:"flex",gap:4}}>
                  {["all","completed","failed"].map(s=>(
                    <button key={s} onClick={()=>setFilter(s)}
                      style={{background:filter===s?M.blueLight:"transparent",border:`1px solid ${filter===s?M.blue:M.gray300}`,borderRadius:4,color:filter===s?M.blue:M.gray600,fontSize:12,padding:"4px 12px",cursor:"pointer",fontFamily:M.sans}}>{s}</button>
                  ))}
                </div>
              )}
            </div>
            {/* Column headers */}
            {tab==="traces"&&(
              <div style={{display:"flex",alignItems:"center",gap:12,padding:"6px 20px",borderBottom:`1px solid ${M.gray200}`,background:M.gray50}}>
                {["","ID","Case","Latency","Failure","Time"].map((h,i)=>(
                  <span key={i} style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".06em",fontWeight:600,minWidth:i===0?8:i===1?64:i===3?70:i===4?100:i===5?80:undefined,flex:i===2?1:undefined}}>{h}</span>
                ))}
              </div>
            )}
            {/* Lists */}
            <div style={{flex:1,overflow:"auto"}}>
              {tab==="traces"&&(
                <>
                  {traces.length===0&&!tLoad&&<div style={{padding:"48px 20px",textAlign:"center",color:M.gray600}}><div style={{fontSize:15,marginBottom:8}}>No traces yet</div><div style={{fontFamily:M.mono,fontSize:13,color:M.gray500}}>pip install cortexops</div></div>}
                  {traces.map((t,i)=>(
                    <div key={t.trace_id} onClick={()=>setSelected(t)}
                      style={{display:"flex",alignItems:"center",gap:12,padding:"10px 20px",borderBottom:`1px solid ${M.gray200}`,cursor:"pointer",animation:`slideIn .15s ease ${Math.min(i,8)*.03}s both`,transition:"background .1s"}}
                      onMouseEnter={e=>e.currentTarget.style.background=M.gray50}
                      onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                      <StatusDot status={t.status}/>
                      <span style={{fontFamily:M.mono,fontSize:12,color:M.gray500,minWidth:64}}>{t.trace_id?.slice(0,8)}</span>
                      <span style={{flex:1,fontSize:14,color:M.gray900}}>{t.case_id||"live trace"}</span>
                      <LatencyChip ms={t.total_latency_ms||0}/>
                      <span style={{minWidth:100,fontSize:12}}>
                        {t.failure_kind?<span style={{background:M.redLight,color:M.red,padding:"2px 8px",borderRadius:4,fontFamily:M.mono,fontSize:11}}>{t.failure_kind.replace("FailureKind.","")}</span>:<span style={{color:M.gray400}}>—</span>}
                      </span>
                      <span style={{fontSize:12,color:M.gray500,minWidth:80,textAlign:"right"}}>{t.created_at?new Date(t.created_at).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"}):""}</span>
                    </div>
                  ))}
                </>
              )}
              {tab==="evals"&&(
                <>
                  {evals.length===0&&!eLoad&&<div style={{padding:"48px 20px",textAlign:"center",color:M.gray600}}><div style={{fontSize:15,marginBottom:8}}>No eval runs yet</div><div style={{fontFamily:M.mono,fontSize:13,color:M.gray500}}>cortexops eval run --dataset golden_v1.yaml</div></div>}
                  {evals.map((run,i)=>(
                    <div key={run.run_id} style={{padding:"14px 20px",borderBottom:`1px solid ${M.gray200}`,animation:`slideIn .15s ease ${i*.04}s both`}}>
                      <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8}}>
                        <StatusDot status={run.status||"completed"}/>
                        <span style={{fontFamily:M.mono,fontSize:12,color:M.gray500}}>{run.run_id?.slice(0,8)}</span>
                        <div style={{flex:1,height:6,background:M.gray200,borderRadius:3,overflow:"hidden"}}>
                          <div style={{width:`${(run.task_completion_rate||0)*100}%`,height:"100%",background:run.task_completion_rate>=.9?M.green:run.task_completion_rate>=.7?M.amber:M.red,borderRadius:3}}/>
                        </div>
                        <span style={{fontFamily:M.mono,fontSize:13,color:M.green,fontWeight:600}}>{((run.task_completion_rate||0)*100).toFixed(0)}%</span>
                        <span style={{fontSize:13,color:M.gray600}}>{run.passed}/{run.total_cases} pass</span>
                        {run.regressions>0&&<span style={{fontSize:11,background:M.redLight,color:M.red,padding:"2px 8px",borderRadius:4}}>{run.regressions} regression</span>}
                      </div>
                      <div style={{display:"flex",gap:20,paddingLeft:18}}>
                        {[["Tool accuracy",`${(run.tool_accuracy||0).toFixed(0)}/100`],["P95",`${Math.round(run.latency_p95_ms||0)}ms`],["Cases",`${run.total_cases}`]].map(([l,v])=>(
                          <span key={l} style={{fontSize:12,color:M.gray600}}>{l}: <span style={{color:M.gray900,fontFamily:M.mono}}>{v}</span></span>
                        ))}
                      </div>
                    </div>
                  ))}
                </>
              )}
              {tab==="errors"&&(
                <>
                  {traces.filter(t=>t.status==="failed").length===0&&<div style={{padding:"48px 20px",textAlign:"center"}}><div style={{fontSize:15,fontWeight:500,color:M.green,marginBottom:6}}>No errors</div><div style={{fontSize:13,color:M.gray600}}>All traces healthy</div></div>}
                  {traces.filter(t=>t.status==="failed").map((t,i)=>(
                    <div key={t.trace_id} onClick={()=>setSelected(t)}
                      style={{padding:"12px 20px",borderBottom:`1px solid ${M.gray200}`,borderLeft:`4px solid ${M.red}`,cursor:"pointer",transition:"background .1s"}}
                      onMouseEnter={e=>e.currentTarget.style.background=M.redLight}
                      onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                      <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:4}}>
                        <span style={{fontFamily:M.mono,fontSize:12,color:M.gray500}}>{t.trace_id?.slice(0,8)}</span>
                        <span style={{flex:1,fontSize:14,color:M.gray900}}>{t.case_id||"live trace"}</span>
                        <span style={{fontSize:11,background:M.redLight,color:M.red,padding:"2px 8px",borderRadius:4,fontFamily:M.mono}}>{t.failure_kind?.replace("FailureKind.","")||"UNKNOWN"}</span>
                      </div>
                      {t.failure_detail&&<div style={{fontSize:12,color:M.gray600,whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis"}}>{t.failure_detail}</div>}
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Right sidebar */}
          <div style={{width:220,borderLeft:`1px solid ${M.gray200}`,background:M.white,padding:"16px 14px",flexShrink:0,overflow:"auto",display:"flex",flexDirection:"column",gap:20}}>
            <div>
              <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".08em",fontWeight:600,marginBottom:10}}>Health</div>
              {[["Success rate",traces.length>0?`${(((traces.length-failed)/traces.length)*100).toFixed(1)}%`:"—",failed/traces.length<.05],
                ["Eval gate",latest?(latest.task_completion_rate>=.9?"Passing":"Failing"):"—",latest?.task_completion_rate>=.9],
                ["Regressions",latest?.regressions??"—",!latest?.regressions]
              ].map(([l,v,ok])=>(
                <div key={l} style={{display:"flex",alignItems:"center",justifyContent:"space-between",padding:"6px 0",borderBottom:`1px solid ${M.gray200}`}}>
                  <span style={{fontSize:12,color:M.gray600}}>{l}</span>
                  <span style={{fontSize:13,fontFamily:M.mono,color:ok?M.green:M.red,fontWeight:600}}>{String(v)}</span>
                </div>
              ))}
            </div>
            <div>
              <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".08em",fontWeight:600,marginBottom:10}}>Failures</div>
              {["TIMEOUT","HALLUCINATION","TOOL_CALL_MISMATCH","OUTPUT_FORMAT","UNKNOWN"].map(k=>{
                const n=traces.filter(t=>t.failure_kind?.includes(k)).length;
                if(!n)return null;
                return(<div key={k} style={{display:"flex",justifyContent:"space-between",padding:"4px 0"}}><span style={{fontSize:11,color:M.gray600,fontFamily:M.mono}}>{k.slice(0,13)}</span><span style={{fontSize:12,color:M.red,fontWeight:600}}>{n}</span></div>);
              })}
              {!traces.some(t=>t.failure_kind)&&<div style={{fontSize:12,color:M.gray400}}>No failures</div>}
            </div>
            <div>
              <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".08em",fontWeight:600,marginBottom:10}}>Latency dist.</div>
              {[["<200ms",t=>t.total_latency_ms<200],["200–500ms",t=>t.total_latency_ms>=200&&t.total_latency_ms<500],["500ms–1s",t=>t.total_latency_ms>=500&&t.total_latency_ms<1000],[">1s",t=>t.total_latency_ms>=1000]].map(([l,fn])=>{
                const n=traces.filter(fn).length;
                const pct=traces.length>0?(n/traces.length)*100:0;
                const c=l===">1s"?M.red:l==="500ms–1s"?M.amber:M.green;
                return(<div key={l} style={{marginBottom:8}}>
                  <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                    <span style={{fontSize:11,color:M.gray600}}>{l}</span>
                    <span style={{fontSize:11,fontFamily:M.mono,color:M.gray600}}>{n}</span>
                  </div>
                  <div style={{height:4,background:M.gray200,borderRadius:2,overflow:"hidden"}}>
                    <div style={{width:`${pct}%`,height:"100%",background:c,borderRadius:2}}/>
                  </div>
                </div>);
              })}
            </div>
            <div style={{marginTop:"auto",paddingTop:12,borderTop:`1px solid ${M.gray200}`}}>
              <div style={{fontSize:11,color:M.gray500,fontFamily:M.mono}}>{API.replace("https://","")}</div>
              <div style={{fontSize:11,color:M.gray500,marginTop:2}}>{project}</div>
            </div>
          </div>
        </div>
      </div>
      {selected&&<WaterfallPanel trace={selected} onClose={()=>setSelected(null)}/>}
    </>
  );
}