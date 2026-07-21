"""
Shared text-to-SQL core used by both the MCP server and the Streamlit app.

Pipeline: natural language question -> LLM -> SQLite SELECT -> DataFrame.
LLMs are reached through an OpenAI-compatible endpoint so the SAME code drives
local models (Ollama) and cloud models (OpenRouter) with only a base_url swap.
"""

import os
import re
import sqlite3

import pandas as pd
import requests
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

import memory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../data/Brazilian_ECommerce_Olist")

# Map friendly SQL table names -> source CSV files. Covers the assignment's
# required trio (orders, order_reviews, order_customers) plus order_items so
# multi-item / multi-seller questions can be answered.
TABLES = {
    "orders": "olist_orders_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "order_customers": "olist_customers_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "products": "olist_products_dataset.csv",
    "product_categories": "product_category_name_translation.csv",
    "sellers": "olist_sellers_dataset.csv",
}

# Join keys taken from the official Olist schema diagram, mapped to the ACTUAL
# column names (which differ from the diagram's shorthand for the zip edges).
JOIN_HINTS = (
    "Join keys:\n"
    "- orders.order_id = order_reviews.order_id\n"
    "- orders.order_id = order_payments.order_id\n"
    "- orders.order_id = order_items.order_id\n"
    "- orders.customer_id = order_customers.customer_id\n"
    "- order_items.product_id = products.product_id\n"
    "- order_items.seller_id = sellers.seller_id\n"
    "- products.product_category_name = product_categories.product_category_name\n"
    "- order_customers.customer_zip_code_prefix and sellers.seller_zip_code_prefix "
    "are geographic zip prefixes (no geolocation table is loaded).\n"
    "IMPORTANT NOTES:\n"
    "- This dataset is anonymized — there is NO product name column. The most "
    "specific product label is products.product_category_name (Portuguese); join "
    "product_categories to get product_category_name_english.\n"
    "- Each row in order_items is ONE sold unit, so units sold = COUNT(*), NOT "
    "SUM(order_item_id) (order_item_id is only the line position within an order). "
    "There is no quantity column.\n"
    "- Revenue = SUM(order_items.price); shipping = order_items.freight_value; "
    "payment amounts are in order_payments.payment_value.\n"
    "- CRITICAL: orders.customer_id is unique PER ORDER, not per person. To count "
    "how many times the SAME real customer ordered, join order_customers and group "
    "by order_customers.customer_unique_id (the real person id)."
)

# OpenAI-compatible endpoints.
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Curated OpenRouter models that are strong at SQL generation.
OPENROUTER_MODELS = [
    "qwen/qwen-2.5-coder-32b-instruct",
    "anthropic/claude-sonnet-4.6",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-chat",
    "google/gemini-flash-1.5",
]

SQL_TEMPLATE = """System: You are an expert data analyst working with a SQLite database.
Schema:
{schema}
{examples}{error_context}
Decide how to respond:
- If a key term is subjective/undefined (e.g. "best", "top", "good") with several
  reasonable metrics, reply with exactly: CLARIFY: <one sentence naming the ambiguity
  and the metric you would assume>.
- If it needs data not in the schema (e.g. churn, profit, returns, ratings text),
  reply with exactly: IMPOSSIBLE: <one sentence on what is missing>.
- Otherwise write ONE valid SQLite query (SELECT or WITH ... SELECT).

SQL rules (when writing SQL):
- Output ONLY the SQL. No markdown, no backticks, no explanation, no <think> blocks.
- Read-only. Never INSERT/UPDATE/DELETE/DROP.
- Only reference columns that exist in the schema above; alias tables correctly.

User question: {question}
Answer:"""


def load_database():
    """Load every CSV into its own in-memory SQLite table.

    Returns (connection, schema_string).
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    schema_blocks = []
    for table_name, csv_file in TABLES.items():
        # utf-8-sig strips the BOM that prefixes the translation file's header.
        df = pd.read_csv(os.path.join(DATA_DIR, csv_file), encoding="utf-8-sig")
        df.to_sql(table_name, conn, index=False, if_exists="replace")
        cols = [f"{row[1]} ({row[2]})" for row in conn.execute(f"PRAGMA table_info({table_name});")]
        schema_blocks.append(f"Table {table_name}: " + ", ".join(cols))
    return conn, "\n".join(schema_blocks) + "\n" + JOIN_HINTS


def list_ollama_models():
    """Return locally pulled Ollama model ids, or [] if Ollama is unreachable."""
    try:
        data = requests.get(f"{OLLAMA_BASE_URL}/models", timeout=3).json()
        return sorted(m["id"] for m in data.get("data", []))
    except Exception:
        return []


def make_llm(provider, model, api_key=None, temperature=0.0):
    """Build a LangChain chat model for 'ollama' or 'openrouter'."""
    if provider == "openrouter":
        return ChatOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key or "MISSING_KEY",
            model=model,
            temperature=temperature,
        )
    # Local Ollama via its OpenAI-compatible API. api_key is ignored but required.
    return ChatOpenAI(
        base_url=OLLAMA_BASE_URL,
        api_key="ollama",
        model=model,
        temperature=temperature,
    )


_SQL_START = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)


def _strip_noise(raw):
    """Remove reasoning blocks and markdown fences, keep everything else."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    return raw.replace("```sql", "").replace("```", "").strip()


def clean_sql(raw):
    """Strip noise and isolate the SQL statement."""
    raw = _strip_noise(raw)
    match = _SQL_START.search(raw)
    if match:
        raw = raw[match.start():]
    return raw.strip().rstrip(";").strip()


def raw_generate(llm, schema, question, examples="", error_context=""):
    """Ask the LLM and return its cleaned raw answer (may be SQL, CLARIFY:, or IMPOSSIBLE:)."""
    chain = PromptTemplate.from_template(SQL_TEMPLATE) | llm | StrOutputParser()
    return _strip_noise(
        chain.invoke(
            {
                "schema": schema,
                "question": question,
                "examples": examples,
                "error_context": error_context,
            }
        )
    )


def generate_sql(llm, schema, question, examples="", error_context=""):
    """Backwards-compatible: return only the cleaned SQL statement."""
    return clean_sql(raw_generate(llm, schema, question, examples, error_context))


EXPLAIN_TEMPLATE = """You are a data analyst. Answer the user's question in ONE or TWO
plain-English sentences using ONLY the query result below. State the actual numbers.
No SQL, no markdown, no preamble.

Question: {question}
Query result (up to 10 rows): {rows}
Answer:"""


def explain_result(llm, question, df, max_rows=10):
    """Second LLM call: turn the result DataFrame into a plain-English answer.

    This closes the assignment's 'generate SQL AND explain the result' loop.
    Best-effort: on any failure returns "" so the table is still shown.
    """
    if df is None or df.empty:
        return ""
    try:
        rows = df.head(max_rows).to_dict("records")
        chain = PromptTemplate.from_template(EXPLAIN_TEMPLATE) | llm | StrOutputParser()
        return _strip_noise(chain.invoke({"question": question, "rows": rows}))
    except Exception:
        return ""


def is_safe(sql):
    """Allow only single read-only statements."""
    stripped = sql.strip().upper()
    if not stripped.startswith(("SELECT", "WITH")):
        return False
    # Reject stacked statements (crude injection guard).
    if ";" in sql.strip().rstrip(";"):
        return False
    return True


def run_sql(conn, sql):
    """Execute SQL and return a DataFrame."""
    cursor = conn.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


_MISSING_COL = re.compile(r"no such column:\s*([\w.]+)", re.IGNORECASE)


def _column_help(conn, error_text):
    """When SQLite reports a missing column, list the columns that DO exist so
    the model can self-correct instead of re-inventing the same bad name."""
    if "no such column" not in error_text.lower():
        return ""
    all_cols = []
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table});")]
        all_cols.append(f"{table}({', '.join(cols)})")
    return "Do NOT invent column names. Valid columns are:\n" + "\n".join(all_cols) + "\n"


def run_with_retry(llm, conn, schema, question, max_retries=3, row_cap=1000, on_step=None):
    """Generate + execute SQL with self-correction and feedback few-shot.

    Injects relevant learned examples, then on any failure feeds the broken SQL
    and its error back to the LLM to try again (up to max_retries).

    on_step(event, detail): optional callback fired at each stage so a UI can
    show the model's work live. Events: 'recall', 'think', 'intent', 'safety',
    'run', 'retry', 'done'.

    Returns a dict: {sql, df, attempts, error, examples_used}.
    """
    step = on_step or (lambda *a, **k: None)

    examples = memory.good_examples(question)
    examples_block = memory.format_examples(examples)
    step("recall", f"{len(examples)} learned example(s) retrieved")

    def result(**kw):
        base = {"kind": "sql", "sql": None, "df": None, "attempts": 0,
                "error": None, "message": None, "examples_used": len(examples)}
        base.update(kw)
        return base

    error_context = ""
    last_sql = None
    for attempt in range(max_retries + 1):
        step("think", f"Generating SQL (attempt {attempt + 1})")
        raw = raw_generate(llm, schema, question, examples_block, error_context)

        # Non-SQL intents: the model recognized ambiguity or impossibility.
        head = raw.strip()
        if head.upper().startswith("CLARIFY:"):
            step("intent", "Model asked to CLARIFY (ambiguous question)")
            return result(kind="clarify", attempts=attempt + 1, message=head[len("CLARIFY:"):].strip())
        if head.upper().startswith("IMPOSSIBLE:"):
            step("intent", "Model declined: IMPOSSIBLE (not in the data)")
            return result(kind="impossible", attempts=attempt + 1, message=head[len("IMPOSSIBLE:"):].strip())

        sql = clean_sql(raw)
        last_sql = sql

        if not is_safe(sql):
            step("safety", "Rejected unsafe/non-SELECT output — asking again")
            error_context = (
                f"Your previous answer was rejected (only single read-only "
                f"SELECT/WITH queries are allowed):\n{sql}\nReturn a valid SELECT.\n"
            )
            continue

        step("run", sql)
        try:
            df = run_sql(conn, sql)
            if row_cap and len(df) > row_cap:
                df = df.head(row_cap)
            step("done", f"{len(df)} row(s) in {attempt + 1} attempt(s)")
            return result(kind="sql", sql=sql, df=df, attempts=attempt + 1)
        except Exception as e:
            step("retry", f"SQL failed: {str(e).splitlines()[0]} — feeding error back")
            error_context = (
                f"Your previous SQL failed.\nSQL: {sql}\nError: {e}\n"
                f"{_column_help(conn, str(e))}"
                f"Fix the query using only columns that exist in the schema.\n"
            )

    return result(kind="error", sql=last_sql, attempts=max_retries + 1, error=error_context.strip())
