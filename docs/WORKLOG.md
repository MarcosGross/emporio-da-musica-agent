# Worklog

Running log of decisions, AI-assisted work and corrections.
Each entry: what I decided / what Claude Code generated / what I corrected.

## 2026-10-31 — Step 0: setup and analysis

**Decided**
- Read the case, the 6 CSVs and the policy manual before writing any code.
- Mapped data quality issues: name/description brand mismatches, active products
  with zero stock, discontinued products with stock, only 4 active promotions,
  order totals that differ from item sums, duplicated customer e-mails,
  inconsistencies in the manual (phone numbers, installment rules).
- Architecture: tool-calling agent; full policy manual in the system prompt
  instead of vector RAG (small document); prices, discounts and installments
  calculated in Python, never by the LLM.
- Order lookup requires order_id + e-mail or phone (LGPD).
- Language: code and docs in English, agent replies in Brazilian Portuguese.

**Claude Code generated**
- Nothing yet.

**Corrected**
- Nothing yet.

## 2026-10-31 — Step 1: data layer and pricing rules

**Decided**
- Installment rules follow manual section 3.1 (min. R$50 up to 3x, R$80 for 4–6x,
  R$100 for 7–12x), not the summary table in section 3.
- Rules apply to new quotes only. Historical orders are shown as recorded, never
  recalculated or "corrected": orders 9, 16 and 18 break the installment minimum
  under both section 3 and 3.1, and orders 3 and 14 contain product 130, which is
  now `coming_soon`. Both are flagged in the data quality report.
- Order totals vs item sums are a warning, not an error: there is no price history,
  so the comparison uses current prices.
- Two active promotions for the same product: the highest discount wins
  (deterministic; does not happen in the current data).
- Products with contradicting brand in the description are kept and flagged
  `description_reliable=False`; the agent shows only name and specs for them,
  which also hides the spec contradictions in 137 (strings) and 142 (keys).
- Switched from requirements.txt to uv + pyproject.toml: lockfile guarantees
  reproducible installs; pip fallback documented in the README.

**Claude Code generated**
- `data.py` (CSV loading, specs parsing, brand mismatch flag, quality report),
  `pricing.py` (final price, PIX, max installments), pytest suite,
  pyproject/uv.lock, README skeleton.

**Corrected**
- Added the checks Claude Code missed: installment rule violations in historical
  orders and orders referencing unreleased products.
- Known limitation recorded: brand detection is a heuristic tuned to this catalog
  (fixed brand and model lists), not a general detector.

## 2026-11-01 — Step 2: agent tools as plain functions

Branch: `feat/agent-tools`.

**Decided**
- Tools are plain Python functions returning JSON-serializable dicts with English
  keys; no LangChain decorators yet. Data is loaded once (cached) so tool
  signatures stay clean for the LLM schema in step 3.
- `get_product` adds a sixth availability value, `ambiguous`, returning the
  candidates instead of picking one (e.g. "Martin D-28" → 93 and 108).
- Unavailable products (out_of_stock, discontinued, coming_soon) are returned
  without prices, so the agent never quotes a price or promotion for something
  that cannot be bought; prices only appear on the alternatives.
- Alternatives: up to 3 sellable products of the same category, closest final
  price first (refined in step 3).
- Price filters and installments use the final price (with promotion); PIX price
  is reported separately.
- Category filter accepts id, exact or partial name, or a close spelling;
  "sopro" matches both wind categories. Unknown category → `unknown_category`
  error listing the valid categories.
- Free-text search initially required every token to match (replaced by
  relevance ranking — see Corrected). The description only counts when
  `description_reliable`.
- Order lookup (LGPD): contact is checked against the order's own customer.
  Missing order, wrong contact, invalid id and empty contact return the exact same
  error. Phone accepted with or without +55, but the area code (DDD) is required.
  The response carries no name, e-mail, phone or customer_id.
- Duplicated e-mail `bruno.martins@jmail.com` opens order 10 (owned by customer
  11, whose e-mail it is) and nothing else; customer 43's phone does not open it.
- Dates are returned as `YYYY-MM-DD` strings as recorded, never compared with today.

**Claude Code generated**
- `tools.py` (list_categories, search_products, get_product, get_order_status)
  and `tests/test_tools.py` (37 tests at first).

**Corrected**
- Free-text search required every word to match: "violão bom para iniciante"
  returned 0 products and "um violão iniciante" returned 1 instead of 3. Found
  by testing realistic customer phrases after the 37 unit tests passed. Fixed by
  removing Portuguese stopwords and ranking by number of matched words; added
  regression tests.
- Ranking introduced a side effect: a ukulele ranked 4th for "violão iniciante"
  because it matched "iniciante". Added `matched_terms` and `full_match_total`
  to the response; the tool docstring (step 3) steers the model to the
  category filter.

## 2026-11-01 — Step 3: conversational agent and CLI

Branch: `feat/react-agent-cli`.

**Decided**
- Policy manual extracted once to `data/processed/policies.md` and reviewed by
  hand; the agent reads the markdown, never the PDF.
- Model: `gpt-5.4-mini-2026-03-17`, pinned to a dated version so behavior and
  evals stay reproducible. Provider and model configurable via `.env`; no
  `temperature` (rejected by GPT-5 models); reasoning effort via
  `LLM_REASONING_EFFORT` (default `low`).
- Conversation history persisted with a SQLite checkpointer, one thread per CLI
  session, resumable with `--thread`. `--debug` prints every tool call, so tool
  usage can be verified instead of assumed.
- Human support channel: WhatsApp (67) 3321-4500 (section 7, which mentions
  human agents) instead of the cover phone (67) 3341-4444; e-mail without the
  accented "ó", which is not a valid address. Kept in one constant.
- Prompt rules take precedence over the manual when they conflict (e.g. the
  installment table in section 3).
- Live test with 5 scenarios: all prices, PIX and installments matched tool
  outputs; no hallucinated numbers.
- Known limitation: 7-string guitars are identified only by name ("7 Cordas");
  `specs.strings` holds the material, not the count. Product 113 (discontinued,
  7-string) gets 6-string nylon alternatives. Not fixed: affects one
  discontinued product and would need a name-based heuristic. A `string_count`
  field in the catalog would solve it properly.

**Claude Code generated**
- `scripts/extract_policies.py` and the first `policies.md`, `llm.py`,
  `prompts.py`, `agent.py`, `cli.py` and `tests/test_agent.py` (offline tests
  with a scripted fake model).

**Corrected**
- Live test failed on the first message: gpt-5.4-mini rejects function tools
  combined with reasoning_effort on /v1/chat/completions (400). The offline
  tests used a fake model and could not catch it. Switched the OpenAI client
  to the Responses API. The error handler kept the CLI alive, as designed.
- Out-of-stock alternatives ignored string type: the steel dreadnought
  Giannini GF-3D got a nylon classical guitar as a "similar" option. The LLM
  only repeated the tool output. Alternatives now prefer the same
  `specs.strings`, then closest price.
- Replaced deprecated `create_react_agent` with `create_agent` instead of
  silencing the deprecation warning.
- Manually fixed policies.md after PDF extraction: title casing and the
  misplaced "24 horas úteis" line in section 7.3.

## 2026-11-02 — Step 4a: guardrails

Branch: `feat/guardrails-evals`.

**Decided**
- Defense in layers: what can be enforced in code stays in code; the prompt
  covers the rest. A prompt alone is not a reliable guardrail.
- Order lookup limited to 3 failures per conversation, enforced in the tool
  wrapper (not the prompt). The counter is rebuilt from the saved history when
  a conversation is resumed, and a lock prevents parallel tool calls from
  bypassing it.
- CLI rejects messages over 1,000 characters without calling the model.
- Prompt rules: no revealing or changing instructions, no off-topic help, no
  unauthorized discounts, no delivery promises beyond the data, no customer
  data, tool output treated as data, not instructions.
- Live test: injection, third-party data, unauthorized discount and off-topic
  requests refused; legitimate suitability question answered from tool data
  (confirmed `get_product` call in a fresh conversation); order lookup blocked
  from the 3rd failure on, with the human support channel. After resuming the
  conversation, the model refused from history without calling the tool, so
  the prompt layer blocked it; the code-level block after restart is covered
  by an offline test that forces the tool call.
- Known limitations: the limit is per conversation, so a new session resets
  it (production would need per-customer or per-IP rate limiting above the
  agent). Within a conversation, the model may reuse tool results already in
  the history instead of calling the tool again; with live stock or prices it
  would need a rule or a TTL to re-query.

**Claude Code generated**
- `OrderLookupLimiter` in `agent.py`, CLI input limit, security rules in
  `prompts.py` and `tests/test_guardrails.py` (20 offline tests).
- Moved the scripted fake model to a shared fixture in `conftest.py` after I
  flagged a test file importing from another.

**Corrected**
- Order lookup limit never triggered in the live test: after 3 failures the
  model stopped calling the tool (it repeated a previous e-mail and answered
  from memory), so the block and the human support referral never reached the
  customer. Offline tests passed because they force the tool call. Fixed by
  returning `attempts_remaining` on every failure and the human support
  channel on the last one, so the referral no longer depends on a 4th call.
- Guardrails made the agent too cautious: for "Is the Yamaha C40 good for
  beginners?" it asked permission instead of calling `get_product`. Found
  only because the live test included a legitimate question next to the
  attacks. Added a rule to call tools proactively and answer suitability
  questions from description and specs.
- CLI exit message suggested `emporio-chat --thread`; fixed to
  `uv run emporio-chat --thread`.