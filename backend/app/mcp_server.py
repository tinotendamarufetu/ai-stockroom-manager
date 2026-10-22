import functools
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from fastmcp import FastMCP

# Ensure parent directory is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from backend.app.database import db_connection, get_db_connection

# Initialize FastMCP Server matching hackathon specification
mcp = FastMCP("stockroom-copilot")

STATUSES = ("critical", "warning", "healthy", "overstocked")
PO_STATUSES = ("pending_review", "approved", "rejected", "received")
MAX_ORDER_QTY = 1000

# Helper for SQLite connections per request
def get_db():
    return get_db_connection()

# Automatic Logging Decorator
def log_event(source, event_type, tool_name=None, sku=None, success=True, summary=None, details=None):
    try:
        with db_connection() as conn:
            conn.execute(
                """INSERT INTO activity_log
                   (source, event_type, tool_name, sku, success, summary, details, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    source,
                    event_type,
                    tool_name,
                    sku,
                    1 if success else 0,
                    summary or tool_name or event_type,
                    json.dumps(details) if details else None,
                ),
            )
            conn.commit()
    except Exception as e:
        logging.getLogger(__name__).exception("Activity logging failed: %s", e)

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
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM v_inventory_status {clause}", params
        ).fetchone()["n"]

        sql_items = f"""
            SELECT sku, name, category, supplier, lead_time_days, on_hand, reorder_point,
                   ROUND(avg_daily_usage, 1) AS avg_daily_usage,
                   CAST(days_of_cover AS REAL) AS days_of_cover, status
            FROM v_inventory_status {clause}
            ORDER BY days_of_cover ASC NULLS LAST LIMIT ?
        """
        rows = [dict(r) for r in conn.execute(sql_items, params + [limit]).fetchall()]

        mix = conn.execute(
            "SELECT status, COUNT(*) AS n FROM v_inventory_status GROUP BY status"
        ).fetchall()
        portfolio = {r["status"]: r["n"] for r in mix}
    finally:
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
    try:
        rows = [
            dict(r)
            for r in conn.execute(sql, ["pending_review"] + params + [limit]).fetchall()
        ]
        at_risk = conn.execute(
            "SELECT COUNT(*) AS n FROM v_inventory_status WHERE days_of_cover < lead_time_days"
        ).fetchone()["n"]
    finally:
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
    try:
        conn.execute("BEGIN IMMEDIATE;")
        item = conn.execute(
            "SELECT * FROM v_inventory_status WHERE sku = ?;",
            (sku,),
        ).fetchone()
        if item is None:
            return {"ok": False, "status": "error", "error": f"Unknown SKU {sku}. Check the SKU and try again."}

        qty = quantity if quantity is not None else item["reorder_qty"]
        if qty < 1 or qty > MAX_ORDER_QTY:
            return {
                "ok": False,
                "status": "error",
                "error": f"Quantity must be between 1 and {MAX_ORDER_QTY}.",
            }

        existing = conn.execute(
            """
            SELECT po_number, sku, quantity, CAST(total_cost AS REAL) AS total_cost, status,
                   created_at
            FROM purchase_orders
            WHERE sku = ? AND status = ?;
            """,
            (sku, "pending_review"),
        ).fetchone()
        if existing:
            po = dict(existing)
            po.update(product=item["name"], supplier=item["supplier"])
            markdown_table = _reorder_markdown_table(po)
            return {
                "ok": True,
                "status": "success",
                "duplicate": True,
                "message": f"An order for {item['name']} is already waiting for approval.",
                "manifest": po,
                "markdown_table": markdown_table,
                "log_summary": f"trigger_reorder: duplicate {sku}",
            }

        unit_cost = float(item["unit_cost"])
        total_cost = round(qty * unit_cost, 2)
        lead_time = int(item["lead_time_days"])
        expected_delivery = (datetime.now() + timedelta(days=lead_time)).strftime("%Y-%m-%d")
        minute_second = datetime.now().strftime("%M%S")
        po_number = None
        for suffix in range(10_000):
            candidate = f"PO-{minute_second}-{suffix:04d}"
            exists = conn.execute(
                "SELECT 1 FROM purchase_orders WHERE po_number = ?;",
                (candidate,),
            ).fetchone()
            if exists is None:
                po_number = candidate
                break
        if po_number is None:
            raise sqlite3.IntegrityError("Could not allocate a unique PO number.")

        conn.execute(
            """
            INSERT INTO purchase_orders
                (po_number, sku, supplier_id, quantity, unit_cost, total_cost, status,
                 created_by, reason, expected_delivery)
            VALUES (?, ?, ?, ?, ?, ?, 'pending_review', 'copilot', ?, ?);
            """,
            (po_number, sku, item["supplier_id"], qty, unit_cost, total_cost, reason, expected_delivery),
        )
        conn.commit()
        po_row = conn.execute(
            """
            SELECT po_number, sku, quantity, status, unit_cost, total_cost,
                   reason, created_at, expected_delivery
            FROM purchase_orders WHERE po_number = ?;
            """,
            (po_number,),
        ).fetchone()
        po = dict(po_row)
        po.update(product=item["name"], supplier=item["supplier"])
    except sqlite3.IntegrityError:
        conn.rollback()
        return {
            "ok": False,
            "status": "error",
            "error": "An order could not be created because a matching pending order already exists.",
        }
    finally:
        conn.close()

    avg = float(item["avg_daily_usage"] or 0)
    cover = None
    if avg > 0:
        stock_at_arrival = max(item["on_hand"] - (avg * item["lead_time_days"]), 0)
        cover = round((stock_at_arrival + qty) / avg, 1)

    markdown_table = _reorder_markdown_table(po)

    return {
        "ok": True,
        "status": "success",
        "duplicate": False,
        "message": f"Created {po['po_number']} for {qty} x {item['name']}.",
        "days_of_cover_after_delivery": cover,
        "manifest": po,
        "markdown_table": markdown_table,
        "log_summary": f"trigger_reorder: {po['po_number']} {sku}",
    }


def _reorder_markdown_table(order: dict) -> str:
    def cell(value):
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")

    return (
        "| PO Number | SKU | Product | Supplier | Qty | Total Cost |\n"
        "|---|---|---|---|---:|---:|\n"
        f"| {cell(order.get('po_number'))} | {cell(order.get('sku'))} | "
        f"{cell(order.get('product'))} | {cell(order.get('supplier'))} | "
        f"{cell(order.get('quantity'))} | ${float(order.get('total_cost') or 0):,.2f} |"
    )

# Tool 4: get_supplier_info
@mcp.tool()
@logged("get_supplier_info")
def get_supplier_info(
    sku: str | None = None,
    name: str | None = None,
    limit: int = 10,
) -> dict:
    """Look up supplier contact details, lead times, reliability, and stocked products."""
    limit = max(1, min(limit, 50))
    conditions = []
    params = []
    if sku:
        conditions.append("p.sku = ?")
        params.append(sku.strip().upper())
    if name:
        conditions.append("s.name LIKE ?")
        params.append(f"%{name.strip()}%")
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    conn = get_db()
    try:
        rows = conn.execute(
            f"""
            SELECT s.supplier_id, s.name, s.contact_email, s.lead_time_days,
                   s.reliability, COUNT(DISTINCT p.sku) AS product_count
            FROM suppliers s
            LEFT JOIN products p ON p.supplier_id = s.supplier_id AND p.active = 1
            {where}
            GROUP BY s.supplier_id, s.name, s.contact_email, s.lead_time_days, s.reliability
            ORDER BY s.name
            LIMIT ?;
            """,
            params + [limit],
        ).fetchall()
    finally:
        conn.close()

    suppliers = [dict(row) for row in rows]
    return {
        "ok": True,
        "suppliers": suppliers,
        "log_summary": f"get_supplier_info: {len(suppliers)} suppliers",
    }


# Tool 5: list_purchase_orders
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
    try:
        sql_orders = f"""
            SELECT po.po_number, po.sku, p.name AS product, s.name AS supplier, po.quantity,
                   CAST(po.total_cost AS REAL) AS total_cost, po.status, po.reason, po.created_at
            FROM purchase_orders po
            JOIN products p ON p.sku = po.sku
            JOIN suppliers s ON s.supplier_id = po.supplier_id
            {where}
            ORDER BY po.created_at DESC, po.po_number DESC LIMIT ?
        """
        rows = [
            dict(row)
            for row in conn.execute(sql_orders, params + [limit]).fetchall()
        ]
        pending = conn.execute(
            """
            SELECT COUNT(*) AS n, COALESCE(SUM(total_cost), 0) AS value
            FROM purchase_orders WHERE status = ?;
            """,
            ("pending_review",),
        ).fetchone()
    finally:
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