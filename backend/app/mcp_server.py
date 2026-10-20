import functools
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from fastmcp import FastMCP

# Ensure parent directory is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from backend.app.database import DB_PATH

# Initialize FastMCP Server matching hackathon specification
mcp = FastMCP("stockroom-copilot")

STATUSES = ("critical", "warning", "healthy", "overstocked")
PO_STATUSES = ("pending_review", "approved", "rejected", "received")
MAX_ORDER_QTY = 1000

# Helper for SQLite connections per request
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

# Automatic Logging Decorator
def log_event(source, event_type, tool_name=None, sku=None, success=True, summary=None, details=None):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO activity_log (source, event_type, tool_name, sku, success, summary, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                source,
                event_type,
                tool_name,
                sku,
                1 if success else 0,
                summary or tool_name,
                json.dumps(details) if details else None,
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Logging error: {e}")

def logged(tool_name):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                log_event(
                    "mcp",
                    "error",
                    tool_name,
                    sku=kwargs.get("sku"),
                    success=False,
                    summary=f"{tool_name} failed",
                    details={"error": str(exc), "args": kwargs},
                )
                return {"ok": False, "error": f"The tool hit an unexpected error: {str(exc)}"}

            summary = result.pop("log_summary", tool_name)
            log_event(
                "mcp",
                "tool_call",
                tool_name,
                sku=kwargs.get("sku"),
                success=bool(result.get("ok", True)),
                summary=summary,
                details={"args": kwargs},
            )
            return result
        return wrapper
    return decorator

# Tool 1: check_inventory_levels
@mcp.tool()
@logged("check_inventory_levels")
def check_inventory_levels(
    query: str | None = None,
    category: str | None = None,
    status: str | None = None,
    below_reorder_point: bool | None = None,
    limit: int = 20,
) -> dict:
    """Look up current stock levels for the store. Use this to answer questions about
    what is in stock, what is below its reorder point, or what is critical, warning,
    healthy, or overstocked. Optional filters: query (matches SKU or product name),
    category, status, below_reorder_point. Returns the lowest days of cover first."""
    limit = max(1, min(limit, 50))
    where, params = [], []

    if query:
        where.append("(sku LIKE ? OR name LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    if category:
        where.append("category LIKE ?")
        params.append(category)
    if status:
        if status not in STATUSES:
            return {"ok": False, "error": "status must be critical, warning, healthy, or overstocked."}
        where.append("status = ?")
        params.append(status)
    if below_reorder_point:
        where.append("on_hand <= reorder_point")

    clause = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_db()
    cursor = conn.cursor()

    total = cursor.execute(f"SELECT COUNT(*) AS n FROM v_inventory_status {clause}", params).fetchone()["n"]

    sql_items = f"""
        SELECT sku, name, category, supplier, lead_time_days, on_hand, reorder_point,
               ROUND(avg_daily_usage, 1) AS avg_daily_usage,
               CAST(days_of_cover AS REAL) AS days_of_cover, status
        FROM v_inventory_status {clause}
        ORDER BY days_of_cover ASC NULLS LAST LIMIT ?
    """
    rows = [dict(r) for r in cursor.execute(sql_items, params + [limit]).fetchall()]

    mix = cursor.execute("SELECT status, COUNT(*) AS n FROM v_inventory_status GROUP BY status").fetchall()
    portfolio = {r["status"]: r["n"] for r in mix}

    conn.close()

    return {
        "ok": True,
        "total_matching": total,
        "returned": len(rows),
        "items": rows,
        "portfolio": portfolio,
        "log_summary": f"check_inventory_levels: {total} matches",
    }

# Tool 2: predict_stockout
@mcp.tool()
@logged("predict_stockout")
def predict_stockout(
    horizon_days: int = 14,
    only_before_delivery: bool = False,
    limit: int = 10,
) -> dict:
    """Find items that will run out soon. An item runs out before delivery when its days of
    cover is less than the supplier lead time. Use this for questions about stockout risk,
    what to reorder, or what is most urgent. Returns the most urgent items first, with
    projected stockout date, days short of lead time, and the suggested order quantity."""
    horizon_days = max(1, min(horizon_days, 60))
    limit = max(1, min(limit, 25))

    if only_before_delivery:
        cond = "v.days_of_cover < v.lead_time_days"
        params = []
    else:
        cond = "(v.days_of_cover < v.lead_time_days OR v.days_of_cover <= ?)"
        params = [horizon_days]

    today_str = datetime.now().strftime("%Y-%m-%d")

    sql = f"""
        SELECT v.sku, v.name, v.supplier, v.lead_time_days, v.on_hand,
               CAST(v.days_of_cover AS REAL) AS days_of_cover,
               ROUND(v.avg_daily_usage, 1) AS avg_daily_usage,
               date('{today_str}', '+' || CAST(CAST(v.days_of_cover AS INT) AS TEXT) || ' days') AS projected_stockout_date,
               CASE WHEN v.days_of_cover < v.lead_time_days THEN 1 ELSE 0 END AS runs_out_before_delivery,
               ROUND(v.lead_time_days - v.days_of_cover, 1) AS days_short,
               v.reorder_qty AS suggested_order_qty,
               EXISTS (SELECT 1 FROM purchase_orders po WHERE po.sku = v.sku AND po.status = ?) AS has_open_po
        FROM v_inventory_status v 
        WHERE v.days_of_cover IS NOT NULL AND {cond}
        ORDER BY (v.lead_time_days - v.days_of_cover) DESC LIMIT ?
    """

    conn = get_db()
    cursor = conn.cursor()

    rows = [dict(r) for r in cursor.execute(sql, ["pending_review"] + params + [limit]).fetchall()]
    at_risk = cursor.execute(
        "SELECT COUNT(*) AS n FROM v_inventory_status WHERE days_of_cover < lead_time_days"
    ).fetchone()["n"]

    conn.close()

    return {
        "ok": True,
        "total_runs_out_before_delivery": at_risk,
        "items": rows,
        "log_summary": f"predict_stockout: {at_risk} at risk",
    }

# Tool 3: trigger_reorder
@mcp.tool()
@logged("trigger_reorder")
def trigger_reorder(sku: str, quantity: int | None = None, reason: str | None = None) -> dict:
    """Draft a purchase order for one SKU. The order is created as pending_review and a human
    must approve it; this tool cannot approve orders. quantity defaults to the product
    standard reorder quantity. If a pending order already exists for the SKU, that order is
    returned instead of creating a duplicate. Include a short reason."""
    sku = sku.strip().upper()
    reason = (reason or "")[:200] or None

    conn = get_db()
    cursor = conn.cursor()

    try:
        item = cursor.execute("SELECT * FROM v_inventory_status WHERE sku = ?", (sku,)).fetchone()
        if item is None:
            conn.close()
            return {"ok": False, "error": f"Unknown SKU {sku}. Check the SKU and try again."}

        qty = quantity if quantity is not None else item["reorder_qty"]
        if qty < 1 or qty > MAX_ORDER_QTY:
            conn.close()
            return {"ok": False, "error": f"Quantity must be between 1 and {MAX_ORDER_QTY}."}

        # Check existing pending PO
        existing = cursor.execute(
            """SELECT po_number, sku, quantity, CAST(total_cost AS REAL) AS total_cost, status,
                      created_at FROM purchase_orders WHERE sku = ? AND status = ?""",
            (sku, "pending_review"),
        ).fetchone()

        if existing:
            conn.close()
            return {
                "ok": True,
                "duplicate": True,
                "message": f"An order for {item['name']} is already waiting for approval.",
                "manifest": dict(existing),
                "log_summary": f"trigger_reorder: duplicate {sku}",
            }

        # Generate PO Number
        cursor.execute("SELECT COUNT(*) + 1046 AS next_id FROM purchase_orders")
        next_po_num = f"PO-{cursor.fetchone()['next_id']}"

        unit_cost = float(item["unit_cost"])
        total_cost = round(qty * unit_cost, 2)
        lead_time = int(item["lead_time_days"])
        exp_del = (datetime.now() + timedelta(days=lead_time)).strftime("%Y-%m-%d")

        cursor.execute(
            """INSERT INTO purchase_orders 
               (po_number, sku, supplier_id, quantity, unit_cost, total_cost, status, created_by, reason, expected_delivery)
               VALUES (?, ?, ?, ?, ?, ?, 'pending_review', 'copilot', ?, ?)""",
            (next_po_num, sku, item["supplier_id"], qty, unit_cost, total_cost, reason, exp_del),
        )
        conn.commit()

        # Fetch freshly inserted PO
        po = dict(
            cursor.execute(
                """SELECT po_number, sku, quantity, status, unit_cost, total_cost, reason, created_at, expected_delivery 
                   FROM purchase_orders WHERE po_number = ?""",
                (next_po_num,),
            ).fetchone()
        )

    except sqlite3.IntegrityError:
        conn.close()
        return {"ok": True, "duplicate": True, "message": "An order for this SKU is already waiting for approval."}

    conn.close()

    avg = float(item["avg_daily_usage"] or 0)
    cover = None
    if avg > 0:
        stock_at_arrival = max(item["on_hand"] - (avg * item["lead_time_days"]), 0)
        cover = round((stock_at_arrival + qty) / avg, 1)

    po["product"] = item["name"]
    po["supplier"] = item["supplier"]

    return {
        "ok": True,
        "duplicate": False,
        "message": f"Created {po['po_number']} for {qty} x {item['name']}.",
        "days_of_cover_after_delivery": cover,
        "manifest": po,
        "log_summary": f"trigger_reorder: {po['po_number']} {sku}",
    }

# Tool 4: list_purchase_orders
@mcp.tool()
@logged("list_purchase_orders")
def list_purchase_orders(status: str | None = None, limit: int = 10) -> dict:
    """List purchase orders, newest first. Use this to answer what is waiting for approval,
    what was approved, and how much pending orders are worth. Optional status filter:
    pending_review, approved, rejected, received."""
    limit = max(1, min(limit, 25))

    if status and status not in PO_STATUSES:
        return {"ok": False, "error": "status must be pending_review, approved, rejected, or received."}

    where = "WHERE po.status = ?" if status else ""
    params = [status] if status else []

    conn = get_db()
    cursor = conn.cursor()

    sql_orders = f"""
        SELECT po.po_number, po.sku, p.name AS product, s.name AS supplier, po.quantity,
               CAST(po.total_cost AS REAL) AS total_cost, po.status, po.reason, po.created_at
        FROM purchase_orders po 
        JOIN products p ON p.sku = po.sku
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        {where}
        ORDER BY po.created_at DESC LIMIT ?
    """
    rows = [dict(r) for r in cursor.execute(sql_orders, params + [limit]).fetchall()]

    pending = cursor.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total_cost), 0) AS value FROM purchase_orders WHERE status = ?",
        ("pending_review",),
    ).fetchone()

    conn.close()

    return {
        "ok": True,
        "orders": rows,
        "pending_count": pending["n"],
        "pending_value": float(pending["value"]),
        "log_summary": f"list_purchase_orders: {len(rows)} rows",
    }

if __name__ == "__main__":
    mcp.run()