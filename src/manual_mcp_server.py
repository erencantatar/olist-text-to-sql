import os
import sqlite3
import warnings
import asyncio
import pandas as pd

# The official low-level MCP SDK imports
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Suppress pandas warnings
warnings.filterwarnings('ignore')

# 1. Initialize the official manual Server instance
server = Server("CSV_Text_To_SQL_Server")

# 2. Database Bootstrap (Unchanged)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE_PATH = os.path.join(BASE_DIR, "../data/Brazilian_ECommerce_Olist/olist_order_reviews_dataset.csv")

conn = sqlite3.connect(":memory:", check_same_thread=False)

def bootstrap_database():
    try:
        df = pd.read_csv(CSV_FILE_PATH)
        df.to_sql("my_table", conn, index=False, if_exists="replace")
        cursor = conn.execute("PRAGMA table_info(my_table);")
        schema_lines = [f"{row[1]} ({row[2]})" for row in cursor.fetchall()]
        return "my_table columns: " + ", ".join(schema_lines)
    except Exception as e:
        return f"CRITICAL ERROR LOADING CSV: {str(e)}"

db_schema = bootstrap_database()

# 3. Setup LangChain and Ollama (Unchanged)
llm = OllamaLLM(model="gemma4:latest", temperature=0)

sql_template = """System: You are an expert data analyst. 
Given the following table schema: {schema}
Write ONLY a valid SQLite SELECT query to answer the user's question. 
Do NOT include markdown formatting, backticks, or explanations. Just the SQL string.

User: {question}
Assistant:"""

prompt = PromptTemplate.from_template(sql_template)
sql_chain = prompt | llm | StrOutputParser()

# ==========================================
# MANUAL MCP IMPLEMENTATION STARTS HERE
# ==========================================

# 4. Explicitly define the Tool Schema API
@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    This endpoint tells the MCP Client what tools exist and exactly 
    how to format the JSON when calling them.
    """
    return [
        types.Tool(
            name="ask_csv",
            description="Translates a natural language question into SQL, runs it against the CSV data, and returns the results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The natural language question to ask the dataset."
                    }
                },
                "required": ["question"],
            },
        )
    ]

# 5. Explicitly handle the Tool Execution API
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """
    This endpoint receives the execution request. We must manually check the tool name,
    extract arguments, and format the output according to the MCP protocol.
    """
    if name != "ask_csv":
        raise ValueError(f"Unknown tool: {name}")

    if not arguments or "question" not in arguments:
        raise ValueError("Missing required argument: 'question'")

    question = arguments["question"]

    if "CRITICAL ERROR" in db_schema:
        return [types.TextContent(type="text", text=db_schema)]

    try:
        # Generate the SQL query
        raw_sql = sql_chain.invoke({"schema": db_schema, "question": question})
        sql_query = raw_sql.strip().replace('```sql', '').replace('```', '')
        
        if not sql_query.upper().startswith("SELECT"):
            return [types.TextContent(type="text", text="Error: Only SELECT queries are permitted.")]
            
        # Execute the query
        cursor = conn.execute(sql_query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        results = [dict(zip(columns, row)) for row in rows]
        
        if not results:
            output_text = f"Query executed successfully ({sql_query}), but returned 0 results."
        else:
            output_text = f"Executed Query: {sql_query}\n\nResults:\n{results}"

        # Return standardized MCP TextContent object
        return [types.TextContent(type="text", text=output_text)]
        
    except Exception as e:
        return [types.TextContent(type="text", text=f"Agent/Database error: {str(e)}")]

# 6. Manually setup the transport streams and run the server
async def main():
    # Initialize standard input/output streams for MCP communication
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="CSV_Text_To_SQL_Server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())