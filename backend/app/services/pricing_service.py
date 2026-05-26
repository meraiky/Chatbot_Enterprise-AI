from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg2.extras

from app.core.config import settings
from app.core.database import get_conn

DEFAULT_PRICING = [
    ("gemini-3-flash-preview", Decimal("0.50"), Decimal("3.00"), "USD"),
    ("models/gemini-embedding-2", Decimal("0.15"), Decimal("0.00"), "USD"),
    ("claude-3-5-sonnet-latest", Decimal("3.00"), Decimal("15.00"), "USD"),
    ("claude-3-5-haiku-latest", Decimal("0.25"), Decimal("1.25"), "USD"),
    ("cache", Decimal("0.00"), Decimal("0.00"), "USD"),
]


def ensure_pricing_table() -> None:
    if not settings.DATABASE_URL:
        return
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS model_pricing (
                    model_name TEXT PRIMARY KEY,
                    input_price_per_1m_tokens NUMERIC(12, 6) NOT NULL DEFAULT 0,
                    output_price_per_1m_tokens NUMERIC(12, 6) NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
        )
        for model, input_price, output_price, currency in DEFAULT_PRICING:
            cur.execute(
                """
                    INSERT INTO model_pricing (
                        model_name, input_price_per_1m_tokens,
                        output_price_per_1m_tokens, currency
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (model_name) DO NOTHING
                    """,
                (model, input_price, output_price, currency),
            )


def get_session_cost(conversation_id: str, usd_to_vnd: float = 25400) -> dict[str, Any]:
    if not settings.DATABASE_URL:
        return {"conversation_id": conversation_id, "total_cost_usd": 0, "total_cost_vnd": 0, "breakdown": []}
    ensure_pricing_table()
    with get_conn() as connection, connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
                SELECT
                    tu.model,
                    COALESCE(SUM(tu.input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(tu.output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(
                        tu.input_tokens * COALESCE(mp.input_price_per_1m_tokens, 0) / 1000000.0
                        + tu.output_tokens * COALESCE(mp.output_price_per_1m_tokens, 0) / 1000000.0
                    ), 0) AS cost_usd
                FROM token_usage tu
                LEFT JOIN model_pricing mp ON mp.model_name = tu.model
                WHERE tu.conversation_id = %s
                GROUP BY tu.model
                ORDER BY cost_usd DESC
                """,
            (conversation_id,),
        )
        rows = cur.fetchall()

    breakdown = [
        {
            "model": row["model"],
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "cost_usd": round(float(row["cost_usd"] or 0), 6),
        }
        for row in rows
    ]
    total_usd = round(sum(item["cost_usd"] for item in breakdown), 6)
    return {
        "conversation_id": conversation_id,
        "total_cost_usd": total_usd,
        "total_cost_vnd": round(total_usd * usd_to_vnd),
        "breakdown": breakdown,
    }


def is_over_budget(conversation_id: str | None = None) -> bool:
    """
    Checks if the current cost exceeds the local budget.
    If conversation_id is provided, checks against that session.
    Otherwise, checks total historical usage.
    """
    if conversation_id:
        cost_data = get_session_cost(conversation_id)
        current_total = cost_data["total_cost_usd"]
    else:
        # Simplified: check all usage if no ID provided
        if not settings.DATABASE_URL:
            return False
        with get_conn() as connection, connection.cursor() as cur:
            cur.execute(
                """
                    SELECT COALESCE(SUM(
                        tu.input_tokens * COALESCE(mp.input_price_per_1m_tokens, 0) / 1000000.0
                        + tu.output_tokens * COALESCE(mp.output_price_per_1m_tokens, 0) / 1000000.0
                    ), 0)
                    FROM token_usage tu
                    LEFT JOIN model_pricing mp ON mp.model_name = tu.model
                    """
            )
            current_total = float(cur.fetchone()[0] or 0)
    
    return current_total >= settings.LOCAL_COST_BUDGET

