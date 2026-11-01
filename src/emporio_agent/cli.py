"""Terminal chat: `uv run emporio-chat [--thread ID] [--debug]`."""

from __future__ import annotations

import argparse
import sys
import uuid

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from emporio_agent.agent import build_agent, open_checkpointer
from emporio_agent.llm import LLMConfigError

EXIT_WORDS = {"sair"}
DEBUG_RESULT_CHARS = 300


def _text(message: BaseMessage) -> str:
    """Plain text of a message whose content may be a string or a list of blocks."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content
                   if isinstance(block, dict) and block.get("type") == "text")


def _shorten(text: str, limit: int = DEBUG_RESULT_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def _print_debug(message: BaseMessage) -> None:
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            print(f"  [tool] {call['name']}({call['args']})")
    elif isinstance(message, ToolMessage):
        print(f"  [result] {message.name}: {_shorten(_text(message))}")


def chat_turn(agent, config: dict, user_input: str, debug: bool) -> str:
    """Run one user turn and return the agent's final reply."""
    reply = ""
    for update in agent.stream({"messages": [("user", user_input)]}, config, stream_mode="updates"):
        for node_update in update.values():
            for message in (node_update or {}).get("messages", []):
                if debug:
                    _print_debug(message)
                if isinstance(message, AIMessage) and not message.tool_calls:
                    reply = _text(message)
    return reply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emporio-chat", description="Empório da Música customer service chat.")
    parser.add_argument("--thread", help="resume an existing conversation by its thread id")
    parser.add_argument("--debug", action="store_true", help="print tool calls, arguments and results")
    args = parser.parse_args(argv)

    try:
        checkpointer = open_checkpointer()
        agent = build_agent(checkpointer=checkpointer)
    except (LLMConfigError, FileNotFoundError) as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        return 2

    thread_id = args.thread or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    history = agent.get_state(config).values.get("messages", []) if args.thread else []

    print("Empório da Música — assistente virtual. Digite 'sair' para encerrar.")
    if args.thread:
        status = f"{len(history)} mensagens anteriores" if history else "nenhuma mensagem anterior, conversa nova"
        print(f"Retomando conversa {thread_id} ({status}).")
    else:
        print(f"Conversa {thread_id} (retome com --thread {thread_id}).")

    while True:
        try:
            user_input = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            break

        try:
            reply = chat_turn(agent, config, user_input, args.debug)
        except KeyboardInterrupt:
            print("\n(resposta interrompida)")
            continue
        except Exception as exc:  # API/network failures should not kill the session
            print(f"\nErro ao falar com o modelo ({type(exc).__name__}): {exc}", file=sys.stderr)
            continue
        print(f"\nAssistente: {reply}")

    print(f"Até mais! Para retomar: emporio-chat --thread {thread_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
