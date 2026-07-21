# Talk With Your Data — Olist Text-to-SQL

Ask questions about the Olist Brazilian e-commerce dataset in plain English. The app
generates SQL, runs it, and explains the result. A local model (Ollama) or a cloud
model (OpenRouter) does the reasoning; a Streamlit chat and an MCP server are the two
frontends; a feedback-learning loop makes it improve over time.

> **Stack:** Streamlit (UI) · LangChain (LLM orchestration) · Ollama / OpenRouter
> (models) · in-memory SQLite (storage) · FastMCP (agent-callable server).

---

## Pipeline

```
User question
     ↓
Feedback memory   → retrieves relevant past good examples (few-shot)
     ↓
LLM               → SQL  |  CLARIFY:  |  IMPOSSIBLE:
     ↓
Safety gate       → read-only, single statement
     ↓
SQLite            → DataFrame   (on error: feed error + real columns back, retry ≤3×)
     ↓
LLM explanation   → plain-English answer
     ↓
Streamlit         → answer + table + chart + 👍/👎
```

---

## Quickstart

### Prerequisites

[Ollama](https://ollama.com) running with a model pulled (default — small and strong at SQL):

```bash
ollama pull qwen2.5-coder:7b
```

### Setup

```bash
./setup.sh                       # creates venv 'eraneos', installs deps
source eraneos/bin/activate
python src/seed_memory.py        # once: seed verified golden examples
```

### Run

```bash
# Streamlit chat UI (recommended) — use `python -m` so the venv interpreter is used
python -m streamlit run src/app.py

# Exploratory data analysis is a page in the app's sidebar (📊 EDA),
# or run it in the terminal:
python src/eda.py

# MCP server
fastmcp run src/mcp_server.py
fastmcp dev inspector src/mcp_server.py      # browser inspector
fastmcp call src/mcp_server.py ask_csv question="which state has most customers"

# Automated eval set
python src/eval.py
```

---

## Project structure

All logic lives in two files (`sql_engine.py` + `memory.py`); everything else is a
thin frontend or script that calls them.

```
Eraneos/
├── readme.MD                      # this file — setup, run, structure, what's implemented
├── learning.md                    # notes: Ollama vs llama.cpp, LangChain, MCP, seeding
├── requirements.txt               # Python deps
├── setup.sh                       # creates venv 'eraneos', installs deps
├── AI_Engineering_Assignment_1.pdf# the original assignment brief
├── docs/
│   └── FINDINGS.md                # data model, join keys, gotchas, break-attempts, eval results
├── data/
│   ├── data_context.MD            # dataset background (Olist, anonymized, GoT-house names)
│   ├── sql_feedback.jsonl         # learned feedback (👍/👎/corrections) — grows at runtime
│   └── Brazilian_ECommerce_Olist/ # the 9 source Olist CSVs:
│       ├── olist_orders_dataset.csv                 # orders (status, timestamps)
│       ├── olist_order_reviews_dataset.csv          # review scores + free-text comments
│       ├── olist_customers_dataset.csv              # customer_id ↔ customer_unique_id, city/state
│       ├── olist_order_items_dataset.csv            # one row per sold unit (price, freight, seller)
│       ├── olist_order_payments_dataset.csv         # payment type, value, installments
│       ├── olist_products_dataset.csv               # product_id → category + dimensions
│       ├── olist_sellers_dataset.csv                # seller_id, city/state
│       ├── product_category_name_translation.csv    # PT → EN category names
│       └── olist_geolocation_dataset.csv            # zip→lat/lng — NOT loaded (see FINDINGS §2)
└── src/
    ├── sql_engine.py              # CORE: load data, build schema, generate/clean SQL,
    │                              #   retry+self-correct loop, safety gate, explain_result
    ├── memory.py                  # feedback store (JSONL) + few-shot retrieval (model-agnostic)
    ├── app.py                     # Streamlit chat UI: NL → SQL → table → chart, live steps, 👍/👎
    ├── eda.py                     # analytics on the dataset (CLI + shared by the EDA page)
    ├── eval.py                    # 6-case eval set asserting expected behaviour per question class
    ├── seed_memory.py             # plants 3 verified "golden" examples into memory (run once)
    ├── mcp_server.py              # MCP server (FastMCP): ask_csv + flag_answer tools
    ├── manual_mcp_server.py       # same server built the hard way (raw MCP SDK) — reference only
    └── pages/                     # Streamlit auto-discovers these as extra sidebar pages
        ├── 1_Feedback_Memory.py   # viewer for everything the flow has learned
        └── 2_EDA.py               # visual EDA tour (charts + insights + suggested questions)
```

**Mental model:** the same engine (`sql_engine.py` + `memory.py`) drives a chat UI
(`app.py`), an agent-callable MCP server (`mcp_server.py`), the eval suite (`eval.py`),
and the EDA page — one brain, many faces.

---

## What's implemented

### Core

- **8 of 9 Olist tables** loaded into in-memory SQLite with correct join keys, and
  data-gotcha hints baked into the prompt (see `docs/FINDINGS.md`).
- **NL → SQL → results → chart** loop, with local Ollama or OpenRouter selectable in the UI.
- **Plain-English explanation** of every result (a second LLM call summarizes the table).
- **Graceful handling of bad questions:** `CLARIFY:` for ambiguous, `IMPOSSIBLE:` for
  unanswerable, plus a self-correcting retry loop that feeds SQL errors back to the model.
  Break-attempts documented in `docs/FINDINGS.md §4`.

### Bonus

- **Streamlit chat frontend** with automatic bar charts and live step-by-step
  visibility (model thinking → SQL tool call → summarizing).
- **EDA page** — a visual tour of the dataset (charts + insights + suggested questions)
  to help ask sharper questions.
- **Feedback-learning memory:** 👍/👎 (+ corrected SQL) is stored and injected as
  few-shot on similar future questions — improves the flow regardless of model.
  Viewable on the "Feedback Memory" page; also exposed via the MCP `flag_answer` tool.
- **MCP server** exposing the same engine as agent-callable tools (`ask_csv`,
  `flag_answer`).
- **Eval set** (`src/eval.py`) asserting expected behaviour per question class.

---

## Dataset

Olist Brazilian E-Commerce — a bol.com-like marketplace. After a customer purchases a
product from the Olist Store, a seller is notified to fulfill the order. Once the
customer receives the product (or the estimated delivery date is due), they get a
satisfaction survey by email where they rate the purchase experience and can leave
comments.

**Attention (data shape):**

1. An order might have multiple items.
2. Each item might be fulfilled by a distinct seller.
3. All text identifying stores and partners was replaced by the names of Game of
   Thrones great houses.

More background: `data/data_context.MD`. Data model, join keys, and the traps that
silently produce wrong answers: `docs/FINDINGS.md`.

---

## Assignment context

Required tables: `orders`, `order_reviews`, `order_customers` (more added as useful).
The app is deliberately tested against four hard question classes — these teach more
than building features:

| Class | Example | Expected behaviour |
|---|---|---|
| **Ambiguous** | *Which customers are best?* | `CLARIFY:` — "best" is undefined |
| **Impossible** | *Which products caused customer churn?* | `IMPOSSIBLE:` — no churn label exists |
| **Misspelled** | *Which stae has most custmers?* | Answers correctly (SP) — LLM robust to typos |
| **Multi-step** | *Which state had highest average review score among customers who ordered more than twice?* | Correct multi-join SQL (needs `customer_unique_id`) |

**Not in scope** (per the brief): deployment, auth, polished UI, exhaustive
documentation. Don't over-engineer.

**Rough time budget:** ~5 min startup · ~10 min data scan.

---

## Docs

- **`docs/FINDINGS.md`** — data model, join keys, data gotchas, break-attempts, eval
  results, environment notes. *Living document.*
- **`learning.md`** — working notes: Ollama vs llama.cpp, the LangChain/Ollama/FastMCP
  roles, why the memory is seeded.
