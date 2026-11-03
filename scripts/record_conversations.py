"""Record example conversations with the real agent into examples/.

Usage:
    uv run python scripts/record_conversations.py            # all conversations
    uv run python scripts/record_conversations.py --only 04  # re-record one (repeatable)

Each script in scripts/conversations.yaml runs in a new thread. Agent replies
are written exactly as returned (no editing or summarizing), with the tool
calls of each turn in a collapsible block. Also rewrites examples/README.md
(the index). This calls the LLM API.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date
from pathlib import Path

import yaml
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from emporio_agent.agent import build_agent
from emporio_agent.llm import LLMConfigError, load_settings

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_FILE = ROOT / "scripts" / "conversations.yaml"
EXAMPLES_DIR = ROOT / "examples"


def _text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content
                   if isinstance(block, dict) and block.get("type") == "text")


def record(agent, script: dict) -> list[dict]:
    """Run the script's messages in one new thread; one entry per turn."""
    config = {"configurable": {"thread_id": f"example-{script['id']}-{uuid.uuid4().hex[:8]}"}}
    turns, seen = [], 0
    for message in script["messages"]:
        state = agent.invoke({"messages": [("user", message)]}, config)
        new, seen = state["messages"][seen:], len(state["messages"])
        ai = [m for m in new if isinstance(m, AIMessage)]
        turns.append({
            "user": message,
            "tool_calls": [call for m in ai for call in m.tool_calls],
            "reply": next((_text(m) for m in reversed(ai) if not m.tool_calls), ""),
        })
    return turns


def render(script: dict, turns: list[dict], settings: dict) -> str:
    lines = [f"_{script['scenario']}. {' '.join(script['demonstrates'].split())}_", ""]
    for turn in turns:
        lines += [f"**Cliente:** {turn['user']}", ""]
        if turn["tool_calls"]:
            lines += ["<details><summary>Tool calls</summary>", ""]
            lines += [f"- `{c['name']}({json.dumps(c['args'], ensure_ascii=False)})`" for c in turn["tool_calls"]]
            lines += ["", "</details>", ""]
        lines += ["**Assistente:**", "", turn["reply"], "", "---", ""]
    lines.append(f"_Recorded on {date.today().isoformat()} with `{settings['provider']}/{settings['model']}` "
                 f"(reasoning effort: {settings['reasoning_effort']})._")
    return "\n".join(lines) + "\n"


def render_index(scripts: list[dict]) -> str:
    lines = [
        "# Example conversations",
        "",
        "Recorded with the real agent by `scripts/record_conversations.py` from the scripts in",
        "`scripts/conversations.yaml`. Agent replies are unedited.",
        "",
        "| File | Scenario | What it demonstrates |",
        "| --- | --- | --- |",
    ]
    for s in scripts:
        name = f"{s['id']}-{s['slug']}.md"
        lines.append(f"| [{name}]({name}) | {s['scenario']} | {' '.join(s['demonstrates'].split())} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record example conversations with the real agent.")
    parser.add_argument("--only", action="append", help="record only this conversation id (repeatable)")
    args = parser.parse_args(argv)

    scripts = yaml.safe_load(SCRIPTS_FILE.read_text(encoding="utf-8"))
    selected = [s for s in scripts if not args.only or s["id"] in args.only]
    unknown = set(args.only or []) - {s["id"] for s in scripts}
    if unknown:
        print(f"Unknown conversation id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    try:
        agent = build_agent(checkpointer=InMemorySaver())
    except (LLMConfigError, FileNotFoundError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    settings = load_settings()

    EXAMPLES_DIR.mkdir(exist_ok=True)
    for script in selected:
        path = EXAMPLES_DIR / f"{script['id']}-{script['slug']}.md"
        print(f"recording {path.name}...", flush=True)
        path.write_text(render(script, record(agent, script), settings), encoding="utf-8")
    (EXAMPLES_DIR / "README.md").write_text(render_index(scripts), encoding="utf-8")
    print(f"Wrote {len(selected)} conversation(s) and examples/README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
