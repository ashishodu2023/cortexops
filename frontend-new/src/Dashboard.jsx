import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";

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
html{scroll-behavior:smooth}
body{background:${M.gray50};color:${M.gray900};font-family:${M.sans};-webkit-font-smoothing:antialiased}
a,button,input,summary{outline-offset:3px}
a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid #60A5FA}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:${M.gray100}}
::-webkit-scrollbar-thumb{background:${M.gray300};border-radius:2px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes slideIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
@keyframes scan{0%{transform:translateX(-120%);opacity:0}30%,70%{opacity:1}100%{transform:translateX(120%);opacity:0}}
@keyframes grow{from{transform:scaleX(.35)}to{transform:scaleX(1)}}
@keyframes breathe{0%,100%{transform:translateY(0)}50%{transform:translateY(-2px)}}
.landing{min-height:100vh;background:#0B0F1A;color:white;display:flex;flex-direction:column}
.landing-wrap{max-width:1180px;margin:0 auto;padding:0 28px}
.landing-nav{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 32px;border-bottom:1px solid rgba(255,255,255,.09);background:rgba(11,15,26,.86);backdrop-filter:blur(14px);position:sticky;top:0;z-index:5}
.landing-links{display:flex;align-items:center;gap:22px;font-size:14px;color:rgba(255,255,255,.68)}
.landing-links a{color:inherit;text-decoration:none}
.landing-btn{display:inline-flex;align-items:center;justify-content:center;background:${M.blue};color:white;text-decoration:none;border:none;border-radius:7px;padding:12px 18px;font-weight:700;cursor:pointer;box-shadow:0 14px 30px rgba(26,115,232,.28)}
.landing-btn.ghost{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.14);box-shadow:none}
.hero-grid{padding:76px 28px 34px;display:grid;grid-template-columns:minmax(0,1fr) minmax(380px,520px);gap:54px;align-items:center}
.hero-title{font-size:58px;line-height:1.02;letter-spacing:-.045em;font-weight:700;margin-bottom:22px}
.hero-copy{font-size:18px;line-height:1.65;color:rgba(255,255,255,.68);max-width:560px;margin-bottom:28px}
.hero-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:24px}
.install-chip{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);border-radius:7px;padding:12px 14px;font-family:${M.mono};font-size:13px;color:rgba(255,255,255,.86)}
.proof-row{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:rgba(255,255,255,.7)}
.proof-row span{display:inline-flex;align-items:center;gap:7px}
.proof-row span:before{content:"";width:6px;height:6px;border-radius:50%;background:#2DD4A7}
.demo-card{background:#111726;border:1px solid rgba(255,255,255,.12);border-radius:14px;overflow:hidden;box-shadow:0 36px 90px rgba(0,0,0,.45);position:relative}
.section{padding:72px 0}
.section.tight{padding-top:0}
.section-head{margin-bottom:30px}
.eyebrow{color:#60A5FA;font-size:12px;font-family:${M.mono};font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}
.section-title{font-size:34px;line-height:1.1;letter-spacing:-.03em;margin-bottom:12px}
.section-copy{color:rgba(255,255,255,.62);font-size:16px;line-height:1.6;max-width:620px}
.trust-grid,.framework-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}
.trust-grid{grid-template-columns:repeat(6,minmax(0,1fr))}
.trust-item,.framework-item{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:13px 10px;text-align:center;font-family:${M.mono};font-size:12px;color:rgba(255,255,255,.72)}
.steps-grid,.feature-grid,.pricing-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.landing-card{background:#111726;border:1px solid rgba(255,255,255,.11);border-radius:10px;padding:20px 18px;color:rgba(255,255,255,.82)}
.landing-card h3{font-size:17px;margin-bottom:8px;color:white}
.landing-card p{font-size:14px;line-height:1.55;color:rgba(255,255,255,.62)}
.code-box{margin-top:14px;background:#0B0F1A;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:13px;font-family:${M.mono};font-size:12px;line-height:1.65;color:rgba(255,255,255,.82);overflow:auto}
.feature-icon{width:36px;height:36px;border-radius:8px;display:grid;place-items:center;margin-bottom:14px;font-weight:700}
.compare-wrap{overflow:auto;border:1px solid rgba(255,255,255,.11);border-radius:10px}
.compare-table{width:100%;border-collapse:collapse;min-width:720px;background:#111726}
.compare-table th,.compare-table td{padding:14px 16px;text-align:left;border-bottom:1px solid rgba(255,255,255,.09);font-size:14px}
.compare-table th{color:rgba(255,255,255,.62);font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.compare-table tr:last-child td{border-bottom:none}
.yes{color:#2DD4A7;font-weight:700}.partial{color:#F5B23D}.no{color:rgba(255,255,255,.38)}
.price-card{display:flex;flex-direction:column;min-height:390px}
.price-card.featured{border-color:#60A5FA;box-shadow:0 0 0 1px rgba(96,165,250,.55),0 28px 70px rgba(26,115,232,.16)}
.price-amount{font-size:36px;font-weight:700;letter-spacing:-.03em;margin:8px 0}
.price-card ul{list-style:none;margin:18px 0 24px;display:grid;gap:9px;flex:1}
.price-card li{color:rgba(255,255,255,.68);font-size:14px}
.price-card li:before{content:"✓";color:#2DD4A7;margin-right:8px}
.faq-list{max-width:780px;margin:0 auto}
.faq-item{border-bottom:1px solid rgba(255,255,255,.11)}
.faq-item summary{cursor:pointer;list-style:none;padding:20px 0;font-weight:700;display:flex;justify-content:space-between;gap:18px}
.faq-item summary::-webkit-details-marker{display:none}
.faq-item summary:after{content:"⌄";color:rgba(255,255,255,.42)}
.faq-item[open] summary:after{transform:rotate(180deg)}
.faq-item:not([open]) div{display:none}
.faq-item[open] div{display:block;color:rgba(255,255,255,.62);font-size:14px;line-height:1.65;padding:0 0 20px}
.cta-band{background:linear-gradient(135deg,#172033,#111726);border:1px solid rgba(255,255,255,.12);border-radius:18px;padding:46px 32px;text-align:center}
.footer-grid{display:grid;grid-template-columns:2fr repeat(4,1fr);gap:28px;border-top:1px solid rgba(255,255,255,.09);padding:38px 0}
.footer-grid h4{font-size:12px;color:rgba(255,255,255,.42);text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}
.footer-grid a{display:block;color:rgba(255,255,255,.62);text-decoration:none;font-size:14px;padding:4px 0}
.login-panel{position:fixed;right:24px;bottom:24px;background:${M.white};color:${M.gray900};border-radius:8px;padding:22px 24px;width:360px;box-shadow:0 20px 70px rgba(0,0,0,.35);border:1px solid ${M.gray200};z-index:6}
@media (max-width:900px){
  .landing-nav{padding:0 20px}.landing-links a:not(.landing-btn){display:none}
  .hero-grid{grid-template-columns:1fr;padding-top:52px}.hero-title{font-size:42px}
  .trust-grid,.framework-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .steps-grid,.feature-grid,.pricing-grid{grid-template-columns:1fr}
  .footer-grid{grid-template-columns:1fr 1fr}.login-panel{position:static;width:auto;margin:0 20px 24px}
}
@media (max-width:560px){
  .landing-wrap{padding:0 20px}.hero-grid{padding-left:20px;padding-right:20px}
  .hero-title{font-size:34px}.hero-copy{font-size:16px}
  .trust-grid,.framework-grid{grid-template-columns:1fr}
  .footer-grid{grid-template-columns:1fr}.section{padding:52px 0}
}
@media (prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important;scroll-behavior:auto!important}
}
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
  const[pricingCycle,setPricingCycle]=useState("monthly");
  const frameworks=["LangGraph","CrewAI","OpenAI Agents","PydanticAI","Google ADK","Smolagents","LlamaIndex","Haystack","AutoGen","DSPy","Agno","+ any callable"];
  const features=[
    ["Trace Explorer","Full agent waterfall with nodes, tools, branches, latency, state, and failure context.","#1A73E8"],
    ["Evaluation","LLM-as-judge scoring, golden datasets, pass rates, regressions, and semantic quality checks.","#137333"],
    ["Monitoring","Production health, latency, drift, anomaly, and cost signals in one operational view.","#B06000"],
    ["Prompt Version","Track every prompt change against evals and traces so teams can roll back regressions.","#7B4F9E"],
    ["CI/CD Gates","GitHub Actions-ready eval gates that fail builds when quality drops below your bar.","#1A73E8"],
    ["Alerts","Route failures, drift, latency spikes, and quality drops to the channels your team already uses.","#C5221F"],
  ];
  const faqs=[
    ["Which frameworks do you support?","CortexOps supports LangGraph, CrewAI, OpenAI Agents SDK, PydanticAI, Google ADK, Smolagents, LlamaIndex, Haystack, AutoGen, DSPy, Agno, and any callable wrapper."],
    ["How is this different from LangSmith or Langfuse?","Those tools are strongest around LLM calls. CortexOps is designed around agent execution: nodes, tools, state transitions, eval gates, monitoring, and alerts."],
    ["Can we self-host?","Yes. CortexOps is open source and MIT licensed, with a Python SDK and deployment paths for teams that need control over data."],
    ["Does it work in CI?","Yes. The eval command can run in GitHub Actions and fail a build when score, regression, latency, or task-completion thresholds are missed."],
    ["Do developers get a live demo?","Yes. The hero preview and dashboard are designed to show the product motion before a user connects their API key."],
  ];
  const submit=async()=>{
    if(!key.startsWith("cxo-")){setErr("Key must start with cxo-");return;}
    setLoading(true);
    try{const r=await fetch(`${API}/health`);if(!r.ok)throw new Error();onLogin(key,proj);}
    catch{setErr("Cannot reach api.getcortexops.com");}
    finally{setLoading(false);}
  };
  return(
    <div className="landing">
      <div className="landing-nav">
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <div style={{width:32,height:32,background:M.blue,borderRadius:8,display:"flex",alignItems:"center",justifyContent:"center"}}>
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
              <path d="M10 2.5 Q14 10 10 17.5" stroke="white" strokeWidth="1.8" strokeLinecap="round"/>
              <path d="M6 2.5 Q10.5 10 6 17.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" opacity=".45"/>
              <circle cx="10" cy="2.5" r="1.8" fill="white"/>
              <circle cx="10" cy="17.5" r="1.8" fill="white"/>
            </svg>
          </div>
          <div style={{fontSize:17,fontWeight:700}}>CortexOps</div>
        </div>
        <div className="landing-links">
          <a href="#social-proof">Customers</a>
          <a href="#how">Docs</a>
          <a href="#features">Blog</a>
          <a href="https://github.com/ashishodu2023/cortexops/releases">Changelog</a>
          <a href="#demo" className="landing-btn" style={{padding:"9px 14px"}}>View Live Demo</a>
        </div>
      </div>

      <main style={{flex:1}}>
        <section className="landing-wrap hero-grid">
          <motion.div initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} transition={{duration:.45,ease:"easeOut"}}>
            <div style={{display:"inline-flex",alignItems:"center",gap:8,background:"rgba(45,212,167,.12)",border:"1px solid rgba(45,212,167,.22)",color:"#2DD4A7",borderRadius:99,padding:"6px 12px",fontSize:12,fontFamily:M.mono,marginBottom:22}}>
              <span style={{width:6,height:6,borderRadius:"50%",background:"#2DD4A7",animation:"pulse 1.8s infinite"}}/>
              Open source reliability infrastructure
            </div>
            <h1 className="hero-title">
              Ship Reliable AI Agents.<br/>Every Time.
            </h1>
            <p className="hero-copy">
              Here is why every AI engineering team needs CortexOps. Trace every node, evaluate every change, monitor production health, and catch regressions before users do.
            </p>
            <div className="hero-actions">
              <a href="#demo" className="landing-btn">View Live Demo</a>
              <span className="install-chip">$ pip install cortexops</span>
            </div>
            <div className="proof-row">
              {["Open Source","MIT License","12 Frameworks","CI Ready"].map(item=><span key={item}>{item}</span>)}
            </div>
          </motion.div>

          <motion.div id="demo" className="demo-card" initial={{opacity:0,y:16}} animate={{opacity:1,y:0}} transition={{duration:.5,ease:"easeOut",delay:.08}}>
            <div style={{position:"absolute",inset:0,background:"linear-gradient(110deg, transparent 35%, rgba(96,165,250,.10) 50%, transparent 65%)",animation:"scan 4s ease-in-out infinite",pointerEvents:"none"}}/>
            <div style={{padding:"14px 16px",borderBottom:"1px solid rgba(255,255,255,.1)",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
              <div style={{fontFamily:M.mono,fontSize:13,color:"rgba(255,255,255,.9)"}}>Hero Dashboard</div>
              <div style={{display:"flex",gap:8}}>
                <span style={{background:"rgba(45,212,167,.12)",color:"#2DD4A7",borderRadius:99,padding:"4px 9px",fontSize:11,fontWeight:700,animation:"breathe 2.2s infinite"}}>Success badge</span>
                <span style={{background:"rgba(242,109,109,.12)",color:"#F26D6D",borderRadius:99,padding:"4px 9px",fontSize:11,fontWeight:700}}>Failure badge</span>
              </div>
            </div>
            <div style={{padding:16}}>
              <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:14}}>
                {[["Node","running...","#F5B23D"],["Latency","updating","#60A5FA"],["Health Score","changing","#2DD4A7"]].map(([l,v,c])=>(
                  <div key={l} style={{background:"#0B0F1A",border:"1px solid rgba(255,255,255,.1)",borderRadius:8,padding:"10px 11px"}}>
                    <div style={{fontSize:10,color:"rgba(255,255,255,.44)",fontFamily:M.mono,marginBottom:4}}>{l}</div>
                    <div style={{fontSize:13,color:c,fontFamily:M.mono,fontWeight:700}}>{v}</div>
                  </div>
                ))}
              </div>
              {[
                ["classify_intent","78%","#1A73E8","1.18s"],
                ["tool call animated","32%","#7B4F9E","active"],
                ["evaluate_policy","52%","#0E8A6D","890ms"],
                ["tool: issue_refund","88%","#D14343","2.01s"],
              ].map(([name,width,color,time],i)=>(
                <div key={name} style={{display:"flex",alignItems:"center",gap:10,marginBottom:9}}>
                  <div style={{width:132,fontSize:12,fontFamily:name.startsWith("tool")?M.mono:M.sans,color:name.includes("issue")?"#F26D6D":"rgba(255,255,255,.72)",whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis"}}>
                    {name}
                  </div>
                  <div style={{flex:1,height:22,background:"#172033",borderRadius:5,position:"relative",overflow:"hidden"}}>
                    <div style={{width,background:color,height:14,borderRadius:4,position:"absolute",top:4,left:i*12,animation:`grow ${1+i*.18}s ease both`,display:"flex",alignItems:"center",paddingLeft:7,fontSize:10,fontFamily:M.mono,fontWeight:700}}>{time}</div>
                  </div>
                </div>
              ))}
              <div style={{marginTop:12,background:"rgba(242,109,109,.12)",border:"1px solid rgba(242,109,109,.25)",borderRadius:8,padding:"10px 12px",fontFamily:M.mono,fontSize:11,color:"#F26D6D",animation:"slideIn .4s ease both"}}>
                Trace expanding... PaymentGatewayTimeout after tool call
              </div>
            </div>
          </motion.div>
        </section>

        <section className="landing-wrap section tight" id="social-proof">
          <div className="trust-grid">
            {["Open Source","MIT","Python SDK","GitHub Actions","Works with LangGraph","Works with CrewAI"].map(item=>(
              <div key={item} className="trust-item">{item}</div>
            ))}
          </div>
        </section>

        <section className="landing-wrap section" id="frameworks">
          <div className="section-head">
            <div className="eyebrow">Works with your stack</div>
            <h2 className="section-title">One integration. Every framework.</h2>
            <p className="section-copy">Instrument the agent framework your team already uses, without rewrites or lock-in.</p>
          </div>
          <div className="framework-grid">{frameworks.map(item=><div key={item} className="framework-item">{item}</div>)}</div>
        </section>

        <section className="landing-wrap section" id="how">
          <div className="section-head">
            <div className="eyebrow">How it works</div>
            <h2 className="section-title">Trace. Evaluate. Monitor.</h2>
            <p className="section-copy">Three production disciplines that turn opaque agent behavior into a system your team can operate.</p>
          </div>
          <div className="steps-grid">
            <div className="landing-card"><h3>1. Trace every run</h3><p>Wrap your agent once and capture nodes, tools, state, latency, and failure details.</p><div className="code-box">from cortexops import CortexTracer<br/>tracer = CortexTracer(project="agent")<br/>agent = tracer.wrap(graph)</div></div>
            <div className="landing-card"><h3>2. Gate on quality</h3><p>Run golden datasets in CI and stop regressions before they reach production.</p><div className="code-box">cortexops eval run \<br/>&nbsp;&nbsp;--dataset gold.yaml \<br/>&nbsp;&nbsp;--fail-on "score &lt; 0.9"</div></div>
            <div className="landing-card"><h3>3. Watch production</h3><p>Monitor health, drift, latency, and alerts after your agents are live.</p><div className="code-box">tracer.monitor(<br/>&nbsp;&nbsp;alert="slack",<br/>&nbsp;&nbsp;on="quality_drop"<br/>)</div></div>
          </div>
        </section>

        <section className="landing-wrap section" id="features">
          <div className="section-head">
            <div className="eyebrow">Platform</div>
            <h2 className="section-title">Here is why every AI engineering team needs CortexOps.</h2>
          </div>
          <div className="feature-grid">
            {features.map(([title,body,color])=>(
              <motion.div key={title} className="landing-card" whileHover={{y:-3}} transition={{duration:.18}}>
                <div className="feature-icon" style={{background:`${color}22`,color}}>●</div>
                <h3>{title}</h3>
                <p>{body}</p>
              </motion.div>
            ))}
          </div>
        </section>

        <section className="landing-wrap section" id="compare">
          <div className="section-head">
            <div className="eyebrow">Why teams switch</div>
            <h2 className="section-title">Built for agents, not just LLM calls.</h2>
          </div>
          <div className="compare-wrap">
            <table className="compare-table">
              <thead><tr><th>Capability</th><th>CortexOps</th><th>LangSmith</th><th>Langfuse</th><th>Arize Phoenix</th></tr></thead>
              <tbody>
                <tr><td>Agent execution tracing</td><td className="yes">Full waterfall</td><td className="partial">LangChain focused</td><td className="partial">LLM calls</td><td className="partial">Span tree</td></tr>
                <tr><td>Framework support</td><td className="yes">12 frameworks</td><td className="partial">LangChain</td><td className="partial">Via SDK</td><td className="partial">Several</td></tr>
                <tr><td>CI/CD eval gate</td><td className="yes">First-class CLI</td><td className="partial">Partial</td><td className="no">Manual</td><td className="partial">Scripted</td></tr>
                <tr><td>Open source</td><td className="yes">MIT</td><td className="no">No</td><td className="yes">Yes</td><td className="partial">Elastic v2</td></tr>
                <tr><td>Production alerts</td><td className="yes">Quality, drift, latency</td><td className="partial">Limited</td><td className="partial">Limited</td><td className="yes">Yes</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section className="landing-wrap section" id="pricing">
          <div className="section-head">
            <div className="eyebrow">Pricing</div>
            <h2 className="section-title">Start free. Scale when you are ready.</h2>
            <div style={{display:"inline-flex",gap:4,background:"rgba(255,255,255,.06)",border:"1px solid rgba(255,255,255,.12)",borderRadius:8,padding:4,marginTop:16}}>
              {["monthly","yearly"].map(cycle=>(
                <button
                  key={cycle}
                  type="button"
                  aria-pressed={pricingCycle===cycle}
                  onClick={()=>setPricingCycle(cycle)}
                  style={{background:pricingCycle===cycle?M.blue:"transparent",color:pricingCycle===cycle?"white":"rgba(255,255,255,.65)",border:"none",borderRadius:6,padding:"7px 13px",fontWeight:700,cursor:"pointer"}}
                >
                  {cycle==="monthly"?"Monthly":"Yearly"}
                </button>
              ))}
            </div>
          </div>
          <div className="pricing-grid">
            {[
              ["Free","$0","For side projects and evaluation.",["Core tracing","Local eval runs","Python SDK","Community support"],false,"Start free"],
              ["Pro",pricingCycle==="monthly"?"$49 / mo":"$490 / yr","For teams shipping agents to production.",["Unlimited traces","LLM-as-judge evals","Drift monitoring","GitHub Actions gates","Priority support"],true,"Start free trial"],
              ["Enterprise","Custom","For compliance, scale, and private deployment.",["Everything in Pro","SSO / SAML","VPC or self-hosted deploy","Dedicated support"],false,"Contact sales"],
            ].map(([name,price,desc,items,featured,cta])=>(
              <div key={name} className={`landing-card price-card ${featured?"featured":""}`}>
                <h3>{name}</h3><div className="price-amount">{price}</div><p>{desc}</p>
                <ul>{items.map(item=><li key={item}>{item}</li>)}</ul>
                <a href="#demo" className={`landing-btn ${featured?"":"ghost"}`}>{cta}</a>
              </div>
            ))}
          </div>
        </section>

        <section className="landing-wrap section" id="faq">
          <div className="section-head" style={{textAlign:"center"}}>
            <div className="eyebrow">FAQ</div>
            <h2 className="section-title">Questions, answered.</h2>
          </div>
          <div className="faq-list">
            {faqs.map(([q,a])=><details key={q} className="faq-item"><summary>{q}</summary><div>{a}</div></details>)}
          </div>
        </section>

        <section className="landing-wrap section">
          <div className="cta-band">
            <h2 className="section-title">Ship agents you can trust.</h2>
            <p className="section-copy" style={{margin:"0 auto 22px"}}>Developers love demos. Start with the live preview, then connect your first project when you are ready.</p>
            <div style={{display:"flex",justifyContent:"center",gap:12,flexWrap:"wrap"}}>
              <a href="#demo" className="landing-btn">View Live Demo</a>
              <a href="https://github.com/ashishodu2023/cortexops" className="landing-btn ghost">View on GitHub</a>
            </div>
          </div>
        </section>
      </main>

      <footer className="landing-wrap">
        <div className="footer-grid">
          <div><h3 style={{marginBottom:10}}>CortexOps</h3><p style={{color:"rgba(255,255,255,.55)",lineHeight:1.6}}>Reliability infrastructure for AI agents. Trace, evaluate, monitor, and alert before users feel the regression.</p></div>
          <div><h4>Product</h4>{["Trace Explorer","Evaluation","Monitoring","Prompt Version","Alerts"].map(item=><a key={item} href="#features">{item}</a>)}</div>
          <div><h4>Developers</h4><a href="#how">Docs</a><a href="https://github.com/ashishodu2023/cortexops">GitHub</a><a href="https://pypi.org/project/cortexops/">Python SDK</a><a href="https://github.com/ashishodu2023/cortexops/releases">Changelog</a></div>
          <div><h4>Company</h4><a href="#social-proof">Customers</a><a href="#features">Blog</a><a href="https://github.com/ashishodu2023/cortexops/issues">Roadmap</a><a href="#faq">Status</a></div>
          <div><h4>Legal</h4><a href="#faq">Security</a><a href="#faq">Privacy</a><a href="#faq">Terms</a><a href="https://github.com/ashishodu2023/cortexops/blob/main/LICENSE">MIT License</a></div>
        </div>
        <div style={{borderTop:"1px solid rgba(255,255,255,.09)",padding:"20px 0 28px",display:"flex",justifyContent:"space-between",gap:12,flexWrap:"wrap",color:"rgba(255,255,255,.45)",fontSize:13}}>
          <span>© 2026 CortexOps · MIT licensed</span><span>Built for engineers shipping AI agents</span>
        </div>
      </footer>

      <div className="login-panel">
        <div style={{fontSize:18,fontWeight:600,marginBottom:4}}>Open dashboard</div>
        <div style={{fontSize:13,color:M.gray600,marginBottom:18}}>Use your CortexOps API key to enter the live console.</div>
        {[["API Key",key,setKey,"cxo-...","password"],["Project",proj,setProj,"payments-agent","text"]].map(([l,v,s,p,t])=>(
          <div key={l} style={{marginBottom:14}}>
            <label style={{display:"block",fontSize:12,fontWeight:500,color:M.gray700,marginBottom:6}}>{l}</label>
            <input value={v} onChange={e=>s(e.target.value)} placeholder={p} type={t}
              onKeyDown={e=>e.key==="Enter"&&submit()}
              style={{width:"100%",background:M.white,border:`1px solid ${M.gray300}`,borderRadius:4,color:M.gray900,fontSize:14,padding:"10px 12px",outline:"none",fontFamily:t==="password"?M.mono:"inherit",transition:"border-color .15s"}}
              onFocus={e=>e.target.style.borderColor=M.blue}
              onBlur={e=>e.target.style.borderColor=M.gray300}
            />
          </div>
        ))}
        {err&&<div style={{background:M.redLight,color:M.red,fontSize:13,padding:"8px 12px",borderRadius:4,marginBottom:14,border:"1px solid rgba(197,34,31,.2)"}}>{err}</div>}
        <button onClick={submit} disabled={loading||!key}
          style={{width:"100%",background:M.blue,color:"white",border:"none",borderRadius:4,padding:12,fontSize:15,fontWeight:500,cursor:loading||!key?"not-allowed":"pointer",opacity:(loading||!key)?0.5:1,boxShadow:M.shadow1}}>
          {loading?"Connecting...":"Open dashboard"}
        </button>
      </div>
    </div>
  );
}

export default function App(){
  const[apiKey,setApiKey]=useState(()=>localStorage.getItem("cxo_key")||"");
  const[project,setProject]=useState(()=>localStorage.getItem("cxo_project")||"payments-agent");
  const[tab,setTab]=useState("traces");
  const tabs=[
    ["traces","Trace Explorer"],
    ["evals","Evaluation"],
    ["monitoring","Monitoring"],
    ["prompts","Prompt Version"],
    ["errors","Alerts"],
  ];
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
              {tabs.map(([t,label])=>(
                <button key={t} onClick={()=>setTab(t)}
                  style={{background:tab===t?M.blueLight:"transparent",color:tab===t?M.blue:M.gray600,border:"none",borderRadius:4,padding:"6px 14px",fontSize:14,fontWeight:tab===t?600:400,cursor:"pointer",fontFamily:M.sans}}>
                  {label}
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
              {tab==="monitoring"&&(
                <div style={{padding:"28px 20px",display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:14}}>
                  {[["Health score",traces.length?`${(((traces.length-failed)/traces.length)*100).toFixed(1)}%`:"—",M.green],["Latency watch",`${avgLat}ms avg`,tcColor],["Drift monitor",latest?.regressions?"Needs review":"Stable",latest?.regressions?M.amber:M.green]].map(([l,v,c])=>(
                    <div key={l} style={{border:`1px solid ${M.gray200}`,borderRadius:8,padding:18,boxShadow:M.shadow1}}>
                      <div style={{fontSize:11,color:M.gray500,textTransform:"uppercase",letterSpacing:".07em",fontWeight:600,marginBottom:8}}>{l}</div>
                      <div style={{fontSize:24,fontWeight:600,color:c,fontFamily:M.mono}}>{v}</div>
                    </div>
                  ))}
                </div>
              )}
              {tab==="prompts"&&(
                <div style={{padding:"48px 20px",textAlign:"center",color:M.gray600}}>
                  <div style={{fontSize:15,fontWeight:500,color:M.gray900,marginBottom:8}}>Prompt Version</div>
                  <div style={{fontSize:13}}>Track prompt changes, connect them to eval runs, and roll back regressions.</div>
                </div>
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
