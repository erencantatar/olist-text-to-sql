"""
Exploratory data analysis on the Olist tables.

Each function returns a (title, insight, DataFrame) triple so the SAME code powers
both the CLI (`python src/eda.py`, prints tables) and the Streamlit EDA page
(pages/2_EDA.py, draws charts). Grounding: run these first to see the shape of the
data, then ask better questions in the chat.

Run:  python src/eda.py
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sql_engine as se  # noqa: E402


def _q(conn, sql):
    return pd.read_sql(sql, conn)


# Each analysis: name -> function(conn) -> (title, insight, df).
# `insight` is the takeaway + a question it suggests asking in the chat.

def review_score_distribution(conn):
    df = _q(conn, "SELECT review_score, COUNT(*) AS n FROM order_reviews "
                  "GROUP BY review_score ORDER BY review_score")
    return (
        "Review score distribution",
        "Bimodal: a big pile of 5s and a spike of 1s (few in the middle). Customers "
        "tend to love it or hate it. → Try: \"Average review score per order status\".",
        df,
    )


def order_status_breakdown(conn):
    df = _q(conn, "SELECT order_status, COUNT(*) AS n FROM orders "
                  "GROUP BY order_status ORDER BY n DESC")
    return (
        "Orders by status",
        "~97% delivered; the rest (canceled/unavailable/shipped) is the interesting "
        "tail. → Try: \"How many orders were canceled?\".",
        df,
    )


def late_delivery_vs_review(conn):
    df = _q(conn,
            "SELECT CASE WHEN julianday(order_delivered_customer_date) > "
            "julianday(order_estimated_delivery_date) THEN 'late' ELSE 'on time' END "
            "AS delivery, ROUND(AVG(r.review_score), 2) AS avg_review_score, "
            "COUNT(*) AS n "
            "FROM orders o JOIN order_reviews r ON o.order_id = r.order_id "
            "WHERE order_delivered_customer_date IS NOT NULL "
            "GROUP BY delivery")
    return (
        "Late delivery vs. review score",
        "THE headline: late orders average ~2.6 stars, on-time ~4.3. Delivery speed "
        "is the strongest driver of satisfaction. → Try: \"Which state has the most "
        "late deliveries?\".",
        df,
    )


def payment_type_share(conn):
    df = _q(conn, "SELECT payment_type, COUNT(*) AS n FROM order_payments "
                  "GROUP BY payment_type ORDER BY n DESC")
    return (
        "Payment methods",
        "Credit card dominates; 'boleto' (Brazilian bank slip) is a strong #2 — a "
        "very local signal. → Try: \"What is the average payment value per payment type?\".",
        df,
    )


def installments_distribution(conn):
    df = _q(conn, "SELECT payment_installments AS installments, COUNT(*) AS n "
                  "FROM order_payments WHERE payment_installments > 0 "
                  "GROUP BY payment_installments ORDER BY payment_installments")
    return (
        "Payment installments",
        "Most pay in 1 shot, but long tails at 10x — Brazilians split purchases into "
        "many monthly 'parcelas'. → Try: \"Average order value by number of installments\".",
        df,
    )


def top_categories(conn):
    df = _q(conn,
            "SELECT pc.product_category_name_english AS category, COUNT(*) AS units_sold "
            "FROM order_items oi "
            "JOIN products p ON oi.product_id = p.product_id "
            "JOIN product_categories pc ON p.product_category_name = pc.product_category_name "
            "GROUP BY category ORDER BY units_sold DESC LIMIT 10")
    return (
        "Top 10 product categories (units sold)",
        "bed_bath_table, health_beauty, sports_leisure lead. No product NAMES exist — "
        "category is the finest label. → Try: \"Top 10 product categories by revenue\".",
        df,
    )


def customers_by_state(conn):
    df = _q(conn, "SELECT customer_state AS state, "
                  "COUNT(DISTINCT customer_unique_id) AS customers "
                  "FROM order_customers GROUP BY customer_state "
                  "ORDER BY customers DESC LIMIT 10")
    return (
        "Customers by state (top 10)",
        "Heavily concentrated in SP (São Paulo), then RJ, MG. Note: counts DISTINCT "
        "customer_unique_id (real people), not customer_id. → Try: \"Which state has "
        "the most customers?\".",
        df,
    )


def orders_over_time(conn):
    df = _q(conn, "SELECT substr(order_purchase_timestamp, 1, 7) AS month, "
                  "COUNT(*) AS orders FROM orders "
                  "WHERE order_purchase_timestamp <> '' "
                  "GROUP BY month ORDER BY month")
    return (
        "Orders per month",
        "Clear growth through 2017 into 2018, with a Nov 2017 spike (Black Friday). "
        "→ Try: \"How many orders were placed in each month of 2018?\".",
        df,
    )


# Ordered registry the Streamlit page and CLI both iterate.
ANALYSES = [
    late_delivery_vs_review,
    review_score_distribution,
    order_status_breakdown,
    orders_over_time,
    top_categories,
    customers_by_state,
    payment_type_share,
    installments_distribution,
]


def run_all(conn):
    """Return a list of (title, insight, df) for every analysis."""
    return [fn(conn) for fn in ANALYSES]


if __name__ == "__main__":
    conn, _ = se.load_database()
    for title, insight, df in run_all(conn):
        print("\n" + "=" * 70)
        print(title)
        print("-" * 70)
        print(df.to_string(index=False))
        print("INSIGHT:", insight)
