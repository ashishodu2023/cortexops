import { useState, useEffect, useRef, useCallback } from "react";
import {
  API,
  apiFetch,
  clearSession,
  ensureSession,
  isAuthError,
  issueToken,
  keyIdFromToken,
  loadSession,
  refreshSession,
  saveSession,
  sessionExpired,
} from "./api.js";
import { clearUiActivity, loadUiActivity, logUiActivity } from "./activity.js";

const M = {
  brand:"#DC2626",brandDark:"#991B1B",brandLight:"rgba(220,38,38,.2)",brandSoft:"#F87171",
  blue:"#3B82F6",blueDark:"#1D4ED8",blueLight:"rgba(59,130,246,.18)",blueSoft:"#60A5FA",
  green:"#22C55E",greenLight:"rgba(34,197,94,.14)",
  red:"#EF4444",redLight:"rgba(239,68,68,.18)",
  amber:"#F59E0B",amberLight:"rgba(245,158,11,.12)",
  purple:"#8B5CF6",purpleLight:"rgba(139,92,246,.14)",
  cyan:"#06B6D4",cyanLight:"rgba(6,182,212,.14)",
  pink:"#EC4899",pinkLight:"rgba(236,72,153,.14)",
  gray50:"#000000",gray100:"#0D0D0D",gray200:"rgba(255,255,255,.11)",
  gray300:"rgba(255,255,255,.18)",gray400:"rgba(255,255,255,.38)",gray500:"rgba(255,255,255,.42)",
  gray600:"rgba(255,255,255,.62)",gray700:"rgba(255,255,255,.72)",gray800:"rgba(255,255,255,.86)",gray900:"rgba(255,255,255,.92)",
  white:"#0D0D0D",ink:"#FFFFFF",
  shadow1:"0 1px 2px rgba(0,0,0,.35),0 1px 3px rgba(0,0,0,.25)",
  shadow2:"0 20px 70px rgba(0,0,0,.45)",
  mono:"'JetBrains Mono','SF Mono','Menlo','Consolas',monospace",
  sans:"'JetBrains Mono','SF Mono','Menlo','Consolas',monospace",
};

const TRACE_NODE_COLORS=[M.blue,M.green,M.purple,M.cyan,M.amber,M.pink,M.brand];

const HOME_URL="https://www.getcortexops.com";
const REFRESH_OPTIONS=[5,10,15,30];
const REFRESH_KEY="cxo_refresh_sec";

function loadRefreshSec(){
  const n=parseInt(localStorage.getItem(REFRESH_KEY)||"5",10);
  return REFRESH_OPTIONS.includes(n)?n:5;
}

const G=`
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap');
html{color-scheme:dark}
*{box-sizing:border-box;margin:0;padding:0}
body{background:${M.gray50};color:${M.gray900};font-family:${M.mono};font-size:14px;line-height:1.6;font-variant-ligatures:none;-webkit-font-smoothing:antialiased;-webkit-print-color-adjust:exact;print-color-adjust:exact}
a,button,input{outline-offset:3px}
a:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid ${M.brandSoft}}
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
.obs-bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.obs-glow{position:absolute;inset:0;background:radial-gradient(ellipse 55% 45% at 15% 20%,rgba(220,38,38,.08),transparent 70%),radial-gradient(ellipse 50% 40% at 85% 75%,rgba(59,130,246,.07),transparent 70%),radial-gradient(ellipse 42% 32% at 50% 55%,rgba(34,197,94,.04),transparent 65%)}
.obs-grid{position:absolute;inset:-1px;background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:48px 48px;mask-image:radial-gradient(ellipse 92% 85% at 50% 35%,#000 15%,transparent 78%);animation:obsGridDrift 80s linear infinite}
.obs-scan-v{position:absolute;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(220,38,38,.4),rgba(59,130,246,.28),transparent);box-shadow:0 0 14px rgba(220,38,38,.12);animation:obsScanV 14s linear infinite}
.obs-scan-h{position:absolute;top:0;bottom:0;width:1px;background:linear-gradient(180deg,transparent,rgba(59,130,246,.22),rgba(34,197,94,.18),transparent);animation:obsScanH 20s linear infinite;animation-delay:-7s}
.obs-svg{position:absolute;inset:0;width:100%;height:100%;opacity:.38}
.obs-trace{fill:none;stroke-width:1.4;stroke-linecap:round;stroke-dasharray:7 13;animation:obsTraceFlow 5s linear infinite}
.obs-trace-1{stroke:rgba(59,130,246,.55)}
.obs-trace-2{stroke:rgba(34,197,94,.5);animation-duration:7s;animation-delay:-2s}
.obs-trace-3{stroke:rgba(220,38,38,.45);animation-duration:6s;animation-delay:-1s}
.obs-trace-4{stroke:rgba(139,92,246,.42);animation-duration:9s;animation-delay:-4s}
.obs-node{position:absolute;left:var(--x);top:var(--y);width:5px;height:5px;border-radius:50%;background:var(--c,${M.brand});box-shadow:0 0 10px var(--c,${M.brand});animation:obsNodePulse 3.2s ease-in-out infinite;animation-delay:var(--d,0s)}
.obs-node::after{content:'';position:absolute;inset:-7px;border-radius:50%;border:1px solid var(--c,${M.brand});opacity:0;animation:obsNodeRing 3.2s ease-out infinite;animation-delay:var(--d,0s)}
.obs-spark{position:absolute;display:flex;align-items:flex-end;gap:3px;opacity:.42}
.obs-spark-tl{top:11%;left:3%;height:34px}
.obs-spark-br{bottom:12%;right:4%;height:26px}
.obs-spark-mr{top:40%;right:2.5%;height:22px;opacity:.28}
.obs-spark-bl{bottom:22%;left:6%;height:20px;opacity:.32}
.obs-spark span{display:block;width:4px;border-radius:2px;background:linear-gradient(180deg,var(--spark,${M.blue}),transparent);transform-origin:bottom;animation:obsSparkBar 2.6s ease-in-out infinite}
.obs-spark span:nth-child(1){height:35%;animation-delay:0s}
.obs-spark span:nth-child(2){height:62%;--spark:${M.green};animation-delay:.25s}
.obs-spark span:nth-child(3){height:48%;--spark:${M.brand};animation-delay:.5s}
.obs-spark span:nth-child(4){height:78%;--spark:${M.purple};animation-delay:.15s}
.obs-spark span:nth-child(5){height:42%;--spark:${M.cyan};animation-delay:.65s}
.obs-spark span:nth-child(6){height:58%;--spark:${M.amber};animation-delay:.35s}
.obs-spark span:nth-child(7){height:70%;--spark:${M.blue};animation-delay:.8s}
.obs-spark span:nth-child(8){height:38%;--spark:${M.green};animation-delay:.45s}
.obs-ring{position:absolute;left:var(--x);top:var(--y);width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:1px solid rgba(220,38,38,.22);animation:obsRingExpand 7s ease-out infinite;animation-delay:var(--d,0s)}
.obs-ring-2{border-color:rgba(59,130,246,.2);animation-duration:9s}
.obs-beacon{position:absolute;left:var(--x);top:var(--y);width:2px;height:2px;border-radius:50%;background:var(--c,${M.brand});box-shadow:0 0 8px var(--c,${M.brand});animation:obsBeacon 5s ease-in-out infinite;animation-delay:var(--d,0s)}
.obs-wave{position:absolute;left:0;right:0;height:40px;opacity:.18;overflow:hidden}
.obs-wave-top{top:8%}
.obs-wave-btm{bottom:6%;opacity:.12}
.obs-wave svg{width:200%;height:100%;animation:obsWaveSlide 18s linear infinite}
.obs-wave-btm svg{animation-duration:22s;animation-direction:reverse}
.obs-ticker{position:absolute;bottom:0;left:0;right:0;height:30px;background:linear-gradient(180deg,transparent,rgba(0,0,0,.55));overflow:hidden;opacity:.55}
.obs-ticker-track{display:flex;gap:48px;white-space:nowrap;font-size:10px;font-family:${M.mono};color:${M.gray500};padding-top:12px;animation:obsTicker 50s linear infinite}
.obs-ticker-track span::before{content:'▸ ';color:${M.brandSoft};opacity:.7}
.obs-shell{position:relative;z-index:1}
@keyframes obsGridDrift{0%{background-position:0 0,0 0}100%{background-position:48px 48px,48px 48px}}
@keyframes obsScanV{0%{top:-2px;opacity:0}6%{opacity:1}94%{opacity:1}100%{top:100%;opacity:0}}
@keyframes obsScanH{0%{left:-2px;opacity:0}8%{opacity:.75}92%{opacity:.75}100%{left:100%;opacity:0}}
@keyframes obsTraceFlow{to{stroke-dashoffset:-40}}
@keyframes obsNodePulse{0%,100%{opacity:.45;transform:scale(1)}50%{opacity:1;transform:scale(1.35)}}
@keyframes obsNodeRing{0%{opacity:.55;transform:scale(.5)}100%{opacity:0;transform:scale(2.4)}}
@keyframes obsSparkBar{0%,100%{transform:scaleY(.35);opacity:.45}50%{transform:scaleY(1);opacity:1}}
@keyframes obsRingExpand{0%{transform:scale(.25);opacity:.5}100%{transform:scale(2.6);opacity:0}}
@keyframes obsBeacon{0%,100%{opacity:0;transform:scale(1)}12%,28%{opacity:1;transform:scale(1.6)}}
@keyframes obsWaveSlide{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
@keyframes obsTicker{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.card-hover{transition:background .15s,border-color .15s,transform .15s,box-shadow .15s}
.card-hover:hover{background:rgba(255,255,255,.04)!important;border-color:rgba(255,255,255,.22)!important;transform:translateY(-1px);box-shadow:0 4px 16px rgba(0,0,0,.25)}
.row-hover{transition:background .12s}
.row-hover:hover{background:rgba(255,255,255,.04)!important}
@media (max-width:1100px){
  .metric-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important}
  .insight-grid{grid-template-columns:1fr!important}
  .overview-layout{grid-template-columns:1fr!important}
}
@media (max-width:768px){
  .dash-sidebar-desktop{display:none!important}
  .mobile-menu-btn{display:inline-flex!important}
  .header-hide-mobile{display:none!important}
  .metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .trace-panel{width:100%!important;max-width:100vw!important}
}
.mobile-menu-btn{display:none;align-items:center;justify-content:center;background:${M.gray100};border:1px solid ${M.gray200};border-radius:6px;width:36px;height:36px;cursor:pointer;color:${M.gray800};flex-shrink:0;padding:0}
.mobile-nav-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:190;animation:fadeIn .2s ease}
.mobile-nav-drawer{position:fixed;top:0;left:0;bottom:0;width:min(280px,88vw);z-index:200;background:${M.white};border-right:1px solid ${M.gray200};display:flex;flex-direction:column;box-shadow:${M.shadow2};animation:slideDrawer .22s ease}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes slideDrawer{from{transform:translateX(-100%)}to{transform:translateX(0)}}
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

function Tile({label,value,unit,hint,delta,deltaUp,spark,color,loading,onClick,active}){
  const clickable=!!onClick;
  return(
    <div className={clickable?"card-hover":""} onClick={onClick} role={clickable?"button":undefined} tabIndex={clickable?0:undefined}
      onKeyDown={clickable?e=>e.key==="Enter"&&onClick():undefined}
      style={{background:M.white,border:`1px solid ${active?color:M.gray200}`,borderRadius:10,padding:"14px 16px",borderTop:`3px solid ${color}`,boxShadow:active?`0 0 0 1px ${color}33,${M.shadow1}`:M.shadow1,cursor:clickable?"pointer":undefined}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:6}}>
        <div style={{fontSize:11,color:M.gray600,fontWeight:500,textTransform:"uppercase",letterSpacing:".05em"}}>{label}</div>
        {clickable&&<span style={{fontSize:10,color:M.gray400}}>→</span>}
      </div>
      {loading?<div style={{width:60,height:26,background:M.gray100,borderRadius:4}}/>
        :<div style={{fontSize:26,fontWeight:600,color:M.gray900,letterSpacing:"-.02em",marginBottom:4}}>{value??"—"}<span style={{fontSize:12,color:M.gray500,fontWeight:400,marginLeft:2}}>{unit}</span></div>}
      {hint&&<div style={{fontSize:11,color:M.gray500,marginBottom:8,lineHeight:1.4}}>{hint}</div>}
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        {delta!==undefined&&<span style={{fontSize:11,color:deltaUp?M.green:M.red,fontWeight:500}}>{deltaUp?"↑":"↓"} {delta}</span>}
        <Sparkline values={spark} color={color}/>
      </div>
    </div>
  );
}

function InsightCard({label,value,sub,color,bar,barColor,onClick,loading}){
  const clickable=!!onClick;
  return(
    <div className={clickable?"card-hover":""} onClick={onClick} role={clickable?"button":undefined} tabIndex={clickable?0:undefined}
      onKeyDown={clickable?e=>e.key==="Enter"&&onClick():undefined}
      style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:10,padding:"16px 18px",boxShadow:M.shadow1,cursor:clickable?"pointer":undefined,display:"flex",flexDirection:"column",gap:6}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".07em",fontWeight:600}}>{label}</div>
        {clickable&&<span style={{fontSize:10,color:M.gray400}}>View →</span>}
      </div>
      {loading?<div style={{width:80,height:32,background:M.gray100,borderRadius:4}}/>
        :<div style={{fontSize:32,fontWeight:700,color,letterSpacing:"-.03em",lineHeight:1}}>{value}</div>}
      {sub&&<div style={{fontSize:12,color:M.gray600,lineHeight:1.45}}>{sub}</div>}
      {bar!=null&&<div style={{marginTop:4,height:6,background:M.gray200,borderRadius:3,overflow:"hidden"}}>
        <div style={{width:`${Math.min(bar,100)}%`,height:"100%",background:barColor||color,borderRadius:3,transition:"width .4s ease"}}/>
      </div>}
    </div>
  );
}

function timeAgo(iso){
  if(!iso)return"—";
  const s=Math.floor((Date.now()-new Date(iso).getTime())/1000);
  if(s<60)return`${s}s ago`;
  if(s<3600)return`${Math.floor(s/60)}m ago`;
  if(s<86400)return`${Math.floor(s/3600)}h ago`;
  return`${Math.floor(s/86400)}d ago`;
}

function formatWhen(iso){
  if(!iso)return"—";
  const d=new Date(iso);
  return d.toLocaleString([],{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});
}

const TRACE_DATE_PRESETS=[["all","All time"],["24h","24 hours"],["7d","7 days"],["30d","30 days"],["custom","Custom"]];

function buildTraceDateQuery(preset,fromDate,toDate){
  if(preset==="all")return"";
  const now=new Date();
  if(preset==="custom"){
    let q="";
    if(fromDate)q+=`&from=${encodeURIComponent(`${fromDate}T00:00:00.000Z`)}`;
    if(toDate)q+=`&to=${encodeURIComponent(`${toDate}T23:59:59.999Z`)}`;
    return q;
  }
  const hours={"24h":24,"7d":24*7,"30d":24*30}[preset];
  if(!hours)return"";
  const from=new Date(now.getTime()-hours*3600*1000);
  return `&from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(now.toISOString())}`;
}

function traceDateLabel(preset,fromDate,toDate){
  if(preset==="all")return"";
  if(preset==="custom"){
    if(fromDate&&toDate)return`${fromDate} → ${toDate}`;
    if(fromDate)return`from ${fromDate}`;
    if(toDate)return`until ${toDate}`;
    return"custom range";
  }
  return TRACE_DATE_PRESETS.find(([k])=>k===preset)?.[1]||"";
}

function Badge({children,color=M.gray600,bg=M.gray100}){
  return<span style={{display:"inline-flex",alignItems:"center",fontSize:11,fontWeight:600,color,background:bg,padding:"3px 8px",borderRadius:5,whiteSpace:"nowrap"}}>{children}</span>;
}

function Section({title,subtitle,action,children,noPad}){
  return(
    <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:12,overflow:"hidden",boxShadow:M.shadow1}}>
      <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",gap:12,padding:"14px 18px",borderBottom:subtitle||children?`1px solid ${M.gray200}`:"none"}}>
        <div>
          <div style={{fontSize:12,color:M.gray500,textTransform:"uppercase",letterSpacing:".07em",fontWeight:700}}>{title}</div>
          {subtitle&&<div style={{fontSize:12,color:M.gray500,marginTop:3,lineHeight:1.4}}>{subtitle}</div>}
        </div>
        {action}
      </div>
      {children&&<div style={{padding:noPad?0:"14px 18px"}}>{children}</div>}
    </div>
  );
}

function QuickLink({label,onClick,color=M.blue}){
  return(
    <button onClick={onClick} style={{background:`${color}18`,border:`1px solid ${color}44`,color,borderRadius:8,padding:"8px 12px",fontSize:12,fontWeight:600,cursor:"pointer",textAlign:"left"}}>
      {label} →
    </button>
  );
}

function DetailRow({label,value,mono}){
  return(
    <div style={{display:"flex",justifyContent:"space-between",gap:12,padding:"6px 0",borderBottom:`1px solid ${M.gray200}`}}>
      <span style={{fontSize:12,color:M.gray500}}>{label}</span>
      <span style={{fontSize:12,color:M.gray900,fontFamily:mono?M.mono:M.sans,fontWeight:500,textAlign:"right"}}>{value}</span>
    </div>
  );
}

function MiniBars({values=[],color=M.blue,h=48}){
  if(!values.length)return null;
  const max=Math.max(...values,1);
  return(
    <div style={{display:"flex",alignItems:"flex-end",gap:3,height:h}}>
      {values.map((v,i)=>(
        <div key={i} style={{flex:1,background:M.gray200,borderRadius:3,overflow:"hidden",height:"100%",display:"flex",alignItems:"flex-end"}}>
          <div style={{width:"100%",height:`${Math.max(8,(v/max)*100)}%`,background:color,borderRadius:3,opacity:.85}}/>
        </div>
      ))}
    </div>
  );
}

function NavIcon({id}){
  const paths={
    overview:"M3 3h4v4H3zm7 0h4v4h-4zm-7 7h4v4H3zm7 0h4v4h-4z",
    traces:"M4 6h12M4 10h8M4 14h10",
    activity:"M12 8v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
    alerts:"M12 3 4 18h16L12 3zm0 5v4m0 3h.01",
    metrics:"M4 16V8m4 8V5m4 11v-6m4 6V4",
    evaluations:"M5 12l4 4 9-10",
    prompts:"M6 4h9l3 3v11H6V4z",
    datasets:"M4 6h12v10H4z M8 3v3 M12 3v3",
    projects:"M3 8h8V3H3zm10 0h8v5h-8z M3 16h8v5H3zm10 0h8v5h-8z",
    "api-keys":"M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm-6 8v-1a5 5 0 0 1 10 0v1",
    usage:"M12 3v15m-6-3h12",
    settings:"M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm8 4h-2M6 12H4",
  };
  const d=paths[id]||paths.overview;
  return(
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{flexShrink:0,opacity:.85}}>
      <path d={d}/>
    </svg>
  );
}

function StatusDot({status}){
  const color={completed:M.green,failed:M.red,running:M.amber}[status]||M.gray500;
  return<span style={{display:"inline-block",width:8,height:8,borderRadius:"50%",background:color,animation:status==="running"?"pulse 1s infinite":"none",flexShrink:0}}/>;
}

function TraceRow({trace,onClick,showCase=true}){
  return(
    <div className="row-hover" onClick={onClick} style={{display:"flex",alignItems:"center",gap:12,padding:"11px 18px",borderBottom:`1px solid ${M.gray200}`,cursor:"pointer"}}>
      <StatusDot status={trace.status}/>
      <div style={{minWidth:76}}>
        <div style={{fontFamily:M.mono,fontSize:12,color:M.gray700,fontWeight:600}}>{trace.trace_id?.slice(0,8)}</div>
        <div style={{fontSize:10,color:M.gray500,marginTop:2}} title={formatWhen(trace.created_at)}>{timeAgo(trace.created_at)}</div>
      </div>
      {showCase&&<span style={{flex:1,fontSize:13,color:M.gray900,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{trace.case_id||"live trace"}</span>}
      <Badge color={trace.status==="failed"?M.red:M.green} bg={trace.status==="failed"?M.redLight:M.greenLight}>{trace.status==="failed"?"Failed":"OK"}</Badge>
      <LatencyChip ms={trace.total_latency_ms||0}/>
      {trace.failure_kind&&<Badge color={M.red} bg={M.redLight}>{trace.failure_kind.replace("FailureKind.","").slice(0,12)}</Badge>}
    </div>
  );
}

function LatencyChip({ms}){
  const c=ms>1000?M.red:ms>500?M.amber:M.green;
  const bg=ms>1000?M.redLight:ms>500?M.amberLight:M.greenLight;
  return<span style={{background:bg,color:c,fontSize:11,fontFamily:M.mono,padding:"2px 7px",borderRadius:4,fontWeight:500}}>{Math.round(ms)}ms</span>;
}

const FAILURE_KIND_COLORS={
  tool_call_mismatch:M.amber,
  hallucination:M.purple,
  timeout:M.cyan,
  output_format:M.blue,
  latency_exceeded:M.amber,
  plan_deviation:M.pink,
  context_overflow:M.red,
  tool_error:M.red,
  unknown:M.gray500,
};

function normFailureKind(k){
  if(!k)return"unknown";
  return String(k).replace(/^FailureKind\./i,"").toLowerCase();
}

function buildFailureKindStats(traces,evals){
  const counts={};
  const bump=(kind)=>{
    const k=normFailureKind(kind);
    counts[k]=(counts[k]||0)+1;
  };
  traces.filter(t=>t.status==="failed").forEach(t=>bump(t.failure_kind||"unknown"));
  (evals[0]?.case_results||[]).filter(cr=>!cr.passed).forEach(cr=>bump(cr.failure_kind||"unknown"));
  return Object.entries(counts).sort((a,b)=>b[1]-a[1]);
}

function failureKindLabel(kind){
  return kind.replace(/_/g," ");
}

function FailureKindPanel({stats,total,onViewAlerts,loading}){
  if(loading)return null;
  if(!stats.length)return(
    <Section title="Failure taxonomy" subtitle="No classified failures in recent traces or evals">
      <div style={{fontSize:13,color:M.gray600,lineHeight:1.55}}>
        When agents fail, CortexOps classifies the root cause — tool mismatch, timeout, hallucination, and more. Failed production traces can be promoted to golden cases in one click.
      </div>
    </Section>
  );
  const max=Math.max(...stats.map(([,n])=>n),1);
  return(
    <Section title="Failure taxonomy" subtitle={`${total} classified failure${total!==1?"s":""} in loaded traces & latest eval`}
      action={onViewAlerts?<button onClick={onViewAlerts} style={{background:"none",border:"none",color:M.blue,fontSize:12,fontWeight:600,cursor:"pointer"}}>View alerts →</button>:null}>
      <div style={{display:"grid",gap:10}}>
        {stats.map(([kind,count])=>{
          const color=FAILURE_KIND_COLORS[kind]||M.gray500;
          const pct=Math.round((count/max)*100);
          return(
            <div key={kind} style={{display:"grid",gridTemplateColumns:"140px 1fr 36px",gap:12,alignItems:"center"}}>
              <span style={{fontSize:12,fontFamily:M.mono,color:M.gray800,textTransform:"capitalize"}}>{failureKindLabel(kind)}</span>
              <div style={{height:10,background:M.gray200,borderRadius:5,overflow:"hidden"}}>
                <div style={{width:`${pct}%`,minWidth:count?`${Math.max(8,pct)}%`:"0",height:"100%",background:color,borderRadius:5}}/>
              </div>
              <span style={{fontSize:12,fontFamily:M.mono,color,fontWeight:600,textAlign:"right"}}>{count}</span>
            </div>
          );
        })}
      </div>
      <div style={{marginTop:12,fontSize:12,color:M.gray500}}>Promote any failed trace to your golden dataset to block regressions in CI.</div>
    </Section>
  );
}

function WaterfallPanel({trace,onClose,loading,datasets,token,onPromoted}){
  const raw=trace.raw_trace||{};const nodes=raw.nodes||[];
  const maxMs=Math.max(...nodes.map(n=>n.latency_ms||0),trace.total_latency_ms||1);
  const copyId=()=>{if(trace.trace_id)navigator.clipboard?.writeText(trace.trace_id);};
  const[promoteDs,setPromoteDs]=useState("");
  const[promoting,setPromoting]=useState(false);
  const[promoteOk,setPromoteOk]=useState("");
  const[promoteErr,setPromoteErr]=useState("");
  useEffect(()=>{
    if(datasets?.length&&!promoteDs)setPromoteDs(datasets[0].id);
  },[datasets,promoteDs]);
  useEffect(()=>{
    const onKey=e=>{if(e.key==="Escape")onClose();};
    window.addEventListener("keydown",onKey);
    return()=>window.removeEventListener("keydown",onKey);
  },[onClose]);
  const promote=async()=>{
    if(!token||!promoteDs||!trace?.trace_id)return;
    setPromoting(true);setPromoteErr("");setPromoteOk("");
    try{
      const res=await apiFetch(token,`/v1/eval/datasets/${promoteDs}/cases/from-trace`,{
        method:"POST",
        body:JSON.stringify({trace_id:trace.trace_id}),
      });
      setPromoteOk(`Added ${res.case_id} to ${res.dataset_name} (${res.case_count} cases)`);
      onPromoted?.(res);
    }catch(e){setPromoteErr(e.message);}
    finally{setPromoting(false);}
  };
  const canPromote=!!token&&datasets?.length>0;
  return(
    <div className="trace-panel" style={{position:"fixed",top:0,right:0,bottom:0,width:560,background:M.white,borderLeft:`1px solid ${M.gray200}`,zIndex:100,display:"flex",flexDirection:"column",boxShadow:"-4px 0 24px rgba(0,0,0,.35)",animation:"slideIn .2s ease"}}>
      <div style={{padding:"16px 20px",borderBottom:`1px solid ${M.gray200}`,display:"flex",alignItems:"flex-start",justifyContent:"space-between",gap:12}}>
        <div style={{minWidth:0}}>
          <button type="button" onClick={onClose} style={{background:"none",border:"none",color:M.blue,fontSize:12,fontWeight:600,cursor:"pointer",padding:0,marginBottom:8}}>← Back</button>
          <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4}}>
            <StatusDot status={trace.status}/>
            <div style={{fontSize:16,fontWeight:600,color:M.gray900}}>Trace detail</div>
            <Badge color={trace.status==="failed"?M.red:M.green} bg={trace.status==="failed"?M.redLight:M.greenLight}>{trace.status}</Badge>
          </div>
          <button onClick={copyId} title="Copy trace ID" style={{background:"none",border:"none",padding:0,cursor:"pointer",fontFamily:M.mono,fontSize:11,color:M.gray500,textAlign:"left"}}>{trace.trace_id} (copy)</button>
          <div style={{fontSize:11,color:M.gray500,marginTop:4}}>{formatWhen(trace.created_at)} · {timeAgo(trace.created_at)}</div>
        </div>
        <button onClick={onClose} style={{background:M.gray100,border:"none",borderRadius:8,width:34,height:34,cursor:"pointer",fontSize:18,color:M.gray600,flexShrink:0}}>×</button>
      </div>
      <div style={{flex:1,overflow:"auto",padding:"16px 20px"}}>
        {loading&&<div style={{fontSize:13,color:M.gray500,marginBottom:12}}>Loading trace detail…</div>}
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:18}}>
          {[["Latency",`${Math.round(trace.total_latency_ms||0)}ms`,M.amber,M.amberLight],
            ["Environment",trace.environment||"development",M.cyan,M.cyanLight],
            ["Case",trace.case_id||"live trace",M.gray700,M.gray100],
            ["Failure",trace.failure_kind?.replace("FailureKind.","")||"none",trace.failure_kind?M.red:M.gray600,trace.failure_kind?M.redLight:M.gray100]
          ].map(([l,v,c,bg])=>(
            <div key={l} style={{background:bg,borderRadius:8,padding:"10px 12px",border:`1px solid ${M.gray200}`}}>
              <div style={{fontSize:10,color:M.gray600,textTransform:"uppercase",letterSpacing:".06em",marginBottom:3,fontWeight:600}}>{l}</div>
              <div style={{fontSize:13,fontFamily:l==="Case"?M.sans:M.mono,color:c,fontWeight:500,wordBreak:"break-word"}}>{v}</div>
            </div>
          ))}
        </div>
        {raw.input&&(
          <div style={{marginBottom:18}}>
            <div style={{fontSize:11,color:M.gray600,textTransform:"uppercase",letterSpacing:".07em",marginBottom:8,fontWeight:600}}>Input</div>
            <div style={{background:M.gray50,borderRadius:8,padding:12,border:`1px solid ${M.gray200}`,fontFamily:M.mono,fontSize:12,color:M.gray900,whiteSpace:"pre-wrap",wordBreak:"break-word"}}>
              {typeof raw.input==="string"?raw.input:JSON.stringify(raw.input,null,2)}
            </div>
          </div>
        )}
        {nodes.length>0&&(
          <div style={{marginBottom:20}}>
            <div style={{fontSize:11,color:M.gray600,textTransform:"uppercase",letterSpacing:".07em",marginBottom:10,fontWeight:600}}>Node waterfall</div>
            {nodes.map((n,i)=>{
              const w=Math.max(2,(n.latency_ms/maxMs)*100);
              const base=TRACE_NODE_COLORS[i%TRACE_NODE_COLORS.length];
              const c=n.latency_ms>1000?M.red:n.latency_ms>500?M.amber:base;
              const bg=n.latency_ms>1000?M.redLight:n.latency_ms>500?M.amberLight:`${c}22`;
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
            <div style={{background:M.gray50,borderRadius:8,padding:12,border:`1px solid ${M.gray200}`,borderLeft:`4px solid ${M.cyan}`,fontFamily:M.mono,fontSize:12,color:M.gray900,whiteSpace:"pre-wrap",wordBreak:"break-all",maxHeight:180,overflow:"auto"}}>
              {JSON.stringify(raw.output,null,2)}
            </div>
          </div>
        )}
        {trace.failure_detail&&(
          <div style={{marginBottom:16}}>
            <div style={{fontSize:11,color:M.gray600,textTransform:"uppercase",letterSpacing:".07em",marginBottom:8,fontWeight:600}}>Failure detail</div>
            <div style={{background:M.redLight,borderRadius:8,padding:12,border:"1px solid rgba(197,34,31,.2)",fontFamily:M.mono,fontSize:12,color:M.red}}>{trace.failure_detail}</div>
          </div>
        )}
        <div style={{marginTop:8,padding:"14px 0 0",borderTop:`1px solid ${M.gray200}`}}>
          <div style={{fontSize:11,color:M.gray600,textTransform:"uppercase",letterSpacing:".07em",fontWeight:600,marginBottom:8}}>Add to golden dataset</div>
          <div style={{fontSize:12,color:M.gray600,marginBottom:10,lineHeight:1.5}}>
            Turn this production trace into a CI eval case — input, tool calls, and failure context are captured automatically.
          </div>
          {!canPromote&&<div style={{fontSize:12,color:M.gray500}}>Sync a dataset first: <span style={{fontFamily:M.mono}}>python run_eval.py --sync-only</span></div>}
          {canPromote&&(
            <div style={{display:"flex",gap:8,flexWrap:"wrap",alignItems:"center"}}>
              <select value={promoteDs} onChange={e=>setPromoteDs(e.target.value)}
                style={{flex:1,minWidth:160,background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:6,padding:"8px 10px",fontSize:12,color:M.gray900}}>
                {datasets.map(d=><option key={d.id} value={d.id}>{d.name} ({d.case_count} cases)</option>)}
              </select>
              <button onClick={promote} disabled={promoting||!promoteDs}
                style={{background:M.brand,color:M.ink,border:"none",borderRadius:6,padding:"8px 14px",fontSize:12,fontWeight:600,cursor:promoting?"wait":"pointer",opacity:promoting?.6:1}}>
                {promoting?"Adding…":"Add golden case"}
              </button>
            </div>
          )}
          {promoteOk&&<div style={{marginTop:10,fontSize:12,color:M.green,background:M.greenLight,padding:"8px 10px",borderRadius:6}}>{promoteOk}</div>}
          {promoteErr&&<div style={{marginTop:10,fontSize:12,color:M.red,background:M.redLight,padding:"8px 10px",borderRadius:6}}>{promoteErr}</div>}
        </div>
      </div>
    </div>
  );
}

function LogoMark({size=32}){
  return(
    <div style={{width:size,height:size,background:M.brand,borderRadius:8,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
      <svg width={size*0.56} height={size*0.56} viewBox="0 0 20 20" fill="none">
        <path d="M10 2.5 Q14 10 10 17.5" stroke={M.ink} strokeWidth="1.8" strokeLinecap="round"/>
        <path d="M6 2.5 Q10.5 10 6 17.5" stroke={M.ink} strokeWidth="1.8" strokeLinecap="round" opacity=".45"/>
        <circle cx="10" cy="2.5" r="1.8" fill={M.ink}/>
        <circle cx="10" cy="17.5" r="1.8" fill={M.ink}/>
      </svg>
    </div>
  );
}

function ObsBg(){
  if(typeof window!=="undefined"&&window.matchMedia("(prefers-reduced-motion: reduce)").matches)return null;
  const items=["trace.ingest OK · 142ms","eval.gate PASS · 98.2%","node.tool_lookup · 890ms","span.PaymentAgent active","webhook.alert queued","p95 latency · 1.2s","quota.used · 12%","ci.gate blocking deploy","replay.trace matched","metric.error_rate · 0.4%"];
  const wave="M0,20 Q25,5 50,18 T100,12 T150,20 T200,8 L200,40 L0,40 Z";
  return(
    <div className="obs-bg" aria-hidden="true">
      <div className="obs-glow"/>
      <div className="obs-grid"/>
      <div className="obs-scan-v"/>
      <div className="obs-scan-h"/>
      <svg className="obs-svg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none" viewBox="0 0 100 100">
        <path className="obs-trace obs-trace-1" d="M0,22 C18,8 32,38 52,18 S82,32 100,14"/>
        <path className="obs-trace obs-trace-2" d="M0,68 C22,82 44,54 66,72 S88,58 100,76"/>
        <path className="obs-trace obs-trace-3" d="M0,44 L28,36 L52,50 L76,38 L100,46"/>
        <path className="obs-trace obs-trace-4" d="M0,58 C30,48 55,62 78,52 S95,60 100,55"/>
      </svg>
      <div className="obs-node" style={{"--x":"11%","--y":"20%","--c":M.blue,"--d":"0s"}}/>
      <div className="obs-node" style={{"--x":"78%","--y":"28%","--c":M.green,"--d":"-1.2s"}}/>
      <div className="obs-node" style={{"--x":"62%","--y":"68%","--c":M.brand,"--d":"-2.4s"}}/>
      <div className="obs-node" style={{"--x":"24%","--y":"72%","--c":M.purple,"--d":"-0.8s"}}/>
      <div className="obs-node" style={{"--x":"88%","--y":"58%","--c":M.cyan,"--d":"-1.8s"}}/>
      <div className="obs-node" style={{"--x":"42%","--y":"14%","--c":M.amber,"--d":"-3s"}}/>
      <div className="obs-ring" style={{"--x":"30%","--y":"38%","--d":"0s"}}/>
      <div className="obs-ring obs-ring-2" style={{"--x":"70%","--y":"62%","--d":"-3.5s"}}/>
      <div className="obs-beacon" style={{"--x":"18%","--y":"48%","--c":M.green,"--d":"0s"}}/>
      <div className="obs-beacon" style={{"--x":"55%","--y":"32%","--c":M.blue,"--d":"-2s"}}/>
      <div className="obs-beacon" style={{"--x":"92%","--y":"42%","--c":M.brand,"--d":"-4s"}}/>
      {["obs-spark-tl","obs-spark-br","obs-spark-mr","obs-spark-bl"].map(cls=>(
        <div key={cls} className={`obs-spark ${cls}`}>{Array.from({length:8},(_,i)=><span key={i}/>)}</div>
      ))}
      <div className="obs-wave obs-wave-top"><svg viewBox="0 0 200 40" preserveAspectRatio="none"><path d={wave} fill="rgba(59,130,246,.35)"/></svg></div>
      <div className="obs-wave obs-wave-btm"><svg viewBox="0 0 200 40" preserveAspectRatio="none"><path d={wave} fill="rgba(220,38,38,.28)"/></svg></div>
      <div className="obs-ticker"><div className="obs-ticker-track">{[...items,...items].map((t,i)=><span key={i}>{t}</span>)}</div></div>
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
    catch(e){
      const msg=e.message||"Invalid API key or unreachable API";
      if(/revoked/i.test(msg)){
        setErr("This API key was revoked or rotated. Create a new key (see docs) and sign in with that key.");
      }else{
        setErr(msg);
      }
    }
    finally{setLoading(false);}
  };
  const inputStyle={width:"100%",background:M.gray50,border:`1px solid ${M.gray300}`,borderRadius:6,color:M.gray900,fontSize:14,padding:"10px 12px",outline:"none"};
  return(
    <div className="obs-shell" style={{minHeight:"100vh",background:M.gray50,color:M.gray900}}>
      <ObsBg/>
      <nav style={{position:"sticky",top:0,zIndex:50,height:64,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"0 32px",borderBottom:`1px solid ${M.gray200}`,background:"rgba(0,0,0,.88)",backdropFilter:"blur(14px)"}}>
        <a href={HOME_URL} style={{display:"flex",alignItems:"center",gap:12,color:M.gray900,textDecoration:"none"}}>
          <LogoMark/>
          <span style={{fontSize:17,fontWeight:700}}>CortexOps</span>
        </a>
        <div className="login-nav-links" style={{display:"flex",alignItems:"center",gap:18,fontSize:14,color:M.gray600}}>
          <a href={`${HOME_URL}/#trusted`} style={{color:"inherit",textDecoration:"none"}}>Trusted by</a>
          <a href={`${HOME_URL}/#frameworks`} style={{color:"inherit",textDecoration:"none"}}>Frameworks</a>
          <a href={`${HOME_URL}/#pricing`} style={{color:"inherit",textDecoration:"none"}}>Pricing</a>
          <a href="https://docs.getcortexops.com" style={{color:"inherit",textDecoration:"none"}}>Docs</a>
          <a href="#login" className="login-cta" style={{background:M.brand,color:M.ink,textDecoration:"none",borderRadius:7,padding:"9px 14px",fontWeight:700,boxShadow:"0 14px 30px rgba(220,38,38,.32)"}}>Open dashboard</a>
        </div>
      </nav>

      <section className="login-hero" style={{maxWidth:1180,margin:"0 auto",padding:"64px 28px 40px",display:"grid",gridTemplateColumns:"minmax(0,1fr) minmax(320px,420px)",gap:48,alignItems:"center"}}>
        <div>
          <div style={{display:"inline-flex",alignItems:"center",gap:8,background:M.greenLight,border:"1px solid rgba(34,197,94,.22)",color:M.green,borderRadius:99,padding:"6px 12px",fontSize:12,fontFamily:M.mono,marginBottom:22}}>
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
            <a href="#login" style={{background:M.brand,color:M.ink,textDecoration:"none",borderRadius:7,padding:"12px 18px",fontWeight:700,boxShadow:"0 14px 30px rgba(220,38,38,.32)"}}>Open dashboard</a>
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
              onFocus={e=>e.target.style.borderColor=M.brand}
              onBlur={e=>e.target.style.borderColor=M.gray300}
            />
          </div>
          <p style={{fontSize:12,color:M.gray500,marginBottom:14}}>Project is resolved from your key after login. Rotated or revoked keys cannot be reused.</p>
          {err&&<div style={{background:M.redLight,color:M.red,fontSize:13,padding:"8px 12px",borderRadius:6,marginBottom:14,border:"1px solid rgba(242,109,109,.25)"}}>{err}</div>}
          <button onClick={submit} disabled={loading||!key}
            style={{width:"100%",background:M.brand,color:M.ink,border:"none",borderRadius:7,padding:12,fontSize:15,fontWeight:700,cursor:loading||!key?"not-allowed":"pointer",opacity:loading||!key?.5:1,boxShadow:"0 14px 30px rgba(220,38,38,.32)"}}>
            {loading?"Connecting…":"Open dashboard →"}
          </button>
          <p style={{color:M.gray500,fontSize:12,marginTop:16,textAlign:"center"}}>
            <a href={HOME_URL} style={{color:M.brandSoft}}>getcortexops.com</a>
            {" · "}
            <a href={`${HOME_URL}/?trial=1`} style={{color:M.brandSoft}}>Get Pro key</a>
          </p>
        </div>
      </section>

      <section style={{maxWidth:1180,margin:"0 auto",padding:"0 28px 48px"}}>
        <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:14,overflow:"hidden",position:"relative",boxShadow:M.shadow2}}>
          <div style={{position:"absolute",inset:0,pointerEvents:"none",background:"linear-gradient(110deg,transparent 35%,rgba(220,38,38,.12) 50%,transparent 65%)",animation:"scan 4s ease-in-out infinite"}}/>
          <div style={{padding:"14px 16px",borderBottom:`1px solid ${M.gray200}`,display:"flex",alignItems:"center",justifyContent:"space-between"}}>
            <div style={{fontFamily:M.mono,fontSize:13}}>Hero Dashboard</div>
            <div style={{display:"flex",gap:8}}>
              <span style={{background:M.greenLight,color:M.green,borderRadius:99,padding:"4px 9px",fontSize:11,fontWeight:700,animation:"breathe 2.2s infinite"}}>Success badge</span>
              <span style={{background:M.redLight,color:M.red,borderRadius:99,padding:"4px 9px",fontSize:11,fontWeight:700,animation:"pulseSoft 1.8s infinite"}}>Failure badge</span>
            </div>
          </div>
          <div style={{padding:16}}>
            <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:14}}>
              {[["Node","running...","#F59E0B"],["Latency","updating...","#3B82F6"],["Health Score","changing...","#22C55E"]].map(([l,v,c])=>(
                <div key={l} style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:8,padding:"10px 11px"}}>
                  <div style={{fontSize:10,color:M.gray500,fontFamily:M.mono,marginBottom:4}}>{l}</div>
                  <div style={{fontSize:13,color:c,fontFamily:M.mono,fontWeight:700,animation:"fadePulse 1.6s ease-in-out infinite"}}>{v}</div>
                </div>
              ))}
            </div>
            {[
              ["classify_intent","78%","#3B82F6","1.18s",0],
              ["tool call animated...","32%","#8B5CF6","active",12],
              ["evaluate_policy","52%","#22C55E","890ms",24],
              ["tool: issue_refund","88%","#EF4444","2.01s",36],
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
  {section:"Monitor",items:[
    ["overview","Overview"],
    ["traces","Traces"],
    ["activity","Activity"],
    ["alerts","Alerts"],
    ["metrics","Metrics"],
  ]},
  {section:"Quality",items:[
    ["evaluations","Evaluations"],
    ["prompts","Prompt Versions"],
    ["datasets","Datasets"],
  ]},
  {section:"Manage",items:[
    ["projects","Projects"],
    ["api-keys","API Keys"],
    ["usage","Usage"],
    ["settings","Settings"],
  ]},
];

const TAB_HINTS={
  overview:"Production health at a glance — traces, evals, and alerts.",
  traces:"Browse and inspect agent runs — filter by status, date range, or search.",
  activity:"Everything you do in this dashboard during the current browser session.",
  evaluations:"Golden dataset results and pass rates over time.",
  prompts:"Track prompt versions linked to eval runs.",
  datasets:"Golden cases for CI and local eval gates.",
  metrics:"Latency, errors, and drift in one view.",
  alerts:"Failed traces and quality drops needing attention.",
  "api-keys":"Rotate or revoke keys for this project.",
  usage:"Quota, retention, and plan limits.",
  projects:"Workspace bound to your API key.",
  settings:"Refresh, API endpoint, and session.",
};

const VALID_TABS=new Set(NAV.flatMap(g=>g.items.map(([id])=>id)));
const TAB_LABELS=Object.fromEntries(NAV.flatMap(g=>g.items));

const ACTIVITY_STYLE={
  auth:{color:M.green,bg:M.greenLight},
  nav:{color:M.blue,bg:M.blueLight},
  trace:{color:M.purple,bg:M.purpleLight},
  key:{color:M.amber,bg:M.amberLight},
  eval:{color:M.cyan,bg:M.cyanLight},
  filter:{color:M.gray800,bg:M.gray100},
  settings:{color:M.gray700,bg:M.gray100},
};

function parseRoute(hash){
  const raw=(hash||"#/overview").replace(/^#/,"");
  const [path,query]=raw.split("?");
  const tab=(path.replace(/^\//,"")||"overview").split("/")[0];
  const traceId=query?new URLSearchParams(query).get("trace"):null;
  return{tab:VALID_TABS.has(tab)?tab:"overview",traceId};
}

function buildRoute(tab,traceId){
  const base=tab==="overview"?"#/overview":`#/${tab}`;
  return traceId?`${base}?trace=${encodeURIComponent(traceId)}`:base;
}

function EmptyState({title,body,hint}){
  return(
    <div style={{padding:"48px 24px",textAlign:"center",color:M.gray600}}>
      <div style={{fontSize:16,fontWeight:500,color:M.gray900,marginBottom:8}}>{title}</div>
      <div style={{fontSize:14,maxWidth:420,margin:"0 auto",lineHeight:1.55}}>{body}</div>
      {hint&&<div style={{fontFamily:M.mono,fontSize:13,color:M.gray500,marginTop:12}}>{hint}</div>}
    </div>
  );
}

function latencyPercentile(traces,pct){
  if(!traces.length)return 0;
  const asc=[...traces].sort((a,b)=>(a.total_latency_ms||0)-(b.total_latency_ms||0));
  const idx=Math.min(asc.length-1,Math.max(0,Math.ceil(asc.length*(pct/100))-1));
  return Math.round(asc[idx]?.total_latency_ms||0);
}

function latencyColor(ms){
  if(ms>2000)return M.red;
  if(ms>1000)return M.amber;
  return M.blue;
}

const METRIC_LABELS={
  task_completion:"Task completion",
  eval_gate:"Eval gate",
  error_rate:"Error rate",
  health_score:"Health score",
  avg_latency:"Avg latency",
  p95_latency:"P95 latency",
  p99_latency:"P99 latency",
  total_traces:"Total traces",
  regressions:"Regressions",
};

function MetricDrilldown({focus,traces,evals,latest,prev,failed,errRate,successRate,healthPct,completed,evalPassing,avgLat,p50,p95,p99,minLat,maxLat,quota,onOpenTrace,onGoTab,onClear}){
  const sorted=[...traces].sort((a,b)=>(b.total_latency_ms||0)-(a.total_latency_ms||0));
  const aboveP95=sorted.filter(t=>(t.total_latency_ms||0)>=p95);
  const aboveP99=sorted.filter(t=>(t.total_latency_ms||0)>=p99);
  const failedTraces=traces.filter(t=>t.status==="failed");
  const latBuckets=traces.slice(0,32).reverse().map(t=>t.total_latency_ms||0);
  const percentileRows=[["Min",`${minLat}ms`],["P50",`${p50}ms`],["Avg",`${avgLat}ms`],["P95",`${p95}ms`],["P99",`${p99}ms`],["Max",`${maxLat}ms`]];

  return(
    <Section
      title={METRIC_LABELS[focus]||"Metric drilldown"}
      subtitle="Detailed breakdown for this signal"
      action={<button onClick={onClear} style={{background:"none",border:"none",color:M.blue,fontSize:12,fontWeight:600,cursor:"pointer"}}>← Close drilldown</button>}
    >
      {(focus==="task_completion"||focus==="eval_gate")&&(
        <div style={{display:"grid",gap:14}}>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:10}}>
            <DetailRow label="Gate status" value={latest?(evalPassing?"Passing":"Failing"):"—"} mono/>
            <DetailRow label="Latest run" value={latest?`${((latest.task_completion_rate||0)*100).toFixed(1)}%`:"—"} mono/>
            <DetailRow label="Cases passed" value={latest?`${latest.passed}/${latest.total_cases}`:"—"} mono/>
            <DetailRow label="Threshold" value="90%" mono/>
            <DetailRow label="vs previous" value={prev&&latest?`${((latest.task_completion_rate-prev.task_completion_rate)*100).toFixed(1)} pts`:"—"} mono/>
            <DetailRow label="Regressions" value={latest?String(latest.regressions??0):"—"} mono/>
          </div>
          {latest?.case_results?.length>0&&(
            <div style={{display:"grid",gap:6}}>
              {latest.case_results.map(cr=>(
                <div key={cr.case_id} style={{display:"flex",alignItems:"center",gap:10,padding:"8px 10px",background:M.gray50,borderRadius:8,border:`1px solid ${M.gray200}`}}>
                  <Badge color={cr.passed?M.green:M.red} bg={cr.passed?M.greenLight:M.redLight}>{cr.passed?"PASS":"FAIL"}</Badge>
                  <span style={{flex:1,fontFamily:M.mono,fontSize:12}}>{cr.case_id}</span>
                  <LatencyChip ms={cr.latency_ms||0}/>
                </div>
              ))}
            </div>
          )}
          <QuickLink label="Open evaluations" onClick={()=>onGoTab("evaluations")} color={M.green}/>
        </div>
      )}

      {focus==="error_rate"&&(
        <div style={{display:"grid",gap:14}}>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:10}}>
            <DetailRow label="Error rate" value={`${errRate}%`} mono/>
            <DetailRow label="Failed traces" value={String(failed)} mono/>
            <DetailRow label="Success rate" value={traces.length?`${(((traces.length-failed)/traces.length)*100).toFixed(1)}%`:"—"} mono/>
          </div>
          <MiniBars values={traces.slice(0,24).reverse().map(t=>t.status==="failed"?100:0)} color={M.red} h={40}/>
          {failedTraces.length>0?failedTraces.slice(0,8).map(t=>(
            <TraceRow key={t.trace_id} trace={t} onClick={()=>onOpenTrace(t)}/>
          )):<EmptyState title="No failures" body="All loaded traces succeeded."/>}
          {failed>0&&<QuickLink label="Review all alerts" onClick={()=>onGoTab("alerts")} color={M.red}/>}
        </div>
      )}

      {(focus==="avg_latency"||focus==="p95_latency"||focus==="p99_latency")&&(
        <div style={{display:"grid",gap:14}}>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:10}}>
            {percentileRows.map(([l,v])=><DetailRow key={l} label={l} value={v} mono/>)}
          </div>
          <MiniBars values={latBuckets} color={latencyColor(focus==="p99_latency"?p99:focus==="p95_latency"?p95:avgLat)} h={56}/>
          {focus==="avg_latency"&&<div style={{fontSize:12,color:M.gray600}}>Mean latency across {traces.length} loaded traces.</div>}
          {focus==="p95_latency"&&<div style={{fontSize:12,color:M.gray600}}>{aboveP95.length} trace{aboveP95.length!==1?"s":""} at or above P95 ({p95}ms) — slowest 5% of loaded sample.</div>}
          {focus==="p99_latency"&&<div style={{fontSize:12,color:M.gray600}}>{aboveP99.length} trace{aboveP99.length!==1?"s":""} at or above P99 ({p99}ms) — slowest 1% of loaded sample.</div>}
          {(focus==="p95_latency"?aboveP95:focus==="p99_latency"?aboveP99:sorted.slice(0,10)).map(t=>(
            <TraceRow key={t.trace_id} trace={t} onClick={()=>onOpenTrace(t)}/>
          ))}
          <QuickLink label="Open traces" onClick={()=>onGoTab("traces")}/>
        </div>
      )}

      {focus==="health_score"&&(
        <div style={{display:"grid",gap:14}}>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:10}}>
            <DetailRow label="Health score" value={successRate!=="—"?`${successRate}%`:"—"} mono/>
            <DetailRow label="Succeeded" value={`${completed}/${traces.length}`} mono/>
            <DetailRow label="Failed" value={String(failed)} mono/>
          </div>
          <MiniBars values={traces.slice(0,24).reverse().map(t=>t.status==="failed"?0:100)} color={M.green} h={40}/>
          {traces.filter(t=>t.status!=="failed").slice(0,6).map(t=>(
            <TraceRow key={t.trace_id} trace={t} onClick={()=>onOpenTrace(t)}/>
          ))}
          {failed>0&&<QuickLink label="Review failures" onClick={()=>onGoTab("alerts")} color={M.red}/>}
        </div>
      )}

      {focus==="regressions"&&(
        <div style={{display:"grid",gap:14}}>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:10}}>
            <DetailRow label="Regressions" value={latest?String(latest.regressions??0):"—"} mono/>
            <DetailRow label="Latest completion" value={latest?`${((latest.task_completion_rate||0)*100).toFixed(1)}%`:"—"} mono/>
            <DetailRow label="Previous completion" value={prev?`${((prev.task_completion_rate||0)*100).toFixed(1)}%`:"—"} mono/>
          </div>
          {latest?.case_results?.filter(cr=>!cr.passed).length>0?(
            latest.case_results.filter(cr=>!cr.passed).map(cr=>(
              <div key={cr.case_id} style={{display:"flex",alignItems:"center",gap:10,padding:"8px 10px",background:M.redLight,borderRadius:8,border:`1px solid rgba(239,68,68,.25)`}}>
                <Badge color={M.red} bg={M.redLight}>FAIL</Badge>
                <span style={{flex:1,fontFamily:M.mono,fontSize:12}}>{cr.case_id}</span>
                {cr.failure_kind&&<span style={{fontSize:10,color:M.red,fontFamily:M.mono}}>{cr.failure_kind.replace("FailureKind.","")}</span>}
              </div>
            ))
          ):<EmptyState title="No regressions" body="Latest eval run is stable versus the previous run."/>}
          <QuickLink label="Open evaluations" onClick={()=>onGoTab("evaluations")} color={M.amber}/>
        </div>
      )}

      {focus==="total_traces"&&(
        <div style={{display:"grid",gap:14}}>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:10}}>
            <DetailRow label="Loaded traces" value={String(traces.length)} mono/>
            <DetailRow label="Completed" value={String(traces.length-failed)} mono/>
            <DetailRow label="Failed" value={String(failed)} mono/>
            <DetailRow label="This month" value={quota?.monthly_traces?.used?.toLocaleString()??"—"} mono/>
            <DetailRow label="Plan limit" value={quota?.monthly_traces?.unlimited?"Unlimited":(quota?.monthly_traces?.limit?.toLocaleString()??"5,000")} mono/>
            <DetailRow label="Retention" value={`${quota?.retention_days??7} days`} mono/>
          </div>
          <MiniBars values={traces.slice(0,24).map(()=>1)} color={M.blue} h={36}/>
          <QuickLink label="Browse all traces" onClick={()=>onGoTab("traces")}/>
        </div>
      )}
    </Section>
  );
}

function HamburgerIcon(){
  return(
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M4 7h16M4 12h16M4 17h16"/>
    </svg>
  );
}

function DeltaStat({label,value,unit,goodWhenPositive=true}){
  const n=typeof value==="number"?value:parseFloat(value)||0;
  const flat=Math.abs(n)<0.0001;
  const positive=goodWhenPositive?n>0:n<0;
  const color=flat?M.gray500:positive?M.green:M.red;
  const sign=n>0?"+":"";
  const display=unit==="pp"?`${sign}${(n*100).toFixed(1)}pp`:unit==="pts"?`${sign}${n.toFixed(1)} pts`:unit==="ms"?`${sign}${Math.round(n)}ms`:`${sign}${n.toFixed(1)}`;
  return(
    <div style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:8,padding:"12px 14px"}}>
      <div style={{fontSize:10,color:M.gray500,textTransform:"uppercase",letterSpacing:".06em",fontWeight:600,marginBottom:4}}>{label}</div>
      <div style={{fontSize:20,fontWeight:700,color,fontFamily:M.mono}}>{flat?"—":display}</div>
    </div>
  );
}

function OnboardingChecklist({tracesCount,evalsCount,datasetsCount,onGoTraces,onGoEvals}){
  const steps=[
    {id:"sdk",label:"Install the SDK",detail:"pip install cortexops",done:true,hint:"pip install cortexops"},
    {id:"trace",label:"Send your first trace",detail:"Instrument your agent with CortexTracer",done:tracesCount>0,action:onGoTraces,actionLabel:"View traces"},
    {id:"eval",label:"Run golden evals",detail:"Push dataset + prompt to the dashboard",done:evalsCount>0,action:onGoEvals,actionLabel:"View evals"},
    {id:"dataset",label:"Sync golden dataset",detail:"python run_eval.py --sync-only",done:datasetsCount>0},
  ];
  const doneCount=steps.filter(s=>s.done).length;
  if(doneCount>=steps.length)return null;
  return(
    <div style={{background:`linear-gradient(135deg, ${M.blueLight} 0%, ${M.white} 70%)`,border:`1px solid ${M.gray200}`,borderRadius:12,padding:"18px 20px",boxShadow:M.shadow1}}>
      <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",gap:12,marginBottom:14,flexWrap:"wrap"}}>
        <div>
          <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".08em",fontWeight:700,marginBottom:4}}>Getting started</div>
          <div style={{fontSize:16,fontWeight:600,color:M.gray900}}>Set up your project ({doneCount}/{steps.length})</div>
          <div style={{fontSize:13,color:M.gray600,marginTop:4}}>Complete these steps to populate traces, evals, and datasets.</div>
        </div>
        <div style={{height:8,width:120,background:M.gray200,borderRadius:4,overflow:"hidden",marginTop:6}}>
          <div style={{width:`${(doneCount/steps.length)*100}%`,height:"100%",background:M.blue,borderRadius:4,transition:"width .3s ease"}}/>
        </div>
      </div>
      <div style={{display:"grid",gap:8}}>
        {steps.map((s,i)=>(
          <div key={s.id} style={{display:"flex",alignItems:"flex-start",gap:12,padding:"10px 12px",background:M.white,borderRadius:8,border:`1px solid ${M.gray200}`}}>
            <div style={{width:22,height:22,borderRadius:"50%",flexShrink:0,display:"flex",alignItems:"center",justifyContent:"center",fontSize:12,fontWeight:700,background:s.done?M.greenLight:M.gray100,color:s.done?M.green:M.gray500,border:`1px solid ${s.done?M.green:M.gray300}`}}>
              {s.done?"✓":i+1}
            </div>
            <div style={{flex:1,minWidth:0}}>
              <div style={{fontSize:14,fontWeight:600,color:M.gray900,marginBottom:2}}>{s.label}</div>
              <div style={{fontSize:12,color:M.gray600,lineHeight:1.45}}>{s.detail}</div>
              {s.hint&&<div style={{fontFamily:M.mono,fontSize:11,color:M.gray500,marginTop:4}}>{s.hint}</div>}
            </div>
            {s.action&&!s.done&&<button onClick={s.action} style={{background:M.blueLight,color:M.blue,border:"none",borderRadius:6,padding:"6px 10px",fontSize:12,fontWeight:600,cursor:"pointer",flexShrink:0}}>{s.actionLabel}</button>}
          </div>
        ))}
      </div>
    </div>
  );
}

function EvalDiffPanel({diff,runA,runB,loading,error,onClose}){
  if(!diff&&!loading&&!error)return null;
  const mapA=Object.fromEntries((runA?.case_results||[]).map(c=>[c.case_id,c]));
  const mapB=Object.fromEntries((runB?.case_results||[]).map(c=>[c.case_id,c]));
  const renderCase=(cid,kind)=>{
    const a=mapA[cid],b=mapB[cid];
    const color=kind==="regression"?M.red:M.green;
    const bg=kind==="regression"?M.redLight:M.greenLight;
    return(
      <div key={cid} style={{display:"flex",alignItems:"flex-start",gap:10,padding:"10px 0",borderBottom:`1px solid ${M.gray200}`}}>
        <Badge color={color} bg={bg}>{kind==="regression"?"REGRESSED":"IMPROVED"}</Badge>
        <div style={{flex:1,minWidth:0}}>
          <div style={{fontFamily:M.mono,fontSize:12,fontWeight:600,color:M.gray800,marginBottom:4}}>{cid}</div>
          <div style={{display:"flex",gap:14,flexWrap:"wrap",fontSize:11,color:M.gray500}}>
            <span>Score: <span style={{fontFamily:M.mono,color:M.gray800}}>{(a?.score??0).toFixed(1)}</span> → <span style={{fontFamily:M.mono,color}}>{(b?.score??0).toFixed(1)}</span></span>
            <span>Pass: <span style={{fontFamily:M.mono,color:M.gray800}}>{a?.passed?"yes":"no"}</span> → <span style={{fontFamily:M.mono,color:b?.passed?M.green:M.red}}>{b?.passed?"yes":"no"}</span></span>
            {b?.failure_detail&&<span style={{color:M.red,fontFamily:M.mono}}>{b.failure_detail}</span>}
          </div>
        </div>
      </div>
    );
  };
  return(
    <div style={{borderBottom:`1px solid ${M.gray200}`,background:M.gray50,padding:"16px 18px"}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,marginBottom:14}}>
        <div>
          <div style={{fontSize:14,fontWeight:600,color:M.gray900}}>Run comparison</div>
          <div style={{fontSize:12,color:M.gray600,marginTop:2,fontFamily:M.mono}}>
            {runA?.run_id?.slice(0,8)} (baseline) → {runB?.run_id?.slice(0,8)} (current)
          </div>
        </div>
        <button onClick={onClose} style={{background:M.gray100,border:`1px solid ${M.gray200}`,borderRadius:6,padding:"6px 10px",fontSize:12,cursor:"pointer",color:M.gray700}}>Close</button>
      </div>
      {loading&&<div style={{fontSize:13,color:M.gray500}}>Computing diff…</div>}
      {error&&<div style={{fontSize:13,color:M.red,background:M.redLight,padding:"10px 12px",borderRadius:6}}>{error}</div>}
      {diff&&!loading&&(
        <>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:10,marginBottom:16}}>
            <DeltaStat label="Task completion" value={diff.task_completion_delta} unit="pp"/>
            <DeltaStat label="Tool accuracy" value={diff.tool_accuracy_delta} unit="pts"/>
            <DeltaStat label="P95 latency" value={diff.latency_p95_delta_ms} unit="ms" goodWhenPositive={false}/>
          </div>
          {diff.regressions?.length>0&&(
            <div style={{marginBottom:12}}>
              <div style={{fontSize:11,color:M.red,textTransform:"uppercase",letterSpacing:".07em",fontWeight:700,marginBottom:8}}>Regressions ({diff.regressions.length})</div>
              {diff.regressions.map(cid=>renderCase(cid,"regression"))}
            </div>
          )}
          {diff.improvements?.length>0&&(
            <div>
              <div style={{fontSize:11,color:M.green,textTransform:"uppercase",letterSpacing:".07em",fontWeight:700,marginBottom:8}}>Improvements ({diff.improvements.length})</div>
              {diff.improvements.map(cid=>renderCase(cid,"improvement"))}
            </div>
          )}
          {!diff.regressions?.length&&!diff.improvements?.length&&(
            <div style={{fontSize:13,color:M.gray600,padding:"8px 0"}}>No significant case-level score changes between these runs.</div>
          )}
        </>
      )}
    </div>
  );
}

function SidebarNav({tab,setTab,project,tier,live,setLive,refreshSec,setRefreshSec,logout,failed,onNavigate}){
  const go=(id)=>{setTab(id);onNavigate?.();};
  return(
    <>
      <div style={{padding:"16px 16px 12px",borderBottom:`1px solid ${M.gray200}`,flexShrink:0}}>
        <a href={HOME_URL} style={{display:"flex",alignItems:"center",gap:10,marginBottom:12,textDecoration:"none",color:"inherit"}} title="CortexOps home">
          <div style={{width:28,height:28,background:M.brand,borderRadius:6,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
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
        </a>
        <div style={{fontSize:11,color:M.gray500,marginBottom:4}}>Project</div>
        <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:6}}>
          <span style={{fontSize:10,fontWeight:600,textTransform:"uppercase",letterSpacing:".06em",background:tier==="pro"?M.brandLight:M.greenLight,color:tier==="pro"?M.brand:M.green,padding:"2px 7px",borderRadius:4}}>{tier}</span>
        </div>
        <div style={{fontFamily:M.mono,fontSize:12,color:M.gray800,background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:6,padding:"7px 9px",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}} title={project}>{project}</div>
      </div>
      <nav style={{flex:1,minHeight:0,overflow:"auto",padding:"8px 8px 10px"}} aria-label="Dashboard">
        {NAV.map(({section,items})=>(
          <div key={section} style={{marginBottom:12}}>
            <div style={{fontSize:10,color:M.gray400,textTransform:"uppercase",letterSpacing:".08em",fontWeight:600,padding:"4px 12px 6px"}}>{section}</div>
            {items.map(([id,label])=>(
              <button key={id} onClick={()=>go(id)}
                style={{width:"100%",display:"flex",alignItems:"center",justifyContent:"space-between",textAlign:"left",background:tab===id?M.brandLight:"transparent",color:tab===id?M.brand:M.gray700,border:"none",borderRadius:8,padding:"8px 12px",fontSize:13,fontWeight:tab===id?600:500,cursor:"pointer",fontFamily:M.sans,marginBottom:2,gap:10}}>
                <span style={{display:"flex",alignItems:"center",gap:9}}><NavIcon id={id}/>{label}</span>
                {id==="alerts"&&failed>0&&<span style={{background:M.red,color:M.ink,borderRadius:99,fontSize:10,padding:"1px 6px",fontWeight:600,minWidth:18,textAlign:"center"}}>{failed}</span>}
              </button>
            ))}
          </div>
        ))}
      </nav>
      <div style={{padding:"12px 14px",borderTop:`1px solid ${M.gray200}`,flexShrink:0,background:M.white}}>
        <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:8,cursor:"pointer"}} onClick={()=>setLive(l=>!l)}>
          <div style={{width:8,height:8,borderRadius:"50%",background:live?M.green:M.gray400,animation:live?"pulse 1.5s infinite":"none"}}/>
          <span style={{fontSize:12,color:live?M.green:M.gray500,fontWeight:500}}>{live?`Live · ${refreshSec}s`:"Paused"}</span>
        </div>
        {live&&(
          <div style={{display:"flex",gap:4,marginBottom:10}}>
            {REFRESH_OPTIONS.map(sec=>(
              <button key={sec} type="button" onClick={()=>setRefreshSec(sec)}
                style={{flex:1,background:refreshSec===sec?M.blueLight:"transparent",border:`1px solid ${refreshSec===sec?M.blue:M.gray300}`,borderRadius:5,color:refreshSec===sec?M.blue:M.gray500,fontSize:10,fontWeight:refreshSec===sec?600:500,padding:"4px 0",cursor:"pointer"}}>
                {sec}s
              </button>
            ))}
          </div>
        )}
        <button onClick={logout} style={{width:"100%",background:M.gray100,border:`1px solid ${M.gray200}`,borderRadius:6,color:M.gray800,fontSize:13,fontWeight:500,cursor:"pointer",padding:"8px 12px"}}>Sign out</button>
      </div>
    </>
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
  const initRoute=typeof window!=="undefined"?parseRoute(window.location.hash):{tab:"overview",traceId:null};
  const[session,setSession]=useState(null);
  const[authReady,setAuthReady]=useState(false);
  const[tab,setTab]=useState(initRoute.tab);
  const[filter,setFilter]=useState("all");
  const[live,setLive]=useState(true);
  const[refreshSec,setRefreshSecState]=useState(loadRefreshSec);
  const setRefreshSec=useCallback((sec)=>{
    setRefreshSecState(sec);
    localStorage.setItem(REFRESH_KEY,String(sec));
  },[]);
  const[selected,setSelected]=useState(initRoute.traceId?{trace_id:initRoute.traceId}:null);
  const[traceDetail,setTraceDetail]=useState(null);
  const[detailLoading,setDetailLoading]=useState(false);
  const[rotatedKey,setRotatedKey]=useState(null);
  const[actionError,setActionError]=useState("");
  const[actionOk,setActionOk]=useState("");
  const[keyAction,setKeyAction]=useState("");
  const[traceSearch,setTraceSearch]=useState("");
  const[traceDatePreset,setTraceDatePreset]=useState("all");
  const[traceDateFrom,setTraceDateFrom]=useState("");
  const[traceDateTo,setTraceDateTo]=useState("");
  const[expandedEval,setExpandedEval]=useState(null);
  const[expandedDataset,setExpandedDataset]=useState(null);
  const[datasetDetail,setDatasetDetail]=useState(null);
  const[datasetDetailLoading,setDatasetDetailLoading]=useState(false);
  const[navOpen,setNavOpen]=useState(false);
  const[metricFocus,setMetricFocus]=useState(null);
  const[compareMode,setCompareMode]=useState(false);
  const[diffRunA,setDiffRunA]=useState("");
  const[diffRunB,setDiffRunB]=useState("");
  const[evalDiff,setEvalDiff]=useState(null);
  const[diffLoading,setDiffLoading]=useState(false);
  const[diffError,setDiffError]=useState("");
  const[uiActivity,setUiActivity]=useState(()=>loadUiActivity());
  const ref=useRef(null);
  const sessionBoot=useRef(false);

  const track=useCallback((type,label,meta={})=>{
    logUiActivity(type,label,meta);
    setUiActivity(loadUiActivity());
  },[]);

  const token=session?.access_token;
  const sessionKeyId=session?.key_id||keyIdFromToken(token);
  const project=session?.project||"payments-agent";
  const tier=session?.tier||"free";

  useEffect(()=>{
    const initial=loadSession();
    if(!initial){setAuthReady(true);return;}

    const finish=(sess)=>{
      setSession(sess);
      setAuthReady(true);
    };

    if(!sessionExpired(initial)){
      finish(initial);
      if(initial.expires_at-Date.now()<15*60_000){
        ensureSession(initial)
          .then(next=>{saveSession(next);setSession(next);})
          .catch(e=>{if(isAuthError(e)){clearSession();setSession(null);}});
      }
      return;
    }

    ensureSession(initial)
      .then(next=>finish(next))
      .catch(e=>{
        if(!isAuthError(e)&&initial.access_token){
          finish(initial);
          return;
        }
        clearSession();
        setAuthReady(true);
      });
  },[]);

  useEffect(()=>{
    if(!token)return;
    const tick=async()=>{
      const current=loadSession();
      if(!current?.access_token||!sessionExpired(current))return;
      try{
        const next=await refreshSession(current);
        setSession(next);
      }catch(e){
        if(isAuthError(e)){clearSession();setSession(null);}
      }
    };
    const id=setInterval(tick,60_000);
    return()=>clearInterval(id);
  },[token]);

  useEffect(()=>{
    if(!session||!authReady||sessionBoot.current)return;
    sessionBoot.current=true;
    track("auth","Session resumed",{project:session.project,tier:session.tier});
  },[session,authReady,track]);

  const filterInit=useRef(false);
  useEffect(()=>{
    if(!session||tab!=="traces")return;
    if(!filterInit.current){filterInit.current=true;return;}
    track("filter",`Trace filter: ${filter}`,{filter});
  },[filter,session,tab,track]);

  const liveInit=useRef(false);
  useEffect(()=>{
    if(!session)return;
    if(!liveInit.current){liveInit.current=true;return;}
    track("settings",live?"Live refresh on":"Live refresh off",{live,seconds:refreshSec});
  },[live,session,refreshSec,track]);

  useEffect(()=>{
    if(!evalDiff||!session)return;
    track("eval","Compared eval runs",{run_a:diffRunA,run_b:diffRunB});
  },[evalDiff,session,diffRunA,diffRunB,track]);

  const traceDateQuery=tab==="traces"?buildTraceDateQuery(traceDatePreset,traceDateFrom,traceDateTo):"";
  const traceLimit=tab==="traces"&&traceDatePreset!=="all"?500:100;
  const statusQuery=tab==="traces"&&filter!=="all"?`&status=${encodeURIComponent(filter)}`:"";
  const tPath=token?`/v1/traces?project=${encodeURIComponent(project)}&limit=${traceLimit}${statusQuery}${traceDateQuery}`:null;
  const ePath=token?`/v1/evals?project=${encodeURIComponent(project)}&limit=20`:null;
  const qPath=token?"/v1/traces/quota":null;
  const kPath=token?`/v1/keys/${encodeURIComponent(project)}`:null;
  const pPath=token?`/v1/prompts/catalog?project=${encodeURIComponent(project)}`:null;
  const dPath=token?"/v1/eval/datasets":null;

  const{data:rawTraces,loading:tLoad,error:tError,refetch:rT}=useFetch(token,tPath);
  const{data:rawEvals,loading:eLoad,refetch:rE}=useFetch(token,ePath);
  const{data:quota,loading:qLoad,refetch:rQ}=useFetch(token,qPath);
  const{data:rawKeys,loading:kLoad,error:kError,refetch:rK}=useFetch(token,kPath);
  const{data:rawPrompts,loading:pLoad,error:pError,refetch:rP}=useFetch(token,pPath);
  const{data:rawDatasets,loading:dLoad,error:dError,refetch:rD}=useFetch(token,dPath);

  useEffect(()=>{
    if(live&&token){ref.current=setInterval(()=>{rT();rE();rQ();rP();rD();},refreshSec*1000);}
    return()=>clearInterval(ref.current);
  },[live,token,refreshSec,rT,rE,rQ,rP,rD]);

  useEffect(()=>{
    if(!token)return;
    if(tab==="datasets")rD();
    if(tab==="prompts")rP();
  },[tab,token,rD,rP]);

  useEffect(()=>{
    if(!expandedDataset||!token){setDatasetDetail(null);return;}
    let cancelled=false;
    setDatasetDetailLoading(true);
    apiFetch(token,`/v1/eval/datasets/${expandedDataset}`)
      .then(d=>{if(!cancelled)setDatasetDetail(d);})
      .catch(()=>{if(!cancelled)setDatasetDetail(null);})
      .finally(()=>{if(!cancelled)setDatasetDetailLoading(false);});
    return()=>{cancelled=true;};
  },[expandedDataset,token]);

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

  useEffect(()=>{
    if(!compareMode||!diffRunA||!diffRunB||!token){setEvalDiff(null);setDiffError("");return;}
    let cancelled=false;
    setDiffLoading(true);
    setDiffError("");
    apiFetch(token,`/v1/evals/diff?a=${encodeURIComponent(diffRunA)}&b=${encodeURIComponent(diffRunB)}`)
      .then(d=>{if(!cancelled)setEvalDiff(d);})
      .catch(e=>{if(!cancelled){setEvalDiff(null);setDiffError(e.message);}})
      .finally(()=>{if(!cancelled)setDiffLoading(false);});
    return()=>{cancelled=true;};
  },[compareMode,diffRunA,diffRunB,token]);

  useEffect(()=>{if(!navOpen)return;const onKey=e=>{if(e.key==="Escape")setNavOpen(false);};window.addEventListener("keydown",onKey);return()=>window.removeEventListener("keydown",onKey);},[navOpen]);

  const tracesList=Array.isArray(rawTraces)?rawTraces:[];

  useEffect(()=>{
    if(!session)return;
    const h=window.location.hash;
    if(!h||/^#login$/.test(h)){
      history.replaceState({tab:"overview",traceId:null},"","#/overview");
      setTab("overview");
      return;
    }
    const route=parseRoute(h);
    setTab(route.tab);
    if(route.traceId){
      const found=tracesList.find(tr=>tr.trace_id===route.traceId);
      setSelected(found||{trace_id:route.traceId});
    }else{
      setSelected(null);
      setTraceDetail(null);
    }
  },[session?.access_token]);

  useEffect(()=>{
    if(!session)return;
    const onHash=()=>{
      const route=parseRoute(window.location.hash);
      setTab(route.tab);
      setNavOpen(false);
      if(route.traceId){
        const found=tracesList.find(tr=>tr.trace_id===route.traceId);
        setSelected(found||{trace_id:route.traceId});
      }else{
        setSelected(null);
        setTraceDetail(null);
      }
    };
    window.addEventListener("hashchange",onHash);
    return()=>window.removeEventListener("hashchange",onHash);
  },[session,rawTraces]);

  useEffect(()=>{
    if(!session)return;
    const onPop=()=>{
      const route=history.state?.tab
        ?{tab:history.state.tab,traceId:history.state.traceId||null}
        :parseRoute(window.location.hash);
      setTab(route.tab);
      setNavOpen(false);
      if(route.traceId){
        const found=tracesList.find(tr=>tr.trace_id===route.traceId);
        setSelected(found||{trace_id:route.traceId});
      }else{
        setSelected(null);
        setTraceDetail(null);
      }
    };
    window.addEventListener("popstate",onPop);
    return()=>window.removeEventListener("popstate",onPop);
  },[session,rawTraces]);

  useEffect(()=>{
    if(!selected?.trace_id||selected.status)return;
    const found=tracesList.find(tr=>tr.trace_id===selected.trace_id);
    if(found)setSelected(found);
  },[rawTraces,selected?.trace_id,selected?.status]);

  const login=(sess)=>{
    saveSession(sess);setSession(sess);
    sessionBoot.current=true;
    track("auth","Signed in",{project:sess.project,tier:sess.tier});
    history.replaceState({tab:"overview",traceId:null},"","#/overview");
    setTab("overview");setSelected(null);setTraceDetail(null);
  };
  const logout=()=>{
    track("auth","Signed out");
    clearUiActivity();
    setUiActivity([]);
    sessionBoot.current=false;
    clearSession();setSession(null);setSelected(null);setTraceDetail(null);setNavOpen(false);
    history.replaceState(null,"","#login");
  };

  const pushRoute=useCallback((nextTab,traceId=null,replace=false)=>{
    const hash=buildRoute(nextTab,traceId);
    const state={tab:nextTab,traceId};
    if(replace)history.replaceState(state,"",hash);
    else history.pushState(state,"",hash);
  },[]);

  const goTab=useCallback((id,focus=null)=>{
    pushRoute(id,null);
    setTab(id);
    setSelected(null);
    setTraceDetail(null);
    setNavOpen(false);
    setMetricFocus((id==="overview"||id==="metrics")?focus:null);
    if(id!=="traces"){setFilter("all");}
    track("nav",`Opened ${TAB_LABELS[id]||id}`,{tab:id});
  },[pushRoute,track]);

  const openMetricDrill=useCallback((focus)=>{
    setMetricFocus(prev=>prev===focus?null:focus);
    if(tab!=="overview"&&tab!=="metrics"){
      pushRoute("metrics",null);
      setTab("metrics");
      setSelected(null);
      setTraceDetail(null);
      setNavOpen(false);
      track("nav","Opened Metrics",{tab:"metrics",focus});
    }
    track("settings",`Metric drilldown: ${focus}`,{metric:focus});
  },[tab,pushRoute,track]);

  const openTrace=useCallback((t)=>{
    if(!t?.trace_id)return;
    pushRoute(tab,t.trace_id);
    setSelected(t);
    track("trace",`Viewed trace ${t.trace_id.slice(0,8)}`,{trace_id:t.trace_id,status:t.status});
  },[tab,pushRoute,track]);

  const closeTrace=useCallback(()=>{
    pushRoute(tab,null);
    setSelected(null);
    setTraceDetail(null);
    track("trace","Closed trace detail");
  },[tab,pushRoute,track]);

  const rotateKey=async(keyId)=>{
    setActionError("");setActionOk("");setKeyAction(keyId);
    try{
      const res=await apiFetch(token,`/v1/keys/${encodeURIComponent(keyId)}/rotate`,{method:"POST",body:"{}"});
      setRotatedKey(res.new_key);
      if(res.new_key){
        try{
          const next=await issueToken(res.new_key);
          saveSession(next);
          setSession(next);
        }catch(e){
          setActionError(`Key rotated but session refresh failed: ${e.message}. Copy the new key and sign in again.`);
        }
      }
      setActionOk(res.message||"Key rotated successfully.");
      track("key","Rotated API key",{key_id:keyId});
      rK();
    }catch(e){setActionError(e.message);}
    finally{setKeyAction("");}
  };

  const revokeKey=async(keyId)=>{
    if(!window.confirm("Revoke this API key? Apps using it will stop working immediately."))return;
    setActionError("");setActionOk("");setKeyAction(keyId);
    const isCurrent=sessionKeyId&&sessionKeyId===keyId;
    try{
      await apiFetch(token,`/v1/keys/${encodeURIComponent(keyId)}`,{method:"DELETE"});
      if(isCurrent){
        clearSession();
        setSession(null);
        setSelected(null);
        setTraceDetail(null);
        history.replaceState(null,"","#login");
        return;
      }
      setActionOk("API key revoked.");
      track("key","Revoked API key",{key_id:keyId});
      rK();
    }catch(e){setActionError(e.message);}
    finally{setKeyAction("");}
  };

  if(!authReady)return<><style>{G}</style><ObsBg/><div className="obs-shell" style={{minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",color:M.gray600}}>Loading session…</div></>;
  if(!session)return<><style>{G}</style><LoginScreen onLogin={login}/></>;

  const traces=Array.isArray(rawTraces)?rawTraces:[];
  const evals=Array.isArray(rawEvals)?rawEvals:[];
  const latest=evals[0];const prev=evals[1];
  const failed=traces.filter(t=>t.status==="failed").length;
  const errRate=traces.length>0?((failed/traces.length)*100).toFixed(1):"0.0";
  const avgLat=traces.length>0?Math.round(traces.reduce((s,t)=>s+(t.total_latency_ms||0),0)/traces.length):0;
  const p50=latencyPercentile(traces,50);
  const p95=latencyPercentile(traces,95);
  const p99=latencyPercentile(traces,99);
  const tcColor=latencyColor(avgLat);
  const p95Color=latencyColor(p95);
  const p99Color=latencyColor(p99);
  const successRate=traces.length>0?(((traces.length-failed)/traces.length)*100).toFixed(1):"—";
  const keys=Array.isArray(rawKeys)?rawKeys:[];
  const prompts=Array.isArray(rawPrompts)?rawPrompts:[];
  const datasets=Array.isArray(rawDatasets)?rawDatasets:[];
  const activeLabel=NAV.flatMap(g=>g.items).find(([id])=>id===tab)?.[1]||"Overview";
  const tabHint=TAB_HINTS[tab]||"";
  const evalPassing=latest&&latest.task_completion_rate>=.9;
  const healthPct=successRate!=="—"?parseFloat(successRate):null;
  const completed=traces.length-failed;
  const minLat=traces.length?Math.min(...traces.map(t=>t.total_latency_ms||0)):0;
  const maxLat=traces.length?Math.max(...traces.map(t=>t.total_latency_ms||0)):0;
  const latBuckets=traces.slice(0,24).reverse().map(t=>t.total_latency_ms||0);
  const overallStatus=healthPct==null?"unknown":healthPct>=95&&evalPassing!==false&&failed===0?"healthy":healthPct>=80?"degraded":"critical";
  const statusColor={healthy:M.green,degraded:M.amber,critical:M.red,unknown:M.gray500}[overallStatus];
  const statusBg={healthy:M.greenLight,degraded:M.amberLight,critical:M.redLight,unknown:M.gray100}[overallStatus];
  const filteredTraces=traces.filter(t=>{
    if(tab==="traces"&&filter!=="all"&&t.status!==filter)return false;
    if(traceSearch.trim()){
      const q=traceSearch.toLowerCase();
      const match=(t.trace_id||"").toLowerCase().includes(q)||(t.case_id||"").toLowerCase().includes(q)||(t.failure_kind||"").toLowerCase().includes(q);
      if(!match)return false;
    }
    return true;
  });
  const traceDateActive=tab==="traces"&&traceDatePreset!=="all";
  const tracesTabFailed=traces.filter(t=>t.status==="failed").length;
  const tracesTabCompleted=traces.length-tracesTabFailed;
  const tracesTabAvgLat=traces.length>0?Math.round(traces.reduce((s,t)=>s+(t.total_latency_ms||0),0)/traces.length):0;
  const failureKindStats=buildFailureKindStats(traces,evals);
  const failureKindTotal=failureKindStats.reduce((s,[,n])=>s+n,0);
  const quotaPct=quota?.monthly_traces?.percent_used??null;

  const metricDrillPanel=metricFocus?(
    <MetricDrilldown
      focus={metricFocus}
      traces={traces}
      evals={evals}
      latest={latest}
      prev={prev}
      failed={failed}
      errRate={errRate}
      successRate={successRate}
      healthPct={healthPct}
      completed={completed}
      evalPassing={evalPassing}
      avgLat={avgLat}
      p50={p50}
      p95={p95}
      p99={p99}
      minLat={minLat}
      maxLat={maxLat}
      quota={quota}
      onOpenTrace={openTrace}
      onGoTab={goTab}
      onClear={()=>setMetricFocus(null)}
    />
  ):null;

  const metricTiles=(
    <div className="metric-grid" style={{display:"grid",gridTemplateColumns:"repeat(6,minmax(0,1fr))",gap:12}}>
      <Tile label="Task completion" value={latest?`${(latest.task_completion_rate*100).toFixed(1)}`:"—"} unit="%" color={M.green}
        hint={latest?`${latest.passed}/${latest.total_cases} eval cases passed`:"Run evals to populate"}
        spark={evals.slice(0,10).reverse().map(e=>(e.task_completion_rate||0)*100)} loading={eLoad}
        delta={prev?`${Math.abs((latest.task_completion_rate-prev.task_completion_rate)*100).toFixed(1)}%`:undefined}
        deltaUp={prev&&latest.task_completion_rate>=prev.task_completion_rate}
        active={metricFocus==="task_completion"}
        onClick={()=>openMetricDrill("task_completion")}/>
      <Tile label="Error rate" value={errRate} unit="%" color={parseFloat(errRate)>5?M.red:M.green}
        hint={`${failed} failed of ${traces.length} traces`}
        spark={traces.slice(0,20).reverse().map(t=>t.status==="failed"?100:0)} loading={tLoad}
        active={metricFocus==="error_rate"}
        onClick={()=>openMetricDrill("error_rate")}/>
      <Tile label="Avg latency" value={avgLat} unit="ms" color={tcColor}
        hint="Mean across recent traces"
        spark={traces.slice(0,20).reverse().map(t=>t.total_latency_ms||0)} loading={tLoad}
        active={metricFocus==="avg_latency"}
        onClick={()=>openMetricDrill("avg_latency")}/>
      <Tile label="P95 latency" value={p95} unit="ms" color={p95Color}
        hint="Slowest 5% of traces"
        spark={traces.slice(0,20).reverse().map(t=>t.total_latency_ms||0)} loading={tLoad}
        active={metricFocus==="p95_latency"}
        onClick={()=>openMetricDrill("p95_latency")}/>
      <Tile label="P99 latency" value={p99} unit="ms" color={p99Color}
        hint="Slowest 1% of traces"
        spark={traces.slice(0,20).reverse().map(t=>t.total_latency_ms||0)} loading={tLoad}
        active={metricFocus==="p99_latency"}
        onClick={()=>openMetricDrill("p99_latency")}/>
      <Tile label="Total traces" value={traces.length} color={M.blue}
        hint={quota?.monthly_traces?`${quota.monthly_traces.used?.toLocaleString()??"—"} this month`:"In current view"}
        spark={traces.slice(0,20).map(()=>1)} loading={tLoad}
        active={metricFocus==="total_traces"}
        onClick={()=>openMetricDrill("total_traces")}/>
    </div>
  );

  return(
    <>
      <style>{G}</style>
      <ObsBg/>
      <div className="obs-shell" style={{display:"flex",height:"100vh",background:M.gray50}}>
        {/* Desktop sidebar */}
        <aside className="dash-sidebar dash-sidebar-desktop" style={{width:248,height:"100vh",minHeight:0,background:M.white,borderRight:`1px solid ${M.gray200}`,display:"flex",flexDirection:"column",flexShrink:0,overflow:"hidden"}}>
          <SidebarNav tab={tab} setTab={goTab} project={project} tier={tier} live={live} setLive={setLive} refreshSec={refreshSec} setRefreshSec={setRefreshSec} logout={logout} failed={failed}/>
        </aside>

        {navOpen&&(
          <>
            <div className="mobile-nav-overlay" onClick={()=>setNavOpen(false)} aria-hidden="true"/>
            <aside className="mobile-nav-drawer" role="dialog" aria-label="Navigation menu" style={{display:"flex",flexDirection:"column"}}>
              <SidebarNav tab={tab} setTab={goTab} project={project} tier={tier} live={live} setLive={setLive} refreshSec={refreshSec} setRefreshSec={setRefreshSec} logout={logout} failed={failed} onNavigate={()=>setNavOpen(false)}/>
            </aside>
          </>
        )}

        {/* Main */}
        <div style={{flex:1,display:"flex",flexDirection:"column",minWidth:0}}>
          <header style={{minHeight:56,background:M.white,borderBottom:`1px solid ${M.gray200}`,display:"flex",alignItems:"center",padding:"10px 20px",gap:12,flexShrink:0}}>
            <button type="button" className="mobile-menu-btn" onClick={()=>setNavOpen(true)} aria-label="Open navigation menu">
              <HamburgerIcon/>
            </button>
            <div style={{flex:1,minWidth:0}}>
              <div style={{display:"flex",alignItems:"center",gap:10,flexWrap:"wrap"}}>
                <h1 style={{fontSize:18,fontWeight:600,color:M.gray900,margin:0}}>{activeLabel}</h1>
                <Badge color={tier==="pro"?M.brand:M.green} bg={tier==="pro"?M.brandLight:M.greenLight}>{tier}</Badge>
                <span className="header-hide-mobile" style={{fontFamily:M.mono,fontSize:11,color:M.gray500}}>{project}</span>
                {live&&<Badge color={M.green} bg={M.greenLight}>● Live · {refreshSec}s</Badge>}
              </div>
              {tabHint&&<p className="header-hide-mobile" style={{fontSize:12,color:M.gray500,margin:"4px 0 0",lineHeight:1.4}}>{tabHint}</p>}
            </div>
            <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:10}}>
              {(tLoad||eLoad)&&<span className="header-hide-mobile" style={{fontSize:11,color:M.gray500,fontFamily:M.mono}}>Updating…</span>}
              <button onClick={()=>{rT();rE();rQ();rK();rP();rD();}} style={{background:M.gray100,border:`1px solid ${M.gray200}`,borderRadius:6,color:M.gray700,fontSize:13,padding:"6px 12px",cursor:"pointer",fontWeight:500}}>↻ Refresh</button>
              <a href={HOME_URL} style={{fontSize:13,color:M.blueSoft,textDecoration:"none",whiteSpace:"nowrap"}}>Home</a>
            </div>
          </header>

          <div style={{flex:1,overflow:"auto",padding:20}}>
            {tab==="overview"&&(
              <div style={{display:"grid",gap:16}}>
                <OnboardingChecklist
                  tracesCount={traces.length}
                  evalsCount={evals.length}
                  datasetsCount={datasets.length}
                  onGoTraces={()=>goTab("traces")}
                  onGoEvals={()=>goTab("evaluations")}
                />

                <div style={{background:`linear-gradient(135deg, ${statusBg} 0%, ${M.white} 55%)`,border:`1px solid ${M.gray200}`,borderRadius:12,padding:"18px 20px",display:"flex",alignItems:"center",justifyContent:"space-between",gap:16,flexWrap:"wrap",boxShadow:M.shadow1}}>
                  <div>
                    <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".08em",fontWeight:700,marginBottom:6}}>Project status</div>
                    <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:6}}>
                      <span style={{fontSize:24,fontWeight:700,color:statusColor,textTransform:"capitalize"}}>{overallStatus==="unknown"?"No data yet":overallStatus}</span>
                      {failed>0&&<Badge color={M.red} bg={M.redLight}>{failed} active alert{failed>1?"s":""}</Badge>}
                    </div>
                    <div style={{fontSize:13,color:M.gray600,lineHeight:1.5}}>
                      {completed} successful · {failed} failed · {evals.length} eval run{evals.length!==1?"s":""} · {datasets.length} dataset{datasets.length!==1?"s":""}
                    </div>
                  </div>
                  <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
                    <QuickLink label="View traces" onClick={()=>goTab("traces")}/>
                    <QuickLink label="Run evals" onClick={()=>goTab("evaluations")} color={M.green}/>
                    {failed>0&&<QuickLink label="Review alerts" onClick={()=>goTab("alerts")} color={M.red}/>}
                  </div>
                </div>

                {metricTiles}
                {metricDrillPanel}

                <div className="overview-layout" style={{display:"grid",gridTemplateColumns:"minmax(0,1.6fr) minmax(280px,1fr)",gap:16,alignItems:"start"}}>
                  <div style={{display:"grid",gap:16}}>
                    <div className="insight-grid" style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:12}}>
                      <InsightCard label="Health score" value={successRate!=="—"?`${successRate}%`:"—"}
                        sub={healthPct!=null?`${completed}/${traces.length} traces succeeded`:"Instrument agents to measure health"}
                        color={healthPct==null?M.gray500:healthPct>=95?M.green:healthPct>=80?M.amber:M.red}
                        bar={healthPct} barColor={healthPct>=95?M.green:healthPct>=80?M.amber:M.red}
                        onClick={()=>openMetricDrill("health_score")} loading={tLoad}/>
                      <InsightCard label="Eval gate" value={latest?(evalPassing?"Passing":"Failing"):"No data"}
                        sub={latest?`${((latest.task_completion_rate||0)*100).toFixed(0)}% · ${latest.passed}/${latest.total_cases} cases · 90% threshold`:"Run golden dataset evals"}
                        color={latest?(evalPassing?M.green:M.red):M.gray500}
                        bar={latest?(latest.task_completion_rate||0)*100:null} barColor={evalPassing?M.green:M.red}
                        onClick={()=>openMetricDrill("eval_gate")} loading={eLoad}/>
                      <InsightCard label="Regressions" value={latest?(latest.regressions??0):"—"}
                        sub={latest?(latest.regressions>0?"Review failing cases in latest run":"Stable vs previous run"):"Tracked across eval history"}
                        color={latest?(latest.regressions>0?M.amber:M.green):M.gray500}
                        onClick={()=>openMetricDrill("regressions")} loading={eLoad}/>
                    </div>

                    <FailureKindPanel
                      stats={failureKindStats}
                      total={failureKindTotal}
                      loading={tLoad}
                      onViewAlerts={failed>0?()=>goTab("alerts"):undefined}
                    />

                    <Section title="Recent traces" subtitle="Click any row to open the node waterfall"
                      action={traces.length>0?<button onClick={()=>goTab("traces")} style={{background:"none",border:"none",color:M.blue,fontSize:12,fontWeight:600,cursor:"pointer"}}>View all →</button>:null}
                      noPad>
                      {traces.slice(0,8).map(t=>(
                        <TraceRow key={t.trace_id} trace={t} onClick={()=>openTrace(t)}/>
                      ))}
                      {traces.length===0&&!tLoad&&<EmptyState title="No traces yet" body="Instrument your agent with CortexTracer to see live runs here." hint="pip install cortexops"/>}
                    </Section>

                    {latest?.case_results?.length>0&&(
                      <Section title="Latest eval cases" subtitle={`Run ${latest.run_id?.slice(0,8)} · ${formatWhen(latest.created_at)}`}
                        action={<button onClick={()=>goTab("evaluations")} style={{background:"none",border:"none",color:M.blue,fontSize:12,fontWeight:600,cursor:"pointer"}}>All runs →</button>}>
                        <div style={{display:"grid",gap:8}}>
                          {latest.case_results.slice(0,6).map(cr=>(
                            <div key={cr.case_id} style={{display:"flex",alignItems:"center",gap:10,padding:"8px 10px",background:M.gray50,borderRadius:8,border:`1px solid ${M.gray200}`}}>
                              <Badge color={cr.passed?M.green:M.red} bg={cr.passed?M.greenLight:M.redLight}>{cr.passed?"PASS":"FAIL"}</Badge>
                              <span style={{flex:1,fontFamily:M.mono,fontSize:12,color:M.gray800}}>{cr.case_id}</span>
                              <span style={{fontSize:11,color:M.gray500,fontFamily:M.mono}}>{Math.round(cr.latency_ms||0)}ms</span>
                              {cr.failure_kind&&<span style={{fontSize:10,color:M.red,fontFamily:M.mono}}>{cr.failure_kind.replace("FailureKind.","")}</span>}
                            </div>
                          ))}
                        </div>
                      </Section>
                    )}
                  </div>

                  <div style={{display:"grid",gap:16}}>
                    <Section title="Usage this month">
                      {qLoad?<div style={{fontSize:13,color:M.gray500}}>Loading quota…</div>:<>
                        <div style={{fontSize:28,fontWeight:700,fontFamily:M.mono,color:M.gray900,marginBottom:4}}>
                          {quota?.monthly_traces?.used?.toLocaleString()??"—"}
                          <span style={{fontSize:14,color:M.gray500,fontWeight:400}}> / {quota?.monthly_traces?.unlimited?"∞":(quota?.monthly_traces?.limit?.toLocaleString()??"5,000")}</span>
                        </div>
                        {!quota?.monthly_traces?.unlimited&&quotaPct!=null&&(
                          <div style={{height:8,background:M.gray200,borderRadius:4,overflow:"hidden",marginBottom:10}}>
                            <div style={{width:`${Math.min(quotaPct,100)}%`,height:"100%",background:quotaPct>90?M.red:quotaPct>70?M.amber:M.green}}/>
                          </div>
                        )}
                        <DetailRow label="Retention" value={`${quota?.retention_days??7} days`}/>
                        <DetailRow label="Plan" value={quota?.tier||tier}/>
                        <DetailRow label="Traces loaded" value={String(traces.length)} mono/>
                        {quota?.upgrade_url&&tier!=="pro"&&<a href={quota.upgrade_url} style={{display:"inline-block",marginTop:10,color:M.blue,fontSize:12,fontWeight:600}}>Upgrade to Pro →</a>}
                      </>}
                    </Section>

                    <Section title="Latency distribution" subtitle={`Min ${minLat}ms · P50 ${p50}ms · Avg ${avgLat}ms · P95 ${p95}ms · P99 ${p99}ms · Max ${maxLat}ms`}
                      action={<button onClick={()=>openMetricDrill("avg_latency")} style={{background:"none",border:"none",color:M.blue,fontSize:12,fontWeight:600,cursor:"pointer"}}>Drill down →</button>}>
                      <MiniBars values={latBuckets} color={tcColor}/>
                    </Section>

                    <Section title="Workspace" subtitle="Resources in this project">
                      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                        {[[evals.length,"Eval runs","evaluations"],[datasets.length,"Datasets","datasets"],[prompts.length,"Prompts","prompts"],[keys.length,"API keys","api-keys"]].map(([n,l,dest])=>(
                          <button key={l} onClick={()=>goTab(dest)} className="card-hover" style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:8,padding:"12px",cursor:"pointer",textAlign:"left"}}>
                            <div style={{fontSize:22,fontWeight:700,color:M.gray900,fontFamily:M.mono}}>{n}</div>
                            <div style={{fontSize:11,color:M.gray500,marginTop:2}}>{l}</div>
                          </button>
                        ))}
                      </div>
                    </Section>

                    {failed>0&&(
                      <Section title="Active alerts" subtitle={`${failed} failed trace${failed>1?"s":""} need review`}
                        action={<button onClick={()=>goTab("alerts")} style={{background:"none",border:"none",color:M.red,fontSize:12,fontWeight:600,cursor:"pointer"}}>View all →</button>}
                        noPad>
                        {traces.filter(t=>t.status==="failed").slice(0,4).map(t=>(
                          <TraceRow key={t.trace_id} trace={t} onClick={()=>openTrace(t)} showCase={false}/>
                        ))}
                      </Section>
                    )}
                  </div>
                </div>
              </div>
            )}

            {tab==="projects"&&(
              <div style={{display:"grid",gap:16,maxWidth:900}}>
                <div style={{background:`linear-gradient(135deg, ${M.blueLight} 0%, ${M.white} 60%)`,border:`1px solid ${M.gray200}`,borderRadius:12,padding:"20px 22px",boxShadow:M.shadow1}}>
                  <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".08em",fontWeight:700,marginBottom:8}}>Active workspace</div>
                  <div style={{fontFamily:M.mono,fontSize:20,fontWeight:700,color:M.gray900,marginBottom:8}}>{project}</div>
                  <div style={{fontSize:14,color:M.gray600,lineHeight:1.55}}>Bound to your API key at login. All traces, evals, datasets, and prompts are scoped to this project.</div>
                </div>
                <div style={{display:"grid",gridTemplateColumns:"repeat(4,minmax(0,1fr))",gap:12}}>
                  {[[traces.length,"Traces",M.blue],[evals.length,"Eval runs",M.green],[datasets.length,"Datasets",M.amber],[prompts.length,"Prompt versions",M.blueSoft]].map(([n,l,c])=>(
                    <div key={l} style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:10,padding:"16px",boxShadow:M.shadow1}}>
                      <div style={{fontSize:26,fontWeight:700,color:c,fontFamily:M.mono}}>{n}</div>
                      <div style={{fontSize:12,color:M.gray500,marginTop:4}}>{l}</div>
                    </div>
                  ))}
                </div>
                <Section title="Project details">
                  <DetailRow label="Tier" value={tier}/>
                  <DetailRow label="API keys" value={String(keys.length)} mono/>
                  <DetailRow label="Failed traces" value={String(failed)} mono/>
                  <DetailRow label="Latest eval" value={latest?`${((latest.task_completion_rate||0)*100).toFixed(0)}% pass`:"—"}/>
                  <DetailRow label="Health" value={successRate!=="—"?`${successRate}%`:"—"}/>
                </Section>
              </div>
            )}

            {tab==="traces"&&(
              <div style={{display:"grid",gap:12}}>
                {tError&&<div style={{background:M.redLight,color:M.red,border:"1px solid rgba(197,34,31,.2)",borderRadius:6,padding:"10px 12px",fontSize:13}}>Failed to load traces: {tError}</div>}
                <div style={{display:"grid",gridTemplateColumns:"repeat(4,minmax(0,1fr))",gap:10}}>
                  {[[traces.length,"In range",M.blue],[tracesTabCompleted,"OK",M.green],[tracesTabFailed,"Failed",M.red],[`${tracesTabAvgLat}ms`,"Avg latency",tracesTabAvgLat>500?M.amber:M.green]].map(([v,l,c])=>(
                    <div key={l} style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:10,padding:"12px 14px"}}>
                      <div style={{fontSize:10,color:M.gray500,textTransform:"uppercase",letterSpacing:".06em",fontWeight:600}}>{l}</div>
                      <div style={{fontSize:20,fontWeight:700,color:c,fontFamily:M.mono,marginTop:4}}>{v}</div>
                    </div>
                  ))}
                </div>
                <Section
                  title="Trace explorer"
                  subtitle={`${filteredTraces.length} shown · ${traces.length} loaded${traceDateActive?` · ${traceDateLabel(traceDatePreset,traceDateFrom,traceDateTo)}`:""}${filter!=="all"?` · ${filter} only`:""}`}
                  action={
                    <input value={traceSearch} onChange={e=>setTraceSearch(e.target.value)} placeholder="Search ID, case, failure…"
                      style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:6,padding:"6px 10px",fontSize:12,color:M.gray900,minWidth:200}}/>
                  } noPad>
                  <div style={{padding:"10px 18px",borderBottom:`1px solid ${M.gray200}`,display:"grid",gap:10}}>
                    <div style={{display:"flex",alignItems:"center",gap:8,flexWrap:"wrap"}}>
                      <span style={{fontSize:10,color:M.gray500,textTransform:"uppercase",letterSpacing:".06em",fontWeight:600,marginRight:4}}>Status</span>
                      {["all","completed","failed"].map(s=>(
                        <button key={s} type="button" onClick={()=>setFilter(s)}
                          style={{background:filter===s?M.blueLight:"transparent",border:`1px solid ${filter===s?M.blue:M.gray300}`,borderRadius:6,color:filter===s?M.blue:M.gray600,fontSize:12,padding:"5px 12px",cursor:"pointer",fontWeight:filter===s?600:500,textTransform:"capitalize"}}>{s}</button>
                      ))}
                    </div>
                    <div style={{display:"flex",alignItems:"center",gap:8,flexWrap:"wrap"}}>
                      <span style={{fontSize:10,color:M.gray500,textTransform:"uppercase",letterSpacing:".06em",fontWeight:600,marginRight:4}}>Date range</span>
                      {TRACE_DATE_PRESETS.map(([key,label])=>(
                        <button key={key} type="button" onClick={()=>setTraceDatePreset(key)}
                          style={{background:traceDatePreset===key?M.blueLight:"transparent",border:`1px solid ${traceDatePreset===key?M.blue:M.gray300}`,borderRadius:6,color:traceDatePreset===key?M.blue:M.gray600,fontSize:12,padding:"5px 12px",cursor:"pointer",fontWeight:traceDatePreset===key?600:500}}>{label}</button>
                      ))}
                      {traceDateActive&&(
                        <button type="button" onClick={()=>{setTraceDatePreset("all");setTraceDateFrom("");setTraceDateTo("");}}
                          style={{background:"none",border:"none",color:M.gray500,fontSize:12,cursor:"pointer",padding:"5px 8px"}}>Clear</button>
                      )}
                    </div>
                    {traceDatePreset==="custom"&&(
                      <div style={{display:"flex",alignItems:"center",gap:10,flexWrap:"wrap"}}>
                        <label style={{display:"flex",alignItems:"center",gap:6,fontSize:12,color:M.gray600}}>
                          From
                          <input type="date" value={traceDateFrom} onChange={e=>setTraceDateFrom(e.target.value)}
                            style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:6,padding:"5px 8px",fontSize:12,color:M.gray900}}/>
                        </label>
                        <label style={{display:"flex",alignItems:"center",gap:6,fontSize:12,color:M.gray600}}>
                          To
                          <input type="date" value={traceDateTo} onChange={e=>setTraceDateTo(e.target.value)}
                            style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:6,padding:"5px 8px",fontSize:12,color:M.gray900}}/>
                        </label>
                        {!traceDateFrom&&!traceDateTo&&<span style={{fontSize:11,color:M.gray500}}>Pick at least one date</span>}
                      </div>
                    )}
                  </div>
                  {tLoad&&<div style={{padding:"24px 18px",fontSize:13,color:M.gray500}}>Loading traces…</div>}
                  {!tLoad&&filteredTraces.length===0&&<EmptyState title="No traces found" body={traceSearch||traceDateActive||filter!=="all"?"Try adjusting search, status filter, or date range.":"Instrument your agent and send traces to this project."} hint="pip install cortexops"/>}
                  {!tLoad&&filteredTraces.map(t=><TraceRow key={t.trace_id} trace={t} onClick={()=>openTrace(t)}/>)}
                </Section>
              </div>
            )}

            {tab==="evaluations"&&(
              <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:10,overflow:"hidden",boxShadow:M.shadow1}}>
                <div style={{padding:"12px 18px",borderBottom:`1px solid ${M.gray200}`,display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,flexWrap:"wrap",background:M.gray50}}>
                  <div style={{fontSize:13,color:M.gray600}}>{evals.length} run{evals.length!==1?"s":""} · compare baseline vs current</div>
                  <button
                    onClick={()=>{
                      if(compareMode){setCompareMode(false);setEvalDiff(null);setDiffError("");track("eval","Closed eval comparison");return;}
                      setCompareMode(true);
                      track("eval","Started eval comparison");
                      if(evals.length>=2){setDiffRunA(evals[1].run_id);setDiffRunB(evals[0].run_id);}
                      else if(evals.length===1){setDiffRunA("");setDiffRunB(evals[0].run_id);}
                    }}
                    disabled={evals.length<2}
                    title={evals.length<2?"Need at least 2 runs to compare":undefined}
                    style={{background:compareMode?M.blue:M.white,color:compareMode?M.ink:M.blue,border:`1px solid ${M.blue}`,borderRadius:6,padding:"6px 12px",fontSize:12,fontWeight:600,cursor:evals.length<2?"not-allowed":"pointer",opacity:evals.length<2?.5:1}}
                  >
                    {compareMode?"Close compare":"Compare runs"}
                  </button>
                </div>
                {compareMode&&evals.length>=2&&(
                  <div style={{padding:"12px 18px",borderBottom:`1px solid ${M.gray200}`,display:"flex",alignItems:"center",gap:12,flexWrap:"wrap"}}>
                    <label style={{fontSize:12,color:M.gray600,display:"flex",alignItems:"center",gap:6}}>
                      Baseline
                      <select value={diffRunA} onChange={e=>setDiffRunA(e.target.value)}
                        style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:6,padding:"5px 8px",fontSize:12,color:M.gray900,fontFamily:M.mono}}>
                        <option value="">Select run…</option>
                        {evals.map(r=><option key={r.run_id} value={r.run_id}>{r.run_id?.slice(0,8)} · {((r.task_completion_rate||0)*100).toFixed(0)}% · {timeAgo(r.created_at)}</option>)}
                      </select>
                    </label>
                    <span style={{color:M.gray500}}>→</span>
                    <label style={{fontSize:12,color:M.gray600,display:"flex",alignItems:"center",gap:6}}>
                      Current
                      <select value={diffRunB} onChange={e=>setDiffRunB(e.target.value)}
                        style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:6,padding:"5px 8px",fontSize:12,color:M.gray900,fontFamily:M.mono}}>
                        <option value="">Select run…</option>
                        {evals.map(r=><option key={r.run_id} value={r.run_id}>{r.run_id?.slice(0,8)} · {((r.task_completion_rate||0)*100).toFixed(0)}% · {timeAgo(r.created_at)}</option>)}
                      </select>
                    </label>
                  </div>
                )}
                {compareMode&&(
                  <EvalDiffPanel
                    diff={evalDiff}
                    runA={evals.find(r=>r.run_id===diffRunA)}
                    runB={evals.find(r=>r.run_id===diffRunB)}
                    loading={diffLoading}
                    error={diffError}
                    onClose={()=>{setCompareMode(false);setEvalDiff(null);setDiffError("");}}
                  />
                )}
                {evals.length>0&&(
                  <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:1,background:M.gray200,borderBottom:`1px solid ${M.gray200}`}}>
                    {[["Latest pass rate",latest?`${((latest.task_completion_rate||0)*100).toFixed(0)}%`:"—",evalPassing?M.green:M.red],
                      ["Cases",latest?`${latest.passed}/${latest.total_cases}`:"—",M.blue],
                      ["Regressions",latest?.regressions??0,latest?.regressions?M.amber:M.green]
                    ].map(([l,v,c])=>(
                      <div key={l} style={{background:M.white,padding:"14px 18px"}}>
                        <div style={{fontSize:10,color:M.gray500,textTransform:"uppercase",letterSpacing:".06em",fontWeight:600,marginBottom:4}}>{l}</div>
                        <div style={{fontSize:22,fontWeight:700,color:c,fontFamily:M.mono}}>{v}</div>
                      </div>
                    ))}
                  </div>
                )}
                {evals.length===0&&!eLoad&&<EmptyState title="No evaluations yet" body="Run golden datasets in CI or locally to populate this view." hint="python run_eval.py --sync-only"/>}
                {evals.map((run,i)=>(
                  <div key={run.run_id} style={{borderBottom:`1px solid ${M.gray200}`,animation:`slideIn .15s ease ${i*.04}s both`}}>
                    <div className="row-hover" onClick={()=>setExpandedEval(expandedEval===run.run_id?null:run.run_id)}
                      style={{padding:"14px 18px",cursor:run.case_results?.length?"pointer":"default"}}>
                      <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8,flexWrap:"wrap"}}>
                        <StatusDot status={run.status||"completed"}/>
                        <div style={{minWidth:80}}>
                          <div style={{fontFamily:M.mono,fontSize:12,color:M.gray700,fontWeight:600}}>{run.run_id?.slice(0,8)}</div>
                          <div style={{fontSize:10,color:M.gray500,marginTop:2}}>{timeAgo(run.created_at)}</div>
                        </div>
                        {compareMode&&(
                          <div style={{display:"flex",gap:6}} onClick={e=>e.stopPropagation()}>
                            <button onClick={()=>setDiffRunA(run.run_id)} style={{background:diffRunA===run.run_id?M.amberLight:"transparent",border:`1px solid ${diffRunA===run.run_id?M.amber:M.gray300}`,borderRadius:4,padding:"2px 8px",fontSize:10,cursor:"pointer",color:diffRunA===run.run_id?M.amber:M.gray500}}>A</button>
                            <button onClick={()=>setDiffRunB(run.run_id)} style={{background:diffRunB===run.run_id?M.blueLight:"transparent",border:`1px solid ${diffRunB===run.run_id?M.blue:M.gray300}`,borderRadius:4,padding:"2px 8px",fontSize:10,cursor:"pointer",color:diffRunB===run.run_id?M.blue:M.gray500}}>B</button>
                          </div>
                        )}
                        <div style={{flex:1}}>
                          <div style={{height:8,background:M.gray200,borderRadius:4,overflow:"hidden"}}>
                            <div style={{width:`${(run.task_completion_rate||0)*100}%`,height:"100%",background:run.task_completion_rate>=.9?M.green:run.task_completion_rate>=.7?M.amber:M.red,borderRadius:4}}/>
                          </div>
                        </div>
                        <span style={{fontFamily:M.mono,fontSize:14,color:run.task_completion_rate>=.9?M.green:M.red,fontWeight:700,minWidth:44,textAlign:"right"}}>{((run.task_completion_rate||0)*100).toFixed(0)}%</span>
                        <span style={{fontSize:13,color:M.gray600,minWidth:72}}>{run.passed}/{run.total_cases}</span>
                        {run.regressions>0&&<Badge color={M.red} bg={M.redLight}>{run.regressions}↓</Badge>}
                        {run.case_results?.length>0&&<span style={{fontSize:11,color:M.gray400}}>{expandedEval===run.run_id?"▲":"▼"}</span>}
                      </div>
                      <div style={{display:"flex",gap:16,paddingLeft:18,flexWrap:"wrap"}}>
                        {[["Tool accuracy",`${(run.tool_accuracy||0).toFixed(0)}/100`],["P50",`${Math.round(run.latency_p50_ms||0)}ms`],["P95",`${Math.round(run.latency_p95_ms||0)}ms`],["Dataset",run.dataset_name||"golden"],["When",formatWhen(run.created_at)]].map(([l,v])=>(
                          <span key={l} style={{fontSize:12,color:M.gray600}}>{l}: <span style={{color:M.gray900,fontFamily:M.mono}}>{v}</span></span>
                        ))}
                      </div>
                    </div>
                    {expandedEval===run.run_id&&run.case_results?.length>0&&(
                      <div style={{padding:"0 18px 14px",background:M.gray50,borderTop:`1px solid ${M.gray200}`}}>
                        {run.case_results.map(cr=>(
                          <div key={cr.case_id} style={{display:"flex",alignItems:"flex-start",gap:10,padding:"10px 0",borderBottom:`1px solid ${M.gray200}`}}>
                            <Badge color={cr.passed?M.green:M.red} bg={cr.passed?M.greenLight:M.redLight}>{cr.passed?"PASS":"FAIL"}</Badge>
                            <div style={{flex:1,minWidth:0}}>
                              <div style={{fontFamily:M.mono,fontSize:12,fontWeight:600,color:M.gray800,marginBottom:4}}>{cr.case_id}</div>
                              <div style={{display:"flex",gap:14,flexWrap:"wrap",fontSize:11,color:M.gray500}}>
                                <span>Score: <span style={{fontFamily:M.mono,color:M.gray800}}>{(cr.score||0).toFixed(2)}</span></span>
                                <span>Tool acc: <span style={{fontFamily:M.mono,color:M.gray800}}>{(cr.tool_accuracy||0).toFixed(0)}</span></span>
                                <span>Latency: <span style={{fontFamily:M.mono,color:M.gray800}}>{Math.round(cr.latency_ms||0)}ms</span></span>
                              </div>
                              {cr.failure_detail&&<div style={{fontSize:11,color:M.red,marginTop:6,fontFamily:M.mono}}>{cr.failure_detail}</div>}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {tab==="prompts"&&(
              <Section title="Prompt versions" subtitle={`${prompts.length} prompt${prompts.length!==1?"s":""} in ${project}`} noPad>
                {pLoad&&<div style={{padding:16,fontSize:13,color:M.gray500}}>Loading prompt versions…</div>}
                {pError&&<div style={{margin:16,background:M.redLight,color:M.red,border:"1px solid rgba(242,109,109,.25)",borderRadius:8,padding:"12px 14px",fontSize:13}}>Could not load prompts: {pError}</div>}
                {!pLoad&&!pError&&prompts.length===0&&(
                  <EmptyState
                    title={`No prompts for “${project}”`}
                    body="Artifacts sync to the project tied to your API key, not the --project flag. Sign out and log in with the key you used for run_eval.py, then run sync again."
                    hint="python run_eval.py --sync-only"
                  />
                )}
                {prompts.map((pv,i)=>(
                  <div key={pv.id} style={{padding:"16px 18px",borderBottom:`1px solid ${M.gray200}`,animation:`slideIn .15s ease ${i*.04}s both`}}>
                    <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8,flexWrap:"wrap"}}>
                      <span style={{fontFamily:M.mono,fontSize:14,color:M.blue,fontWeight:600}}>{pv.prompt_name}</span>
                      <Badge color={M.blue} bg={M.blueLight}>v{pv.version}</Badge>
                      {pv.model&&<Badge>{pv.model}</Badge>}
                      <span style={{fontSize:11,color:M.gray500,marginLeft:"auto"}}>{formatWhen(pv.created_at)}</span>
                    </div>
                    <div style={{fontSize:12,color:M.gray600,marginBottom:10}}>{pv.commit_message||"No commit message"} · {pv.author||"unknown"} · temp {pv.temperature??0.7}</div>
                    <div style={{background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:8,padding:12,fontFamily:M.mono,fontSize:11,color:M.gray800,whiteSpace:"pre-wrap",maxHeight:160,overflow:"auto",lineHeight:1.5}}>{pv.content}</div>
                  </div>
                ))}
              </Section>
            )}

            {tab==="datasets"&&(
              <div style={{background:M.white,border:`1px solid ${M.gray200}`,borderRadius:10,overflow:"hidden",boxShadow:M.shadow1}}>
                <div style={{padding:"14px 18px",borderBottom:`1px solid ${M.gray200}`,background:M.gray50}}>
                  <div style={{fontSize:15,fontWeight:600,color:M.gray900}}>Golden datasets</div>
                  <div style={{fontSize:12,color:M.gray600,marginTop:4}}>Scoped to project <span style={{fontFamily:M.mono,color:M.blue}}>{project}</span></div>
                </div>
                {dLoad&&<div style={{padding:16,fontSize:13,color:M.gray500}}>Loading datasets…</div>}
                {dError&&<div style={{margin:16,background:M.redLight,color:M.red,border:"1px solid rgba(242,109,109,.25)",borderRadius:8,padding:"12px 14px",fontSize:13}}>Could not load datasets: {dError}</div>}
                {!dLoad&&!dError&&datasets.length===0&&(
                  <EmptyState
                    title={`No datasets for “${project}”`}
                    body="Your eval runner syncs to whichever project your API key belongs to. Check the sidebar project matches, or re-login with the correct cxo- key."
                    hint="python run_eval.py --sync-only"
                  />
                )}
                {datasets.map((ds,i)=>(
                  <div key={ds.id} style={{borderBottom:`1px solid ${M.gray200}`,animation:`slideIn .15s ease ${i*.04}s both`}}>
                    <div className="row-hover" onClick={()=>setExpandedDataset(expandedDataset===ds.id?null:ds.id)}
                      style={{padding:"14px 18px",cursor:"pointer"}}>
                      <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:6}}>
                        <span style={{fontFamily:M.mono,fontSize:14,color:M.blue,fontWeight:600}}>{ds.name}</span>
                        <span style={{fontSize:11,background:M.blueLight,color:M.blue,padding:"2px 8px",borderRadius:4,fontFamily:M.mono}}>{ds.case_count} cases</span>
                        <span style={{marginLeft:"auto",fontSize:11,color:M.gray500}}>{expandedDataset===ds.id?"Hide":"Show cases"} →</span>
                      </div>
                      {ds.description&&<div style={{fontSize:13,color:M.gray600,lineHeight:1.45,marginBottom:4}}>{ds.description}</div>}
                      <div style={{fontSize:11,color:M.gray500,fontFamily:M.mono}}>
                        {ds.id?.slice(0,8)} · {ds.created_at?new Date(ds.created_at).toLocaleString():"—"}
                      </div>
                    </div>
                    {expandedDataset===ds.id&&(
                      <div style={{padding:"0 18px 14px",borderTop:`1px solid ${M.gray200}`,background:M.gray50}}>
                        {datasetDetailLoading&&<div style={{padding:"12px 0",fontSize:13,color:M.gray500}}>Loading cases…</div>}
                        {!datasetDetailLoading&&datasetDetail?.cases?.map((c,j)=>(
                          <div key={c.id||j} style={{padding:"10px 0",borderBottom:j<datasetDetail.cases.length-1?`1px solid ${M.gray200}`:"none"}}>
                            <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4}}>
                              <span style={{fontFamily:M.mono,fontSize:12,color:M.gray700,fontWeight:600}}>{c.id||`case-${j+1}`}</span>
                              {(c.tags||[]).slice(0,3).map(tag=>(
                                <span key={tag} style={{fontSize:10,background:M.gray200,color:M.gray600,padding:"1px 6px",borderRadius:4}}>{tag}</span>
                              ))}
                            </div>
                            <div style={{fontSize:13,color:M.gray800,marginBottom:4}}>{typeof c.input==="string"?c.input:JSON.stringify(c.input)}</div>
                            {c.expected_tool_calls?.length>0&&(
                              <div style={{fontSize:11,color:M.gray500,fontFamily:M.mono}}>
                                tools: {c.expected_tool_calls.join(", ")}
                              </div>
                            )}
                          </div>
                        ))}
                        {!datasetDetailLoading&&(!datasetDetail?.cases||datasetDetail.cases.length===0)&&(
                          <div style={{padding:"12px 0",fontSize:13,color:M.gray500}}>No cases in this dataset.</div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {tab==="metrics"&&(
              <div style={{display:"grid",gap:16}}>
                {metricTiles}
                {metricDrillPanel}
                {!metricFocus&&(
                  <div className="insight-grid" style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:12}}>
                    <InsightCard label="Health score" value={successRate!=="—"?`${successRate}%`:"—"}
                      sub={`${traces.length-failed} of ${traces.length} traces succeeded`}
                      color={healthPct==null?M.gray500:healthPct>=95?M.green:healthPct>=80?M.amber:M.red}
                      bar={healthPct} barColor={healthPct>=95?M.green:healthPct>=80?M.amber:M.red}
                      onClick={()=>openMetricDrill("health_score")}/>
                    <InsightCard label="Latency watch" value={`${avgLat}ms`}
                      sub={`P95 ${p95}ms · P99 ${p99}ms · ${avgLat>500?"above target":"within target"}`}
                      color={tcColor}
                      onClick={()=>openMetricDrill("avg_latency")}/>
                    <InsightCard label="Drift monitor" value={latest?.regressions>0?`${latest.regressions} found`:"Stable"}
                      sub={latest?.regressions>0?"Review failing eval cases":"No regressions in latest run"}
                      color={latest?.regressions?M.amber:M.green}
                      onClick={()=>openMetricDrill("regressions")}/>
                  </div>
                )}
              </div>
            )}

            {tab==="alerts"&&(
              <Section title="Alerts" subtitle={failed?`${failed} failed trace${failed>1?"s":""} requiring attention`:"All systems healthy"} noPad>
                {failed===0&&<EmptyState title="No alerts" body="All traces are healthy. When failures appear, open a trace and add it to your golden dataset in one click."/>}
                {failed>0&&datasets.length>0&&(
                  <div style={{padding:"10px 18px",background:M.amberLight,borderBottom:`1px solid ${M.gray200}`,fontSize:12,color:M.gray700}}>
                    Open a failed trace → <strong>Add golden case</strong> to block this regression in CI.
                  </div>
                )}
                {traces.filter(t=>t.status==="failed").map(t=>(
                  <div key={t.trace_id} onClick={()=>openTrace(t)} className="row-hover"
                    style={{padding:"12px 18px",borderBottom:`1px solid ${M.gray200}`,borderLeft:`4px solid ${M.red}`,cursor:"pointer"}}>
                    <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:6}}>
                      <span style={{fontFamily:M.mono,fontSize:12,color:M.gray700,fontWeight:600}}>{t.trace_id?.slice(0,8)}</span>
                      <span style={{flex:1,fontSize:14,color:M.gray900}}>{t.case_id||"live trace"}</span>
                      <Badge color={M.red} bg={M.redLight}>{t.failure_kind?.replace("FailureKind.","")||"UNKNOWN"}</Badge>
                      <LatencyChip ms={t.total_latency_ms||0}/>
                    </div>
                    {t.failure_detail&&<div style={{fontSize:12,color:M.gray600,lineHeight:1.45}}>{t.failure_detail}</div>}
                    <div style={{fontSize:11,color:M.gray500,marginTop:6}}>{formatWhen(t.created_at)} · {timeAgo(t.created_at)}</div>
                  </div>
                ))}
              </Section>
            )}

            {tab==="api-keys"&&(
              <div style={{maxWidth:720,display:"grid",gap:14}}>
                {actionError&&<div style={{background:M.redLight,color:M.red,border:"1px solid rgba(197,34,31,.2)",borderRadius:6,padding:"10px 12px",fontSize:13}}>{actionError}</div>}
                {actionOk&&<div style={{background:M.greenLight,color:M.green,border:"1px solid rgba(220,38,38,.35)",borderRadius:6,padding:"10px 12px",fontSize:13}}>{actionOk}</div>}
                {kError&&<div style={{background:M.redLight,color:M.red,border:"1px solid rgba(197,34,31,.2)",borderRadius:6,padding:"10px 12px",fontSize:13}}>Failed to load keys: {kError}</div>}
                {session?.scope==="read_only"&&(
                  <div style={{background:M.amberLight,color:M.gray700,border:`1px solid ${M.amber}`,borderRadius:6,padding:"10px 12px",fontSize:13}}>
                    Your key has <strong>read_only</strong> scope. Rotate and revoke require a read_write key.
                  </div>
                )}
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
                      {sessionKeyId===k.id&&<Badge color={M.blue} bg={M.blueLight}>current</Badge>}
                      {k.is_active&&session?.scope!=="read_only"&&<>
                        <button type="button" disabled={!!keyAction} onClick={()=>rotateKey(k.id)} style={{background:M.blueLight,color:M.blue,border:"none",borderRadius:4,padding:"6px 10px",fontSize:12,cursor:keyAction?"wait":"pointer",fontWeight:600,opacity:keyAction&&keyAction!==k.id?.6:1}}>
                          {keyAction===k.id?"…":"Rotate"}
                        </button>
                        <button type="button" disabled={!!keyAction} onClick={()=>revokeKey(k.id)} style={{background:M.redLight,color:M.red,border:"none",borderRadius:4,padding:"6px 10px",fontSize:12,cursor:keyAction?"wait":"pointer",fontWeight:600,opacity:keyAction&&keyAction!==k.id?.6:1}}>
                          {keyAction===k.id?"…":"Revoke"}
                        </button>
                      </>}
                    </div>
                  ))}
                </PanelCard>
                <PanelCard title="Session">
                  <div style={{fontSize:13,color:M.gray600}}>Your session is saved in this browser and auto-refreshes hourly. Use <strong>Sign out</strong> in the sidebar to clear it.</div>
                </PanelCard>
              </div>
            )}

            {tab==="activity"&&(
              <div style={{maxWidth:760,display:"grid",gap:14}}>
                <PanelCard title="Session activity">
                  <div style={{fontSize:13,color:M.gray600,marginBottom:14}}>
                    Actions you take in this dashboard during the current browser tab. Cleared when you sign out or close the tab.
                  </div>
                  <div style={{display:"flex",gap:8,marginBottom:14}}>
                    <button type="button" onClick={()=>{clearUiActivity();setUiActivity([]);}} style={{background:M.gray100,border:`1px solid ${M.gray300}`,borderRadius:4,padding:"6px 12px",fontSize:12,cursor:"pointer"}}>Clear activity</button>
                    <span style={{fontSize:12,color:M.gray500,alignSelf:"center"}}>{uiActivity.length} event{uiActivity.length===1?"":"s"}</span>
                  </div>
                  {uiActivity.length===0&&<div style={{fontSize:13,color:M.gray500}}>No activity yet — navigate, inspect traces, or manage keys to build your timeline.</div>}
                  {uiActivity.map(row=>{
                    const style=ACTIVITY_STYLE[row.type]||ACTIVITY_STYLE.settings;
                    return(
                      <div key={row.id} style={{display:"grid",gridTemplateColumns:"auto 1fr auto",gap:12,padding:"10px 0",borderBottom:`1px solid ${M.gray200}`}}>
                        <span style={{fontSize:10,fontWeight:700,textTransform:"uppercase",letterSpacing:".06em",color:style.color,background:style.bg,borderRadius:4,padding:"4px 8px",alignSelf:"start"}}>{row.type}</span>
                        <div>
                          <div style={{fontSize:14,color:M.gray900}}>{row.label}</div>
                          {row.meta&&Object.keys(row.meta).length>0&&(
                            <div style={{fontFamily:M.mono,fontSize:11,color:M.gray500,marginTop:4}}>
                              {Object.entries(row.meta).map(([k,v])=>`${k}: ${v}`).join(" · ")}
                            </div>
                          )}
                        </div>
                        <div style={{fontSize:11,color:M.gray500,whiteSpace:"nowrap"}} title={new Date(row.at).toLocaleString()}>{timeAgo(row.at)}</div>
                      </div>
                    );
                  })}
                </PanelCard>
              </div>
            )}

            {tab==="usage"&&(
              <div style={{display:"grid",gap:16}}>
                <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:12}}>
                  <Section title="Monthly traces">
                    {qLoad?<div style={{fontSize:13,color:M.gray500}}>Loading…</div>:<>
                      <div style={{fontSize:32,fontWeight:700,fontFamily:M.mono}}>{quota?.monthly_traces?.used??"—"}</div>
                      <div style={{fontSize:13,color:M.gray600,marginTop:6}}>
                        {quota?.monthly_traces?.unlimited?"Unlimited (Pro)":`of ${quota?.monthly_traces?.limit?.toLocaleString()??"5,000"} monthly limit`}
                      </div>
                      {!quota?.monthly_traces?.unlimited&&quotaPct!=null&&(
                        <div style={{marginTop:12,height:10,background:M.gray200,borderRadius:5,overflow:"hidden"}}>
                          <div style={{width:`${Math.min(quotaPct,100)}%`,height:"100%",background:quotaPct>90?M.red:quotaPct>70?M.amber:M.green}}/>
                        </div>
                      )}
                    </>}
                  </Section>
                  <Section title="Retention & plan">
                    <div style={{fontSize:32,fontWeight:700,fontFamily:M.mono,textTransform:"capitalize"}}>{quota?.tier||tier}</div>
                    <DetailRow label="Trace history" value={`${quota?.retention_days??7} days`}/>
                    <DetailRow label="Failed in view" value={String(failed)} mono/>
                  </Section>
                  <Section title="In this session">
                    <DetailRow label="Traces loaded" value={String(traces.length)} mono/>
                    <DetailRow label="Eval runs" value={String(evals.length)} mono/>
                    <DetailRow label="Datasets" value={String(datasets.length)} mono/>
                    <DetailRow label="Prompts" value={String(prompts.length)} mono/>
                  </Section>
                </div>
                <Section title="Plan features">
                  <div style={{display:"grid",gridTemplateColumns:"repeat(2,minmax(0,1fr))",gap:8}}>
                    {[["Slack alerts",quota?.features?.slack_alerts],["LLM judge",quota?.features?.llm_judge],["Prompt versioning",quota?.features?.prompt_versioning],["Extended retention",tier==="pro"]].map(([f,on])=>(
                      <div key={f} style={{display:"flex",alignItems:"center",gap:8,padding:"10px 12px",background:M.gray50,borderRadius:8,border:`1px solid ${M.gray200}`}}>
                        <span style={{color:on?M.green:M.gray400,fontWeight:700}}>{on?"✓":"—"}</span>
                        <span style={{fontSize:13,color:M.gray700}}>{f}</span>
                      </div>
                    ))}
                  </div>
                  {quota?.upgrade_url&&tier!=="pro"&&<a href={quota.upgrade_url} style={{display:"inline-block",marginTop:14,color:M.blue,fontSize:13,fontWeight:600}}>Upgrade to Pro →</a>}
                </Section>
              </div>
            )}

            {tab==="settings"&&(
              <div style={{maxWidth:520,display:"grid",gap:14}}>
                <PanelCard title="Project">
                  <div style={{fontFamily:M.mono,fontSize:14,background:M.gray50,border:`1px solid ${M.gray200}`,borderRadius:4,padding:"10px 12px"}}>{project}</div>
                  <div style={{fontSize:12,color:M.gray500,marginTop:8}}>Project is determined by your API key.</div>
                </PanelCard>
                <PanelCard title="Live refresh">
                  <label style={{display:"flex",alignItems:"center",gap:10,cursor:"pointer",fontSize:14,marginBottom:14}}>
                    <input type="checkbox" checked={live} onChange={e=>setLive(e.target.checked)}/>
                    Enable live polling
                  </label>
                  <div style={{fontSize:12,color:M.gray500,marginBottom:8}}>Refresh interval</div>
                  <div style={{display:"flex",gap:8}}>
                    {REFRESH_OPTIONS.map(sec=>(
                      <button key={sec} type="button" onClick={()=>setRefreshSec(sec)}
                        style={{flex:1,background:refreshSec===sec?M.blueLight:M.gray50,border:`1px solid ${refreshSec===sec?M.blue:M.gray300}`,borderRadius:6,color:refreshSec===sec?M.blue:M.gray600,fontSize:13,fontWeight:refreshSec===sec?600:500,padding:"8px 0",cursor:"pointer"}}>
                        {sec}s
                      </button>
                    ))}
                  </div>
                  <div style={{fontSize:12,color:M.gray500,marginTop:10}}>
                    {live?`Polling traces and evals every ${refreshSec} seconds.`:"Live polling is paused."}
                  </div>
                </PanelCard>
                <PanelCard title="API">
                  <div style={{fontFamily:M.mono,fontSize:13,color:M.gray700}}>{API}</div>
                </PanelCard>
              </div>
            )}
          </div>
        </div>
      </div>
      {selected&&<WaterfallPanel trace={traceDetail||selected} loading={detailLoading} datasets={datasets} token={token}
        onPromoted={(res)=>{
          rD();
          if(expandedDataset&&res?.dataset_id===expandedDataset&&token){
            apiFetch(token,`/v1/eval/datasets/${expandedDataset}`).then(setDatasetDetail).catch(()=>{});
          }
        }}
        onClose={closeTrace}/>}
    </>
  );
}