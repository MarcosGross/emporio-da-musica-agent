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