"""
Model-agnostic feedback memory for the text-to-SQL flow.

Feedback (thumbs up / thumbs down + optional corrected SQL) is appended to a
JSONL file. On every new question the most relevant positive/corrected examples
are retrieved and injected into the prompt as few-shot guidance — so the flow
improves over time regardless of which LLM is used (Vanna-style training).
"""

import json
import os
import re
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDBACK_PATH = os.path.join(BASE_DIR, "../data/sql_feedback.jsonl")

_TOKEN = re.compile(r"[a-z0-9_]+")


def _tokens(text):
    return set(_TOKEN.findall((text or "").lower()))


def load_feedback():
    """Return all feedback entries (empty list if none)."""
    if not os.path.exists(FEEDBACK_PATH):
        return []
    entries = []
    with open(FEEDBACK_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def save_feedback(question, sql, verdict, correction=None, note=None):
    """Append one feedback entry. verdict is 'up', 'down', or 'flag'."""
    entry = {
        "question": question,
        "sql": sql,
        "verdict": verdict,
        "correction": correction,
        "note": note,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    os.makedirs(os.path.dirname(FEEDBACK_PATH), exist_ok=True)
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def good_examples(question, k=3):
    """Return up to k (question, sql) pairs learned from feedback, ranked by
    token overlap with the incoming question.

    Positive feedback contributes its SQL; negative feedback contributes its
    correction (the fixed SQL the user supplied). Only overlapping matches are
    returned so unrelated examples never mislead the model.
    """
    pairs = []
    for e in load_feedback():
        if e.get("verdict") == "up" and e.get("sql"):
            pairs.append((e["question"], e["sql"]))
        elif e.get("verdict") == "down" and e.get("correction"):
            pairs.append((e["question"], e["correction"]))

    q_tokens = _tokens(question)
    scored = []
    for ex_q, ex_sql in pairs:
        overlap = len(q_tokens & _tokens(ex_q))
        if overlap > 0:
            scored.append((overlap, ex_q, ex_sql))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(ex_q, ex_sql) for _, ex_q, ex_sql in scored[:k]]


def format_examples(examples):
    """Render (question, sql) pairs as a prompt block, or '' if none."""
    if not examples:
        return ""
    lines = ["Examples of correct queries for similar past questions:"]
    for q, sql in examples:
        lines.append(f"Q: {q}\nSQL: {sql}")
    return "\n".join(lines) + "\n"
