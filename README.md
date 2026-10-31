# Empório da Música — Customer Service Agent

Python agent that answers customers of a fictional music store, built on the
store's CSV exports and policy manual (`data/raw/`).

## Setup

Requires Python 3.11+.

### With uv (recommended)

`uv.lock` pins every dependency, so installs are reproducible.

```bash
uv sync          # creates .venv with runtime + dev dependencies
uv run pytest
```

### With pip (fallback)

pip does not read `uv.lock`, so versions are resolved from the ranges in
`pyproject.toml` and may differ from the locked ones.

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Copy `.env.example` to `.env` and fill in the LLM settings (used from step 2 on).

## Known limitations

- Brand/description mismatch detection is a heuristic tuned to this catalog: it
  relies on a fixed list of brands and model lines (e.g. Precision → Fender).
  A product from an unlisted brand is not checked.
- Products with `description_reliable=False` should be presented by name and
  specs only; their descriptions also contradict the specs (137: "5 cordas" vs
  4 strings, 142: "88 teclas" vs 61 keys).
- Order totals are compared with current prices because there is no price
  history; mismatches are warnings, not errors.
