import sqlite3
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "stockroom.db"

def get_db_connection():
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enable Foreign Keys & Write-Ahead Logging (WAL) for high-concurrency shared state
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Suppliers
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        lead_time_days INTEGER NOT NULL,
        contact_email TEXT,
        reliability REAL DEFAULT 0.95
    );
    """)

    # 2. Products
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        sku TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        zone TEXT NOT NULL,
        supplier_id INTEGER NOT NULL,
        unit_cost REAL NOT NULL,
        reorder_qty INTEGER NOT NULL,
        active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
    );
    """)

    # 3. Inventory
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        sku TEXT PRIMARY KEY,
        on_hand INTEGER NOT NULL,
        reorder_point INTEGER NOT NULL,
        safety_stock INTEGER NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sku) REFERENCES products(sku)
    );
    """)

    # 4. Sales Daily
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales_daily (
        sku TEXT NOT NULL,
        sale_date DATE NOT NULL,
        units_sold INTEGER NOT NULL,
        PRIMARY KEY (sku, sale_date),
        FOREIGN KEY (sku) REFERENCES products(sku)
    );
    """)

    # 5. Purchase Orders
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS purchase_orders (
        po_number TEXT PRIMARY KEY,
        sku TEXT NOT NULL,
        supplier_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_cost REAL NOT NULL,
        total_cost REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending_review',
        created_by TEXT DEFAULT 'copilot',
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        decided_at TIMESTAMP,
        expected_delivery DATE,
        FOREIGN KEY (sku) REFERENCES products(sku),
        FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
    );
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_one_open_po_per_sku 
    ON purchase_orders(sku) 
    WHERE status = 'pending_review';
    """)

    # 6. Activity Log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        event_type TEXT NOT NULL,
        tool_name TEXT,
        sku TEXT,
        success BOOLEAN DEFAULT 1,
        summary TEXT NOT NULL,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 7. Persistent Session Memory Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL, -- 'user' or 'model'
        content TEXT NOT NULL,
        tools_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 8. Inventory Status View
    cursor.execute("DROP VIEW IF EXISTS v_inventory_status;")
    cursor.execute("""
    CREATE VIEW v_inventory_status AS
    WITH usage AS (
        SELECT 
            sku, 
            CAST(SUM(units_sold) AS REAL) / 30.0 AS avg_daily_usage
        FROM sales_daily
        WHERE sale_date >= date('now', '-30 days')
        GROUP BY sku
    )
    SELECT
        p.sku, 
        p.name, 
        p.category, 
        p.zone,
        s.supplier_id, 
        s.name AS supplier, 
        s.lead_time_days,
        i.on_hand, 
        i.reorder_point, 
        p.reorder_qty, 
        p.unit_cost,
        COALESCE(u.avg_daily_usage, 0) AS avg_daily_usage,
        CASE 
            WHEN COALESCE(u.avg_daily_usage, 0) = 0 THEN NULL
            ELSE ROUND(i.on_hand / u.avg_daily_usage, 1) 
        END AS days_of_cover,
        CASE
            WHEN COALESCE(u.avg_daily_usage, 0) = 0 THEN 'overstocked'
            WHEN (i.on_hand / u.avg_daily_usage) < s.lead_time_days THEN 'critical'
            WHEN (i.on_hand / u.avg_daily_usage) < (s.lead_time_days + 7) THEN 'warning'
            WHEN (i.on_hand / u.avg_daily_usage) > 90 THEN 'overstocked'
            ELSE 'healthy'
        END AS status
    FROM products p
    JOIN suppliers s ON s.supplier_id = p.supplier_id
    JOIN inventory i ON i.sku = p.sku
    LEFT JOIN usage u ON u.sku = p.sku
    WHERE p.active = 1;
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database schema with WAL mode and persistent session memory initialized!")