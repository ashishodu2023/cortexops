"""
CortexOps — run evals against the payments agent
=================================================

Usage:
    cd examples/langgraph_payments
    pip install -e ../../sdk
    python run_eval.py

    # With CI threshold (exits non-zero if eval fails):
    python run_eval.py --fail-on "task_completion < 0.90"

    # Push dataset + prompt to dashboard without re-running evals:
    python run_eval.py --sync-only

    # Save results to JSON:
    python run_eval.py --output results.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from cortexops import CortexTracer, EvalSuite
from cortexops.client import CortexClient
from cortexops.eval import EvalThresholdError
from agent import build_agent

DEFAULT_PROJECT = "payments-agent"

PAYMENTS_ROUTER_PROMPT = """You are a payments support routing agent.

Given a customer message, decide which tool to call next:
- lookup_refund — when the message references a refund ID (REF-####)
- classify_dispute — when the customer describes a billing or delivery dispute
- route_escalation — after a dispute is classified, route to the right team

Respond with structured tool calls only. Never invent refund statuses.
"""


def _dataset_snapshot(dataset_raw: dict) -> dict:
    desc = dataset_raw.get("description") or ""
    if not isinstance(desc, str):
        desc = str(desc)
    return {
        "name": dataset_raw.get("name") or "golden_v1",
        "description": desc.strip(),
        "cases": dataset_raw.get("cases") or [],
    }


def _prompt_snapshot() -> dict:
    return {
        "prompt_name": "payments-router",
        "content": PAYMENTS_ROUTER_PROMPT,
        "model": "mock-router",
        "commit_message": "Initial payments agent router prompt",
        "author": "cortexops-sdk",
    }


def _resolve_api_project(client: CortexClient, fallback: str) -> str:
    try:
        return client.project_for_key()
    except Exception:
        return fallback


def _sync_dashboard_artifacts(client: CortexClient, project: str, dataset_raw: dict) -> None:
    """Push golden dataset + prompt via dedicated API endpoints."""
    snap = _dataset_snapshot(dataset_raw)
    if snap["cases"]:
        try:
            existing = {d.get("name") for d in client.list_datasets()}
            if snap["name"] not in existing:
                client.create_dataset(
                    name=snap["name"],
                    description=snap["description"],
                    cases=snap["cases"],
                )
                print(f"  Dataset synced: {snap['name']} ({len(snap['cases'])} cases)")
            else:
                print(f"  Dataset already exists: {snap['name']}")
        except Exception as exc:
            print(f"  Dataset sync failed: {exc}")

    try:
        catalog = client.list_prompt_catalog(project)
        if any(p.get("prompt_name") == "payments-router" for p in catalog):
            print("  Prompt already exists: payments-router")
        else:
            snap = _prompt_snapshot()
            client.commit_prompt(
                project,
                snap["prompt_name"],
                snap["content"],
                model=snap["model"],
                commit_message=snap["commit_message"],
                author=snap["author"],
            )
            print("  Prompt synced: payments-router v1")
    except Exception as exc:
        print(f"  Prompt sync failed: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Run CortexOps evals for the payments agent")
    parser.add_argument("--dataset", default="golden_v1.yaml", help="Path to golden dataset YAML")
    parser.add_argument("--project", default=os.getenv("CORTEXOPS_PROJECT", DEFAULT_PROJECT))
    parser.add_argument("--api-key", default=os.getenv("CORTEXOPS_API_KEY"), help="Override API key")
    parser.add_argument("--fail-on", default=None, help="e.g. 'task_completion < 0.90'")
    parser.add_argument("--output", default=None, help="Save JSON summary to this path")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-case output")
    parser.add_argument("--sync-only", action="store_true", help="Only sync dataset/prompt to the API")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    dataset_raw = yaml.safe_load(dataset_path.read_text())
    dataset_raw["project"] = args.project

    tracer = CortexTracer(project=args.project, api_key=args.api_key)

    if args.sync_only:
        if not tracer.is_hosted:
            print("Error: No API key found. Set CORTEXOPS_API_KEY or run: cortexops login")
            sys.exit(1)
        client = CortexClient(api_key=tracer.api_key, base_url=tracer.api_url)
        api_project = _resolve_api_project(client, args.project)
        if api_project != args.project:
            print(f"Note: using project '{api_project}' from your API key (not --project {args.project})")
        print("Syncing dashboard artifacts…")
        _sync_dashboard_artifacts(client, api_project, dataset_raw)
        print(f"\nDone. Open the dashboard and log in with this API key.")
        print(f"  Sidebar project should show: {api_project}")
        sys.exit(0)

    print("CortexOps eval runner")
    print(f"  Project  : {args.project}")
    print(f"  Dataset  : {args.dataset}")
    print(f"  Fail on  : {args.fail_on or 'none'}")
    print()

    agent = tracer.wrap(build_agent())

    def instrumented_agent(inp: dict) -> dict:
        return agent.invoke(inp)

    try:
        summary = EvalSuite.run(
            dataset=dataset_raw,
            agent=instrumented_agent,
            verbose=not args.quiet,
            fail_on=args.fail_on,
        )
    except EvalThresholdError as e:
        print(f"\nCI gate FAILED: {e}")
        sys.exit(1)

    if tracer.is_hosted:
        client = CortexClient(api_key=tracer.api_key, base_url=tracer.api_url)
        api_project = _resolve_api_project(client, args.project)
        if api_project != args.project:
            print(f"\nNote: API key is for project '{api_project}' (not '{args.project}')")
        summary.project = api_project
        try:
            client.push_eval(
                summary,
                dataset=_dataset_snapshot(dataset_raw),
                prompt=_prompt_snapshot(),
            )
            print(f"\nEval pushed to dashboard (run_id={summary.run_id[:8]}...)")
            print("  Dataset + prompt included in ingest")
        except Exception as exc:
            print(f"\nWarning: eval ingest failed: {exc}")
            print("  Trying standalone dataset/prompt sync…")
            _sync_dashboard_artifacts(client, api_project, dataset_raw)
    else:
        print("\nNo API key — eval ran locally only. Set CORTEXOPS_API_KEY to push to dashboard.")

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(summary.model_dump(mode="json"), indent=2))
        print(f"\nResults written to {out_path}")

    exit_code = 0 if summary.failed == 0 else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
