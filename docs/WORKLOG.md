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