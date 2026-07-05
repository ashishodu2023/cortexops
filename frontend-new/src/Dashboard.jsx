import { useState, useEffect, useRef, useCallback } from "react";
import {
  API,
  apiFetch,
  clearSession,
  ensureSession,
  issueToken,
  loadSession,
  saveSession,
} from "./api.js";

const M = {
  blue:"#1A73E8",blueDark:"#1557B0",blueLight:"rgba(26,115,232,.18)",blueSoft:"#60A5FA",
  green:"#2DD4A7",greenLight:"rgba(45,212,167,.12)",
  red:"#F26D6D",redLight:"rgba(242,109,109,.12)",
  amber:"#F5B23D",amberLight:"rgba(245,178,61,.12)",
  gray50:"#0B0F1A",gray100:"#111726",gray200:"rgba(255,255,255,.11)",
  gray300:"rgba(255,255,255,.18)",gray400:"rgba(255,255,255,.38)",gray500:"rgba(255,255,255,.42)",
  gray600:"rgba(255,255,255,.62)",gray700:"rgba(255,255,255,.72)",gray800:"rgba(255,255,255,.86)",gray900:"rgba(255,255,255,.92)",
  white:"#111726",ink:"#FFFFFF",
  shadow1:"0 1px 2px rgba(0,0,0,.35),0 1px 3px rgba(0,0,0,.25)",
  shadow2:"0 20px 70px rgba(0,0,0,.45)",
  mono:"'Roboto Mono','Courier New',monospace",
  sans:"'Google Sans','Segoe UI',Roboto,sans-serif",
};

const G=`
@import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;600;700&family=Roboto+Mono:wght@400;500&family=Roboto:wght@300;400;500&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{background:${M.gray50};color:${M.gray900};font-family:${M.sans};-webkit-font-smoothing:antialiased}
a,button,input{outline-offset:3px}
a:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid ${M.blueSoft}}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:${M.gray100}}
::-webkit-scrollbar-thumb{background:${M.gray300};border-radius:2px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes pulseSoft{0%,100%{opacity:1}50%{opacity:.55}}
@keyframes fadePulse{0%,100%{opacity:1}50%{opacity:.55}}
@keyframes slideIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
@keyframes scan{0%{transform:translateX(-120%);opacity:0}30%,70%{opacity:1}100%{transform:translateX(120%);opacity:0}}
@keyframes grow{from{transform:scaleX(.35)}to{transform:scaleX(1)}}
@keyframes breathe{0%,100%{transform:translateY(0)}50%{transform:translateY(-2px)}}
@keyframes shimmer{0%,100%{filter:brightness(1)}50%{filter:brightness(1.35)}}
@media (max-width:900px){
  .login-hero{grid-template-columns:1fr!important;padding-top:40px!important}
  .login-hero h1{font-size:36px!important}
  .login-nav-links a:not(.login-cta){display:none!important}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
`;

function useFetch(token,path){
  const[data,setData]=useState(null);const[loading,setLoading]=useState(false);const[error,setError]=useState(null);
  const fetch_=useCallback(async()=>{
    if(!token||!path)return;setLoading(true);setError(null);
    try{setData(await apiFetch(token,path));}
    catch(e){setError(e.message);}
    finally{setLoading(false);}
  },[token,path]);
  useEffect(()=>{fetch_();},[fetch_]);
  return{data,loading,error,refetch:fetch_};
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

function WaterfallPanel({trace,onClose,loading}){
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
        {loading&&<div style={{fontSize:13,color:M.gray500,marginBottom:12}}>Loading trace detail…</div>}
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

function LogoMark({size=32}){
  return(
    <div style={{width:size,height:size,background:M.blue,borderRadius:8,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
      <svg width={size*0.56} height={size*0.56} viewBox="0 0 20 20" fill="none">
        <path d="M10 2.5 Q14 10 10 17.5" stroke={M.ink} strokeWidth="1.8" strokeLinecap="round"/>
        <path d="M6 2.5 Q10.5 10 6 17.5" stroke={M.ink} strokeWidth="1.8" strokeLinecap="round" opacity=".45"/>
        <circle cx="10" cy="2.5" r="1.8" fill={M.ink}/>
        <circle cx="10" cy="17.5" r="1.8" fill={M.ink}/>
      </svg>
    </div>
  );
}

function LoginScreen({onLogin}){
  const[key,setKey]=useState("");
  const[err,setErr]=useState("");const[loading,setLoading]=useState(false);
  const submit=async()=>{
    if(!key.startsWith("cxo-")){setErr("Key must start with cxo-");return;}
    setLoading(true);setErr("");
    try{const sess=await issueToken(key);onLogin(sess);}
    catch(e){setErr(e.message||"Invalid API key or unreachable API");}
    finally{setLoading(false);}
  };
  const inputStyle={width:"100%",background:M.gray50,border:`1px solid ${M.gray300}`,borderRadius:6,color:M.gray900,fontSize:14,padding:"10px 12px",outline:"none"};
  return(
    <div style={{minHeight:"100vh",background:M.gray50,color:M.gray900}}>
      <nav style={{position:"sticky",top:0,zIndex:50,height:64,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"0 32px",borderBottom:`1px solid ${M.gray200}`,background:"rgba(11,15,26,.86)",backdropFilter:"blur(14px)"}}>
        <a href="https://getcortexops.com" style={{display:"flex",alignItems:"center",gap:12,color:M.gray900,textDecoration:"none"}}>
          <LogoMark/>
          <span style={{fontSize:17,fontWeight:700}}>CortexOps</span>
        </a>
        <div className="login-nav-links" style={{display:"flex",alignItems:"center",gap:18,fontSize:14,color:M.gray600}}>
          <a href="https://getcortexops.com/#trusted" style={{color:"inherit",textDecoration:"none"}}>Trusted by</a>
          <a href="https://getcortexops.com/#frameworks" style={{color:"inherit",textDecoration:"none"}}>Frameworks</a>
          <a href="https://getcortexops.com/#pricing" style={{color:"inherit",textDecoration:"none"}}>Pricing</a>
          <a href="https://docs.getcortexops.com" style={{color:"inherit",textDecoration:"none"}}>Docs</a>
          <a href="#login" className="login-cta" style={{background:M.blue,color:M.ink,textDecoration:"none",borderRadius:7,padding:"9px 14px",fontWeight:700,boxShadow:"0 14px 30px rgba(26,115,232,.28)"}}>Open dashboard</a>
        </div>
      </nav>

      <section className="login-hero" style={{maxWidth:1180,margin:"0 auto",padding:"64px 28px 40px",display:"grid",gridTemplateColumns:"minmax(0,1fr) minmax(320px,420px)",gap:48,alignItems:"center"}}>
        <div>
          <div style={{display:"inline-flex",alignItems:"center",gap:8,background:M.greenLight,border:"1px solid rgba(45,212,167,.22)",color:M.green,borderRadius:99,padding:"6px 12px",fontSize:12,fontFamily:M.mono,marginBottom:22}}>
            <span style={{width:6,height:6,borderRadius:"50%",background:M.green,animation:"pulse 1.8s infinite"}}/>
            Open source reliability infrastructure
          </div>
          <h1 style={{fontSize:52,lineHeight:1.02,letterSpacing:"-.045em",fontWeight:700,marginBottom:22}}>
            Ship Reliable AI Agents.<br/>Every Time.
          </h1>
          <p style={{fontSize:18,lineHeight:1.65,color:M.gray600,maxWidth:560,marginBottom:28}}>
            Trace every node, evaluate every change, monitor production health, and catch regressions before users do.
          </p>
          <div style={{display:"flex",gap:12,flexWrap:"wrap",marginBottom:24}}>
            <a href="#login" style={{background:M.blue,color:M.ink,textDecoration:"none",borderRadius:7,padding:"12px 18px",fontWeight:700,boxShadow:"0 14px 30px rgba(26,115,232,.28)"}}>Open dashboard</a>
            <span style={{background:"rgba(255,255,255,.05)",border:`1px solid ${M.gray200}`,borderRadius:7,padding:"12px 14px",fontFamily:M.mono,fontSize:13,color:M.gray800}}>$ pip install cortexops</span>
          </div>
          <div style={{display:"flex",gap:18,flexWrap:"wrap",fontSize:13,color:M.gray600}}>
            {["Open Source","MIT License","12 Frameworks","CI Ready"].map(item=>(
              <span key={item} style={{display:"inline-flex",alignItems:"center",gap:7}}>
                <span style={{width:6,height:6,borderRadius:"50%",background:M.green}}/>{item}
              </span>
            ))}
          </div>
        </div>

        <div id="login" style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:14,padding:"28px 24px",boxShadow:M.shadow2}}>
          <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:22}}>
            <LogoMark size={36}/>
            <div>
              <div style={{fontSize:18,fontWeight:700}}>Open dashboard</div>
              <div style={{fontSize:13,color:M.gray600}}>Same product. Live console.</div>
            </div>
          </div>
          <div style={{marginBottom:14}}>
            <label style={{display:"block",fontSize:12,fontWeight:500,color:M.gray600,marginBottom:6}}>API Key</label>
            <input value={key} onChange={e=>setKey(e.target.value)} placeholder="cxo-..." type="password"
              onKeyDown={e=>e.key==="Enter"&&submit()}
              style={{...inputStyle,fontFamily:M.mono}}
              onFocus={e=>e.target.style.borderColor=M.blue}
              onBlur={e=>e.target.style.borderColor=M.gray300}
            />
          </div>
          <p style={{fontSize:12,color:M.gray500,marginBottom:14}}>Project is resolved from your key after login.</p>
          {err&&<div style={{background:M.redLight,color:M.red,fontSize:13,padding:"8px 12px",borderRadius:6,marginBottom:14,border:"1px solid rgba(242,109,109,.25)"}}>{err}</div>}
          <button onClick={submit} disabled={loading||!key}
            style={{width:"100%",background:M.blue,color:M.ink,border:"none",borderRadius:7,padding:12,fontSize:15,fontWeight:700,cursor:loading||!key?"not-allowed":"pointer",opacity:loading||!key?.5:1,boxShadow:"0 14px 30px rgba(26,115,232,.28)"}}>
            {loading?"Connecting…":"Open dashboard →"}
          </button>
          <p style={{color:M.gray500,fontSize:12,marginTop:16,textAlign:"center"}}>
            <a href="https://getcortexops.com" style={{color:M.blueSoft}}>getcortexops.com</a>
            {" · "}
            <a href="https://getcortexops.com/?trial=1" style={{color:M.blueSoft}}>Get Pro key</a>
          </p>
        </div>
      </section>

      <section style={{maxWidth:1180,margin:"0 auto",padding:"0 28px 48px"}}>
        <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:14,overflow:"hidden",position:"relative",boxShadow:M.shadow2}}>
          <div style={{position:"absolute",inset:0,pointerEvents:"none",background:"linear-gradient(110deg,transparent 35%,rgba(96,165,250,.10) 50%,transparent 65%)",animation:"scan 4s ease-in-out infinite"}}/>
          <div style={{padding:"14px 16px",borderBottom:`1px solid ${M.gray200}`,display:"flex",alignItems:"center",justifyContent:"space-between"}}>
            <div style={{fontFamily:M.mono,fontSize:13}}>Hero Dashboard</div>
            <div style={{display:"flex",gap:8}}>
              <span style={{background:M.greenLight,color:M.green,borderRadius:99,padding:"4px 9px",fontSize:11,fontWeight:700,animation:"breathe 2.2s infinite"}}>Success badge</span>
              <span style={{background:M.redLight,color:M.red,borderRadius:99,padding:"4px 9px",fontSize:11,fontWeight:700,animation:"pulseSoft 1.8s infinite"}}>Failure badge</span>
            </div>
          </div>
          <div style={{padding:16}}>
            <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:14}}>
              {[["Node","running...","#F5B23D"],["Latency","updating...","#60A5FA"],["Health Score","changing...","#2DD4A7"]].map(([l,v,c])=>(
                <div key={l} style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:8,padding:"10px 11px"}}>
                  <div style={{fontSize:10,color:M.gray500,fontFamily:M.mono,marginBottom:4}}>{l}</div>
                  <div style={{fontSize:13,color:c,fontFamily:M.mono,fontWeight:700,animation:"fadePulse 1.6s ease-in-out infinite"}}>{v}</div>
                </div>
              ))}
            </div>
            {[
              ["classify_intent","78%","#1A73E8","1.18s",0],
              ["tool call animated...","32%","#7B4F9E","active",12],
              ["evaluate_policy","52%","#0E8A6D","890ms",24],
              ["tool: issue_refund","88%","#D14343","2.01s",36],
            ].map(([name,width,color,time,left],i)=>(
              <div key={name} style={{display:"flex",alignItems:"center",gap:10,marginBottom:9}}>
                <div style={{width:132,fontSize:12,fontFamily:name.startsWith("tool")?M.mono:M.sans,color:name.includes("issue")?M.red:M.gray700,whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis"}}>{name}</div>
                <div style={{flex:1,height:22,background:"#172033",borderRadius:5,position:"relative",overflow:"hidden"}}>
                  <div style={{width,background:color,height:14,borderRadius:4,position:"absolute",top:4,left,animation:`grow ${1+i*.18}s ease both`,display:"flex",alignItems:"center",paddingLeft:7,fontSize:10,fontFamily:M.mono,fontWeight:700,color:M.ink}}>{time}</div>
                </div>
              </div>
            ))}
            <div style={{marginTop:12,background:M.redLight,border:"1px solid rgba(242,109,109,.25)",borderRadius:8,padding:"10px 12px",fontFamily:M.mono,fontSize:11,color:M.red,animation:"slideIn .4s ease both, pulseSoft 2.4s ease-in-out infinite"}}>
              Trace expanding... PaymentGatewayTimeout after tool call
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

const NAV=[
  ["overview","Overview"],
  ["projects","Projects"],
  ["traces","Traces"],
  ["evaluations","Evaluations"],
  ["prompts","Prompt Versions"],
  ["datasets","Datasets"],
  ["metrics","Metrics"],
  ["alerts","Alerts"],
  ["api-keys","API Keys"],
  ["usage","Usage"],
  ["settings","Settings"],
];

function EmptyState({title,body,hint}){
  return(
    <div style={{padding:"48px 24px",textAlign:"center",color:M.gray600}}>
      <div style={{fontSize:16,fontWeight:500,color:M.gray900,marginBottom:8}}>{title}</div>
      <div style={{fontSize:14,maxWidth:420,margin:"0 auto",lineHeight:1.55}}>{body}</div>
      {hint&&<div style={{fontFamily:M.mono,fontSize:13,color:M.gray500,marginTop:12}}>{hint}</div>}
    </div>
  );
}

function PanelCard({title,children}){
  return(
    <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:8,padding:18,boxShadow:M.shadow1}}>
      <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".07em",fontWeight:600,marginBottom:10}}>{title}</div>
      {children}
    </div>
  );
}

export default function App(){
  const[session,setSession]=useState(null);
  const[authReady,setAuthReady]=useState(false);
  const[tab,setTab]=useState("overview");
  const[filter,setFilter]=useState("all");
  const[live,setLive]=useState(true);
  const[selected,setSelected]=useState(null);
  const[traceDetail,setTraceDetail]=useState(null);
  const[detailLoading,setDetailLoading]=useState(false);
  const[rotatedKey,setRotatedKey]=useState(null);
  const[actionError,setActionError]=useState("");
  const ref=useRef(null);

  const token=session?.access_token;
  const project=session?.project||"payments-agent";
  const tier=session?.tier||"free";

  useEffect(()=>{
    const initial=loadSession();
    if(initial)setSession(initial);
    if(!initial){setAuthReady(true);return;}
    let cancelled=false;
    ensureSession(initial)
      .then((next)=>{
        if(cancelled)return;
        setSession(next);
        saveSession(next);
        setAuthReady(true);
      })
      .catch(()=>{
        if(!cancelled){clearSession();setSession(null);setAuthReady(true);}
      });
    return()=>{cancelled=true;};
  },[]);

  const tPath=token?`/v1/traces?project=${encodeURIComponent(project)}&limit=100${filter!=="all"?`&status=${filter}`:""}`:null;
  const ePath=token?`/v1/evals?project=${encodeURIComponent(project)}&limit=20`:null;
  const qPath=token?"/v1/traces/quota":null;
  const kPath=token?`/v1/keys/${encodeURIComponent(project)}`:null;
  const pPath=token?`/v1/prompts/catalog?project=${encodeURIComponent(project)}`:null;

  const{data:rawTraces,loading:tLoad,refetch:rT}=useFetch(token,tPath);
  const{data:rawEvals,loading:eLoad,refetch:rE}=useFetch(token,ePath);
  const{data:quota,loading:qLoad,refetch:rQ}=useFetch(token,qPath);
  const{data:rawKeys,loading:kLoad,refetch:rK}=useFetch(token,kPath);
  const{data:rawPrompts,loading:pLoad,refetch:rP}=useFetch(token,pPath);

  useEffect(()=>{
    if(live&&token){ref.current=setInterval(()=>{rT();rE();rQ();},5000);}
    return()=>clearInterval(ref.current);
  },[live,token,rT,rE,rQ]);

  useEffect(()=>{
    if(!selected?.trace_id||!token){setTraceDetail(null);return;}
    let cancelled=false;
    setDetailLoading(true);
    apiFetch(token,`/v1/traces/${selected.trace_id}`)
      .then(d=>{if(!cancelled)setTraceDetail(d);})
      .catch(()=>{if(!cancelled)setTraceDetail(selected);})
      .finally(()=>{if(!cancelled)setDetailLoading(false);});
    return()=>{cancelled=true;};
  },[selected?.trace_id,token]);

  const login=(sess)=>{saveSession(sess);setSession(sess);};
  const logout=()=>{clearSession();setSession(null);setSelected(null);setTraceDetail(null);};

  const rotateKey=async(keyId)=>{
    setActionError("");
    try{
      const res=await apiFetch(token,`/v1/keys/${keyId}/rotate`,{method:"POST"});
      setRotatedKey(res.new_key);
      if(res.new_key){
        const next=await issueToken(res.new_key);
        saveSession(next);
        setSession(next);
      }
      rK();
    }catch(e){setActionError(e.message);}
  };

  const revokeKey=async(keyId)=>{
    setActionError("");
    try{
      await apiFetch(token,`/v1/keys/${keyId}`,{method:"DELETE"});
      rK();
    }catch(e){setActionError(e.message);}
  };

  if(!authReady)return<><style>{G}</style><div style={{minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",color:M.gray600}}>Loading session…</div></>;
  if(!session)return<><style>{G}</style><LoginScreen onLogin={login}/></>;

  const traces=Array.isArray(rawTraces)?rawTraces:[];
  const evals=Array.isArray(rawEvals)?rawEvals:[];
  const latest=evals[0];const prev=evals[1];
  const failed=traces.filter(t=>t.status==="failed").length;
  const errRate=traces.length>0?((failed/traces.length)*100).toFixed(1):"0.0";
  const avgLat=traces.length>0?Math.round(traces.reduce((s,t)=>s+(t.total_latency_ms||0),0)/traces.length):0;
  const sorted=[...traces].sort((a,b)=>b.total_latency_ms-a.total_latency_ms);
  const p95=sorted.length>0?Math.round(sorted[Math.floor(sorted.length*0.05)]?.total_latency_ms||0):0;
  const tcColor=avgLat>1000?M.red:avgLat>500?M.amber:M.green;
  const successRate=traces.length>0?(((traces.length-failed)/traces.length)*100).toFixed(1):"—";
  const keys=Array.isArray(rawKeys)?rawKeys:[];
  const prompts=Array.isArray(rawPrompts)?rawPrompts:[];
  const activeLabel=NAV.find(([id])=>id===tab)?.[1]||"Overview";

  const metricTiles=(
    <div style={{display:"grid",gridTemplateColumns:"repeat(5,minmax(0,1fr))",gap:12}}>
      <Tile label="Task completion" value={latest?`${(latest.task_completion_rate*100).toFixed(1)}`:"—"} unit="%" color={M.green}
        spark={evals.slice(0,10).reverse().map(e=>(e.task_completion_rate||0)*100)} loading={eLoad}
        delta={prev?`${Math.abs((latest.task_completion_rate-prev.task_completion_rate)*100).toFixed(1)}%`:undefined}
        deltaUp={prev&&latest.task_completion_rate>=prev.task_completion_rate}/>
      <Tile label="Error rate" value={errRate} unit="%" color={parseFloat(errRate)>5?M.red:M.green} spark={traces.slice(0,20).reverse().map(t=>t.status==="failed"?100:0)} loading={tLoad}/>
      <Tile label="Avg latency" value={avgLat} unit="ms" color={tcColor} spark={traces.slice(0,20).reverse().map(t=>t.total_latency_ms||0)} loading={tLoad}/>
      <Tile label="P95 latency" value={p95} unit="ms" color={p95>2000?M.red:p95>1000?M.amber:M.blue} spark={traces.slice(0,20).reverse().map(t=>t.total_latency_ms||0)} loading={tLoad}/>
      <Tile label="Total traces" value={traces.length} color={M.blue} spark={traces.slice(0,20).map(()=>1)} loading={tLoad}/>
    </div>
  );

  return(
    <>
      <style>{G}</style>
      <div style={{display:"flex",height:"100vh",background:M.gray50}}>
        {/* Left nav */}
        <aside style={{width:220,background:M.white,borderRight:`1px solid ${M.gray200}`,display:"flex",flexDirection:"column",flexShrink:0}}>
          <div style={{padding:"16px 16px 12px",borderBottom:`1px solid ${M.gray200}`}}>
            <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:12}}>
              <div style={{width:28,height:28,background:M.blue,borderRadius:6,display:"flex",alignItems:"center",justifyContent:"center"}}>
                <svg width="16" height="16" viewBox="0 0 14 14" fill="none">
                  <path d="M7 1.5 Q10.5 7 7 12.5" stroke={M.ink} strokeWidth="1.5" strokeLinecap="round"/>
                  <path d="M4 1.5 Q8 7 4 12.5" stroke={M.ink} strokeWidth="1.5" strokeLinecap="round" opacity=".4"/>
                  <circle cx="7" cy="1.5" r="1.3" fill={M.ink}/><circle cx="7" cy="12.5" r="1.3" fill={M.ink}/>
                </svg>
              </div>
              <div>
                <div style={{fontSize:14,fontWeight:600,color:M.gray900}}>CortexOps</div>
                <div style={{fontSize:11,color:M.gray500}}>Dashboard</div>
              </div>
            </div>
            <div style={{fontSize:11,color:M.gray500,marginBottom:4}}>Project · {tier}</div>
            <div style={{fontFamily:M.mono,fontSize:12,color:M.gray800,background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:4,padding:"6px 8px",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{project}</div>
          </div>
          <nav style={{flex:1,overflow:"auto",padding:"10px 8px"}} aria-label="Dashboard">
            {NAV.map(([id,label])=>(
              <button key={id} onClick={()=>setTab(id)}
                style={{width:"100%",display:"flex",alignItems:"center",justifyContent:"space-between",textAlign:"left",background:tab===id?M.blueLight:"transparent",color:tab===id?M.blue:M.gray700,border:"none",borderRadius:6,padding:"9px 12px",fontSize:13,fontWeight:tab===id?600:500,cursor:"pointer",fontFamily:M.sans,marginBottom:2}}>
                <span>{label}</span>
                {id==="alerts"&&failed>0&&<span style={{background:M.red,color:M.ink,borderRadius:99,fontSize:10,padding:"1px 6px",fontWeight:600}}>{failed}</span>}
              </button>
            ))}
          </nav>
          <div style={{padding:"12px 14px",borderTop:`1px solid ${M.gray200}`}}>
            <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:8,cursor:"pointer"}} onClick={()=>setLive(l=>!l)}>
              <div style={{width:8,height:8,borderRadius:"50%",background:live?M.green:M.gray400,animation:live?"pulse 1.5s infinite":"none"}}/>
              <span style={{fontSize:12,color:live?M.green:M.gray500,fontWeight:500}}>{live?"Live · 5s":"Paused"}</span>
            </div>
            <button onClick={logout} style={{background:"none",border:"none",color:M.gray600,fontSize:12,cursor:"pointer",padding:0}}>Sign out</button>
          </div>
        </aside>

        {/* Main */}
        <div style={{flex:1,display:"flex",flexDirection:"column",minWidth:0}}>
          <header style={{height:56,background:M.white,borderBottom:`1px solid ${M.gray200}`,display:"flex",alignItems:"center",padding:"0 20px",gap:12,flexShrink:0}}>
            <h1 style={{fontSize:18,fontWeight:600,color:M.gray900,margin:0}}>{activeLabel}</h1>
            <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:10}}>
              <button onClick={()=>{rT();rE();rQ();rK();rP();}} style={{background:M.gray100,border:`1px solid ${M.gray200}`,borderRadius:4,color:M.gray700,fontSize:13,padding:"6px 10px",cursor:"pointer"}}>↻ Refresh</button>
              <a href="https://getcortexops.com" style={{fontSize:13,color:M.blueSoft,textDecoration:"none"}}>getcortexops.com</a>
            </div>
          </header>

          <div style={{flex:1,overflow:"auto",padding:20}}>
            {tab==="overview"&&(
              <div style={{display:"grid",gap:16}}>
                {metricTiles}
                <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:14}}>
                  <PanelCard title="Health score"><div style={{fontSize:28,fontWeight:600,color:M.green,fontFamily:M.mono}}>{successRate}{successRate!=="—"?"%":""}</div></PanelCard>
                  <PanelCard title="Eval gate"><div style={{fontSize:28,fontWeight:600,color:latest?(latest.task_completion_rate>=.9?M.green:M.red):M.gray500,fontFamily:M.mono}}>{latest?(latest.task_completion_rate>=.9?"Passing":"Failing"):"—"}</div></PanelCard>
                  <PanelCard title="Regressions"><div style={{fontSize:28,fontWeight:600,color:!latest?.regressions?M.green:M.amber,fontFamily:M.mono}}>{latest?.regressions??"—"}</div></PanelCard>
                </div>
                <PanelCard title="Recent traces">
                  {traces.slice(0,5).map(t=>(
                    <div key={t.trace_id} onClick={()=>{setSelected(t);setTab("traces");}} style={{display:"flex",alignItems:"center",gap:10,padding:"8px 0",borderBottom:`1px solid ${M.gray200}`,cursor:"pointer"}}>
                      <StatusDot status={t.status}/>
                      <span style={{fontFamily:M.mono,fontSize:12,color:M.gray500}}>{t.trace_id?.slice(0,8)}</span>
                      <span style={{flex:1,fontSize:13}}>{t.case_id||"live trace"}</span>
                      <LatencyChip ms={t.total_latency_ms||0}/>
                    </div>
                  ))}
                  {traces.length===0&&<div style={{fontSize:13,color:M.gray500}}>No traces yet</div>}
                </PanelCard>
              </div>
            )}

            {tab==="projects"&&(
              <div style={{maxWidth:520,display:"grid",gap:14}}>
                <PanelCard title="Active project">
                  <div style={{fontSize:14,color:M.gray700,marginBottom:12}}>Your project is bound to the API key used at login.</div>
                  <div style={{fontFamily:M.mono,fontSize:14,background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:4,padding:"10px 12px"}}>{project}</div>
                </PanelCard>
                <PanelCard title="Current">
                  <div style={{fontFamily:M.mono,fontSize:14}}>{project}</div>
                  <div style={{fontSize:13,color:M.gray600,marginTop:8}}>{traces.length} traces · {evals.length} eval runs · tier {tier}</div>
                </PanelCard>
              </div>
            )}

            {tab==="traces"&&(
              <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:8,overflow:"hidden"}}>
                <div style={{display:"flex",alignItems:"center",padding:"10px 16px",borderBottom:`1px solid ${M.gray200}`,gap:8}}>
                  {["all","completed","failed"].map(s=>(
                    <button key={s} onClick={()=>setFilter(s)}
                      style={{background:filter===s?M.blueLight:"transparent",border:`1px solid ${filter===s?M.blue:M.gray300}`,borderRadius:4,color:filter===s?M.blue:M.gray600,fontSize:12,padding:"4px 12px",cursor:"pointer"}}>{s}</button>
                  ))}
                </div>
                <div style={{display:"flex",alignItems:"center",gap:12,padding:"6px 16px",borderBottom:`1px solid ${M.gray200}`,background:M.gray50}}>
                  {["","ID","Case","Latency","Failure","Time"].map((h,i)=>(
                    <span key={i} style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".06em",fontWeight:600,minWidth:i===0?8:i===1?64:i===3?70:i===4?100:i===5?80:undefined,flex:i===2?1:undefined}}>{h}</span>
                  ))}
                </div>
                {traces.length===0&&!tLoad&&<EmptyState title="No traces yet" body="Instrument your agent and send traces to this project." hint="pip install cortexops"/>}
                {traces.map((t,i)=>(
                  <div key={t.trace_id} onClick={()=>setSelected(t)}
                    style={{display:"flex",alignItems:"center",gap:12,padding:"10px 16px",borderBottom:`1px solid ${M.gray200}`,cursor:"pointer",animation:`slideIn .15s ease ${Math.min(i,8)*.03}s both`}}
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
              </div>
            )}

            {tab==="evaluations"&&(
              <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:8,overflow:"hidden"}}>
                {evals.length===0&&!eLoad&&<EmptyState title="No evaluations yet" body="Run golden datasets in CI or locally to populate this view." hint='cortexops eval run --dataset golden_v1.yaml'/>}
                {evals.map((run,i)=>(
                  <div key={run.run_id} style={{padding:"14px 16px",borderBottom:`1px solid ${M.gray200}`,animation:`slideIn .15s ease ${i*.04}s both`}}>
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
              </div>
            )}

            {tab==="prompts"&&(
              <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:8,overflow:"hidden"}}>
                {pLoad&&<div style={{padding:16,fontSize:13,color:M.gray500}}>Loading prompt versions…</div>}
                {!pLoad&&prompts.length===0&&<EmptyState title="No prompt versions yet" body="Commit prompt versions from your agent pipeline or API to track changes against evals." hint="POST /v1/prompts"/>}
                {prompts.map((pv,i)=>(
                  <div key={pv.id} style={{padding:"14px 16px",borderBottom:`1px solid ${M.gray200}`,animation:`slideIn .15s ease ${i*.04}s both`}}>
                    <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8}}>
                      <span style={{fontFamily:M.mono,fontSize:13,color:M.blue,fontWeight:600}}>{pv.prompt_name}</span>
                      <span style={{fontSize:11,background:M.blueLight,color:M.blue,padding:"2px 8px",borderRadius:4,fontFamily:M.mono}}>v{pv.version}</span>
                      {pv.model&&<span style={{fontSize:12,color:M.gray500}}>{pv.model}</span>}
                    </div>
                    <div style={{fontSize:12,color:M.gray600,marginBottom:8}}>{pv.commit_message||"No commit message"} · {pv.author||"unknown"}</div>
                    <div style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:6,padding:10,fontFamily:M.mono,fontSize:11,color:M.gray800,whiteSpace:"pre-wrap",maxHeight:120,overflow:"auto"}}>{pv.content}</div>
                  </div>
                ))}
              </div>
            )}

            {tab==="datasets"&&(
              <EmptyState title="Datasets" body="Versioned golden cases for CI and local eval runs. Store cases as YAML and gate merges on score." hint="cortexops eval run --dataset golden_v1.yaml"/>
            )}

            {tab==="metrics"&&(
              <div style={{display:"grid",gap:16}}>
                {metricTiles}
                <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:14}}>
                  <PanelCard title="Health score"><div style={{fontSize:24,fontWeight:600,color:M.green,fontFamily:M.mono}}>{successRate}{successRate!=="—"?"%":""}</div></PanelCard>
                  <PanelCard title="Latency watch"><div style={{fontSize:24,fontWeight:600,color:tcColor,fontFamily:M.mono}}>{avgLat}ms avg</div></PanelCard>
                  <PanelCard title="Drift monitor"><div style={{fontSize:24,fontWeight:600,color:latest?.regressions?M.amber:M.green,fontFamily:M.mono}}>{latest?.regressions?"Needs review":"Stable"}</div></PanelCard>
                </div>
              </div>
            )}

            {tab==="alerts"&&(
              <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:8,overflow:"hidden"}}>
                {traces.filter(t=>t.status==="failed").length===0&&<EmptyState title="No alerts" body="All traces are healthy. Failures and quality drops will appear here."/>}
                {traces.filter(t=>t.status==="failed").map(t=>(
                  <div key={t.trace_id} onClick={()=>setSelected(t)}
                    style={{padding:"12px 16px",borderBottom:`1px solid ${M.gray200}`,borderLeft:`4px solid ${M.red}`,cursor:"pointer"}}
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
              </div>
            )}

            {tab==="api-keys"&&(
              <div style={{maxWidth:720,display:"grid",gap:14}}>
                {actionError&&<div style={{background:M.redLight,color:M.red,border:"1px solid rgba(197,34,31,.2)",borderRadius:6,padding:"10px 12px",fontSize:13}}>{actionError}</div>}
                {rotatedKey&&(
                  <PanelCard title="New key — copy now">
                    <div style={{fontFamily:M.mono,fontSize:13,background:M.greenLight,border:`1px solid rgba(45,212,167,.3)`,borderRadius:4,padding:"10px 12px",wordBreak:"break-all"}}>{rotatedKey}</div>
                    <div style={{fontSize:12,color:M.gray600,marginTop:8}}>Shown once. Your session was updated to use the new key.</div>
                    <button onClick={()=>setRotatedKey(null)} style={{marginTop:10,background:M.gray100,border:`1px solid ${M.gray300}`,borderRadius:4,padding:"8px 12px",cursor:"pointer"}}>Dismiss</button>
                  </PanelCard>
                )}
                <PanelCard title="API keys for this project">
                  {kLoad&&<div style={{fontSize:13,color:M.gray500}}>Loading keys…</div>}
                  {!kLoad&&keys.length===0&&<div style={{fontSize:13,color:M.gray500}}>No keys found for this project.</div>}
                  {keys.map(k=>(
                    <div key={k.id} style={{display:"flex",alignItems:"center",gap:12,padding:"10px 0",borderBottom:`1px solid ${M.gray200}`}}>
                      <div style={{flex:1}}>
                        <div style={{fontSize:14,fontWeight:500}}>{k.name||"default"}</div>
                        <div style={{fontFamily:M.mono,fontSize:11,color:M.gray500}}>{k.id.slice(0,8)}… · {k.tier} · {k.scope}</div>
                        <div style={{fontSize:11,color:M.gray500,marginTop:4}}>Created {k.created_at?new Date(k.created_at).toLocaleDateString():"—"}{k.last_used_at?` · Last used ${new Date(k.last_used_at).toLocaleDateString()}`:""}</div>
                      </div>
                      <span style={{fontSize:11,color:k.is_active?M.green:M.red,fontWeight:600}}>{k.is_active?"active":"revoked"}</span>
                      {k.is_active&&<>
                        <button onClick={()=>rotateKey(k.id)} style={{background:M.blueLight,color:M.blue,border:"none",borderRadius:4,padding:"6px 10px",fontSize:12,cursor:"pointer",fontWeight:600}}>Rotate</button>
                        <button onClick={()=>revokeKey(k.id)} style={{background:M.redLight,color:M.red,border:"none",borderRadius:4,padding:"6px 10px",fontSize:12,cursor:"pointer",fontWeight:600}}>Revoke</button>
                      </>}
                    </div>
                  ))}
                </PanelCard>
                <PanelCard title="Session">
                  <div style={{fontSize:13,color:M.gray600,marginBottom:10}}>Dashboard uses a short-lived JWT (1 hour). Sign out to clear the session.</div>
                  <button onClick={logout} style={{background:M.redLight,color:M.red,border:`1px solid rgba(197,34,31,.2)`,borderRadius:4,padding:"10px 14px",fontWeight:600,cursor:"pointer"}}>Sign out</button>
                </PanelCard>
              </div>
            )}

            {tab==="usage"&&(
              <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:14}}>
                <PanelCard title="Monthly traces">
                  {qLoad?<div style={{fontSize:13,color:M.gray500}}>Loading…</div>:<>
                    <div style={{fontSize:28,fontWeight:600,fontFamily:M.mono}}>{quota?.monthly_traces?.used??"—"}</div>
                    <div style={{fontSize:13,color:M.gray600,marginTop:6}}>
                      {quota?.monthly_traces?.unlimited?"Unlimited (Pro)":`of ${quota?.monthly_traces?.limit?.toLocaleString()??"5,000"} limit`}
                    </div>
                    {!quota?.monthly_traces?.unlimited&&quota?.monthly_traces?.percent_used!=null&&(
                      <div style={{marginTop:10,height:8,background:M.gray200,borderRadius:4,overflow:"hidden"}}>
                        <div style={{width:`${Math.min(quota.monthly_traces.percent_used,100)}%`,height:"100%",background:quota.monthly_traces.percent_used>90?M.red:quota.monthly_traces.percent_used>70?M.amber:M.green}}/>
                      </div>
                    )}
                  </>}
                </PanelCard>
                <PanelCard title="Retention">
                  <div style={{fontSize:28,fontWeight:600,fontFamily:M.mono}}>{quota?.retention_days??"—"}</div>
                  <div style={{fontSize:13,color:M.gray600,marginTop:6}}>days of trace history</div>
                </PanelCard>
                <PanelCard title="Plan">
                  <div style={{fontSize:28,fontWeight:600,textTransform:"capitalize"}}>{quota?.tier||tier}</div>
                  <div style={{fontSize:13,color:M.gray600,marginTop:6}}>
                    {quota?.features?.slack_alerts?"Slack alerts · ":""}
                    {quota?.features?.llm_judge?"LLM judge · ":""}
                    {quota?.features?.prompt_versioning?"Prompt versioning":""}
                  </div>
                  {quota?.upgrade_url&&<a href={quota.upgrade_url} style={{display:"inline-block",marginTop:12,color:M.blue,fontSize:13}}>Upgrade to Pro</a>}
                </PanelCard>
                <PanelCard title="Traces in view"><div style={{fontSize:28,fontWeight:600,fontFamily:M.mono}}>{traces.length}</div></PanelCard>
                <PanelCard title="Eval runs loaded"><div style={{fontSize:28,fontWeight:600,fontFamily:M.mono}}>{evals.length}</div></PanelCard>
                <PanelCard title="Failed traces"><div style={{fontSize:28,fontWeight:600,fontFamily:M.mono,color:failed?M.red:M.green}}>{failed}</div></PanelCard>
              </div>
            )}

            {tab==="settings"&&(
              <div style={{maxWidth:520,display:"grid",gap:14}}>
                <PanelCard title="Project">
                  <div style={{fontFamily:M.mono,fontSize:14,background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:4,padding:"10px 12px"}}>{project}</div>
                  <div style={{fontSize:12,color:M.gray500,marginTop:8}}>Project is determined by your API key.</div>
                </PanelCard>
                <PanelCard title="Live refresh">
                  <label style={{display:"flex",alignItems:"center",gap:10,cursor:"pointer",fontSize:14}}>
                    <input type="checkbox" checked={live} onChange={e=>setLive(e.target.checked)}/>
                    Poll traces and evaluations every 5 seconds
                  </label>
                </PanelCard>
                <PanelCard title="API">
                  <div style={{fontFamily:M.mono,fontSize:13,color:M.gray700}}>{API}</div>
                </PanelCard>
                <PanelCard title="Account">
                  <button onClick={logout} style={{background:M.gray100,border:`1px solid ${M.gray300}`,borderRadius:4,padding:"10px 14px",cursor:"pointer"}}>Sign out</button>
                </PanelCard>
              </div>
            )}
          </div>
        </div>
      </div>
      {selected&&<WaterfallPanel trace={traceDetail||selected} loading={detailLoading} onClose={()=>{setSelected(null);setTraceDetail(null);}}/>}
    </>
  );
}