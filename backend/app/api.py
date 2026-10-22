import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import json
import logging
import random
import time
import sqlite3
from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.app.database import db_connection
from backend.app.agent import run_agent_loop, run_agent_workflow
from backend.app.pdf_generator import generate_po_pdf
from backend.seed_data import seed_database

logger = logging.getLogger(__name__)

MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "stockroom-secret-token-2026")

app = FastAPI(title="Stockroom Copilot Enterprise API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    logger.error(
        "Unhandled API error for %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=503,
        content={
            "status": "error",
            "message": "The service is temporarily unavailable. Please retry.",
        },
    )


# Authentication Guardrail for MCP / API routes
async def verify_bearer_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing."
        )
    token_type, _, token = authorization.partition(" ")
    if token_type.lower() != "bearer" or token != MCP_BEARER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired Bearer Token."
        )
    return True

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_session"

# --- 1. Async Dashboard Metric Endpoints ---

@app.get("/api/dashboard/stats")
def get_dashboard_stats():
    with db_connection() as conn:
        cursor = conn.cursor()

        risk_row = cursor.execute("""
        SELECT 
            COUNT(*) AS total_skus,
            SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) AS critical_count
        FROM v_inventory_status;
    """).fetchone()

        total_skus = risk_row["total_skus"] or 0
        critical_skus = risk_row["critical_count"] or 0
        critical_pct = round((critical_skus / total_skus) * 100, 1) if total_skus else 0

        val_row = cursor.execute(
            "SELECT ROUND(COALESCE(SUM(on_hand * unit_cost), 0)) AS total_val FROM v_inventory_status;"
        ).fetchone()

        po_row = cursor.execute("""
        SELECT COUNT(*) AS open_count, COALESCE(SUM(total_cost), 0) AS open_val 
        FROM purchase_orders WHERE status = 'pending_review';
    """).fetchone()

        cover_row = cursor.execute("""
        SELECT ROUND(AVG(CASE WHEN days_of_cover > 90 THEN 90 ELSE days_of_cover END), 1) AS avg_cover 
        FROM v_inventory_status WHERE days_of_cover IS NOT NULL;
    """).fetchone()

    return {
        "stockout_risk": {"critical_count": critical_skus, "critical_pct": critical_pct, "total_skus": total_skus},
        "inventory_value": val_row["total_val"] or 0,
        "open_purchase_orders": {"count": po_row["open_count"], "total_value": po_row["open_val"]},
        "avg_days_of_cover": cover_row["avg_cover"] or 0.0,
    }

@app.get("/api/dashboard/runway")
def get_stockout_runway():
    with db_connection() as conn:
        rows = conn.execute("""
        SELECT name, days_of_cover, lead_time_days, status
        FROM v_inventory_status
        WHERE status IN ('critical', 'warning')
        ORDER BY (days_of_cover - lead_time_days) ASC
        LIMIT 6;
    """).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/dashboard/health")
def get_inventory_health():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM v_inventory_status GROUP BY status;"
        ).fetchall()
    return {r["status"]: r["count"] for r in rows}

@app.get("/api/dashboard/manifest")
def get_replenishment_manifest():
    with db_connection() as conn:
        rows = conn.execute("""
        SELECT 
            po.po_number, po.sku, p.name AS product, s.name AS supplier,
            v.on_hand, v.days_of_cover, v.lead_time_days,
            po.quantity AS po_qty, po.status, po.total_cost
        FROM purchase_orders po
        JOIN products p ON p.sku = po.sku
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        LEFT JOIN v_inventory_status v ON v.sku = po.sku
        WHERE po.status = 'pending_review'
        ORDER BY po.created_at DESC;
    """).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/dashboard/activity")
def get_activity_log(limit: int = Query(default=5, ge=1, le=100)):
    with db_connection() as conn:
        rows = conn.execute("""
        SELECT strftime('%H:%M:%S', created_at) as time, summary
        FROM activity_log
        ORDER BY id DESC
        LIMIT ?;
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]

# --- 2. Human-in-the-Loop Actions & PDF Generation ---

# In backend/app/api.py

@app.post("/api/orders/{po_number}/approve")
def approve_order(po_number: str):
    """Approve a pending purchase order, retrying transient SQLite lock errors."""
    max_retries = 5
    for attempt in range(max_retries + 1):
        try:
            with db_connection() as conn:
                conn.execute("BEGIN IMMEDIATE;")
                cursor = conn.execute(
                    """
                    UPDATE purchase_orders
                    SET status = 'approved', decided_at = CURRENT_TIMESTAMP
                    WHERE po_number = ? AND status = 'pending_review';
                    """,
                    (po_number,),
                )
                if cursor.rowcount == 0:
                    existing = conn.execute(
                        "SELECT status FROM purchase_orders WHERE po_number = ?;",
                        (po_number,),
                    ).fetchone()
                    conn.rollback()
                    if existing is None:
                        return JSONResponse(
                            status_code=404,
                            content={"status": "error", "message": f"PO {po_number} was not found."},
                        )
                    if existing["status"] == "approved":
                        return {
                            "status": "success",
                            "message": f"PO {po_number} was already approved.",
                        }
                    return JSONResponse(
                        status_code=409,
                        content={
                            "status": "error",
                            "message": f"PO {po_number} is not awaiting approval.",
                        },
                    )

                conn.execute(
                    """
                    INSERT INTO activity_log (source, event_type, summary)
                    VALUES ('user', 'approval', ?);
                    """,
                    (f"PO Approved: {po_number}",),
                )
                conn.commit()

            return {"status": "success", "message": f"PO {po_number} approved successfully."}
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() and attempt < max_retries:
                time.sleep(min(0.1 * (2 ** attempt) + random.uniform(0, 0.05), 2.0))
                continue
            logger.exception("Database error approving PO %s", po_number)
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": "The order could not be approved. Please retry."},
            )
        except Exception:
            logger.exception("Unexpected error approving PO %s", po_number)
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": "The order could not be approved. Please retry."},
            )

@app.get("/api/orders/{po_number}/pdf")
def get_order_pdf(po_number: str):
    with db_connection() as conn:
        order = conn.execute("""
            SELECT po.po_number, po.sku, p.name AS product, s.name AS supplier,
                   po.quantity, po.unit_cost, po.total_cost, po.status,
                   po.reason, po.created_at, po.expected_delivery, po.created_by
            FROM purchase_orders po
            JOIN products p ON p.sku = po.sku
            JOIN suppliers s ON s.supplier_id = po.supplier_id
            WHERE po.po_number = ?;
        """, (po_number,)).fetchone()

    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found.")

    pdf_bytes = generate_po_pdf(dict(order))
    return Response(content=pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename={po_number}.pdf"
    })

@app.get("/api/mcp-status")
async def get_mcp_status():
    return {
        "status": "online",
        "connected": True,
        "tools_count": 5,
        "tools": [
            "check_inventory_levels",
            "get_supplier_info",
            "predict_stockout",
            "trigger_reorder",
            "list_purchase_orders",
        ],
        "server": "FastMCP Streamable HTTP"
    }

@app.post("/api/demo/reset")
def reset_demo_data():
    seed_database()
    return {"ok": True, "message": "Demo data restored."}

# --- 3. Async Agent Chat Endpoint with Persistent Session Memory ---

@app.post("/api/chat")
def chat_endpoint(payload: ChatRequest):
    history = []
    try:
        with db_connection() as conn:
            history_rows = conn.execute(
                """
                SELECT role, content
                FROM chat_sessions
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT 10;
                """,
                (payload.session_id,),
            ).fetchall()
            history = [dict(row) for row in reversed(history_rows)]
            conn.execute(
                "INSERT INTO chat_sessions (session_id, role, content) VALUES (?, 'user', ?);",
                (payload.session_id, payload.message),
            )
            conn.commit()
    except Exception:
        logger.exception("Could not load or save chat history for session %s", payload.session_id)

    try:
        result = run_agent_loop(payload.message, history)
        if not isinstance(result, dict) or not isinstance(result.get("reply"), str):
            raise ValueError("Agent returned an invalid response.")
    except Exception:
        logger.exception("Agent failed; trying the local workflow fallback.")
        try:
            result = run_agent_workflow(payload.message)
        except Exception:
            logger.exception("Local workflow fallback failed.")
            result = {
                "reply": (
                    "### Copilot is temporarily unavailable\n\n"
                    "| Status | Details |\n|---|---|\n"
                    "| Not completed | The request could not be processed. Please try again. |"
                ),
                "tool_calls": [],
            }

    reply = result.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        reply = (
            "### Copilot response\n\n"
            "| Status | Details |\n|---|---|\n"
            "| No response | No analysis was returned. Please try again. |"
        )
    tool_calls = result.get("tool_calls")
    if not isinstance(tool_calls, list):
        tool_calls = []
    response_payload = {"reply": reply, "tool_calls": tool_calls}
    if result.get("status") == "error":
        response_payload["status"] = "error"

    try:
        with db_connection() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (session_id, role, content, tools_json)
                VALUES (?, 'model', ?, ?);
                """,
                (payload.session_id, reply, json.dumps(tool_calls)),
            )
            conn.commit()
    except Exception:
        logger.exception("Could not persist assistant response for session %s", payload.session_id)

    return response_payload

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.api:app", host="127.0.0.1", port=8000, reload=True)