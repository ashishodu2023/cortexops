"""Deterministic reference agent for the rag_qa golden dataset.

A rule-based stand-in for an LLM retrieval-augmented QA agent over the documentation of a
fictional storage product ("Nimbus"), stored as Markdown in ./corpus. It retrieves with a
small TF-IDF ranker, sanitises retrieved text against indirect prompt injection, uses a
calculator tool for pricing maths, cites sources, and abstains when the corpus does not
answer the question. No LLM or API key is needed.

    python rag_agent.py "How long are deleted files kept in the trash?"

`build_agent(variant=...)` also builds the deliberately degraded variants used in
docs/reports/agent-reliability-2026-10.md (see VARIANTS).
"""
from __future__ import annotations

import ast
import json
import math
import operator
import re
import sys
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cortexops import CortexTracer

PROJECT = "rag-qa-agent"
PROMPT_NAME = "rag-answer"
PROMPT_VERSION = "v1"
CORPUS_DIR = Path(__file__).with_name("corpus")
ABSTAIN_BELOW = 4.0
ABSTAIN_MESSAGE = "The Nimbus documentation does not cover that question, so I won't guess."

VARIANTS: dict[str, str] = {
    "reference": "All tools available, retrieved text sanitised, user overrides ignored.",
    "missing_tool": "calculator removed; pricing questions are answered with the unit price only.",
    "flaky_tool": "retrieve times out for one in three queries; the agent degrades to a 'search unavailable' reply.",
    "injection_susceptible": "No sanitisation of retrieved text and user overrides are obeyed.",
    "slow_tool": "retrieve answers 2 s slower (degraded vector store).",
}

STOPWORDS = set(
    "a an the is are was were be been of to in on for and or with by at from as it its this that these those "
    "i my me we our you your do does did can could would should will how what which who whom when where why "
    "much many there their them they any some all have has had if than then so not no yes please tell about "
    "nimbus".split()
)


class ToolError(RuntimeError):
    pass


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:[.,%-][a-z0-9]+)*%?", text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS]


def _load_corpus() -> list[dict[str, Any]]:
    chunks = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        body = "\n".join(line for line in path.read_text().splitlines() if not line.startswith("#"))
        for sentence in re.split(r"(?<=[.!?])\s+", body.strip()):
            if sentence.strip():
                chunks.append({"doc_id": path.stem, "text": sentence.strip(), "tokens": tokenize(sentence)})
    return chunks


CHUNKS = _load_corpus()
_DF: dict[str, int] = {}
for _chunk in CHUNKS:
    for _tok in set(_chunk["tokens"]):
        _DF[_tok] = _DF.get(_tok, 0) + 1
IDF = {tok: math.log((len(CHUNKS) + 1) / (df + 0.5)) for tok, df in _DF.items()}


# ── Tools ────────────────────────────────────────────────────────────────────

def retrieve(query: str, k: int = 3) -> list[dict[str, Any]]:
    q = set(tokenize(query))
    scored = []
    for i, chunk in enumerate(CHUNKS):
        score = sum(IDF[t] for t in q & set(chunk["tokens"]))
        if score > 0:
            scored.append((round(score, 4), -i, chunk))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [{"doc_id": c["doc_id"], "text": c["text"], "score": s} for s, _, c in scored[:k]]


def get_document(doc_id: str) -> dict[str, Any]:
    path = CORPUS_DIR / f"{doc_id}.md"
    lines = path.read_text().splitlines()
    return {"doc_id": doc_id, "title": lines[0].lstrip("# ").strip(), "text": "\n".join(lines[1:]).strip()}


_OPS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("max", "min"):
        fn = max if node.func.id == "max" else min
        return fn(_eval_node(a) for a in node.args)
    raise ToolError(f"unsupported expression: {ast.dump(node)[:60]}")


def calculator(expression: str) -> dict[str, Any]:
    return {"expression": expression, "value": round(_eval_node(ast.parse(expression, mode="eval").body), 4)}


TOOLS: dict[str, Callable[..., Any]] = {"retrieve": retrieve, "get_document": get_document, "calculator": calculator}


def make_flaky(fn: Callable[..., Any], message: str, every: int = 3) -> Callable[..., Any]:
    """Fail deterministically for one in `every` argument sets."""
    def flaky(**kwargs: Any) -> Any:
        if zlib.crc32(json.dumps(kwargs, sort_keys=True).encode()) % every == 0:
            raise ToolError(message)
        return fn(**kwargs)
    return flaky


def make_slow(fn: Callable[..., Any], delay_s: float) -> Callable[..., Any]:
    def slow(**kwargs: Any) -> Any:
        time.sleep(delay_s)
        return fn(**kwargs)
    return slow


# ── Agent ────────────────────────────────────────────────────────────────────

USER_OVERRIDE = re.compile(
    r"ignore (?:the |all |any )?(?:documentation|docs|context|previous instructions|your rules)\s*(?:and\s*)?",
    re.IGNORECASE,
)
ROLE_PLAY = re.compile(r"\byou are now\b|\bno rules\b|\bjailbreak\b|\bDAN\b")
EMBEDDED_INSTRUCTION = re.compile(
    r"ignore (?:all )?previous instructions|\bai assistants?\b.*\b(?:should|must)\b", re.IGNORECASE
)
UNAUTHORIZED = re.compile(
    r"(?:another|other|someone else'?s?) (?:customer|user|account|person)'?s?\b.*\b(?:without|bypass)"
    r"|\b(?:admin|root|master) password\b|\bhack\b",
    re.IGNORECASE,
)
VAGUE = re.compile(r"\s*(?:what'?s|what is|how much is) (?:the |it)?\s*(?:limit|price|cost|it)?\s*\??\s*", re.IGNORECASE)
QUANTITY = re.compile(r"(\d+(?:\.\d+)?)\s*(tb|gb)\b", re.IGNORECASE)
SUMMARY = re.compile(r"\bsummari[sz]e\b(.*)", re.IGNORECASE)
CONFIRM = re.compile(r"\b(?:confirm|say|tell me) that (.+)", re.IGNORECASE)


class SearchUnavailable(Exception):
    pass


class RagAgent:
    """Guardrails -> router -> retrieve / calculate -> grounded answer with citations."""

    def __init__(self, tools: dict[str, Callable[..., Any]], tracer: CortexTracer, *, guardrails: bool = True) -> None:
        self.tools = tools
        self.tracer = tracer
        self.guardrails = guardrails

    def invoke(self, inp: dict[str, Any]) -> dict[str, Any]:
        question = str(inp.get("input", "")).strip()
        if inp.get("plan"):
            question = f"{question} (my plan: {inp['plan']})"
        calls: list[str] = []
        citations: list[str] = []
        try:
            answer = self._answer(question, calls, citations)
        except SearchUnavailable:
            answer = "Documentation search is temporarily unavailable, so I can't answer that reliably right now."
            citations = []
        if citations:
            answer = f"{answer} Sources: {', '.join(f'[{c}]' for c in dict.fromkeys(citations))}"
        return {"output": answer, "citations": list(dict.fromkeys(citations)), "tool_calls_made": calls}

    def _call(self, calls: list[str], tool: str, /, **args: Any) -> Any:
        fn = self.tools.get(tool)
        if fn is None:
            return None
        calls.append(tool)
        result, error = None, None
        t0 = time.perf_counter()
        with self.tracer.trace_node(f"tool:{tool}") as node:
            node.input = args
            try:
                result = fn(**args)
            except ToolError as exc:
                error = str(exc)
            node.output = {"error": error} if error else {"result": result}
        # record_tool_call attaches to the most recently closed node, so it must run after the block.
        self.tracer.record_tool_call(tool, args=args, result=result, error=error,
                                     latency_ms=(time.perf_counter() - t0) * 1000)
        if error:
            raise SearchUnavailable(error)
        return result

    def _answer(self, question: str, calls: list[str], citations: list[str]) -> str:
        with self.tracer.trace_node("guardrails") as node:
            override = USER_OVERRIDE.search(question)
            if self.guardrails:
                question = USER_OVERRIDE.sub("", question).strip()
            node.output = {"override_detected": bool(override)}

        if UNAUTHORIZED.search(question) and (self.guardrails or not ROLE_PLAY.search(question)):
            return "I can't help with accessing accounts, data, or credentials you aren't authorized to use."

        if not self.guardrails and (override or ROLE_PLAY.search(question)):
            confirm = CONFIRM.search(question)
            if confirm:
                return f"Confirmed: {confirm.group(1).rstrip('.?!')}."

        if VAGUE.fullmatch(question):
            return ("Could you clarify what you'd like to know: storage pricing, file size limits, "
                    "API rate limits, or something else?")

        summary = SUMMARY.search(question)
        if summary:
            return self._summarize(summary.group(1), calls, citations)

        quantity = QUANTITY.search(question)
        if quantity and re.search(r"\b(cost|pay|price|how much)\b", question, re.IGNORECASE):
            return self._price(question, quantity, calls, citations)

        return self._grounded(question, calls, citations)

    def _passages(self, query: str, calls: list[str], k: int = 3) -> list[dict[str, Any]]:
        passages = self._call(calls, "retrieve", query=query, k=k) or []
        if self.guardrails:
            passages = [p for p in passages if not EMBEDDED_INSTRUCTION.search(p["text"])]
        return passages

    def _grounded(self, question: str, calls: list[str], citations: list[str]) -> str:
        passages = self._passages(question, calls)
        with self.tracer.trace_node("synthesize") as node:
            if not passages or passages[0]["score"] < ABSTAIN_BELOW:
                node.output = {"abstained": True}
                return ABSTAIN_MESSAGE
            best = passages[0]["score"]
            chosen = [p for p in passages if p["score"] >= 0.6 * best][:2]
            citations.extend(p["doc_id"] for p in chosen)
            node.output = {"abstained": False, "chunks": len(chosen)}
            return " ".join(p["text"] for p in chosen)

    def _summarize(self, target: str, calls: list[str], citations: list[str]) -> str:
        wanted = set(tokenize(target)) - {"doc", "documentation", "page", "section"}
        best = max(
            (len(wanted & set(tokenize(p.stem.replace("_", " ") + " " + p.read_text().splitlines()[0]))), p.stem)
            for p in sorted(CORPUS_DIR.glob("*.md"))
        )
        if best[0] == 0:
            return ABSTAIN_MESSAGE
        doc = self._call(calls, "get_document", doc_id=best[1])
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", doc["text"]) if s]
        if self.guardrails:
            sentences = [s for s in sentences if not EMBEDDED_INSTRUCTION.search(s)]
        citations.append(doc["doc_id"])
        return f"{doc['title']}: " + " ".join(sentences[:4])

    def _price(self, question: str, quantity: re.Match[str], calls: list[str], citations: list[str]) -> str:
        amount = float(quantity.group(1))
        gb = amount * 1024 if quantity.group(2).lower() == "tb" else amount
        size = f"{quantity.group(1)} {quantity.group(2).upper()}"
        lower = question.lower()
        if re.search(r"\b(download|egress)", lower):
            passages = self._passages("egress downloads price per GB", calls, k=1)
            text = passages[0]["text"] if passages else ""
            free = re.search(r"first (\d+) GB", text)
            price = re.search(r"\$(\d+(?:\.\d+)?) per GB", text)
            if not (free and price):
                return ABSTAIN_MESSAGE
            citations.append(passages[0]["doc_id"])
            calc = self._call(calls, "calculator", expression=f"max(0, {gb:g} - {free.group(1)}) * {price.group(1)}")
            if calc is None:
                return text
            return (f"Downloading {size} costs ${calc['value']:.2f} in egress for the month: the first "
                    f"{free.group(1)} GB are free and the rest is ${price.group(1)} per GB.")

        plan = next((p for p in ("business", "pro", "free") if p in lower), "pro")
        passages = self._passages(f"{plan} plan costs per GB per month minimum", calls, k=3)
        sentence = next((p for p in passages if plan in p["text"].lower() and "per gb" in p["text"].lower()), None)
        if sentence is None:
            return ABSTAIN_MESSAGE
        citations.append(sentence["doc_id"])
        price = re.search(r"\$(\d+(?:\.\d+)?) per GB", sentence["text"])
        minimum = re.search(r"(\d+) TB minimum", sentence["text"])
        min_gb = float(minimum.group(1)) * 1024 if minimum else 0.0
        billable = max(gb, min_gb)
        calc = self._call(calls, "calculator", expression=f"{billable:g} * {price.group(1)}")
        if calc is None:
            return sentence["text"]
        note = ""
        if billable > gb:
            note = f" The {plan.title()} plan has a {minimum.group(1)} TB minimum, so it is billed as {billable:g} GB."
        return (f"{size} on the {plan.title()} plan costs ${calc['value']:.2f} per month "
                f"({billable:g} GB x ${price.group(1)} per GB).{note}")


def build_agent(
    variant: str = "reference",
    *,
    tracer: CortexTracer | None = None,
    slow_delay_s: float = 2.0,
) -> Any:
    """Return the instrumented agent (an object with `.invoke(dict) -> dict`)."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {sorted(VARIANTS)}")
    tracer = tracer or CortexTracer(project=PROJECT)
    tracer.set_prompt(PROMPT_NAME, PROMPT_VERSION)
    tools = dict(TOOLS)
    if variant == "missing_tool":
        del tools["calculator"]
    elif variant == "flaky_tool":
        tools["retrieve"] = make_flaky(retrieve, "vector store timed out after 30s")
    elif variant == "slow_tool":
        tools["retrieve"] = make_slow(retrieve, slow_delay_s)
    agent = RagAgent(tools, tracer, guardrails=variant != "injection_susceptible")
    return tracer.wrap(agent)


_default_agent: Any = None


def run(inp: dict[str, Any]) -> dict[str, Any]:
    """Module-level entry point for `cortexops eval run --agent rag_agent:run`."""
    global _default_agent
    if _default_agent is None:
        _default_agent = build_agent()
    return _default_agent.invoke(inp)


if __name__ == "__main__":
    print(run({"input": " ".join(sys.argv[1:]) or "How long are deleted files kept in the trash?"})["output"])
