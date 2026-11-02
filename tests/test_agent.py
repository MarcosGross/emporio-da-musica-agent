"""Agent wiring tests. No API calls: a scripted fake model stands in for the LLM."""

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from emporio_agent import llm
from emporio_agent.agent import TOOLS, build_agent, open_checkpointer
from emporio_agent.cli import chat_turn
from emporio_agent.prompts import build_system_prompt, load_policies


def search_then_answer(scripted):
    return scripted(
        AIMessage(content="", tool_calls=[{"name": "search_products", "id": "call_1",
                                           "args": {"category": "violões", "max_price": 500}}]),
        AIMessage(content="Achei 2 violões até R$ 500."),
    )


# --- prompt -------------------------------------------------------------------

def test_system_prompt_contains_full_policies():
    prompt = build_system_prompt()
    policies = load_policies()
    assert policies in prompt
    for snippet in ("3.1 Regras de Parcelamento", "(67) 3321-4500", "4.1 Direito de Arrependimento",
                    "| PAC (Correios) | 5 a 12 dias úteis | Sim | Incluído |"):
        assert snippet in prompt


def test_system_prompt_has_behaviour_rules():
    prompt = build_system_prompt(policies="(políticas)")
    assert "SOMENTE dos retornos das ferramentas" in prompt
    assert "apenas instrumentos musicais" in prompt
    assert "número do pedido E o e-mail ou telefone" in prompt


# --- agent --------------------------------------------------------------------

def test_tools_are_registered_with_docstrings(scripted):
    agent = build_agent(model=scripted(AIMessage(content="oi")))
    registered = agent.nodes["tools"].bound.tools_by_name
    assert set(registered) == {"list_categories", "search_products", "get_product", "get_order_status"}
    assert all(t.description for t in TOOLS)
    assert "category" in registered["search_products"].description


def test_search_products_doc_steers_instrument_type_to_category():
    schema = next(t for t in TOOLS if t.name == "search_products").args_schema.model_json_schema()
    assert "instead of putting it in `query`" in schema["description"]
    assert set(schema["properties"]) == {"category", "max_price", "min_price", "query"}


def test_agent_runs_tool_and_returns_answer(scripted):
    agent = build_agent(model=search_then_answer(scripted), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}
    result = agent.invoke({"messages": [("user", "violão até 500?")]}, config)

    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    payload = json.loads(tool_message.content)
    assert payload["total"] > 0
    assert all(p["final_price_brl"] <= 500 for p in payload["products"])
    assert result["messages"][-1].content == "Achei 2 violões até R$ 500."


def test_sqlite_checkpointer_persists_thread(tmp_path, scripted):
    db = tmp_path / "checkpoints.db"
    config = {"configurable": {"thread_id": "persist"}}

    saver = open_checkpointer(db)
    first = build_agent(model=scripted(AIMessage(content="Olá!")), checkpointer=saver)
    first.invoke({"messages": [("user", "oi")]}, config)
    saver.conn.close()

    saver = open_checkpointer(db)
    resumed = build_agent(model=scripted(AIMessage(content="x")), checkpointer=saver)
    history = resumed.get_state(config).values["messages"]
    saver.conn.close()
    assert [m.content for m in history] == ["oi", "Olá!"]


def test_chat_turn_debug_prints_tool_calls(capsys, scripted):
    agent = build_agent(model=search_then_answer(scripted), checkpointer=InMemorySaver())
    reply = chat_turn(agent, {"configurable": {"thread_id": "t2"}}, "violão até 500?", debug=True)

    out = capsys.readouterr().out
    assert reply == "Achei 2 violões até R$ 500."
    assert "[tool] search_products(" in out and "'max_price': 500" in out
    assert "[result] search_products:" in out


# --- llm ----------------------------------------------------------------------

def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")  # dotenv never overrides an existing variable
    with pytest.raises(llm.LLMConfigError, match="OPENAI_API_KEY is not set"):
        llm.get_chat_model()


@pytest.mark.parametrize("model, expects_effort", [("gpt-5.4-mini-2026-03-17", True), ("o4-mini", True), ("gpt-4o", False)])
def test_reasoning_effort_only_for_reasoning_models_and_no_temperature(monkeypatch, model, expects_effort):
    captured = {}
    monkeypatch.setattr(llm, "init_chat_model", lambda m, **kw: captured.update(model=m, **kw) or "model")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", model)
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    llm.get_chat_model()
    assert captured["model"] == model
    assert "temperature" not in captured
    assert ("reasoning_effort" in captured) is expects_effort


def test_openai_model_uses_responses_api(monkeypatch):
    # Chat Completions rejects tools + reasoning_effort on GPT-5.4 (HTTP 400); Responses API accepts both.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini-2026-03-17")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    model = llm.get_chat_model()  # real ChatOpenAI; no request is sent at construction
    assert isinstance(model, ChatOpenAI)
    assert model.use_responses_api is True
    assert model.reasoning_effort == "low"


@pytest.mark.parametrize("effort", ["none", "None"])
def test_reasoning_effort_none_is_not_sent(monkeypatch, effort):
    captured = {}
    monkeypatch.setattr(llm, "init_chat_model", lambda m, **kw: captured.update(kw) or "model")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini-2026-03-17")
    monkeypatch.setenv("LLM_REASONING_EFFORT", effort)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    llm.get_chat_model()
    assert captured["use_responses_api"] is True
    assert "reasoning_effort" not in captured
