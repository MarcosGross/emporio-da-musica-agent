"""Run the agent eval cases against the real model.

Usage:
    uv run python -m evals.run              # all cases
    uv run python -m evals.run --case ID    # one case (repeat --case for several)
    uv run python -m evals.run --repeat 3   # every case 3 times, to expose unstable ones

Each run of a case uses a new thread. The report goes to the terminal and to
evals/results/<date>-<model>.md. This calls the LLM API (and costs money),
so it is deliberately not part of the pytest suite.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx
import openai
import yaml
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from emporio_agent.agent import build_agent
from emporio_agent.llm import LLMConfigError, load_settings

# USD per 1M tokens, used for the cost estimate only. Update PRICES_SOURCE when
# you change them; the report quotes both.
PRICES_PER_MILLION = {
    "gpt-5.4-mini-2026-03-17": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
}
PRICES_SOURCE = ("set by hand in evals/run.py from the assistant's own estimate; "
                 "NOT checked against the OpenAI pricing page")

# API connection problems and timeouts are infrastructure, not agent behaviour: the run is
# retried from scratch, and if it still fails it is reported as ERROR, apart from FAIL.
INFRA_ERRORS = (openai.APIConnectionError, httpx.TransportError, TimeoutError)  # APITimeoutError included
INFRA_RETRIES = 2

EVALS_DIR = Path(__file__).resolve().parent
CASES_FILE = EVALS_DIR / "cases.yaml"
RESULTS_DIR = EVALS_DIR / "results"

NUMBER = re.compile(r"\d[\d.,]*\d|\d")


# --- matching helpers -----------------------------------------------------------

def normalize(text: object) -> str:
    """Lowercase, strip accents and collapse whitespace."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def parse_number(token: str) -> float | None:
    """'5.519,08' / '5519,08' / '5519.08' / '1.000' -> float."""
    token = token.strip(".,")
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    elif "." in token and len(token.rsplit(".", 1)[1]) == 3:
        token = token.replace(".", "")  # thousands separator
    try:
        return float(token)
    except ValueError:
        return None


def numbers_in(text: str) -> set[float]:
    return {n for n in (parse_number(t) for t in NUMBER.findall(text)) if n is not None}


def appears(item: object, answer: str) -> bool:
    if isinstance(item, list):
        return any(appears(i, answer) for i in item)
    if isinstance(item, dict) and "regex" in item:
        return re.search(item["regex"], normalize(answer)) is not None
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        return any(abs(n - float(item)) < 0.005 for n in numbers_in(answer))
    return normalize(item) in normalize(answer)


def arg_matches(expected: object, actual: object) -> bool:
    if isinstance(expected, dict) and "regex" in expected:
        return actual is not None and re.search(expected["regex"], normalize(actual)) is not None
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return abs(float(actual) - float(expected)) < 0.005
        except (TypeError, ValueError):
            return False
    return normalize(expected) == normalize(actual)


def label(item: object) -> str:
    if isinstance(item, list):
        return " | ".join(map(label, item))
    if isinstance(item, dict) and "regex" in item:
        return f"/{item['regex']}/"
    return str(item)


# --- running a case -------------------------------------------------------------

@dataclass
class ToolCall:
    name: str
    args: dict
    result: dict | None = None


@dataclass
class CaseResult:
    case: dict
    answers: list[str] = field(default_factory=list)  # final reply of each turn
    tool_calls: list[ToolCall] = field(default_factory=list)
    checks: list[tuple[str, bool]] = field(default_factory=list)
    latency_s: float = 0.0
    tokens: dict = field(default_factory=lambda: {"input": 0, "cached_input": 0, "output": 0})
    error: str | None = None
    infra_error: bool = False  # error is an API connection/timeout problem, not the agent
    attempts: int = 1

    @property
    def status(self) -> str:
        if self.infra_error:
            return "ERROR"
        return "PASS" if self.passed else "FAIL"

    @property
    def answer(self) -> str:
        """Final reply of the last turn."""
        return self.answers[-1] if self.answers else ""

    @property
    def passed(self) -> bool:
        return self.error is None and all(ok for _, ok in self.checks)


def is_infra_error(exc: BaseException) -> bool:
    return isinstance(exc, INFRA_ERRORS)


def run_case(agent, case: dict) -> CaseResult:
    """One run of a case; infrastructure errors are retried in a fresh thread."""
    for attempt in range(1, INFRA_RETRIES + 2):
        result = _run_once(agent, case)
        result.attempts = attempt
        if not result.infra_error:
            break
    return result


def _run_once(agent, case: dict) -> CaseResult:
    result = CaseResult(case=case)
    config = {"configurable": {"thread_id": f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"}}
    seen = 0
    start = time.perf_counter()
    try:
        for message in case["messages"]:
            state = agent.invoke({"messages": [("user", message)]}, config)
            new = state["messages"][seen:]
            seen = len(state["messages"])
            _collect(result, new)
    except Exception as exc:  # one failing case must not stop the run
        result.error = f"{type(exc).__name__}: {exc}"
        result.infra_error = is_infra_error(exc)
    result.latency_s = time.perf_counter() - start
    if result.error is None:
        result.checks = evaluate(case, result)
    return result


def _collect(result: CaseResult, messages: list) -> None:
    """Record one turn: tool calls/results, token usage and the turn's final reply."""
    by_id: dict[str, ToolCall] = {}
    reply = ""
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                tool_call = ToolCall(call["name"], call["args"])
                by_id[call["id"]] = tool_call
                result.tool_calls.append(tool_call)
            usage = message.usage_metadata or {}
            cached = (usage.get("input_token_details") or {}).get("cache_read", 0) or 0
            result.tokens["input"] += (usage.get("input_tokens", 0) or 0) - cached
            result.tokens["cached_input"] += cached
            result.tokens["output"] += usage.get("output_tokens", 0) or 0
            if not message.tool_calls:
                reply = message.text if isinstance(message.text, str) else message.text()
        elif isinstance(message, ToolMessage) and message.tool_call_id in by_id:
            try:
                by_id[message.tool_call_id].result = json.loads(message.content)
            except (TypeError, ValueError):
                by_id[message.tool_call_id].result = None
    result.answers.append(reply)


def evaluate(case: dict, result: CaseResult) -> list[tuple[str, bool]]:
    checks = []
    calls = result.tool_calls

    for spec in case.get("tools_called", []):
        if isinstance(spec, str):
            spec = {"name": spec}
        if "any_of" in spec:
            ok = any(c.name in spec["any_of"] for c in calls)
            checks.append((f"called any of {spec['any_of']}", ok))
            continue
        args = spec.get("args", {})
        ok = any(c.name == spec["name"] and all(arg_matches(v, c.args.get(k)) for k, v in args.items())
                 for c in calls)
        checks.append((f"called {spec['name']}" + (f" with {args}" if args else ""), ok))

    for name in case.get("tools_not_called", []):
        checks.append((f"did not call {name}", all(c.name != name for c in calls)))

    for spec in case.get("tool_results", []):
        ok = any(c.name == spec["tool"] and c.result and c.result.get(spec["field"]) == spec["equals"]
                 for c in calls)
        checks.append((f"{spec['tool']}.{spec['field']} == {spec['equals']}", ok))

    checks += text_checks(case, result.answer)

    for spec in case.get("turn_checks", []):
        turn = spec["turn"]
        answer = result.answers[turn - 1] if turn <= len(result.answers) else ""
        checks += text_checks(spec, answer, prefix=f"turn {turn} ")

    return checks


def text_checks(spec: dict, answer: str, prefix: str = "") -> list[tuple[str, bool]]:
    checks = [(f"{prefix}contains {label(item)}", appears(item, answer)) for item in spec.get("must_contain", [])]
    for item in spec.get("must_not_contain", []):
        for single in item if isinstance(item, list) else [item]:
            checks.append((f"{prefix}does not contain {single}", not appears(single, answer)))
    return checks


# --- reporting ------------------------------------------------------------------

def estimate_cost(tokens: dict, model: str) -> float | None:
    prices = PRICES_PER_MILLION.get(model)
    if prices is None:
        return None
    return sum(tokens[kind] * prices[kind] for kind in ("input", "cached_input", "output")) / 1_000_000


def total_tokens(tokens: dict) -> int:
    return tokens["input"] + tokens["cached_input"] + tokens["output"]


@dataclass
class CaseSummary:
    """All runs of one case."""

    case: dict
    runs: list[CaseResult]

    @property
    def agent_runs(self) -> list[CaseResult]:
        """Runs that reached a verdict on the agent (infrastructure errors excluded)."""
        return [r for r in self.runs if not r.infra_error]

    @property
    def errors(self) -> int:
        return len(self.runs) - len(self.agent_runs)

    @property
    def passes(self) -> int:
        return sum(r.passed for r in self.agent_runs)

    @property
    def status(self) -> str:
        if not self.agent_runs:
            return "ERROR"
        if self.passes == len(self.agent_runs):
            return "PASS"
        return "FAIL" if self.passes == 0 else "UNSTABLE"

    @property
    def score(self) -> str:
        """e.g. "4/4 (+1 error)": passes over agent runs, errors shown apart."""
        return f"{self.passes}/{len(self.agent_runs)}" + (f" (+{self.errors} error)" if self.errors else "")

    @property
    def avg_latency_s(self) -> float:
        runs = self.agent_runs or self.runs
        return sum(r.latency_s for r in runs) / len(runs)

    @property
    def avg_tokens(self) -> float:
        return sum(total_tokens(r.tokens) for r in self.runs) / len(self.runs)

    def failed_checks(self) -> list[str]:
        """Each failing check (or error) with how many runs it failed in."""
        counts: dict[str, int] = {}
        for run in self.agent_runs:
            failures = [run.error] if run.error else [name for name, ok in run.checks if not ok]
            for name in failures:
                counts[name] = counts.get(name, 0) + 1
        return [f"{name} ({n}/{len(self.agent_runs)})" for name, n in counts.items()]


def print_table(summaries: list[CaseSummary]) -> None:
    width = max(len(s.case["id"]) for s in summaries)
    print(f"\n{'case'.ljust(width)}  passes  errors  status    latency  tokens")
    for s in summaries:
        print(f"{s.case['id'].ljust(width)}  {s.passes:>2}/{len(s.agent_runs):<3}  {s.errors:>6}  {s.status:<8}  "
              f"{s.avg_latency_s:6.1f}s  {s.avg_tokens:>6.0f}")


def overall(summaries: list[CaseSummary], model: str) -> dict:
    runs = [r for s in summaries for r in s.runs]
    agent_runs = [r for s in summaries for r in s.agent_runs]
    checks = [ok for r in agent_runs for _, ok in r.checks]
    tokens = {k: sum(r.tokens[k] for r in runs) for k in ("input", "cached_input", "output")}  # all attempts cost
    return {
        "stable_cases": sum(s.status == "PASS" for s in summaries),
        "unstable_cases": sum(s.status == "UNSTABLE" for s in summaries),
        "failed_cases": sum(s.status == "FAIL" for s in summaries),
        "error_cases": sum(s.status == "ERROR" for s in summaries),
        "cases": len(summaries),
        "runs_passed": sum(r.passed for r in agent_runs),
        "agent_runs": len(agent_runs),
        "runs": len(runs),
        "errors": len(runs) - len(agent_runs),
        "retried_runs": sum(r.attempts > 1 for r in runs),
        "checks_passed": sum(checks),
        "checks": len(checks),
        "avg_latency_s": sum(r.latency_s for r in agent_runs or runs) / len(agent_runs or runs),
        "tokens": tokens,
        "cost_usd": estimate_cost(tokens, model),
    }


def _run_details(title: str, run: CaseResult) -> list[str]:
    lines = [f"#### {title}", ""]
    if run.tool_calls:
        lines += [f"- tool `{c.name}({json.dumps(c.args, ensure_ascii=False)})`" for c in run.tool_calls]
    else:
        lines.append("- tools: none")
    lines += [f"- {'✅' if ok else '❌'} {name}" for name, ok in run.checks]
    if run.error:
        kind = "infrastructure error (not counted as agent failure)" if run.infra_error else "error"
        lines.append(f"- ❌ {kind}: {run.error}")
    if run.attempts > 1:
        lines.append(f"- attempts: {run.attempts} (retried after API connection errors)")
    for turn, answer in enumerate(run.answers or [""], start=1):
        title = "**Resposta final:**" if len(run.answers) <= 1 else f"**Resposta (turno {turn}):**"
        lines += ["", title, "", *[f"> {line}" for line in (answer or "(vazia)").splitlines()]]
    lines.append("")
    return lines


def render_markdown(summaries: list[CaseSummary], settings: dict, stats: dict, repeat: int) -> str:
    t = stats["tokens"]
    prices = PRICES_PER_MILLION.get(settings["model"])
    if stats["cost_usd"] is None:
        cost_lines = [f"- No price configured for `{settings['model']}` in `PRICES_PER_MILLION`."]
    else:
        cost_lines = [
            f"- **Estimated** cost of this run ({stats['runs']} case runs): US$ {stats['cost_usd']:.4f}",
            f"- Prices used (USD per 1M tokens): input {prices['input']}, cached input "
            f"{prices['cached_input']}, output {prices['output']}",
            f"- Source of the prices: {PRICES_SOURCE}.",
            "- Reasoning tokens are counted inside output tokens, as reported by the provider.",
        ]

    lines = [
        f"# Eval report — {date.today().isoformat()}",
        "",
        f"- Model: `{settings['provider']}/{settings['model']}` (reasoning effort: {settings['reasoning_effort']})",
        f"- Runs per case: {repeat}",
        f"- Cases passing every run: **{stats['stable_cases']}/{stats['cases']}** — "
        f"unstable: {stats['unstable_cases']}, failing every run: {stats['failed_cases']}"
        + (f", only errors: {stats['error_cases']}" if stats["error_cases"] else ""),
        f"- Runs passed: {stats['runs_passed']}/{stats['agent_runs']} "
        f"({stats['runs_passed'] / max(stats['agent_runs'], 1):.0%}), excluding infrastructure errors",
        f"- Infrastructure errors (ERROR): {stats['errors']} of {stats['runs']} runs — API connection or "
        f"timeout still failing after {INFRA_RETRIES} retries; not counted as agent failures. "
        f"Runs retried at least once: {stats['retried_runs']}",
        f"- Checks passed: {stats['checks_passed']}/{stats['checks']} "
        f"({stats['checks_passed'] / max(stats['checks'], 1):.0%})",
        f"- Average latency per case run: {stats['avg_latency_s']:.1f}s",
        f"- Tokens: {t['input']} input + {t['cached_input']} cached input + {t['output']} output",
        "",
        "## Cost (estimate)",
        "",
        *cost_lines,
        "",
        "## Results",
        "",
        "| Case | Passes | Errors | Status | Avg latency | Avg tokens | Failed checks (runs) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in summaries:
        status = s.status if s.status == "PASS" else f"**{s.status}**"
        failed = "; ".join(s.failed_checks()) or "—"
        lines.append(f"| {s.case['id']} | {s.passes}/{len(s.agent_runs)} | {s.errors} | {status} | "
                     f"{s.avg_latency_s:.1f}s | {s.avg_tokens:.0f} | {failed.replace('|', '/')} |")

    lines += ["", "## Details", ""]
    for s in summaries:
        lines += [f"### {s.case['id']} — {s.status} ({s.score})", "",
                  f"_{s.case.get('description', '')}_", ""]
        lines += [f"> **Cliente:** {m}" for m in s.case["messages"]]
        lines.append("")
        failing = [(i, r) for i, r in enumerate(s.runs, start=1) if not r.passed]
        if failing:  # every failing or errored run, so instability can be diagnosed
            for i, run in failing:
                lines += _run_details(f"Run {i} — {run.status}", run)
        else:
            lines += _run_details("Run 1 — PASS", s.runs[0])
    return "\n".join(lines)


def report_path(model: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{date.today().isoformat()}-{re.sub(r'[^A-Za-z0-9._-]+', '_', model)}"
    path, n = RESULTS_DIR / f"{base}.md", 2
    while path.exists():  # keep earlier runs from the same day
        path, n = RESULTS_DIR / f"{base}-{n}.md", n + 1
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run", description="Run agent evals against the real model.")
    parser.add_argument("--case", action="append", help="run only this case id (repeatable)")
    parser.add_argument("--repeat", type=int, default=1, help="runs per case (default 1)")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    if args.case:
        unknown = set(args.case) - {c["id"] for c in cases}
        if unknown:
            print(f"Unknown case id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        cases = [c for c in cases if c["id"] in args.case]

    try:
        agent = build_agent(checkpointer=InMemorySaver())
    except (LLMConfigError, FileNotFoundError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    settings = load_settings()

    summaries = []
    for case in cases:
        runs = []
        for i in range(1, args.repeat + 1):
            print(f"running {case['id']} ({i}/{args.repeat})...", flush=True)
            runs.append(run_case(agent, case))
        summaries.append(CaseSummary(case, runs))

    stats = overall(summaries, settings["model"])
    print_table(summaries)
    path = report_path(settings["model"])
    path.write_text(render_markdown(summaries, settings, stats, args.repeat), encoding="utf-8")
    cost = "n/a" if stats["cost_usd"] is None else f"US$ {stats['cost_usd']:.4f} (estimate)"
    print(f"\n{stats['stable_cases']}/{stats['cases']} cases passed every run "
          f"({stats['unstable_cases']} unstable, {stats['failed_cases']} failing), "
          f"{stats['runs_passed']}/{stats['agent_runs']} runs passed, {stats['errors']} infrastructure "
          f"error(s) (not agent failures), avg latency {stats['avg_latency_s']:.1f}s, cost {cost}")
    print(f"Report: {path.relative_to(EVALS_DIR.parent)}")
    return 0 if stats["stable_cases"] == stats["cases"] else 1


if __name__ == "__main__":
    sys.exit(main())
