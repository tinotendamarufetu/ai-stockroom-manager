# 📦 Stockroom Copilot

An AI supply chain copilot for small hardware and building supply businesses, built for the **Amazon Developer Hackathon (Alexa+ Track)**.

Stockroom Copilot analyzes inventory risks against supplier delivery lead times, predicts stockouts before they hit customer order fulfillment, and drafts purchase orders for human-in-the-loop approval.

---

## 🌟 Key Features
* **Self-Hosted MCP Server (Spec 2025-11-25):** 4 production tools served over Streamable HTTP with Bearer Token protection.
* **Lead-Time Aware Stockout Prediction:** Identifies critical items where `Days of Cover < Supplier Lead Time`.
* **Human-in-the-Loop Safety Boundary:** The agent can draft purchase orders (`pending_review`), but cannot approve them.
* **Interactive Alexa+ Echo Show Simulation:** Streamlit dashboard featuring live inventory KPIs, stockout runway charts, interactive Copilot chat, and PDF PO invoice exports.
* **Input & Output Guardrail Layer:** Active protection against prompt injection, dangerous SQL execution, and unverified order commitments.

---

## 🛠️ Architecture

```text
Streamlit Dashboard (Alexa+ Simulation)
   │ (HTTPS / API)
   ▼
FastAPI Server (Async Endpoints + Bearer Auth)
   │-- /api/*           Metrics, Manifest, PDF Exports
   │-- /api/chat        Gemini 2.5 Flash Agent Loop
   │
   ▼ (Streamable HTTP / Local Call)
FastMCP Server (`mcp_server.py`)
   │-- check_inventory_levels()
   │-- predict_stockout()
   │-- trigger_reorder()
   │-- list_purchase_orders()
   │
   ▼ (Parameterized SQL / WAL Mode)
SQLite Database (`stockroom.db`)

🚀 Quick Start Guide
1. Environment Setup
Bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
2. Configure Environment Variables
Create a .env file in the root folder:

Code snippet
GEMINI_API_KEY=your_gemini_api_key_here
MCP_BEARER_TOKEN=stockroom-secret-token-2026
3. Seed Database
Bash
python backend/seed_data.py
4. Launch Services
Terminal 1 (Backend API):

Bash
python -m backend.app.api
Terminal 2 (Streamlit UI):

Bash
streamlit run frontend/app.py
Open http://localhost:8501 in your browser!

📄 License
Licensed under the MIT License.


---

### Final Launch Checklist before Submission
1. Push code to your public GitHub repository (`stockroom-copilot`).
2. Verify `LICENSE`, `README.md`, `docs/feedback.md`, and `docs/friction_log.md` are present.
3. Record your 3-minute screen demo showing:
   * Copilot answering *"What stock runs out before supplier delivery?"*
   * Tool execution chips appearing (`predict_stockout`, `trigger_reorder`).
   * Inspecting PO details, downloading the PDF invoice, and clicking **Approve** in the Replenishment Manifest.
4. Submit on Devpost under the **Alexa+ Track** and select **Open Source Challenge**.

You built an end-to-end, production-grade AI agent system! Let me know if you need any a