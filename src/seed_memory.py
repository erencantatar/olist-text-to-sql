"""
Seed the feedback memory with a few verified 'golden' query examples.

These become few-shot guidance so hard/multi-step questions work reliably from
the start (and demonstrate the learning loop). Safe to re-run — it appends.

Run:  python src/seed_memory.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory as mem  # noqa: E402

GOLDEN = [
    (
        "Which state had highest average review score among customers who ordered more than twice?",
        """WITH repeat_customers AS (
  SELECT oc.customer_unique_id, MAX(oc.customer_state) AS customer_state
  FROM orders o
  JOIN order_customers oc ON o.customer_id = oc.customer_id
  GROUP BY oc.customer_unique_id
  HAVING COUNT(DISTINCT o.order_id) > 2
)
SELECT rc.customer_state, AVG(r.review_score) AS avg_score
FROM repeat_customers rc
JOIN order_customers oc ON oc.customer_unique_id = rc.customer_unique_id
JOIN orders o ON o.customer_id = oc.customer_id
JOIN order_reviews r ON r.order_id = o.order_id
GROUP BY rc.customer_state
ORDER BY avg_score DESC
LIMIT 1""",
    ),
    (
        "Top 10 product categories by units sold",
        """SELECT pc.product_category_name_english, COUNT(*) AS units_sold
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
JOIN product_categories pc ON p.product_category_name = pc.product_category_name
GROUP BY pc.product_category_name_english
ORDER BY units_sold DESC
LIMIT 10""",
    ),
    (
        "How many unique customers ordered more than twice?",
        """SELECT COUNT(*) AS repeat_customers
FROM (
  SELECT oc.customer_unique_id
  FROM orders o
  JOIN order_customers oc ON o.customer_id = oc.customer_id
  GROUP BY oc.customer_unique_id
  HAVING COUNT(DISTINCT o.order_id) > 2
)""",
    ),
]

if __name__ == "__main__":
    for question, sql in GOLDEN:
        mem.save_feedback(question, sql.strip(), "up", note="seeded golden example")
    print(f"Seeded {len(GOLDEN)} golden examples -> {mem.FEEDBACK_PATH}")
