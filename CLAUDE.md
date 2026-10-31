# Empório da Música — Customer Service Agent

## Context
Technical case for Artefact (AI Engineer). Python agent that answers customers
of a fictional music store. Raw data in data/raw/ (CSVs + policy manual PDF).

## Architecture decisions (owner: Marcos)
- Agent: LangGraph ReAct agent with tool calling; SQLite checkpointer for chat history.
- LLM: provider-agnostic via langchain `init_chat_model`; LLM_PROVIDER/LLM_MODEL in .env. Default OpenAI.
- Policies: full manual text goes in the system prompt (~3k tokens). No vector RAG — document is small; retrieval would only add failure modes.
- Structured data: deterministic Python tools over pandas. The LLM never calculates prices, discounts or installments.
- Interface: CLI first.

## Business rules
- Sellable product = status "active" AND stock_quantity > 0.
- Only promotions with is_active == 1. Always show original price + discount %.
- PIX 5% discount does NOT stack with promotions.
- Order status requires order_id + matching customer email or phone (LGPD).
- Store sells instruments only — no accessories (strings, cables, picks, pedals, amps, cases).

## Conventions
- Code, identifiers, commits and README in English. Agent replies in Brazilian Portuguese.
- Conventional commits (feat/fix/docs/chore/test). Never commit .env.
- Do not commit on my behalf — stop after each step and summarize changes.