"""ReAct agent wiring (langchain create_agent): tools, system prompt and SQLite checkpointer."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from langchain.agents import create_agent
from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph

from emporio_agent import tools as store_tools
from emporio_agent.llm import get_chat_model
from emporio_agent.prompts import HUMAN_SUPPORT, build_system_prompt

CHECKPOINT_DB = Path(__file__).resolve().parents[2] / "data" / "checkpoints.db"

MAX_ORDER_LOOKUP_FAILURES = 3

TOO_MANY_ATTEMPTS = {
    "found": False,
    "error": "too_many_attempts",
    "message": "Too many failed order lookups in this conversation. Order data was not queried.",
    "human_support": HUMAN_SUPPORT,
}


def _json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)


@tool(parse_docstring=True)
def list_categories() -> str:
    """List every product category with how many products are available to buy in each.

    Use it when the customer asks what the store sells or which kinds of instruments
    exist. A category with 0 sellable products has nothing to offer right now.
    """
    return _json(store_tools.list_categories())


@tool(parse_docstring=True)
def search_products(category: str | None = None, max_price: float | None = None,
                    min_price: float | None = None, query: str | None = None) -> str:
    """Search products that are available to buy, with prices already calculated.

    If the customer names a type of instrument (violão, guitarra, baixo, ukulele,
    bateria, teclado...), pass it in `category` instead of putting it in `query`;
    use `query` only for other words (brand, model, feature, level such as
    "iniciante"). Results are ranked by matched query terms, then by final price,
    and capped at 10: `total` counts all matches and `full_match_total` those
    matching every query term. Each item carries original price, active promotion
    percent, final price, PIX price, max interest-free installments and installment
    value: quote these numbers as given, never recompute them.

    Args:
        category: Category name or id, e.g. "violões", "guitarras", "ukuleles".
        max_price: Maximum final price in BRL.
        min_price: Minimum final price in BRL.
        query: Free-text keywords other than the instrument type.
    """
    return _json(store_tools.search_products(category=category, max_price=max_price,
                                             min_price=min_price, query=query))


@tool(parse_docstring=True)
def get_product(name_or_id: str) -> str:
    """Look up one product by id or (approximate) name and check its availability.

    Always use it before confirming that a specific product is available.
    `availability` is one of: available (with full prices), out_of_stock,
    discontinued, coming_soon (each with up to 3 sellable alternatives from the same
    category, closest in price), ambiguous (several candidates: ask the customer
    which one) or not_found.

    Args:
        name_or_id: Product id (e.g. "95") or name as the customer wrote it.
    """
    return _json(store_tools.get_product(name_or_id))


class OrderLookupLimiter:
    """Counts failed order lookups per conversation (thread_id) and blocks after a limit.

    Successes do not reset the count. A thread seen for the first time in this
    process starts from the failures already in its checkpointed history, so
    restarting the CLI with --thread does not reset the limit. The lock keeps
    parallel tool calls from slipping past the limit.
    """

    def __init__(self, max_failures: int = MAX_ORDER_LOOKUP_FAILURES):
        self.max_failures = max_failures
        self._failures: dict[str, int] = {}
        self._lock = threading.Lock()

    def lookup(self, thread_id: str, history: list[BaseMessage], order_id: str, contact: str) -> dict:
        with self._lock:
            if thread_id not in self._failures:
                self._failures[thread_id] = _failed_lookups_in(history)
            if self._failures[thread_id] >= self.max_failures:
                return dict(TOO_MANY_ATTEMPTS)
            result = store_tools.get_order_status(order_id, contact)
            if not result["found"]:
                self._failures[thread_id] += 1
                remaining = self.max_failures - self._failures[thread_id]
                result["attempts_remaining"] = remaining
                if remaining == 0:
                    # The model may stop calling the tool before seeing too_many_attempts,
                    # so the last allowed failure already carries the human channel.
                    result["human_support"] = HUMAN_SUPPORT
            return result

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


def _failed_lookups_in(history: list[BaseMessage]) -> int:
    failed = 0
    for message in history:
        if isinstance(message, ToolMessage) and message.name == "get_order_status":
            try:
                failed += json.loads(message.content).get("error") == store_tools.ORDER_NOT_FOUND["error"]
            except (TypeError, ValueError):
                continue
    return failed


ORDER_LOOKUPS = OrderLookupLimiter()


@tool(parse_docstring=True)
def get_order_status(order_id: str, contact: str, runtime: ToolRuntime) -> str:
    """Get the status of an order. Requires the order number AND the customer's contact.

    Only call it when the customer has given both; otherwise ask for what is
    missing. If `found` is false, the order id and contact do not match: say the
    order could not be located with those details, without guessing which is wrong.
    Failures include `attempts_remaining`. If it is 0, or `error` is
    "too_many_attempts", do not call this tool again in this conversation and do
    not ask for new details: point the customer to the human support channel in
    `human_support`.

    Args:
        order_id: Order number given by the customer.
        contact: E-mail or phone number registered on the order.
    """
    thread_id = str((runtime.config.get("configurable") or {}).get("thread_id", "default"))
    history = runtime.state.get("messages", []) if runtime.state else []
    return _json(ORDER_LOOKUPS.lookup(thread_id, history, order_id, contact))


TOOLS = [list_categories, search_products, get_product, get_order_status]


def open_checkpointer(path: Path = CHECKPOINT_DB) -> SqliteSaver:
    """SQLite checkpointer kept open for the whole chat session."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def build_agent(model: BaseChatModel | None = None,
                checkpointer: BaseCheckpointSaver | None = None,
                system_prompt: str | None = None) -> CompiledStateGraph:
    return create_agent(
        model=model or get_chat_model(),
        tools=TOOLS,
        system_prompt=system_prompt or build_system_prompt(),
        checkpointer=checkpointer,
    )
