# MASEV -- Multi-Agent System Evaluation

**Beyond Task Completion: Coordination, Communication, Role Adherence, Emergent Behavior**

MASEV is an open-source evaluation framework for LLM-based multi-agent systems. While existing tools measure *whether* a task was completed, MASEV measures *how* agents coordinated to get there -- exposing failure modes invisible to outcome-only metrics.

## Why MASEV?

A multi-agent system scoring 95% task success might still exhibit:

- **Redundant work** -- agents duplicating each other's tool calls
- **Wasted messages** -- inter-agent communication that changes nothing
- **Role drift** -- agents straying from their assigned responsibilities  
- **Free-riding** -- some agents contributing nothing while others carry the load

These process-level problems predict catastrophic failures under distribution shift. MASEV detects them.

## Quick Start

```bash
pip install masev
```

```python
from masev import MASEvaluator, AgentSpec

evaluator = MASEvaluator(
    agents=["fraud_detector", "compliance", "router"],
    role_specs=[
        AgentSpec("fraud_detector", "Fraud Detection", "Flags risky transactions",
                  expected_actions=["tool_call", "reasoning", "message"]),
        AgentSpec("compliance", "Compliance", "Checks AML/KYC requirements",
                  expected_actions=["tool_call", "reasoning", "message"]),
        AgentSpec("router", "Payment Router", "Selects optimal payment rail",
                  expected_actions=["tool_call", "reasoning", "output"]),
    ],
)

# Ingest traces from your multi-agent system
for trace in your_traces:
    evaluator.ingest(trace)

# Evaluate
report = evaluator.evaluate()
print(report.summary())
```

Output:
```
MASEV Evaluation Report
==================================================
Traces evaluated: 50
Agents: 3
Task Success Rate: 0.940

Dimension Scores (0-1, higher is better):
  Coordination Efficiency: 0.823
    - Entropy:    0.761
    - Redundancy: 0.912
    - Parallelism:0.758
  Communication Quality:   0.764
    - MUR:        0.820
    - Density:    0.693
    - Overhead:   0.781
  Role Adherence:          0.881
    - Divergence: 0.089
    - Drift:      0.023

Emergent Behaviors:
  free_riding: 0.040
  trust_polarization: 0.020
  spontaneous_specialization: 0.520
  leadership_emergence: 0.150
  information_hoarding: 0.030
```

## Four Evaluation Dimensions

| Dimension | What it measures | Key metric |
|-----------|-----------------|------------|
| **Coordination (C)** | Work partitioning, redundancy, parallelism | Coordination Entropy |
| **Communication (Q)** | Message utility, information density, overhead | Message Utility Ratio |
| **Role Adherence (R)** | Behavioral consistency with role specs | JS Divergence + Drift |
| **Emergent Behavior (E)** | Free-riding, polarization, specialization | Temporal motif detection |

## Running Experiments

### Payment Workflow Benchmark

```bash
python -m experiments.run_payment_workflow \
    --model gpt-4o \
    --topology star \
    --trials 50 \
    --output results/payment_gpt4o_star.json
```

### MultiAgentBench (MARBLE) Integration

```bash
# First, run MARBLE scenarios to generate logs
# Then evaluate with MASEV:
python -m experiments.marble_adapter \
    --marble-log path/to/marble/logs/ \
    --output results/marble_masev.json
```

## Creating Traces

MASEV works with any multi-agent framework. Wrap your agent execution to emit `Trace` objects:

```python
from masev import Trace, TraceStep, Action, ActionType, Message

trace = Trace(agents=["agent_a", "agent_b"])

step = TraceStep(step_id=0, timestamp=1234567890.0)
step.actions.append(Action(
    agent_id="agent_a",
    action_type=ActionType.TOOL_CALL,
    content="Searching database for user records",
    tool_name="db_query",
    tool_args={"table": "users", "limit": 10},
))
step.messages.append(Message(
    sender="agent_a",
    receiver="agent_b",
    content="Found 10 user records, processing now",
))
trace.steps.append(step)
```

## Configuration

All hyperparameters from the paper (Table A.1) are configurable:

```python
from masev import MetricConfig

config = MetricConfig(
    redundancy_threshold=0.85,    # tau
    mur_threshold=0.05,           # epsilon
    free_riding_contrib_threshold=0.15,
    drift_penalty=0.30,           # lambda
    drift_window_size=5,
)
evaluator = MASEvaluator(agents=[...], config=config)
```

## Development

```bash
git clone https://github.com/cortexops/masev.git
cd masev
pip install -e ".[dev]"
pytest tests/ -v
```

## Citation

```bibtex
@inproceedings{verma2026masev,
  title={Beyond Task Completion: A Unified Metrics Framework for Evaluating
         Coordination Dynamics in LLM-Based Multi-Agent Systems},
  author={Verma, Ashish},
  booktitle={NeurIPS},
  year={2026}
}
```

## License

Apache 2.0
