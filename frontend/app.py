import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# Page Configuration
st.set_page_config(
    page_title="Stockroom Copilot | Carltren Supply",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

API_BASE_URL = "http://127.0.0.1:8000/api"

# Inject Scoped Custom CSS for High-Contrast Cards & Dark Copilot Panel
st.markdown("""
<style>
    /* Main Background */
    .stApp {
        background-color: #F8FAFC !important;
        color: #0F172A;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }

    /* Brand Header */
    .brand-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-bottom: 12px;
        margin-bottom: 16px;
        border-bottom: 1px solid #E2E8F0;
    }
    .brand-title {
        font-size: 22px;
        font-weight: 800;
        color: #0F172A;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .brand-subtitle {
        font-size: 13px;
        color: #64748B;
    }
    .badge-mcp {
        background-color: #DCFCE7;
        color: #15803D;
        font-size: 12px;
        font-weight: 600;
        padding: 4px 12px;
        border-radius: 16px;
        border: 1px solid #BBF7D0;
    }
    .badge-db {
        background-color: #DBEAFE;
        color: #1D4ED8;
        font-size: 12px;
        font-weight: 600;
        padding: 4px 12px;
        border-radius: 16px;
        border: 1px solid #BFDBFE;
    }

    /* Left Side Metrics Card */
    .metric-card {
        background: #FFFFFF;
        border-radius: 10px;
        padding: 16px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .metric-label {
        font-size: 11px;
        font-weight: 700;
        color: #64748B;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }
    .metric-value {
        font-size: 28px;
        font-weight: 800;
        color: #0F172A;
        margin: 2px 0;
    }
    .metric-subtext {
        font-size: 12px;
        color: #94A3B8;
    }
    .text-critical { color: #DC2626; }

    /* Dark Echo Show Copilot Container Wrapper */
    .copilot-wrapper {
        background-color: #111827;
        border-radius: 14px;
        padding: 18px;
        border: 1px solid #1F2937;
        color: #F9FAFB;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .copilot-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-bottom: 10px;
        border-bottom: 1px solid #1F2937;
        margin-bottom: 12px;
    }

    /* Custom Chat Bubbles in Right Panel */
    .chat-user {
        background-color: #1F2937;
        color: #F9FAFB;
        padding: 10px 14px;
        border-radius: 8px;
        margin-bottom: 8px;
        font-size: 13px;
        border-left: 3px solid #EA580C;
    }
    .chat-assistant {
        background-color: #111827;
        color: #F3F4F6;
        padding: 12px 14px;
        border-radius: 8px;
        margin-bottom: 12px;
        font-size: 13px;
        border: 1px solid #1F2937;
    }

    /* Tool Chips */
    .tool-chip {
        display: inline-block;
        background-color: #1F2937;
        color: #FB923C;
        font-family: monospace;
        font-size: 11px;
        padding: 3px 8px;
        border-radius: 4px;
        margin-right: 4px;
        margin-bottom: 6px;
        border: 1px solid #374151;
    }

    /* Activity Terminal Log */
    .activity-row {
        font-family: monospace;
        font-size: 11px;
        color: #64748B;
        padding: 4px 0;
        border-bottom: 1px dashed #E2E8F0;
    }

    /* Pending Badge */
    .status-pending {
        background-color: #FEF3C7;
        color: #92400E;
        font-size: 11px;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

# API Helpers
def fetch_api(endpoint):
    try:
        res = requests.get(f"{API_BASE_URL}/{endpoint}", timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def post_api(endpoint, data=None):
    try:
        res = requests.post(f"{API_BASE_URL}/{endpoint}", json=data or {}, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

# Brand Header
st.markdown("""
<div class="brand-header">
    <div>
        <div class="brand-title">📦 Stockroom Copilot</div>
        <div class="brand-subtitle">Carltren Supply • Hardware, Fasteners & Building Supplies</div>
    </div>
    <div style="display: flex; gap: 10px;">
        <span class="badge-mcp">● FastMCP Server Active (4 tools)</span>
        <span class="badge-db">● SQLite Sync Active</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Main 2-Column Layout
col_left, col_right = st.columns([1.65, 1.0], gap="large")

# ==========================================
# LEFT COLUMN: DASHBOARD METRICS & TABLES
# ==========================================
with col_left:
    stats = fetch_api("dashboard/stats") or {
        "stockout_risk": {"critical_count": 27, "critical_pct": 5.4},
        "inventory_value": 1481000,
        "open_purchase_orders": {"count": 4, "total_value": 11840},
        "avg_days_of_cover": 26.5
    }

    # 1. Metric Cards
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Stockout Risk</div>
            <div class="metric-value text-critical">{stats['stockout_risk']['critical_count']} <span style="font-size: 14px;">SKUs</span></div>
            <div class="metric-subtext">{stats['stockout_risk']['critical_pct']}% of catalog below lead time</div>
        </div>
        """, unsafe_allow_html=True)

    with m2:
        val_k = round(stats['inventory_value'] / 1000)
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Inventory Value</div>
            <div class="metric-value">${val_k}K</div>
            <div class="metric-subtext">500 SKUs across 6 categories</div>
        </div>
        """, unsafe_allow_html=True)

    with m3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Open Purchase Orders</div>
            <div class="metric-value">{stats['open_purchase_orders']['count']}</div>
            <div class="metric-subtext">${stats['open_purchase_orders']['total_value']:,} awaiting approval</div>
        </div>
        """, unsafe_allow_html=True)

    with m4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Average Days of Cover</div>
            <div class="metric-value">{stats['avg_days_of_cover']}</div>
            <div class="metric-subtext">Target range is 20 to 30 days</div>
        </div>
        """, unsafe_allow_html=True)

    st.write("")

    # 2. Stockout Runway
    st.markdown("#### Stockout runway <span style='font-size: 12px; color: #64748B; font-weight: normal;'>— Days of cover against supplier lead time</span>", unsafe_allow_html=True)
    runway_data = fetch_api("dashboard/runway") or []
    if runway_data:
        for item in runway_data:
            c_name, c_bar, c_val = st.columns([2.5, 4, 1.2])
            with c_name:
                st.markdown(f"<div style='font-size: 13px; font-weight: 600; padding-top: 4px;'>{item['name']}</div>", unsafe_allow_html=True)
            with c_bar:
                pct = min(float(item['days_of_cover']) / 10.0, 1.0)
                st.progress(pct)
            with c_val:
                st.markdown(f"<div style='font-size: 12px; font-family: monospace; color: #475569; text-align: right; padding-top: 4px;'>{item['days_of_cover']}d / {item['lead_time_days']}d</div>", unsafe_allow_html=True)

    st.write("")

    # 3. Inventory Health
    st.markdown("#### Inventory health <span style='font-size: 12px; color: #64748B; font-weight: normal;'>— 500 SKUs in the catalog</span>", unsafe_allow_html=True)
    health = fetch_api("dashboard/health") or {"critical": 27, "warning": 68, "healthy": 307, "overstocked": 98}
    
    h1, h2, h3, h4 = st.columns(4)
    with h1:
        st.markdown(f"<div style='border-left: 4px solid #DC2626; padding-left: 8px;'><div style='font-size: 22px; font-weight: 800;'>{health.get('critical',0)}</div><div style='font-size: 11px; color: #64748B; font-weight: 700;'>CRITICAL</div></div>", unsafe_allow_html=True)
    with h2:
        st.markdown(f"<div style='border-left: 4px solid #EA580C; padding-left: 8px;'><div style='font-size: 22px; font-weight: 800;'>{health.get('warning',0)}</div><div style='font-size: 11px; color: #64748B; font-weight: 700;'>WARNING</div></div>", unsafe_allow_html=True)
    with h3:
        st.markdown(f"<div style='border-left: 4px solid #16A34A; padding-left: 8px;'><div style='font-size: 22px; font-weight: 800;'>{health.get('healthy',0)}</div><div style='font-size: 11px; color: #64748B; font-weight: 700;'>HEALTHY</div></div>", unsafe_allow_html=True)
    with h4:
        st.markdown(f"<div style='border-left: 4px solid #94A3B8; padding-left: 8px;'><div style='font-size: 22px; font-weight: 800;'>{health.get('overstocked',0)}</div><div style='font-size: 11px; color: #64748B; font-weight: 700;'>OVERSTOCKED</div></div>", unsafe_allow_html=True)

    st.write("")
    st.divider()

    # 4. Replenishment Manifest
    st.markdown("#### Replenishment manifest <span style='font-size: 12px; color: #64748B; font-weight: normal;'>— Drafted by the copilot, approved by you</span>", unsafe_allow_html=True)
    manifest_items = fetch_api("dashboard/manifest") or []
    
    if not manifest_items:
        st.info("No pending purchase orders.")
    else:
        th1, th2, th3, th4, th5, th6, th7 = st.columns([1.2, 2.3, 1.8, 0.8, 0.8, 1.1, 1.8])
        th1.markdown("**SKU**")
        th2.markdown("**PRODUCT**")
        th3.markdown("**SUPPLIER**")
        th4.markdown("**STOCK**")
        th5.markdown("**COVER**")
        th6.markdown("**STATUS**")
        th7.markdown("**ACTION**")

        for row in manifest_items:
            r1, r2, r3, r4, r5, r6, r7 = st.columns([1.2, 2.3, 1.8, 0.8, 0.8, 1.1, 1.8])
            r1.caption(row['sku'])
            r2.markdown(f"<div style='font-size: 12px; font-weight: 600;'>{row['product']}</div>", unsafe_allow_html=True)
            r3.caption(row['supplier'])
            r4.markdown(f"<div style='font-size: 12px;'>{row['on_hand'] or 0}</div>", unsafe_allow_html=True)
            r5.markdown(f"<div style='font-size: 12px; color: #DC2626; font-weight: 600;'>{row['days_of_cover']}d</div>", unsafe_allow_html=True)
            r6.markdown("<span class='status-pending'>Pending</span>", unsafe_allow_html=True)
            
            with r7:
                if st.button("Approve", key=f"app_{row['po_number']}", type="primary", use_container_width=True):
                    res = post_api(f"orders/{row['po_number']}/approve")
                    if res and res.get("ok"):
                        st.toast(f"Approved {row['po_number']}!")
                        st.rerun()

            with st.expander(f"🔍 Inspect {row['po_number']} Details & Generate PDF"):
                st.write(f"**Order Total:** ${row['total_cost']:,.2f} | **Reorder Qty:** {row['po_qty']} units")
                st.write(f"**Supplier:** {row['supplier']} | **Stock On Arrival Cover:** {row['days_of_cover']} Days")
                try:
                    pdf_res = requests.get(f"{API_BASE_URL}/orders/{row['po_number']}/pdf")
                    if pdf_res.status_code == 200:
                        st.download_button(
                            label=f"📄 Download {row['po_number']} PDF",
                            data=pdf_res.content,
                            file_name=f"{row['po_number']}.pdf",
                            mime="application/pdf",
                            key=f"pdf_{row['po_number']}"
                        )
                except Exception:
                    st.caption("PDF preview unavailable.")

# ==========================================
# RIGHT COLUMN: DARK ECHO SHOW COPILOT PANEL
# ==========================================
with col_right:
    # Encapsulated Dark Header Card
    st.markdown("""
    <div class="copilot-wrapper">
        <div class="copilot-header">
            <div style="font-size: 16px; font-weight: 700; color: #F9FAFB;">🎙️ Copilot Chat</div>
            <span style="font-size: 10px; font-family: monospace; background-color: #1F2937; color: #94A3B8; padding: 2px 6px; border-radius: 4px;">Alexa+ Simulation • Gemini + FastMCP</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hello! I am your Stockroom Copilot. Ask me plain-English questions like *'What stock will run out before my supplier can deliver?'* or ask me to draft purchase orders."}
        ]

    # Render Chat History
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f"<div class='chat-user'><b>You:</b> {msg['content']}</div>", unsafe_allow_html=True)
        else:
            tools_html = ""
            if "tools" in msg and msg["tools"]:
                tools_html = "".join([f"<span class='tool-chip'>⚙️ {t['tool']}()</span>" for t in msg["tools"]]) + "<br/>"
            st.markdown(f"<div class='chat-assistant'>{tools_html}<b>Copilot:</b><br/>{msg['content']}</div>", unsafe_allow_html=True)

    st.write("")
    st.caption("Quick Queries:")
    q1 = st.button("⚠️ What stock runs out first?", key="btn_q1", use_container_width=True)
    q2 = st.button("📝 Draft orders for the worst ones", key="btn_q2", use_container_width=True)

    user_query = st.chat_input("Ask about stock, orders, or lead times...")
    
    if q1:
        user_query = "What stock will run out before the supplier can deliver?"
    elif q2:
        user_query = "Yes, draft orders for the four worst."

    if user_query:
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.spinner("Executing FastMCP tools..."):
            api_history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages[:-1]]
            response = post_api("chat", {"message": user_query, "history": api_history})
            if response:
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": response.get("reply", "Done."),
                    "tools": response.get("tool_calls", [])
                })
                st.rerun()

    st.divider()

    # Activity Stream
    st.markdown("##### Activity log <span style='font-size: 11px; color: #64748B; font-weight: normal;'>— Real-time MCP tool executions</span>", unsafe_allow_html=True)
    activities = fetch_api("dashboard/activity") or []
    if activities:
        for act in activities:
            st.markdown(f"<div class='activity-row'><code>{act['time']}</code> — {act['summary']}</div>", unsafe_allow_html=True)