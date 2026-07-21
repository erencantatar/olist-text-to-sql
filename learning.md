
- **Model Caching (The Big Difference):** When you run a script using `llama-cpp-python`, it has to load the multi-gigabyte model file from your SSD into your M1 Max's unified memory every single time you execute the code. This adds a noticeable delay (several seconds) before the first word is generated. Ollama runs as a background service and keeps the model loaded in memory for 5 minutes after a request. When you run your LangChain script multiple times, it connects instantly.
- **Auto-Tuning:** Ollama automatically detects your Apple Silicon and optimally configures the thread count and GPU offloading parameters (doing the equivalent of `n_gpu_layers=-1` for you).
- **Overhead:** Ollama does add a microscopic amount of HTTP API overhead since LangChain talks to it over `localhost`, but this is measured in milliseconds and is completely eclipsed by the time saved not reloading the model into RAM.Here is the simplest way to understand how these four tools fit together in the AI world. Think of them as different parts of a restaurant.

  ### 1. Ollama: The Kitchen (The Engine)

  Ollama is the software that actually runs the AI model on your computer. Large Language Models (LLMs) are usually massive, complex files that are hard to set up. Ollama hides all that complexity. It downloads the model, optimizes it for your specific hardware, and keeps it running so you can ask it questions.
  - **In simple terms:** It is the engine that makes the AI think and type locally on your machine.

  ### 2. FastAPI: The Waiter (The Communicator)

  FastAPI is a tool for building APIs (Application Programming Interfaces). An API is just a doorway that allows two different pieces of software to talk to each other over a network. If you build an AI application on your laptop and want a website frontend to be able to talk to it, you use FastAPI to create the web links (endpoints) to handle those requests.
  - **In simple terms:** It takes a request from a user, hands it to your code, and delivers the answer back.

  ### 3. LangChain: The Recipe (The Orchestrator)

  By themselves, AI models are just text generators trapped in a box; they can't search the web, read your PDFs, or query a database. LangChain is a framework that connects the AI to the outside world. It allows you to "chain" steps together—for example: Step 1) Read a database, Step 2) Give that data to the AI, Step 3) Have the AI write a summary.
  - **In simple terms:** It is the glue that connects the AI brain to actual tools and data.

  ### 4. LangSmith: The Manager (The Dashboard)

  When you build a complex app with LangChain, the AI might make 10 different decisions and tool calls before giving the user a final answer. If the final answer is wrong, it is very hard to figure out *why*. LangSmith is a tracking platform that logs every single thing your LangChain app does. You can look at it to see exactly what prompt was sent, how long it took, and how much it cost.
  - **In simple terms:** It is the security camera and performance tracker for your AI application.

  **How they work together:**

  You use **LangChain** to write the logic, which asks **Ollama** to generate the text. You expose that setup to the internet using **FastAPI**, and you monitor the whole operation to fix bugs using **LangSmith**.

**Recommendation:** for *this* assignment, SQLite is genuinely enough — but if you want the professional/scale story (and it's a low-risk swap), move to **DuckDB + parquet**. Polars is the wrong lever here (speeds loading, not querying).

FASTMCP vs MCP;

## What `python src/seed_memory.py` does (simple)

Think of the feedback memory as a **notebook of "good answers."** Normally it fills up as *you* thumbs-up answers in the chat. But an empty notebook = the model gets no hints on hard questions.

The seed script = **pre-writing 3 correct answers into that notebook before anyone uses the app.** It stores 3 verified question→SQL pairs (the tricky multi-step one, top-categories, repeat-customer count) marked 👍.

Result: when someone asks a similar hard question, the model sees the matching example and copies the pattern → works first try instead of failing.

`# once` = run it a single time to plant the seeds. Running again just adds duplicates (harmless). It writes to `data/sql_feedback.jsonl`.

Simplest analogy: **giving the model a cheat-sheet of worked examples before the exam.**

Confirmed: **dataset has NO product names.** Products are anonymized — only `product_category_name` (Portuguese) + an English translation table. No "xbox". Best you can get = category like `computers_accessories`.

Two bugs to fix:

1. `products` + translation tables never loaded.
2. Model hallucinated columns — `quantity` (doesn't exist; each row = 1 unit) and earlier `SUM(order_item_id)` (that's a line-number, not a count). Need schema hints.

Fixing engine — add 2 tables + guidance: