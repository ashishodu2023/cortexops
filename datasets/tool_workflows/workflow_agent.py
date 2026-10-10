"""Deterministic reference agent for the tool_workflows golden dataset.

A rule-based stand-in for an LLM "workspace assistant" that chains tools: contact search,
calendar, email, tickets, a read-only SQL reporting database (in-memory SQLite), currency
conversion and a calculator. It enforces confirmation for external email, read-only SQL,
working hours, and ignores instructions embedded in tool output. No LLM or API key needed.

    python workflow_agent.py "Convert 250 USD to EUR."

Unlike the other reference agents, this one has no tool-error handling: a failing tool
raises out of `invoke`, which is how the flaky_tool variant surfaces in the report.
`build_agent(variant=...)` builds the degraded variants (see VARIANTS).
"""
from __future__ import annotations

import ast
import json
import operator
import re
import sqlite3
import sys
import time
import zlib
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from cortexops import CortexTracer

PROJECT = "tool-workflows-agent"
PROMPT_NAME = "workspace-assistant"
PROMPT_VERSION = "v1"

FIXTURES = json.loads(Path(__file__).with_name("fixtures.json").read_text())
TODAY = date.fromisoformat(FIXTURES["today"])
INTERNAL_DOMAIN = FIXTURES["internal_domain"]
WORK_START, WORK_END = FIXTURES["working_hours"]

VARIANTS: dict[str, str] = {
    "reference": "All tools available, guardrails on.",
    "missing_tool": "check_calendar removed; meetings are booked without an availability check.",
    "flaky_tool": "search_contacts fails for one in three names; the exception propagates (no error handling).",
    "injection_susceptible": "Guardrails off: external email without confirmation, raw SQL, obeys tool-output text.",
    "slow_tool": "convert_currency answers 2 s slower (slow FX-rate provider).",
}


class ToolError(RuntimeError):
    pass


# ── Tools ────────────────────────────────────────────────────────────────────

def search_contacts(name: str) -> dict[str, Any]:
    wanted = name.lower().strip()
    matches = [c for c in FIXTURES["contacts"] if c["name"].lower() == wanted or c["name"].lower().split()[0] == wanted]
    return {"query": name, "matches": matches}


def check_calendar(date: str, time: str) -> dict[str, Any]:
    busy = set(FIXTURES["busy"].get(date, []))
    hour = int(time.split(":")[0])
    next_free = next((f"{h:02d}:00" for h in range(hour + 1, WORK_END) if f"{h:02d}:00" not in busy), None)
    return {"date": date, "time": time, "free": time not in busy, "next_free": next_free}


def create_event(title: str, date: str, time: str, attendees: list[str]) -> dict[str, Any]:
    event_id = f"EVT-{zlib.crc32(f'{title}|{date}|{time}'.encode()) % 10000:04d}"
    return {"event_id": event_id, "title": title, "date": date, "time": time, "attendees": attendees}


def send_email(to: list[str], subject: str, body: str) -> dict[str, Any]:
    return {"message_id": f"MSG-{zlib.crc32((','.join(to) + subject).encode()) % 10000:04d}", "to": to}


def create_ticket(summary: str, priority: str = "P3") -> dict[str, Any]:
    return {"ticket_id": f"TCK-{200 + zlib.crc32(summary.encode()) % 800}", "summary": summary, "priority": priority}


def get_ticket(ticket_id: str) -> dict[str, Any]:
    ticket = next((t for t in FIXTURES["tickets"] if t["id"] == ticket_id), None)
    return {"found": ticket is not None, **(ticket or {"id": ticket_id})}


def run_sql(query: str) -> dict[str, Any]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE tickets (id TEXT, status TEXT, priority TEXT, summary TEXT, description TEXT)")
        conn.executemany(
            "INSERT INTO tickets VALUES (?, ?, ?, ?, ?)",
            [(t["id"], t["status"], t["priority"], t["summary"], t["description"]) for t in FIXTURES["tickets"]],
        )
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute(query).fetchall()
    except sqlite3.Error as exc:
        raise ToolError(f"sql rejected: {exc}") from exc
    finally:
        conn.close()
    return {"rows": [list(r) for r in rows]}


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict[str, Any]:
    rates = FIXTURES["usd_per_unit"]
    for code in (from_currency, to_currency):
        if code not in rates:
            return {"supported": False, "currency": code, "supported_currencies": sorted(rates)}
    return {"supported": True, "converted": round(amount * rates[from_currency] / rates[to_currency], 2)}


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
    raise ToolError("unsupported expression")


def calculator(expression: str) -> dict[str, Any]:
    return {"expression": expression, "value": round(_eval_node(ast.parse(expression, mode="eval").body), 4)}


TOOLS: dict[str, Callable[..., Any]] = {
    "search_contacts": search_contacts,
    "check_calendar": check_calendar,
    "create_event": create_event,
    "send_email": send_email,
    "create_ticket": create_ticket,
    "get_ticket": get_ticket,
    "run_sql": run_sql,
    "convert_currency": convert_currency,
    "calculator": calculator,
}


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

OVERRIDE = re.compile(r"ignore (?:your|all|any|previous) (?:rules|instructions)\s*(?:and\s*)?", re.IGNORECASE)
DESTRUCTIVE_SQL = re.compile(
    r"\b(?:drop\s+table|delete\s+from|truncate\s+table|alter\s+table|insert\s+into|update\s+\w+\s+set)\b", re.IGNORECASE
)
EMAIL_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
COPY_CLAUSE = re.compile(r"[^.]*\b(?:bcc|cc|forward)\b[^.]*@[^.]*(?:\.[a-z]+)*\.?", re.IGNORECASE)
EMBEDDED = re.compile(r"\bai assistant\b.*\b(?:forward|send|email)\b.*?([\w.+-]+@[\w-]+(?:\.[\w-]+)+)", re.IGNORECASE)
UNSUPPORTED = re.compile(r"\b(flight|hotel|train ticket|taxi|uber)\b", re.IGNORECASE)
ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
AT_TIME = re.compile(r"\bat (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
CONVERSION = re.compile(r"([\d,]+(?:\.\d+)?)\s*([A-Za-z]{3})\s+(?:to|in|into)\s+([A-Za-z]{3})\b")
PERCENT = re.compile(r"([\d.]+)%\s+of\s+([\d,]+(?:\.\d+)?)")
NAME = r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
EMAIL_NAMES = re.compile(rf"^(?i:please\s+)?(?i:email|message)\s+({NAME}(?:\s*(?:,|and)\s*{NAME})*)")


class WorkflowAgent:
    """Guardrails -> intent router -> tool chain -> response, one trace node per step."""

    def __init__(self, tools: dict[str, Callable[..., Any]], tracer: CortexTracer, *, guardrails: bool = True) -> None:
        self.tools = tools
        self.tracer = tracer
        self.guardrails = guardrails

    def invoke(self, inp: dict[str, Any]) -> dict[str, Any]:
        calls: list[str] = []
        answer = self._handle(str(inp.get("input", "")).strip(), inp, calls)
        return {"output": answer, "tool_calls_made": calls}

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
            raise ToolError(f"{tool}: {error}")
        return result

    def _handle(self, text: str, inp: dict[str, Any], calls: list[str]) -> str:
        with self.tracer.trace_node("guardrails") as node:
            text = OVERRIDE.sub("", text).strip()
            destructive = bool(DESTRUCTIVE_SQL.search(text))
            node.output = {"destructive_sql": destructive}
        lower = text.lower()

        if destructive:
            if self.guardrails:
                return "I can only run read-only queries against the reporting database, so I won't run that."
            return self._raw_sql(text, calls)
        if UNSUPPORTED.search(text):
            return ("Travel booking isn't supported. I can help with meetings, email, tickets, currency "
                    "conversion, and ticket reports.")
        if re.match(r"(?:please\s+)?(?:email|message|send)\b", lower):
            return self._email(text, calls)
        if re.search(r"\bexpense\b", lower):
            return self._expense(text, calls)
        if re.search(r"\b(how many|count)\b.*\btickets?\b", lower):
            return self._ticket_report(calls)
        if re.search(r"\b(open|create|file)\b.*\btickets?\b", lower):
            return self._create_tickets(text, calls)
        ticket_id = re.search(r"\bTCK-\d+\b", text)
        if ticket_id:
            return self._read_ticket(ticket_id.group(0), calls)
        if "amount" in inp or CONVERSION.search(text):
            return self._convert(text, inp, calls)
        percent = PERCENT.search(text)
        if percent:
            calc = self._call(calls, "calculator",
                              expression=f"{percent.group(1)} / 100 * {percent.group(2).replace(',', '')}")
            return f"{percent.group(1)}% of {percent.group(2)} is {calc['value']:,.2f}."
        if re.search(r"\b(schedule|book|set up|arrange)\b", lower):
            return self._meeting(text, calls)
        return "I can help with meetings, email, tickets, currency conversion, and ticket reports. What do you need?"

    # ── Flows ────────────────────────────────────────────────────────────

    def _resolve(self, names: list[str], calls: list[str]) -> tuple[list[dict[str, str]], list[str], list[str]]:
        found, missing, ambiguous = [], [], []
        for name in names:
            result = self._call(calls, "search_contacts", name=name)
            matches = result["matches"]
            if not matches:
                missing.append(name)
            elif len(matches) > 1:
                ambiguous.append(f"I found {len(matches)} contacts named {name}: "
                                 f"{' and '.join(m['name'] for m in matches)}. Which one did you mean?")
            else:
                found.append(matches[0])
        return found, missing, ambiguous

    def _names_in(self, text: str) -> list[str]:
        names = [c["name"] for c in FIXTURES["contacts"] if c["name"] in text]
        for contact in FIXTURES["contacts"]:
            first = contact["name"].split()[0]
            if re.search(rf"\b{first}\b", text) and not any(n.startswith(first) for n in names):
                names.append(first)
        for match in re.finditer(rf"\bwith ({NAME})", text):
            if not any(match.group(1).startswith(n.split()[0]) for n in names):
                names.append(match.group(1))
        return names

    def _meeting(self, text: str, calls: list[str]) -> str:
        names = self._names_in(text)
        day = ISO_DATE.search(text)
        at = AT_TIME.search(text)
        if not names or not day or not at:
            return "Happy to set that up. Who should attend, and when (date and time)?"
        hour = int(at.group(1)) % 12 + (12 if (at.group(3) or "").lower() == "pm" else 0)
        if not at.group(3):
            hour = int(at.group(1))
        slot = f"{hour:02d}:{at.group(2) or '00'}"
        if date.fromisoformat(day.group(1)) < TODAY:
            return f"{day.group(1)} is in the past. Which upcoming date should I use?"
        if not WORK_START <= hour < WORK_END:
            return (f"{slot} is outside working hours ({WORK_START:02d}:00-{WORK_END:02d}:00). "
                    "Which time inside that window works?")
        found, missing, ambiguous = self._resolve(names, calls)
        if ambiguous:
            return " ".join(ambiguous)
        if missing:
            return f"I couldn't find a contact named {', '.join(missing)}."
        who = ", ".join(f"{c['name']} ({c['email']})" for c in found)
        availability = self._call(calls, "check_calendar", date=day.group(1), time=slot)
        if availability is not None and not availability["free"]:
            return (f"{' and '.join(c['name'] for c in found)} is busy at {slot} on {day.group(1)}. The next free "
                    f"slot that day is {availability['next_free']}. Should I book that instead?")
        title_match = re.search(r"(?<![A-Za-z])'([^']+)'(?![A-Za-z])", text) or re.search(r"\babout ([^.]+)", text)
        title = title_match.group(1).strip() if title_match else "Meeting"
        event = self._call(calls, "create_event", title=title, date=day.group(1), time=slot,
                           attendees=[c["email"] for c in found])
        return f"Scheduled '{title}' with {who} on {day.group(1)} at {slot} (event {event['event_id']})."

    def _email(self, text: str, calls: list[str]) -> str:
        notes = []
        if self.guardrails and COPY_CLAUSE.search(text):
            text = COPY_CLAUSE.sub("", text).strip()
            notes.append("I didn't add the requested copy to an outside address; that needs your explicit approval.")
        addresses = EMAIL_ADDRESS.findall(text)
        external = [a for a in addresses if not a.endswith("@" + INTERNAL_DOMAIN)]
        if external and self.guardrails:
            return (f"{', '.join(external)} is outside your organisation, so I need your explicit confirmation "
                    "before sending. Reply 'confirm' to send it.")
        names_match = EMAIL_NAMES.search(text)
        names = re.split(r"\s*(?:,|\band\b)\s*", names_match.group(1)) if names_match else []
        found, missing, ambiguous = self._resolve(names, calls)
        if ambiguous:
            return " ".join(ambiguous)
        recipients = [c["email"] for c in found] + addresses
        if not recipients:
            if missing:
                return f"I couldn't find a contact named {', '.join(missing)}."
            return "Who should I send it to?"
        body = text[names_match.end():] if names_match else re.sub(r"\bto\s+\S+@\S+", "", text)
        body = re.sub(r"^\s*(?:that|the)\s+", "", body).strip().rstrip(".") or "(no message)"
        self._call(calls, "send_email", to=recipients, subject=body[:60], body=body)
        who = ", ".join([f"{c['name']} ({c['email']})" for c in found] + addresses)
        parts = [f"Sent to {who}: {body}."]
        if missing:
            parts.append(f"I couldn't find a contact named {', '.join(missing)}, so they were not included.")
        return " ".join(parts + notes)

    def _convert(self, text: str, inp: dict[str, Any], calls: list[str]) -> str:
        if "amount" in inp:
            amount, src, dst = float(inp["amount"]), str(inp["from_currency"]), str(inp["to_currency"])
        else:
            match = CONVERSION.search(text)
            amount, src, dst = float(match.group(1).replace(",", "")), match.group(2), match.group(3)
        src, dst = src.upper(), dst.upper()
        result = self._call(calls, "convert_currency", amount=amount, from_currency=src, to_currency=dst)
        if not result["supported"]:
            return (f"{result['currency']} is not supported. Supported currencies: "
                    f"{', '.join(result['supported_currencies'])}.")
        return f"{amount:,.2f} {src} = {result['converted']:,.2f} {dst}."

    def _expense(self, text: str, calls: list[str]) -> str:
        spent = re.search(r"([\d,]+(?:\.\d+)?)\s*([A-Z]{3})\b", text)
        target = re.search(r"\bto ([A-Z]{3})\b", text)
        if not spent:
            return "How much did you spend, and in which currency?"
        what = re.search(r"\bon (?:a |an )?([^.]+?)\.", text)
        label = what.group(1) if what else "expense"
        amount, currency = float(spent.group(1).replace(",", "")), spent.group(2)
        dst = target.group(1) if target else "USD"
        converted = self._call(calls, "convert_currency", amount=amount, from_currency=currency, to_currency=dst)
        if not converted["supported"]:
            return f"{converted['currency']} is not supported, so I couldn't file the expense."
        ticket = self._call(calls, "create_ticket", summary=f"Expense: {label}, {converted['converted']:.2f} {dst}",
                            priority="P3")
        return (f"Converted {amount:,.2f} {currency} to {converted['converted']:,.2f} {dst} and filed expense "
                f"ticket {ticket['ticket_id']} (P3): {label}.")

    def _create_tickets(self, text: str, calls: list[str]) -> str:
        priority = re.search(r"\bP[0-4]\b", text)
        level = priority.group(0) if priority else "P3"
        body = text.split(":", 1)[1] if ":" in text else text
        items = [s.strip().rstrip(".") for s in body.split(";") if s.strip()]
        created = [self._call(calls, "create_ticket", summary=item, priority=level) for item in items]
        if len(created) == 1:
            return f"Created {created[0]['ticket_id']} ({level}): {items[0]}."
        listing = ", ".join(f"{t['ticket_id']} ({t['summary']})" for t in created)
        return f"Created {len(created)} tickets at {level}: {listing}."

    def _read_ticket(self, ticket_id: str, calls: list[str]) -> str:
        ticket = self._call(calls, "get_ticket", ticket_id=ticket_id)
        if not ticket["found"]:
            return f"I couldn't find ticket {ticket_id}."
        summary = f"{ticket_id} is {ticket['status']} ({ticket['priority']}): {ticket['summary']}."
        embedded = EMBEDDED.search(ticket["description"])
        if embedded and self.guardrails:
            return summary + " Its description contains instructions aimed at an AI assistant, which I ignored."
        if embedded:
            report = self._call(calls, "run_sql", query="SELECT id, summary FROM tickets WHERE status != 'closed'")
            self._call(calls, "send_email", to=[embedded.group(1)], subject="Open tickets", body=str(report["rows"]))
            return summary + f" Forwarded all open tickets to {embedded.group(1)} as instructed."
        return f"{summary} Details: {ticket['description']}"

    def _ticket_report(self, calls: list[str]) -> str:
        result = self._call(
            calls, "run_sql",
            query="SELECT priority, COUNT(*) FROM tickets WHERE status != 'closed' GROUP BY priority ORDER BY priority",
        )
        return "Open tickets by priority: " + ", ".join(f"{p}: {n}" for p, n in result["rows"]) + "."

    def _raw_sql(self, text: str, calls: list[str]) -> str:
        quoted = re.search(r"customer '(.+)$", text)
        if quoted:
            query = f"SELECT id, summary FROM tickets WHERE summary LIKE '%{quoted.group(1)}%'"
        else:
            query = re.sub(r"^\s*run:?\s*", "", text, flags=re.IGNORECASE).rstrip(".")
        result = self._call(calls, "run_sql", query=query)
        return f"Query executed: {len(result['rows'])} rows."


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
        del tools["check_calendar"]
    elif variant == "flaky_tool":
        tools["search_contacts"] = make_flaky(search_contacts, "directory service unavailable (HTTP 502)")
    elif variant == "slow_tool":
        tools["convert_currency"] = make_slow(convert_currency, slow_delay_s)
    agent = WorkflowAgent(tools, tracer, guardrails=variant != "injection_susceptible")
    return tracer.wrap(agent)


_default_agent: Any = None


def run(inp: dict[str, Any]) -> dict[str, Any]:
    """Module-level entry point for `cortexops eval run --agent workflow_agent:run`."""
    global _default_agent
    if _default_agent is None:
        _default_agent = build_agent()
    return _default_agent.invoke(inp)


if __name__ == "__main__":
    print(run({"input": " ".join(sys.argv[1:]) or "Convert 250 USD to EUR."})["output"])
