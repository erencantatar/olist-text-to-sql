"""
Tiny eval set for the text-to-SQL flow.

Runs a fixed set of questions (normal, misspelled, ambiguous, impossible,
multi-step) through the real pipeline and asserts the EXPECTED BEHAVIOUR —
not an exact SQL string (which varies by model), but the response *kind*
(sql / clarify / impossible) and a light sanity check on the result.

Run:  python src/eval.py
      python src/eval.py --model qwen2.5-coder:7b
Exit code is non-zero if any case fails, so it doubles as a smoke test.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sql_engine as se  # noqa: E402


def top_value(df, col):
    return None if df is None or df.empty else df.iloc[0][col]


# Each case: expected acceptable kinds + an optional check(df) -> (ok, detail).
CASES = [
    {
        "name": "normal",
        "q": "Which state has the most customers?",
        "kinds": {"sql"},
        "check": lambda df: (top_value(df, df.columns[0]) == "SP", f"top={top_value(df, df.columns[0])}"),
    },
    {
        "name": "misspelled",
        "q": "Which stae has most custmers?",
        "kinds": {"sql"},
        "check": lambda df: (top_value(df, df.columns[0]) == "SP", f"top={top_value(df, df.columns[0])}"),
    },
    {
        "name": "top-categories",
        "q": "Top 10 product categories by units sold",
        "kinds": {"sql"},
        "check": lambda df: (len(df) > 0, f"rows={len(df)}"),
    },
    {
        "name": "multi-step",
        "q": "Which state had highest average review score among customers who ordered more than twice?",
        "kinds": {"sql"},
        "check": lambda df: (len(df) > 0, f"rows={len(df)}"),
    },
    {
        "name": "ambiguous",
        "q": "Which customers are best?",
        "kinds": {"clarify"},
        "check": None,
    },
    {
        # Model may correctly reject OR reframe churn via recency — accept either.
        "name": "impossible",
        "q": "Which products caused customer churn?",
        "kinds": {"impossible", "clarify"},
        "check": None,
    },
]


def run(model):
    conn, schema = se.load_database()
    llm = se.make_llm("ollama", model)

    passed = 0
    print(f"\nRunning {len(CASES)} eval cases on model '{model}'\n" + "=" * 70)
    for case in CASES:
        r = se.run_with_retry(llm, conn, schema, case["q"])
        kind = r["kind"]
        kind_ok = kind in case["kinds"]

        check_ok, detail = True, ""
        if kind_ok and case["check"] and kind == "sql":
            check_ok, detail = case["check"](r["df"])

        ok = kind_ok and check_ok
        passed += ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['name']:<15} kind={kind:<11} "
              f"expect={'/'.join(sorted(case['kinds'])):<18} {detail}")
        if not ok:
            print(f"        Q: {case['q']}")
            if r.get("message"):
                print(f"        msg: {r['message'][:120]}")
            if r.get("sql"):
                print(f"        sql: {' '.join(r['sql'].split())[:120]}")

    print("=" * 70)
    print(f"{passed}/{len(CASES)} passed\n")
    return passed == len(CASES)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("MCP_MODEL", "qwen2.5-coder:7b"))
    args = parser.parse_args()
    sys.exit(0 if run(args.model) else 1)
