# mcp_server.py
"""Stockroom Copilot MCP server (FastMCP) - five read/draft inventory tools.

Run standalone over Streamable HTTP (for MCP Inspector and the hackathon demo):
    python -m backend.app.mcp_server        (serves http://127.0.0.1:8001/mcp)
"""
import functools
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta

from fastmcp import FastMCP

# Ensure the repo root is importable when this file is run directly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from backend.app.database import db_connection, get_db_connection

logger = logging.getLogger(__name__)

mcp = FastMCP("stockroom-copilot")

STATUSES = ("critical", "warning", "healthy", "overstocked")
PO_STATUSES = ("pending_review", "approved", "rejected", "received")
MAX_ORDER_QTY = 1000


def get_db():
    return get_db_connection()


def _as_int(value, default, lo, hi):
    """Models often send numbers as floats or strings (10.0, '5'). Coerce and clamp."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(lo, min(number, hi))


def _clean_text(value, max_len=100):
    if value is None:
        return None
    text = str(value).strip()[:max_len]
    return text or None


# ---------------------------------------------------------------------------
# Activity logging
# ---------------------------------------------------------------------------
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
                    json.dumps(details, default=str) if details else None,
                ),
            )
            conn.commit()
    except Exception:
        logger.exception("Activity logging failed")


def logged(tool_name):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                logger.exception("Tool %s failed", tool_name)
                log_event(
                    "mcp", "error", tool_name,
                    sku=kwargs.get("sku"), success=False,
                    summary=f"{tool_name} failed",
                    details={"error": str(exc), "args": kwargs},
                )
                # Do not leak raw exception text to the model or the user
                return {"ok": False, "error": "The tool hit an unexpected problem. Please try again."}

            summary = result.pop("log_summary", tool_name)
            log_event(
                "mcp", "tool_call", tool_name,
                sku=kwargs.get("sku"),
                success=bool(result.get("ok", True)),
                summary=summary,
                details={"args": kwargs},
            )
            return result
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Tool 1: check_inventory_levels
# ---------------------------------------------------------------------------
@mcp.tool()
@logged("check_inventory_levels")
def check_inventory_levels(
    query: str | None = None,
    category: str | None = None,
    status: str | None = None,
    below_reorder_point: bool | None = None,
    limit: int = 20,
) -> dict:
    """Look up current stock: quantity on hand, days of cover, reorder point and health status.

    Use this for: stock levels for a category (for example Electrical), how many of a product
    are on hand, items below their reorder point, or items that are healthy or overstocked.
    Filters: query (SKU or product name text), category (keyword such as Electrical, Plumbing,
    Paint), status (critical, warning, healthy, overstocked), below_reorder_point.

    Not for ranking stockout risk (use predict_stockout), supplier details (use
    get_supplier_info), or purchase orders (use list_purchase_orders or trigger_reorder).
    Read-only."""
    limit = _as_int(limit, 20, 1, 50)
    query = _clean_text(query)
    category = _clean_text(category)
    status = _clean_text(status)
    status = status.lower() if status else None

    where, params = [], []
    if query:
        where.append("(sku LIKE ? OR name LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    if category:
        where.append("category LIKE ?")
        params.append(f"%{category}%")
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

        rows = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT sku, name, category, supplier, lead_time_days, on_hand, reorder_point,
                       ROUND(avg_daily_usage, 1) AS avg_daily_usage,
                       CAST(days_of_cover AS REAL) AS days_of_cover, status
                FROM v_inventory_status {clause}
                ORDER BY days_of_cover ASC NULLS LAST LIMIT ?
                """,
                params + [limit],
            ).fetchall()
        ]

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


# ---------------------------------------------------------------------------
# Tool 2: predict_stockout
# ---------------------------------------------------------------------------
@mcp.tool()
@logged("predict_stockout")
def predict_stockout(
    horizon_days: int = 14,
    only_before_delivery: bool = False,
    limit: int = 10,
) -> dict:
    """Rank products that will run out before their supplier can deliver.

    An item is at risk when its days of cover is less than its supplier lead time. Use this for
    questions like: what will stock out, which SKUs are at risk, what is most urgent, what are
    the worst items. Returns the most urgent items first with projected stockout date, days
    short of lead time, suggested order quantity and whether a purchase order is already open.
    Set only_before_delivery to true to list only items already below their lead time.

    Not for plain stock lookups (use check_inventory_levels), supplier details (use
    get_supplier_info), or creating orders (use trigger_reorder). Read-only."""
    horizon_days = _as_int(horizon_days, 14, 1, 60)
    limit = _as_int(limit, 10, 1, 25)
    only_before_delivery = bool(only_before_delivery)

    if only_before_delivery:
        cond, params = "v.days_of_cover < v.lead_time_days", []
    else:
        cond, params = "(v.days_of_cover < v.lead_time_days OR v.days_of_cover <= ?)", [horizon_days]

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

    for row in rows:
        row["runs_out_before_delivery"] = bool(row["runs_out_before_delivery"])
        row["has_open_po"] = bool(row["has_open_po"])

    return {
        "ok": True,
        "total_runs_out_before_delivery": at_risk,
        "returned": len(rows),
        "items": rows,
        "log_summary": f"predict_stockout: {at_risk} at risk",
    }


# ---------------------------------------------------------------------------
# Tool 3: trigger_reorder
# ---------------------------------------------------------------------------
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


@mcp.tool()
@logged("trigger_reorder")
def trigger_reorder(sku: str, quantity: int | None = None, reason: str | None = None) -> dict:
    """Create ONE draft purchase order (status pending_review) for ONE SKU.

    Use this only when the owner explicitly asks to draft, create or place an order. The sku must
    come from a predict_stockout or check_inventory_levels result. quantity defaults to the
    product's standard reorder quantity. If a pending order already exists for the SKU, that
    order is returned instead of creating a duplicate. This tool cannot approve orders; a human
    approves them in the dashboard."""
    sku = (_clean_text(sku, 40) or "").upper()
    reason = _clean_text(reason, 200)
    if not sku:
        return {"ok": False, "status": "error", "error": "A SKU is required."}
    if quantity is not None:
        quantity = _as_int(quantity, 0, -10**9, 10**9)

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        item = conn.execute("SELECT * FROM v_inventory_status WHERE sku = ?;", (sku,)).fetchone()
        if item is None:
            return {"ok": False, "status": "error", "error": f"Unknown SKU {sku}. Check the SKU and try again."}

        qty = quantity if quantity is not None else item["reorder_qty"]
        if qty < 1 or qty > MAX_ORDER_QTY:
            return {
                "ok": False, "status": "error",
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
            return {
                "ok": True, "status": "success", "duplicate": True,
                "message": f"An order for {item['name']} is already waiting for approval.",
                "manifest": po,
                "markdown_table": _reorder_markdown_table(po),
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
                "SELECT 1 FROM purchase_orders WHERE po_number = ?;", (candidate,)
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
            "ok": False, "status": "error",
            "error": "An order could not be created because a matching pending order already exists.",
        }
    finally:
        try:
            conn.rollback()  # no-op after a commit; discards any open transaction on early returns
        except sqlite3.Error:
            pass
        conn.close()

    avg = float(item["avg_daily_usage"] or 0)
    cover = None
    if avg > 0:
        stock_at_arrival = max(item["on_hand"] - (avg * item["lead_time_days"]), 0)
        cover = round((stock_at_arrival + qty) / avg, 1)

    return {
        "ok": True, "status": "success", "duplicate": False,
        "message": f"Created {po['po_number']} for {qty} x {item['name']}.",
        "days_of_cover_after_delivery": cover,
        "manifest": po,
        "markdown_table": _reorder_markdown_table(po),
        "log_summary": f"trigger_reorder: {po['po_number']} {sku}",
    }


# ---------------------------------------------------------------------------
# Tool 4: get_supplier_info
# ---------------------------------------------------------------------------
@mcp.tool()
@logged("get_supplier_info")
def get_supplier_info(
    sku: str | None = None,
    name: str | None = None,
    limit: int = 10,
) -> dict:
    """Look up supplier contact email, lead time in days, reliability score and product count.

    Use this when the owner asks about a supplier (for example Summit Paint Co), a supplier's
    lead time or reliability, who supplies a SKU, or wants a supplier list. Filter by name (part
    of the supplier name) or sku.

    Not for stockout risk (use predict_stockout), stock quantities (use check_inventory_levels),
    or purchase orders. Read-only."""
    limit = _as_int(limit, 10, 1, 50)
    sku = _clean_text(sku, 40)
    name = _clean_text(name)

    conditions, params = [], []
    if sku:
        conditions.append("p.sku = ?")
        params.append(sku.upper())
    if name:
        conditions.append("s.name LIKE ?")
        params.append(f"%{name}%")
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
        "returned": len(suppliers),
        "suppliers": suppliers,
        "log_summary": f"get_supplier_info: {len(suppliers)} suppliers",
    }


# ---------------------------------------------------------------------------
# Tool 5: list_purchase_orders
# ---------------------------------------------------------------------------
@mcp.tool()
@logged("list_purchase_orders")
def list_purchase_orders(status: str | None = None, limit: int = 10) -> dict:
    """List existing purchase orders, newest first, plus the pending-approval count and value.

    Use this for: what is waiting for approval, which orders are pending, what was approved, or
    the current PO queue. Optional status filter: pending_review, approved, rejected, received.

    Not for creating orders (use trigger_reorder) or stockout analysis (use predict_stockout).
    Read-only."""
    limit = _as_int(limit, 10, 1, 25)
    status = _clean_text(status)
    status = status.lower() if status else None

    if status and status not in PO_STATUSES:
        return {"ok": False, "error": "status must be pending_review, approved, rejected, or received."}

    where = "WHERE po.status = ?" if status else ""
    params = [status] if status else []

    conn = get_db()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT po.po_number, po.sku, p.name AS product, s.name AS supplier, po.quantity,
                       CAST(po.total_cost AS REAL) AS total_cost, po.status, po.reason, po.created_at
                FROM purchase_orders po
                JOIN products p ON p.sku = po.sku
                JOIN suppliers s ON s.supplier_id = po.supplier_id
                {where}
                ORDER BY po.created_at DESC, po.po_number DESC LIMIT ?
                """,
                params + [limit],
            ).fetchall()
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
        "returned": len(rows),
        "orders": rows,
        "pending_count": pending["n"],
        "pending_value": float(pending["value"]),
        "log_summary": f"list_purchase_orders: {len(rows)} rows",
    }


if __name__ == "__main__":
    # Streamable HTTP so MCP Inspector (and judges) can connect; the API uses port 8000.
    mcp.run(transport="http", host="127.0.0.1", port=int(os.getenv("MCP_PORT", "8001")))