import warnings
warnings.filterwarnings("ignore")  # keep pandas warnings out of the MCP stdio stream

import os
import sys

from fastmcp import FastMCP

# Make sql_engine importable regardless of the launch directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sql_engine as se  # noqa: E402
import memory  # noqa: E402

# 1. Initialize the MCP server
mcp = FastMCP("CSV_Text_To_SQL_Server")

# 2. Load all CSVs into an in-memory SQLite database + build the schema string
conn, db_schema = se.load_database()

# 3. Local LLM (override with MCP_MODEL env var). Must be pulled in Ollama.
MODEL = os.getenv("MCP_MODEL", "qwen2.5-coder:7b")
llm = se.make_llm("ollama", MODEL)


# 4. MCP tool
@mcp.tool
def ask_csv(question: str) -> str:
    """
    Translate a natural-language question into SQL, run it against the Olist
    tables (orders, order_reviews, order_customers, order_items), and return
    the results.
    """
    try:
        result = se.run_with_retry(llm, conn, db_schema, question)
        kind = result["kind"]

        if kind == "clarify":
            return f"CLARIFICATION NEEDED: {result['message']}"
        if kind == "impossible":
            return f"NOT ANSWERABLE: {result['message']}"
        if kind == "error":
            return f"Failed after {result['attempts']} attempt(s).\nLast SQL: {result['sql']}\n{result['error']}"

        sql, df = result["sql"], result["df"]
        if df.empty:
            return f"Executed successfully ({sql}), but returned 0 rows."
        answer = se.explain_result(llm, question, df)
        return (
            f"Answer: {answer}\n\n"
            f"Executed Query: {sql}\n"
            f"(attempts: {result['attempts']}, learned examples used: {result['examples_used']})\n\n"
            f"Results:\n{df.to_dict('records')}"
        )
    except Exception as e:
        return f"Agent error: {e}"


@mcp.tool
def flag_answer(question: str, sql: str, verdict: str, correction: str = "", note: str = "") -> str:
    """
    Give feedback on a generated query so future answers improve (model-agnostic).

    verdict: 'up' (correct), 'down' (wrong), or 'flag' (needs review).
    correction: the corrected SQL, if you know it (strongly recommended for 'down').
    note: optional free-text comment.
    Stored feedback is retrieved as few-shot examples on similar future questions.
    """
    verdict = verdict.lower().strip()
    if verdict not in {"up", "down", "flag"}:
        return "Error: verdict must be 'up', 'down', or 'flag'."
    memory.save_feedback(question, sql, verdict, correction=correction or None, note=note or None)
    return f"Saved '{verdict}' feedback. It will guide future queries on similar questions."


if __name__ == "__main__":
    mcp.run()
