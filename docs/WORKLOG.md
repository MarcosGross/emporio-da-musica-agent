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
