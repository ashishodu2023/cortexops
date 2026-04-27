"""
Real multi-agent payment workflow using Claude API calls.
"""
from __future__ import annotations
import json, sys, time, argparse
from pathlib import Path
from typing import Any
import numpy as np
import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from masev import (
    Action, ActionType, AgentSpec, MASEvaluator,
    Message, MetricConfig, Trace, TraceStep,
)

FRAUD_PROMPT = """You are a Fraud Detection Agent in a payment pipeline. Analyze the transaction for fraud risk.
Evaluate: amount patterns, destination risk, payee history, velocity patterns, type anomalies.
Respond ONLY with JSON: {"fraud_risk":"low|medium|high","risk_score":0.0-1.0,"flags":[],"recommendation":"approve|review|block","reasoning":"brief"}"""

COMPLIANCE_PROMPT = """You are a Compliance Agent in a payment pipeline. You receive transaction details AND fraud assessment.
Evaluate: AML (>$10K needs SAR), KYC status, sanctions, reporting thresholds, structuring detection.
Respond ONLY with JSON: {"compliance_status":"approved|review|blocked","aml_flag":bool,"kyc_status":"verified|pending|failed","sanctions_clear":bool,"reporting_required":bool,"reasoning":"brief"}"""

ROUTER_PROMPT = """You are a Payment Router Agent. You receive transaction, fraud assessment, AND compliance decision.
Rails: ach_standard, ach_sameday, wire_domestic, wire_international, wire_enhanced_dd, card_network, instant, hold, block.
Respond ONLY with JSON: {"selected_rail":"rail","final_action":"process|hold|block","estimated_settlement":"time","fees_basis_points":int,"reasoning":"brief"}"""

SCENARIOS = [
    {"id":"r001","description":"Domestic ACH $500 to known payee","amount":500,"currency":"USD","type":"ach","destination":"domestic","payee_known":True,"expected":"approve"},
    {"id":"r002","description":"International wire $15K to new payee high-risk country","amount":15000,"currency":"USD","type":"wire","destination":"international_high_risk","payee_known":False,"expected":"review"},
    {"id":"r003","description":"Recurring card $99.99 subscription","amount":99.99,"currency":"USD","type":"card","destination":"domestic","payee_known":True,"expected":"approve"},
    {"id":"r004","description":"Large corporate wire $250K cross-border","amount":250000,"currency":"USD","type":"wire","destination":"international","payee_known":True,"expected":"review"},
    {"id":"r005","description":"Structuring pattern: small transfers totaling $9,500","amount":9500,"currency":"USD","type":"ach","destination":"domestic","payee_known":False,"expected":"block"},
    {"id":"r006","description":"P2P $50 to friend","amount":50,"currency":"USD","type":"p2p","destination":"domestic","payee_known":True,"expected":"approve"},
    {"id":"r007","description":"Crypto withdrawal $5K to external wallet","amount":5000,"currency":"USD","type":"crypto","destination":"external","payee_known":False,"expected":"review"},
    {"id":"r008","description":"Refund $1,200 disputed transaction","amount":1200,"currency":"USD","type":"refund","destination":"domestic","payee_known":True,"expected":"approve"},
    {"id":"r009","description":"Velocity anomaly: 20 transactions in 5 minutes","amount":200,"currency":"USD","type":"card","destination":"domestic","payee_known":False,"expected":"block"},
    {"id":"r010","description":"Cross-border payroll batch $45K","amount":45000,"currency":"USD","type":"batch_ach","destination":"international","payee_known":True,"expected":"approve"},
]

ROLE_SPECS = [
    AgentSpec("fraud_detector","Fraud Detection","Analyzes transactions for fraud",expected_actions=["tool_call","reasoning","message"]),
    AgentSpec("compliance_checker","Compliance","Checks regulatory requirements",expected_actions=["tool_call","reasoning","message"]),
    AgentSpec("router","Payment Router","Routes payments optimally",expected_actions=["tool_call","reasoning","output"]),
]
AGENTS = ["fraud_detector","compliance_checker","router"]

client = anthropic.Anthropic()

def call_agent(system_prompt: str, user_msg: str) -> str:
    resp = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=500,
        system=system_prompt, messages=[{"role":"user","content":user_msg}],
    )
    return resp.content[0].text

def run_trial(scenario: dict, topology: str) -> Trace:
    trace = Trace(agents=AGENTS, task_description=scenario["description"],
                  metadata={"scenario_id":scenario["id"],"topology":topology,"model":"claude-sonnet-4-6"})
    tx = f"Type:{scenario['type']} Amount:${scenario['amount']} Dest:{scenario['destination']} Payee_known:{scenario['payee_known']} Desc:{scenario['description']}"
    steps = []

    # Step 1: Fraud
    s1 = TraceStep(step_id=0, timestamp=time.time())
    s1.actions.append(Action(agent_id="fraud_detector",action_type=ActionType.REASONING,
        content=f"Analyzing: {scenario['type']} ${scenario['amount']} to {scenario['destination']}",timestamp=time.time()))
    fraud_resp = call_agent(FRAUD_PROMPT, tx)
    s1.actions.append(Action(agent_id="fraud_detector",action_type=ActionType.TOOL_CALL,
        content=fraud_resp,tool_name="fraud_analysis",timestamp=time.time()))
    s1.messages.append(Message(sender="fraud_detector",receiver="compliance_checker",
        content=f"Fraud result: {fraud_resp}",timestamp=time.time()))
    if topology == "graph":
        s1.messages.append(Message(sender="fraud_detector",receiver="router",
            content=f"FYI fraud: {fraud_resp[:150]}",timestamp=time.time()))
    steps.append(s1)

    # Step 2: Compliance
    s2 = TraceStep(step_id=1, timestamp=time.time())
    s2.actions.append(Action(agent_id="compliance_checker",action_type=ActionType.REASONING,
        content=f"Reviewing compliance for ${scenario['amount']} {scenario['type']}",timestamp=time.time()))
    comp_resp = call_agent(COMPLIANCE_PROMPT, f"{tx}\n\nFraud Assessment:\n{fraud_resp}")
    s2.actions.append(Action(agent_id="compliance_checker",action_type=ActionType.TOOL_CALL,
        content=comp_resp,tool_name="compliance_check",timestamp=time.time()))
    s2.messages.append(Message(sender="compliance_checker",receiver="router",
        content=f"Compliance: {comp_resp}",timestamp=time.time()))
    if topology == "graph":
        s2.messages.append(Message(sender="compliance_checker",receiver="fraud_detector",
            content=f"FYI compliance: {comp_resp[:150]}",timestamp=time.time()))
    if topology == "star":
        s2.actions.append(Action(agent_id="fraud_detector",action_type=ActionType.REASONING,
            content="Awaiting routing decision",timestamp=time.time()))
    steps.append(s2)

    # Step 3: Router
    s3 = TraceStep(step_id=2, timestamp=time.time())
    s3.actions.append(Action(agent_id="router",action_type=ActionType.REASONING,
        content=f"Selecting rail for {scenario['type']} ${scenario['amount']}",timestamp=time.time()))
    route_resp = call_agent(ROUTER_PROMPT, f"{tx}\n\nFraud:\n{fraud_resp}\n\nCompliance:\n{comp_resp}")
    s3.actions.append(Action(agent_id="router",action_type=ActionType.OUTPUT,
        content=route_resp,timestamp=time.time()))
    if topology in ("star","tree"):
        s3.messages.append(Message(sender="router",receiver="fraud_detector",
            content=f"Decision: {route_resp[:120]}",timestamp=time.time()))
        s3.messages.append(Message(sender="router",receiver="compliance_checker",
            content=f"Decision: {route_resp[:120]}",timestamp=time.time()))
    steps.append(s3)

    trace.steps = steps

    # Evaluate success
    try:
        rj = json.loads(route_resp)
        fa = rj.get("final_action","")
        exp = scenario["expected"]
        if exp == "approve": trace.task_success = fa == "process"
        elif exp == "review": trace.task_success = fa in ("hold","process")
        elif exp == "block": trace.task_success = fa in ("block","hold")
    except:
        lower = route_resp.lower()
        exp = scenario["expected"]
        if exp == "block": trace.task_success = "block" in lower or "hold" in lower
        elif exp == "review": trace.task_success = "hold" in lower or "process" in lower
        else: trace.task_success = "block" not in lower
    trace.task_score = 1.0 if trace.task_success else 0.0
    return trace

def run_experiment(topology="star", n_trials=30, output_path=None):
    print(f"REAL experiment: claude-sonnet-4-6 / {topology} / {n_trials} trials")
    print("="*60)
    evaluator = MASEvaluator(agents=AGENTS, role_specs=ROLE_SPECS, config=MetricConfig())
    trial_results = []; errors = 0

    for trial in range(n_trials):
        scenario = SCENARIOS[trial % len(SCENARIOS)]
        try:
            trace = run_trial(scenario, topology)
            sr = evaluator.evaluate_single(trace)
            trial_results.append({
                "trial":trial,"scenario_id":scenario["id"],"task_success":trace.task_success,
                "coordination":sr.coordination,"communication":sr.communication,"role_adherence":sr.role_adherence,
                "n_actions":trace.total_actions,"n_messages":trace.total_messages,
            })
            evaluator.ingest(trace)
            st = "✓" if trace.task_success else "✗"
            print(f"  [{st}] {trial+1}/{n_trials}: {scenario['id']} C={sr.coordination:.2f} Q={sr.communication:.2f} R={sr.role_adherence:.2f}")
        except Exception as e:
            errors += 1; print(f"  [E] {trial+1}/{n_trials}: {e}")

    if not trial_results: return {}
    report = evaluator.evaluate()
    print(f"\n{'='*60}\nDone: {len(trial_results)} ok, {errors} errors\n")
    print(report.summary())

    output = {
        "experiment":{"model":"claude-sonnet-4-6","topology":topology,"n_trials":len(trial_results),"errors":errors,"benchmark":"payment_workflow_REAL"},
        "report":{
            "coordination":report.coordination,"communication":report.communication,
            "role_adherence":report.role_adherence,"task_success_rate":report.task_success_rate,
            "sub_metrics":{k:getattr(report,k) for k in ["coordination_entropy","redundancy_ratio","parallelism_index","message_utility_ratio","information_density","communication_overhead","behavioral_divergence","role_drift_rate"]},
            "emergent_behaviors":report.emergent_behaviors.as_dict(),
        },
        "trial_means":{k:float(np.mean([t[k] for t in trial_results])) for k in ["coordination","communication","role_adherence"]},
        "trial_stds":{k:float(np.std([t[k] for t in trial_results])) for k in ["coordination","communication","role_adherence"]},
        "trials":trial_results,
    }
    if output_path:
        Path(output_path).parent.mkdir(parents=True,exist_ok=True)
        with open(output_path,"w") as f: json.dump(output,f,indent=2)
        print(f"Saved to {output_path}")
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topology",default="star",choices=["star","graph","tree"])
    parser.add_argument("--trials",type=int,default=30)
    parser.add_argument("--output",default=None)
    args = parser.parse_args()
    if not args.output: args.output = f"results/real/payment_real_{args.topology}.json"
    run_experiment(args.topology, args.trials, args.output)
