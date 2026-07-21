"""
Feedback Memory viewer.

Lists every feedback entry the flow has learned from (thumbs up / down /
flag + optional corrected SQL). Auto-appears in the Streamlit sidebar as a
second page next to the main chat.
"""

import os
import sys

import pandas as pd
import streamlit as st

# memory.py lives in src/ (parent of this pages/ folder).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory as mem  # noqa: E402

st.set_page_config(page_title="Feedback Memory", page_icon="🧠", layout="wide")

st.title("🧠 Feedback Memory")
st.caption("Everything the text-to-SQL flow has learned. Up/corrected entries become few-shot examples on similar future questions.")

entries = mem.load_feedback()

if not entries:
    st.info("No feedback yet. Use 👍 / 👎 under answers in the chat to teach the flow.")
    st.stop()

df = pd.DataFrame(entries)
for col in ["ts", "verdict", "question", "sql", "correction", "note"]:
    if col not in df.columns:
        df[col] = None

# --- Summary metrics
counts = df["verdict"].value_counts().to_dict()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total", len(df))
c2.metric("👍 up", counts.get("up", 0))
c3.metric("👎 down", counts.get("down", 0))
c4.metric("🚩 flag", counts.get("flag", 0))

# --- Filter
verdicts = sorted(df["verdict"].dropna().unique().tolist())
chosen = st.multiselect("Filter by verdict", verdicts, default=verdicts)
view = df[df["verdict"].isin(chosen)].iloc[::-1]  # newest first

st.dataframe(
    view[["ts", "verdict", "question", "sql", "correction", "note"]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "ts": st.column_config.TextColumn("When", width="small"),
        "verdict": st.column_config.TextColumn("Verdict", width="small"),
        "question": st.column_config.TextColumn("Question", width="medium"),
        "sql": st.column_config.TextColumn("Generated SQL", width="large"),
        "correction": st.column_config.TextColumn("Corrected SQL", width="large"),
        "note": st.column_config.TextColumn("Note", width="small"),
    },
)

# --- Detail view (full SQL, hard to read in a table cell)
with st.expander("🔍 Inspect an entry"):
    labels = [f"{i}: [{r['verdict']}] {str(r['question'])[:60]}" for i, r in view.reset_index().iterrows()]
    if labels:
        pick = st.selectbox("Entry", range(len(labels)), format_func=lambda i: labels[i])
        row = view.reset_index().iloc[pick]
        st.markdown(f"**Question:** {row['question']}")
        st.markdown("**Generated SQL:**")
        st.code(row["sql"] or "", language="sql")
        if row.get("correction"):
            st.markdown("**Corrected SQL (the taught answer):**")
            st.code(row["correction"], language="sql")
        if row.get("note"):
            st.markdown(f"**Note:** {row['note']}")

st.divider()
col_a, col_b = st.columns(2)
with col_a:
    st.download_button(
        "⬇️ Export feedback (JSONL)",
        data="\n".join(__import__("json").dumps(e) for e in entries),
        file_name="sql_feedback.jsonl",
        mime="application/jsonl",
    )
with col_b:
    if st.button("🗑️ Clear ALL feedback", type="secondary"):
        if os.path.exists(mem.FEEDBACK_PATH):
            os.remove(mem.FEEDBACK_PATH)
        st.rerun()
