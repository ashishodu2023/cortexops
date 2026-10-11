"""Execute the code in docs/integrations/<framework>.md against the real framework packages.

    pip install -e "sdk[pytest]" langgraph langchain-core pydantic-ai-slim openai-agents google-adk crewai
    python docs/integrations/_verify/verify_guides.py              # every guide whose framework is installed
    python docs/integrations/_verify/verify_guides.py langgraph    # one guide

For each guide, the fenced blocks whose first line is `# <file>` (or `# <file> (continued)`) are
written verbatim to a temporary directory. The one line that selects a hosted model is swapped for an
offline fake from fakes.py (see SUBSTITUTIONS), so the framework's real agent loop, tool execution and
result objects run without API keys. Then the guide's own shell commands (`pytest ...`,
`PYTHONPATH=. cortexops eval run ...`) are run exactly as written, plus `python my_agent.py` and the
extra checks below. Exits 1 if anything fails.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUIDES = HERE.parent

SUBSTITUTIONS: dict[str, list[tuple[str, str]]] = {
    "langgraph": [("from langchain_openai import ChatOpenAI", "from fakes import FakeChatOpenAI as ChatOpenAI")],
    "pydantic_ai": [('MODEL = "openai:gpt-4o-mini"',
                     "from fakes import pydantic_ai_model\nMODEL = pydantic_ai_model()")],
    "openai_agents": [('MODEL = "gpt-4o-mini"', "from fakes import openai_agents_model\nMODEL = openai_agents_model()")],
    "google_adk": [('MODEL = "gemini-2.0-flash"', "from fakes import adk_model\nMODEL = adk_model()")],
    "crewai": [('LLM = "gpt-4o-mini"', "from fakes import crewai_llm\nLLM = crewai_llm()")],
}
PACKAGES = {
    "langgraph": ["langgraph", "langchain_core"],
    "pydantic_ai": ["pydantic_ai"],
    "openai_agents": ["agents"],
    "google_adk": ["google.adk"],
    "crewai": ["crewai"],
}
DISTRIBUTIONS = {
    "langgraph": "langgraph", "pydantic_ai": "pydantic-ai-slim", "openai_agents": "openai-agents",
    "google_adk": "google-adk", "crewai": "crewai",
}

# Extra behaviour the guides claim, checked against the real packages.
EXTRA_CHECKS: dict[str, str] = {
    "langgraph": """
import asyncio
from langchain_core.messages import HumanMessage
from my_agent import traced_graph, tracer
state = asyncio.run(traced_graph.ainvoke({"messages": [HumanMessage("Status of REF-9902?")]}))
assert "pending" in state["messages"][-1].content
assert tracer.last_trace().status.value == "completed"
assert type(traced_graph.get_graph()).__name__ == "Graph"
tracer.last_trace().model_dump(mode="json")
""",
    "pydantic_ai": """
from my_agent import traced_agent, tracer
result = traced_agent.run_sync("Status of REF-9902?")
assert result.output == "Refund REF-9902 is pending." and not hasattr(result, "data")
assert tracer.last_trace().output["result"].startswith("AgentRunResult(")
from pydantic_ai.models.test import TestModel
from my_agent import agent, eval_agent
with agent.override(model=TestModel()):
    out = eval_agent({"input": "Status of REF-8821?"})
assert out["output"] and out["tool_calls_made"] == ["lookup_refund"], out
""",
    "openai_agents": """
import asyncio
from my_agent import traced_agent, tracer
result = asyncio.run(traced_agent.run("Status of REF-9902?"))
assert result.final_output == "Refund REF-9902 is pending.", result.final_output
assert tracer.last_trace().status.value == "completed"
""",
    "google_adk": """
from cortexops import CortexTracer
from my_agent import root_agent, traced_agent, tracer
out = traced_agent.invoke({"input": "Status of REF-9902?"})
assert out == {"output": "Refund REF-9902 is pending.", "tool_calls_made": ["lookup_refund"]}, out
assert tracer.last_trace().output == out and tracer.last_trace().status.value == "completed"
try:
    CortexTracer(project="probe").wrap(root_agent).run("hello")
except Exception as exc:
    print("direct wrap(agent).run fails as documented:", type(exc).__name__)
else:
    raise AssertionError("wrap(agent).run unexpectedly worked; update the guide")
""",
    "crewai": """
from my_agent import traced_crew, tracer
result = traced_crew.kickoff(inputs={"question": "Status of REF-9902?"})
assert "pending" in result.raw
assert tracer.last_trace().input == {"question": "Status of REF-9902?"}
""",
}

FILE_HEADER = re.compile(r"^# ([\w./-]+\.(?:py|yaml))( \(continued\))?$")
ENV_ASSIGNMENT = re.compile(r"^[A-Z_][A-Z0-9_]*=")
FENCE = re.compile(r"^```(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def extract(guide: Path) -> tuple[dict[str, str], list[str], list[str]]:
    files: dict[str, str] = {}
    commands: list[str] = []
    python_blocks: list[str] = []
    for lang, body in FENCE.findall(guide.read_text()):
        first = body.splitlines()[0] if body.strip() else ""
        header = FILE_HEADER.match(first)
        if lang == "python":
            python_blocks.append(body)
        if header:
            name = header.group(1)
            if header.group(2):
                files[name] = files[name].rstrip("\n") + "\n\n\n" + body
            else:
                files[name] = body
        elif lang == "bash":
            commands += [ln for ln in body.splitlines() if ln.startswith(("pytest ", "PYTHONPATH=. cortexops"))]
    return files, commands, python_blocks


def run(cmd: str | list[str], cwd: Path, env: dict[str, str]) -> tuple[bool, str]:
    """Run a guide command such as `PYTHONPATH=. cortexops eval run ...` without a shell."""
    argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    env = dict(env)
    while argv and ENV_ASSIGNMENT.match(argv[0]):
        key, _, value = argv.pop(0).partition("=")
        env[key] = value
    argv[0] = shutil.which(argv[0], path=env["PATH"]) or argv[0]
    proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=600,
                          stdin=subprocess.DEVNULL)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:]


def verify(name: str) -> list[str]:
    errors: list[str] = []
    guide = GUIDES / f"{name}.md"
    files, commands, python_blocks = extract(guide)
    for block in python_blocks:
        try:
            ast.parse(block)
        except SyntaxError as exc:
            errors.append(f"python block does not parse: {exc}")
    if {"my_agent.py", "golden.yaml", "test_my_agent.py"} - set(files):
        return errors + [f"missing file blocks, found {sorted(files)}"]
    if len(commands) < 2:
        errors.append(f"expected pytest and cortexops commands, found {commands}")

    for old, new in SUBSTITUTIONS[name]:
        count = files["my_agent.py"].count(old)
        if count != 1:
            return errors + [f"model line {old!r} found {count} times in my_agent.py"]
        files["my_agent.py"] = files["my_agent.py"].replace(old, new)

    with tempfile.TemporaryDirectory(prefix=f"guide-{name}-") as tmp:
        work = Path(tmp)
        for filename, content in files.items():
            (work / filename).write_text(content)
        shutil.copy(HERE / "fakes.py", work / "fakes.py")
        (work / "home").mkdir()
        env = {
            **os.environ,
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(work / "home"),
            "OPENAI_AGENTS_DISABLE_TRACING": "1",
            "CREWAI_DISABLE_TELEMETRY": "true",
            "CREWAI_TRACING_ENABLED": "false",
            "OTEL_SDK_DISABLED": "true",
            "PYDANTIC_AI_NO_BANNER": "1",
            "PYTHONWARNINGS": "ignore",
        }
        env.pop("CORTEXOPS_API_KEY", None)
        env.pop("PYTHONPATH", None)

        ok, out = run([sys.executable, "my_agent.py"], work, env)
        if not ok or "completed" not in out or "v2" not in out:
            errors.append(f"python my_agent.py failed or missed status/prompt version:\n{out}")
        for cmd in commands:
            ok, out = run(cmd, work, env)
            if not ok:
                errors.append(f"`{cmd}` failed:\n{out}")
        (work / "_extra_check.py").write_text(EXTRA_CHECKS[name])
        ok, out = run([sys.executable, "_extra_check.py"], work, env)
        if not ok:
            errors.append(f"extra check failed:\n{out}")
    return errors


def installed(name: str) -> bool:
    try:
        return all(importlib.util.find_spec(pkg) is not None for pkg in PACKAGES[name])
    except ModuleNotFoundError:
        return False


def main(argv: list[str]) -> int:
    from importlib.metadata import version

    names = argv or sorted(SUBSTITUTIONS)
    failed = False
    for name in names:
        if not installed(name):
            print(f"SKIP  {name}: {', '.join(PACKAGES[name])} not installed")
            continue
        errors = verify(name)
        label = f"{name} ({DISTRIBUTIONS[name]} {version(DISTRIBUTIONS[name])})"
        if errors:
            failed = True
            print(f"FAIL  {label}")
            for err in errors:
                print("      " + err.replace("\n", "\n      "))
        else:
            print(f"PASS  {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
