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
- Architecture: LangGraph ReAct agent with tool calling; full policy manual in the
  system prompt instead of vector RAG (small document); prices, discounts and
  installments calculated in Python, never by the LLM.
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
  `description_reliable=False`; the agent should show only name and specs for them,
  which also hides the spec contradictions in 137 (strings) and 142 (keys).
- Switched from requirements.txt to uv + pyproject.toml: lockfile guarantees reproducible installs; pip fallback documented in the README.

**Claude Code generated**
- `data.py` (CSV loading, specs parsing, brand mismatch flag, quality report),
  `pricing.py` (final price, PIX, max installments), pytest suite, pyproject/uv.lock, README.

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
  price first.
- Price filters and installments use the final price (with promotion); PIX price
  is reported separately.
- Category filter accepts id, exact or partial name, or a close spelling;
  "sopro" matches both wind categories. Unknown category → `unknown_category`
  error listing the valid categories.
- Free-text search requires every token in name, specs or description, and the
  description only counts when `description_reliable`.
- Order lookup (LGPD): contact is checked against the order's own customer.
  Missing order, wrong contact, invalid id and empty contact return the exact same
  error. Phone accepted with or without +55, but the area code (DDD) is required.
  The response carries no name, e-mail, phone or customer_id.
- Duplicated e-mail `bruno.martins@jmail.com` opens order 10 (owned by customer
  11, whose e-mail it is) and nothing else; customer 43's phone does not open it.
- Dates are returned as `YYYY-MM-DD` strings as recorded, never compared with today.

**Claude Code generated**
- `tools.py` (list_categories, search_products, get_product, get_order_status)
  and `tests/test_tools.py` (37 tests; 71 in the suite).

**Corrected**
- Free-text search required every word to match: "violão bom para iniciante"
  returned 0 products and "um violão iniciante" returned 1 instead of 3. Found
  by testing realistic customer phrases after the 37 unit tests passed. Fixed by
  removing Portuguese stopwords and ranking by number of matched words; added
  regression tests.
- Ranking introduced a side effect: a ukulele ranked 4th for "violão iniciante"
  because it matched "iniciante". Added `matched_terms` and `full_match_total`
  to the response; the tool docstring (step 3) will steer the model to the
  category filter.
