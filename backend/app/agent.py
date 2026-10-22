import os
import logging
import re
import dotenv
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

dotenv.load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Supported model string for google-genai SDK
MODEL_NAME = "gemini-2.5-flash"

EXECUTIVE_SYSTEM_INSTRUCTION = """
You are Stockroom Copilot, an AI supply chain analyst for Carltren Supply (hardware and building supplies).
Your role is to analyze inventory risks against supplier lead times and draft purchase orders for human authorization.

STRICT FORMATTING & STYLE RULES FOR EXECUTIVE OUTPUTS:
1. Tone: Concise, professional, data-driven, and authoritative.
2. Structure: Always structure responses using Markdown headings (###), bold key metrics, bullet points, and clean tables for multiple items.
3. Tables: When listing products, stockouts, or purchase orders, format them into GitHub-flavored Markdown tables containing:
   - SKU
   - Product Name
   - Supplier & Lead Time
   - Stock / Cover
   - Suggested Action / Financial Cost
4. Reorder Guidance: When calling `trigger_reorder`, provide an Executive Reorder Summary table showing the drafted PO number, line item, supplier, quantity, unit cost, total cost, and estimated delivery days. Include a bold **Total Financial Commitment** summary line.
5. Action Required: Always explicitly inform the user that drafted purchase orders are set to 'pending_review' and require human approval via the Replenishment Manifest interface on their dashboard.
6. Safety Boundary: Never pretend to approve or complete orders yourself. Emphasize that final approval rests with the human user.
"""

# ==========================================
# 🛡️ GUARDRAILS LAYER
# ==========================================

SUSPICIOUS_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"system\s*prompt",
    r"drop\s+table",
    r"delete\s+from",
    r"update\s+products",
    r"alter\s+table",
    r"eval\(",
    r"<script>",
]

def validate_input(user_message: str) -> tuple[bool, str | None]:
    clean_msg = user_message.lower().strip()
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, clean_msg):
            return False, "⚠️ **Security Guardrail Triggered:** Input contains restricted administrative keywords or prompt modification attempts. Please rephrase your query."
    if len(user_message) > 1000:
        return False, "⚠️ **Input Guardrail Triggered:** Message exceeds the maximum length of 1,000 characters."
    return True, None

def validate_output(reply_text: str, executed_tools: list) -> str:
    if not reply_text:
        return "Completed analysis."
    reorder_called = any(
        t.get("tool") == "trigger_reorder" and t.get("status", "success") == "success"
        for t in executed_tools
    )
    if reorder_called:
        disclaimer = "\n\n⚠️ **Action Required:** Purchase orders have been drafted with status `pending_review`. Final approval must be authorized by a human operator in the **Replenishment Manifest** panel."
        if "pending_review" not in reply_text.lower() and "replenishment manifest" not in reply_text.lower():
            reply_text += disclaimer
    return reply_text



# ==========================================
# 📝 ACTIVITY LOGGING
# ==========================================
def log_mcp_execution(tool_name: str, status: str, summary: str):
    """Record agent-side executions using the current activity_log schema."""
    from backend.app.database import db_connection

    try:
        with db_connection() as conn:
            conn.execute(
                """
                INSERT INTO activity_log
                    (source, event_type, tool_name, success, summary, created_at)
                VALUES ('mcp', 'tool_call', ?, 1, ?, CURRENT_TIMESTAMP);
                """,
                (tool_name, f"{status}: {summary}"),
            )
            conn.commit()
    except Exception:
        logger.exception("Could not log agent execution for %s", tool_name)

# ==========================================
# ⚡ FALLBACK TOOL EXECUTOR (ZERO-RISK GUARANTEE)
# ==========================================

def execute_fallback_response(user_message: str) -> dict:
    """Run safe local tools and return a deterministic Markdown response."""
    from backend.app.mcp_server import (
        get_supplier_info,
        list_purchase_orders,
        predict_stockout,
        trigger_reorder,
    )

    message = user_message.lower()
    requested_numbers = re.findall(r"\b\d+\b", message)
    limit = max(1, min(int(requested_numbers[0]), 25)) if requested_numbers else 5
    calls = []

    def run_tool(name, tool, **arguments):
        result = tool(**arguments)
        calls.append({
            "tool": name,
            "args": arguments,
            "status": "success" if result.get("ok") else "error",
            "result": result,
        })
        return result

    def cell(value):
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")

    def failure_reply(title, result):
        return {
            "reply": (
                f"### {title}\n\n"
                "| Status | Details |\n|---|---|\n"
                f"| Not completed | {cell(result.get('error') or 'The tool failed. Please retry.')} |"
            ),
            "tool_calls": calls,
            "status": "error",
        }

    if "supplier" in message:
        result = run_tool("get_supplier_info", get_supplier_info, limit=limit)
        if not result.get("ok"):
            return failure_reply("Supplier lookup unavailable", result)
        suppliers = result.get("suppliers", [])
        rows = "\n".join(
            f"| {cell(row.get('name'))} | {cell(row.get('contact_email'))} | "
            f"{cell(row.get('lead_time_days'))} days | {cell(row.get('reliability'))} |"
            for row in suppliers
        ) or "| No supplier records found. | | | |"
        return {
            "reply": "### Supplier information\n\n| Supplier | Contact | Lead time | Reliability |\n"
            "|---|---|---:|---:|\n" + rows,
            "tool_calls": calls,
        }

    if any(
        phrase in message
        for phrase in ("draft", "reorder", "restock", "create order", "place order")
    ):
        risks = run_tool(
            "predict_stockout",
            predict_stockout,
            only_before_delivery=True,
            limit=limit,
        )
        if not risks.get("ok"):
            return failure_reply("Reorder request not completed", risks)
        items = risks.get("items", [])
        orders = []
        for item in items:
            order_result = run_tool(
                "trigger_reorder",
                trigger_reorder,
                sku=item["sku"],
                quantity=item.get("suggested_order_qty"),
                reason="Stockout projected before supplier delivery.",
            )
            if order_result.get("ok") and order_result.get("manifest"):
                orders.append(order_result["manifest"])

        table = ["| PO Number | SKU | Product | Supplier | Qty | Total Cost |",
                 "|---|---|---|---|---:|---:|"]
        table.extend(
            f"| {cell(order.get('po_number'))} | {cell(order.get('sku'))} | "
            f"{cell(order.get('product'))} | {cell(order.get('supplier'))} | "
            f"{cell(order.get('quantity'))} | ${float(order.get('total_cost') or 0):,.2f} |"
            for order in orders
        )
        if not orders:
            table.append("| No eligible at-risk items found. | | | | | |")
        total = sum(float(order.get("total_cost") or 0) for order in orders)
        reply = (
            "### Executive Reorder Summary\n\n"
            f"Drafted or matched **{len(orders)}** pending purchase orders:\n\n"
            + "\n".join(table)
            + f"\n\n**Total Financial Commitment:** **${total:,.2f}**"
        )
        failed_orders = sum(call.get("status") == "error" for call in calls[1:])
        if failed_orders:
            reply += (
                f"\n\n**Warning:** {failed_orders} order(s) could not be drafted. "
                "Review the tool status and retry."
            )
        if orders:
            reply += (
                "\n\nPurchase orders remain `pending_review` and require human approval "
                "in the **Replenishment Manifest**."
            )
        return {"reply": reply, "tool_calls": calls}

    if any(word in message for word in ("stock", "run out", "deliver", "critical", "sku", "worst")):
        result = run_tool(
            "predict_stockout",
            predict_stockout,
            horizon_days=14,
            limit=limit,
        )
        if not result.get("ok"):
            return failure_reply("Stockout report unavailable", result)
        items = result.get("items", [])
        rows = "\n".join(
            f"| {cell(item.get('sku'))} | {cell(item.get('name'))} | "
            f"{cell(item.get('supplier'))} | {cell(item.get('lead_time_days'))}d | "
            f"{cell(item.get('days_of_cover'))}d |"
            for item in items
        ) or "| No stockout risks found. | | | | |"
        return {
            "reply": "### Stockout risk report\n\n"
            "| SKU | Product | Supplier | Lead time | Days of cover |\n"
            "|---|---|---|---:|---:|\n" + rows,
            "tool_calls": calls,
        }

    result = run_tool(
        "list_purchase_orders",
        list_purchase_orders,
        status="pending_review",
        limit=limit,
    )
    if not result.get("ok"):
        return failure_reply("Purchase order lookup unavailable", result)
    orders = result.get("orders", [])
    rows = "\n".join(
        f"| {cell(order.get('po_number'))} | {cell(order.get('sku'))} | "
        f"{cell(order.get('product'))} | {cell(order.get('supplier'))} | "
        f"${float(order.get('total_cost') or 0):,.2f} |"
        for order in orders
    ) or "| No pending purchase orders. | | | | |"
    return {
        "reply": "### Pending purchase orders\n\n"
        "| PO Number | SKU | Product | Supplier | Total Cost |\n"
        "|---|---|---|---|---:|\n" + rows,
        "tool_calls": calls,
    }

# ==========================================
# 🤖 AGENT CONVERSATION LOOP
# ==========================================

def run_agent_loop(user_message: str, history: list | None = None) -> dict:
    # 1. Run Input Guardrail Check
    is_valid, guardrail_error = validate_input(user_message)
    if not is_valid:
        return {"reply": guardrail_error, "tool_calls": []}

    if not client:
        return execute_fallback_response(user_message)

    from backend.app.mcp_server import (
        check_inventory_levels,
        get_supplier_info,
        predict_stockout,
        trigger_reorder,
        list_purchase_orders,
    )

    tools_map = {
        "check_inventory_levels": check_inventory_levels,
        "get_supplier_info": get_supplier_info,
        "predict_stockout": predict_stockout,
        "trigger_reorder": trigger_reorder,
        "list_purchase_orders": list_purchase_orders,
    }

    tool_declarations = [
        check_inventory_levels,
        get_supplier_info,
        predict_stockout,
        trigger_reorder,
        list_purchase_orders,
    ]

    executed_tool_calls = []

    try:
        chat_history = [
            types.Content(
                role="user" if item.get("role") == "user" else "model",
                parts=[types.Part.from_text(text=item.get("content", ""))],
            )
            for item in (history or [])[-2:]
        ]
        chat = client.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=EXECUTIVE_SYSTEM_INSTRUCTION,
                tools=tool_declarations,
                temperature=0.1,
            ),
            history=chat_history,
        )

        response = chat.send_message(user_message)

        rounds = 0
        max_rounds = 6

        while response.function_calls and rounds < max_rounds:
            rounds += 1
            for function_call in response.function_calls:
                fn_name = function_call.name
                fn_args = dict(function_call.args) if function_call.args else {}

                executed_tool_calls.append({"tool": fn_name, "args": fn_args})

                if fn_name in tools_map:
                    try:
                        tool_result = tools_map[fn_name](**fn_args)
                    except Exception as e:
                        tool_result = {"ok": False, "error": str(e)}
                else:
                    tool_result = {"ok": False, "error": f"Tool {fn_name} not recognized."}

                executed_tool_calls[-1]["status"] = (
                    "success" if tool_result.get("ok", True) else "error"
                )
                executed_tool_calls[-1]["result"] = tool_result
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": tool_result}
                    )
                )

        if response.function_calls:
            logger.warning("Agent reached its tool-call limit; using the local workflow fallback.")
            return run_agent_workflow(user_message)

        raw_reply = response.text or (
            "### Copilot response\n\n"
            "| Status | Details |\n|---|---|\n"
            "| No response | The model did not return an answer. Please retry. |"
        )
        final_reply = validate_output(raw_reply, executed_tool_calls)

        return {
            "reply": final_reply,
            "tool_calls": executed_tool_calls
        }

    except Exception:
        logger.exception("Gemini execution failed; using the local workflow fallback.")
        return run_agent_workflow(user_message)


# ==========================================
# 🛡️ SAFE FALLBACK EXECUTION WRAPPER
# ==========================================
# In backend/app/agent.py

def run_agent_workflow(user_message: str) -> dict:
    """Run local tool-backed fallback without claiming actions that did not complete."""
    try:
        return execute_fallback_response(user_message)
    except Exception:
        logger.exception("Local workflow fallback failed.")
        return {
            "reply": (
                "### Copilot is temporarily unavailable\n\n"
                "| Status | Details |\n|---|---|\n"
                "| Not completed | The request could not be processed. Please try again. |"
            ),
            "tool_calls": [],
            "status": "error",
        }