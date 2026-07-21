# Findings & Design Notes

Living document — everything discovered building this text-to-SQL app on the
Olist dataset. Updated as we go.

---

## 1. Architecture

```
User question
   ↓
Feedback memory  → retrieves relevant past good examples (few-shot)
   ↓
LLM (local Ollama or OpenRouter)  → SQL  |  CLARIFY:  |  IMPOSSIBLE:
   ↓
Safety gate (read-only, single statement)
   ↓
SQLite (in-memory, all CSVs loaded)  → DataFrame
   ↓   (on error: feed error + valid columns back to the LLM, retry up to 3x)
Streamlit chat  → table + auto chart + 👍/👎 feedback
```

| File | Role |
|---|---|
| `src/sql_engine.py` | Shared core: load data, build schema, generate/clean SQL, retry loop, safety |
| `src/memory.py` | Feedback store (JSONL) + few-shot retrieval — model-agnostic learning |
| `src/app.py` | Streamlit chat UI, demo buttons, feedback widgets |
| `src/pages/1_Feedback_Memory.py` | Viewer for all learned feedback |
| `src/mcp_server.py` | MCP server exposing `ask_csv` + `flag_answer` tools |
| `src/eval.py` | Automated eval set (asserts expected behaviour) |
| `src/seed_memory.py` | Seeds verified "golden" examples into memory |

**Storage choice: in-memory SQLite.** ~100k rows/table is tiny; queries run in
<10ms. DuckDB/Postgres would be the move at millions+ rows, but here SQLite is
sufficient and standard-SQL-friendly for the LLM. (DuckDB+parquet noted as the
scale path.)

**LLM access: OpenAI-compatible endpoint for both providers.** One `ChatOpenAI`
drives local Ollama (`http://localhost:11434/v1`) and OpenRouter
(`https://openrouter.ai/api/v1`) — only `base_url` differs.

---

## 2. Data model — tables & join keys

Loaded 8 of the 9 CSVs (geolocation skipped — ~1M rows, messy many-to-many zip
joins, not needed for current questions).

| Table | Key columns |
|---|---|
| orders | order_id, customer_id, order_status, timestamps |
| order_reviews | review_id, order_id, review_score, review_comment_message |
| order_customers | customer_id, customer_unique_id, customer_zip_code_prefix, customer_city/state |
| order_items | order_id, order_item_id, product_id, seller_id, price, freight_value |
| order_payments | order_id, payment_type, payment_value |
| products | product_id, product_category_name |
| product_categories | product_category_name, product_category_name_english |
| sellers | seller_id, seller_zip_code_prefix, seller_city/state |

**Join keys (from the official Olist schema diagram):**
- orders.order_id = order_reviews.order_id
- orders.order_id = order_payments.order_id
- orders.order_id = order_items.order_id
- orders.customer_id = order_customers.customer_id
- order_items.product_id = products.product_id
- order_items.seller_id = sellers.seller_id
- products.product_category_name = product_categories.product_category_name

---

## 3. Data gotchas discovered (the important ones)

These are the traps that silently produce wrong answers. All are now encoded in
the LLM prompt (`JOIN_HINTS`).

1. **`customer_id` is unique PER ORDER, not per person.**
   Each order gets a fresh `customer_id`. The real repeat-customer identity is
   `order_customers.customer_unique_id`. Counting orders per `customer_id` always
   gives 1 → "customers who ordered more than twice" returns **0 rows** if you use
   the wrong column. This broke the multi-step question until fixed.

2. **No product names exist — dataset is anonymized.**
   There is no "Xbox"-style name. Most specific label = `product_category_name`
   (Portuguese) → join `product_categories` for `product_category_name_english`.
   (GoT house names replaced *store/partner* names in review text, not products.)

3. **`order_item_id` is a line position, not a quantity.**
   It's the item's index within an order (1,2,3…). Units sold = `COUNT(*)`, never
   `SUM(order_item_id)`. There is no quantity column; each row = one unit.

4. **Translation CSV has a UTF-8 BOM** on its header, corrupting the first column
   name and breaking the category join. Fixed with `encoding="utf-8-sig"`.

5. **Revenue / money** lives in `order_items.price` (+ `freight_value` shipping)
   and `order_payments.payment_value`.

---

## 4. Break-attempts (required by the brief)

We deliberately tried to break the app with the four question classes from the
brief. Behaviour and *why*:

| Class | Question | Default-model behaviour (before) | Behaviour now | Why |
|---|---|---|---|---|
| **Misspelled** | "Which stae has most custmers?" | ✅ correct (SP) | ✅ correct (SP) | LLMs are robust to typos; the schema anchors intent. |
| **Ambiguous** | "Which customers are best?" | Silently assumed best = most orders, returned IDs with no warning | 🤔 **CLARIFY** — names the ambiguity, states the metric it would assume | Prompt now instructs the model to emit `CLARIFY:` for subjective terms instead of guessing silently. |
| **Impossible** | "Which products caused customer churn?" | Invented churn = `order_status='unavailable'`, 0 rows | Returns **CLARIFY** (reframes churn via recency) | There is no churn label. Model declines a hard definition. Note: it treats churn as *proxy-able* by recency rather than strictly impossible — defensible but not the textbook "impossible". A stronger model or a 👎+note sharpens this. |
| **Multi-step** | "Which state had highest avg review score among customers who ordered more than twice?" | Valid-looking CTE but **0 rows** (used `customer_id`), later a CTE-alias error | ✅ correct first try (AM) | Fixed by the `customer_unique_id` hint + a seeded golden example. Genuinely hard for a 7B; this is the case the feedback loop exists for. |

**General failure mode observed:** small local models (qwen2.5-coder:7b) sometimes
**hallucinate column names** (`category_id`, `product_name`) or reference a CTE not
in the `FROM`. Mitigations, in order of strength:
1. Rich schema + join hints in the prompt.
2. Retry loop that feeds the SQL error + the real column list back to the model.
3. **Feedback memory** — the durable fix: 👎 + corrected SQL (or a seeded golden
   example) makes that class of question work permanently, on any model.

---

## 5. Eval results

`python src/eval.py` — asserts expected *kind* (sql/clarify/impossible) and a
light result check, not exact SQL.

```
[PASS] normal          kind=sql       top=SP
[PASS] misspelled      kind=sql       top=SP
[PASS] top-categories  kind=sql       rows=10
[PASS] multi-step      kind=sql       rows=1
[PASS] ambiguous       kind=clarify
[PASS] impossible      kind=clarify/impossible
6/6 passed
```

(Requires Ollama running + `python src/seed_memory.py` run once for the
multi-step golden example.)

---

## 6. Environment gotchas (for reproducing)

- **FastMCP 3.x** removed bare `fastmcp dev <file>`. Use `fastmcp dev inspector
  src/mcp_server.py`, or `fastmcp run src/mcp_server.py`.
- **stdio MCP server is not a chat box** — typing English into a `fastmcp run`
  terminal raises a JSON-RPC parse error. Use the Inspector UI or `fastmcp call`.
- **`fastmcp call` args are `key=value`**, not `--flags` (`question="..."`, no
  backslashes — those only exist inside setup.sh's echo).
- **Two Streamlit installs on this machine** (venv + global user-site). Always run
  `python -m streamlit run src/app.py` inside the venv so the right interpreter
  (with `langchain_openai`) is used.

---

## 7. Model notes

- `gemma3:1b` — too weak; ignores "SQL only", leaks prose. Fails the safety gate.
- `qwq` / reasoning models — heavy, slow, leak `<think>` blocks (stripped in code).
- **`qwen2.5-coder:7b` — the sweet spot**: small (~4.7GB), fast on M1, built for
  SQL, obeys instructions. Default for both MCP and Streamlit.
- OpenRouter path exists (same code, cloud models) — add key to use.
