import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import sqlite3
import json
import httpx
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from backend.app.database import DB_PATH, get_db_connection
from backend.app.agent import run_agent_loop
from backend.app.pdf_generator import generate_po_pdf

MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "stockroom-secret-token-2026")

app = FastAPI(title="Stockroom Copilot Enterprise API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
async def get_dashboard_stats():
    conn = get_db_connection()
    cursor = conn.cursor()

    risk_row = cursor.execute("""
        SELECT 
            COUNT(*) AS total_skus,
            SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) AS critical_count
        FROM v_inventory_status;
    """).fetchone()

    total_skus = risk_row["total_skus"] or 1
    critical_skus = risk_row["critical_count"] or 0
    critical_pct = round((critical_skus / total_skus) * 100, 1)

    val_row = cursor.execute("SELECT ROUND(SUM(on_hand * unit_cost)) AS total_val FROM v_inventory_status;").fetchone()

    po_row = cursor.execute("""
        SELECT COUNT(*) AS open_count, COALESCE(SUM(total_cost), 0) AS open_val 
        FROM purchase_orders WHERE status = 'pending_review';
    """).fetchone()

    cover_row = cursor.execute("""
        SELECT ROUND(AVG(CASE WHEN days_of_cover > 90 THEN 90 ELSE days_of_cover END), 1) AS avg_cover 
        FROM v_inventory_status WHERE days_of_cover IS NOT NULL;
    """).fetchone()

    conn.close()

    return {
        "stockout_risk": {"critical_count": critical_skus, "critical_pct": critical_pct, "total_skus": total_skus},
        "inventory_value": val_row["total_val"] or 0,
        "open_purchase_orders": {"count": po_row["open_count"], "total_value": po_row["open_val"]},
        "avg_days_of_cover": cover_row["avg_cover"] or 0.0,
    }

@app.get("/api/dashboard/runway")
async def get_stockout_runway():
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT name, days_of_cover, lead_time_days, status
        FROM v_inventory_status
        WHERE status IN ('critical', 'warning')
        ORDER BY (days_of_cover - lead_time_days) ASC
        LIMIT 6;
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/dashboard/health")
async def get_inventory_health():
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute("SELECT status, COUNT(*) as count FROM v_inventory_status GROUP BY status;").fetchall()
    conn.close()
    return {r["status"]: r["count"] for r in rows}

@app.get("/api/dashboard/manifest")
async def get_replenishment_manifest():
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT 
            po.po_number, po.sku, p.name AS product, s.name AS supplier,
            v.on_hand, v.days_of_cover, po.quantity AS po_qty, po.status, po.total_cost
        FROM purchase_orders po
        JOIN products p ON p.sku = po.sku
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        LEFT JOIN v_inventory_status v ON v.sku = po.sku
        WHERE po.status = 'pending_review'
        ORDER BY po.created_at DESC;
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/dashboard/activity")
async def get_activity_log(limit: int = 5):
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT strftime('%H:%M:%S', created_at) as time, summary
        FROM activity_log
        ORDER BY id DESC
        LIMIT ?;
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# --- 2. Human-in-the-Loop Actions & PDF Generation ---

@app.post("/api/orders/{po_number}/approve")
async def approve_order(po_number: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    order = cursor.execute("SELECT * FROM purchase_orders WHERE po_number = ?", (po_number,)).fetchone()
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Purchase order not found.")

    cursor.execute("UPDATE purchase_orders SET status = 'approved', decided_at = CURRENT_TIMESTAMP WHERE po_number = ?;", (po_number,))
    cursor.execute("INSERT INTO activity_log (source, event_type, sku, summary) VALUES ('ui', 'po_approved', ?, ?);",
                   (order["sku"], f"PO Approved: {po_number} for SKU {order['sku']}"))
    conn.commit()
    conn.close()
    return {"ok": True, "message": f"Order {po_number} successfully approved."}

@app.get("/api/orders/{po_number}/pdf")
async def get_order_pdf(po_number: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    order = cursor.execute("""
        SELECT po.po_number, po.sku, p.name AS product, s.name AS supplier,
               po.quantity, po.unit_cost, po.total_cost, po.status,
               po.reason, po.created_at, po.expected_delivery, po.created_by
        FROM purchase_orders po
        JOIN products p ON p.sku = po.sku
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        WHERE po.po_number = ?;
    """, (po_number,)).fetchone()
    conn.close()

    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found.")

    pdf_bytes = generate_po_pdf(dict(order))
    return Response(content=pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename={po_number}.pdf"
    })

# --- 3. Async Agent Chat Endpoint with Persistent Session Memory ---

@app.post("/api/chat")
async def chat_endpoint(payload: ChatRequest):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Load persistent chat history for session_id
    history_rows = cursor.execute(
        "SELECT role, content FROM chat_sessions WHERE session_id = ? ORDER BY id ASC LIMIT 10;",
        (payload.session_id,)
    ).fetchall()
    
    history = [dict(r) for r in history_rows]

    # Save user message
    cursor.execute(
        "INSERT INTO chat_sessions (session_id, role, content) VALUES (?, 'user', ?);",
        (payload.session_id, payload.message)
    )
    conn.commit()

    # Execute Agent Loop
    result = run_agent_loop(payload.message, history)

    # Save assistant message
    cursor.execute(
        "INSERT INTO chat_sessions (session_id, role, content, tools_json) VALUES (?, 'model', ?, ?);",
        (payload.session_id, result["reply"], json.dumps(result.get("tool_calls", [])))
    )
    conn.commit()
    conn.close()

    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.api:app", host="127.0.0.1", port=8000, reload=True)