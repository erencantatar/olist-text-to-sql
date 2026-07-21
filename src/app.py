"""
Streamlit chat frontend for the Olist text-to-SQL engine.

Run:  python -m streamlit run src/app.py
Ask questions in natural language -> see the SQL, the result table, and a chart.
Pick any local Ollama model or an OpenRouter model in the sidebar.
Thumbs up/down (and optional corrected SQL) teach the flow via feedback memory.
"""

import os
import sys

import streamlit as st

# Make local modules importable no matter where Streamlit is launched from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sql_engine as se  # noqa: E402
import memory as mem  # noqa: E402

st.set_page_config(page_title="Olist Text-to-SQL", page_icon="🗃️", layout="wide")


@st.cache_resource(show_spinner="Loading Olist CSVs into SQLite…")
def get_db():
    return se.load_database()


conn, schema = get_db()


def render_chart(df):
    """Auto-plot a bar chart when the result looks categorical + numeric."""
    if df is None or df.empty or df.shape[1] < 2 or len(df) > 50:
        return
    numeric = df.select_dtypes("number").columns.tolist()
    category = [c for c in df.columns if c not in numeric]
    if not numeric or not category:
        return
    try:
        st.bar_chart(df.set_index(category[0])[numeric])
    except Exception:
        pass  # Charting is best-effort; the table is always shown.


def feedback_ui(idx, msg):
    """Thumbs up/down + correction box under an assistant message."""
    question, sql = msg.get("question"), msg.get("sql")
    if not question or not sql:
        return

    choice = st.feedback("thumbs", key=f"fb_{idx}")  # 0 = down, 1 = up
    if choice == 1 and not msg.get("saved"):
        mem.save_feedback(question, sql, "up")
        msg["saved"] = True
        st.toast("👍 Saved as a good example — future queries will learn from it.")
    elif choice == 0:
        correction = st.text_input(
            "Optional: paste the correct SQL to teach the system",
            key=f"corr_{idx}",
        )
        if st.button("Save feedback", key=f"save_{idx}") and not msg.get("saved"):
            mem.save_feedback(question, sql, "down", correction=correction or None)
            msg["saved"] = True
            st.toast("👎 Feedback saved.")


STEP_ICON = {
    "recall": "🧠", "think": "🤔", "intent": "🛑", "safety": "🛡️",
    "run": "🔧", "retry": "🔁", "done": "✅", "explain": "📝",
}


def compute_answer(provider, model, api_key, temperature, question):
    """Run the full retry pipeline and return an assistant message dict.

    Streams each pipeline stage into an st.status panel so the user can watch
    the model think → call the SQL tool → summarize, including any retries.
    """
    llm = se.make_llm(provider, model, api_key, temperature)

    with st.status("Working…", expanded=True) as status:
        def on_step(event, detail):
            icon = STEP_ICON.get(event, "•")
            if event == "run":
                status.write(f"{icon} **Calling SQL tool:**")
                status.code(detail, language="sql")
            else:
                status.write(f"{icon} {detail}")

        result = se.run_with_retry(llm, conn, schema, question, on_step=on_step)

        if result["kind"] == "sql" and result["df"] is not None and not result["df"].empty:
            status.write(f"{STEP_ICON['explain']} Summarizing the result…")
            answer = se.explain_result(llm, question, result["df"])
        else:
            answer = ""
        status.update(label="Done", state="complete", expanded=False)

    kind = result["kind"]
    msg = {"role": "assistant", "question": question, "sql": result["sql"]}

    if kind == "clarify":
        msg["content"] = f"🤔 **Ambiguous** — {result['message']}\n\nRephrase with a specific metric and I'll answer."
    elif kind == "impossible":
        msg["content"] = f"🚫 **Not answerable from this data** — {result['message']}"
    elif kind == "error":
        msg["content"] = (
            f"❌ Failed after {result['attempts']} attempt(s). "
            f"Last error: {result['error'].splitlines()[-1] if result['error'] else 'unknown'}"
        )
    else:
        df = result["df"]
        note = "" if result["examples_used"] == 0 else f" · {result['examples_used']} learned example(s)"
        meta = f"_Returned {len(df)} row(s) in {result['attempts']} attempt(s){note}._"
        msg["content"] = f"{answer}\n\n{meta}" if answer else f"Returned **{len(df)}** row(s) in {result['attempts']} attempt(s){note}."
        msg["df"] = df
    return msg


# ---------------------------------------------------------------- Sidebar
with st.sidebar:
    st.header("⚙️ Model settings")

    provider_label = st.radio("Provider", ["Local (Ollama)", "OpenRouter"], index=0)

    if provider_label.startswith("Local"):
        provider = "ollama"
        models = se.list_ollama_models()
        if not models:
            st.warning("No Ollama models found. Is `ollama serve` running?")
            models = ["qwen2.5-coder:7b"]
        default = models.index("qwen2.5-coder:7b") if "qwen2.5-coder:7b" in models else 0
        model = st.selectbox("Model", models, index=default)
        api_key = None
    else:
        provider = "openrouter"
        model = st.selectbox("Model", se.OPENROUTER_MODELS)
        api_key = st.text_input(
            "OpenRouter API key",
            type="password",
            value=os.getenv("OPENROUTER_API_KEY", ""),
            help="Add later — leave blank to use local models for now.",
        )

    temperature = st.slider("Temperature", 0.0, 1.0, 0.0, 0.1)
    show_sql = st.checkbox("Show generated SQL", value=True)

    st.divider()
    st.caption(f"🧠 Feedback memory: {len(mem.load_feedback())} entries")
    if st.button("🚩 Flag this conversation"):
        n = 0
        for m in st.session_state.get("messages", []):
            if m["role"] == "assistant" and m.get("question") and m.get("sql"):
                mem.save_feedback(m["question"], m["sql"], "flag", note="flagged conversation")
                n += 1
        st.toast(f"Flagged {n} answer(s) for review.")
    if st.button("🧹 Clear chat"):
        st.session_state.messages = []

    with st.expander("📋 Schema"):
        st.code(schema)

# ---------------------------------------------------------------- Main
st.title("🗃️ Olist Text-to-SQL Chat")
st.caption("Ask about orders, reviews, customers, items, payments, sellers — NL → SQL → table → chart.")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Replay full history (single source of rendering for user + assistant).
for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if show_sql and msg.get("sql"):
            st.code(msg["sql"], language="sql")
        if msg.get("df") is not None:
            st.dataframe(msg["df"], use_container_width=True)
            render_chart(msg["df"])
        if msg["role"] == "assistant":
            feedback_ui(idx, msg)

# Clickable demo questions (includes the 4 classic hard cases).
DEMOS = [
    "Which state has the most customers?",
    "Top 10 product categories by units sold",
    "Average review score per order status",
    "Which customers are best?",
    "Which products caused customer churn?",
    "Which state had highest average review score among customers who ordered more than twice?",
]
if len(st.session_state.messages) == 0:
    st.markdown("**💡 Try one of these:**")
    demo_cols = st.columns(3)
    for i, dq in enumerate(DEMOS):
        if demo_cols[i % 3].button(dq, key=f"demo_{i}", use_container_width=True):
            st.session_state.pending_q = dq
            st.rerun()

# Question source: typed input OR a clicked demo.
question = st.chat_input("Ask a question about the data…")
if not question and st.session_state.get("pending_q"):
    question = st.session_state.pop("pending_q")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    if provider == "openrouter" and not api_key:
        st.session_state.messages.append(
            {"role": "assistant", "content": "⚠️ Add your OpenRouter API key in the sidebar, or switch to a local model."}
        )
    else:
        with st.spinner(f"Thinking with {model}…"):
            try:
                st.session_state.messages.append(
                    compute_answer(provider, model, api_key, temperature, question)
                )
            except Exception as e:
                st.session_state.messages.append({"role": "assistant", "content": f"❌ Error: {e}"})
    st.rerun()
