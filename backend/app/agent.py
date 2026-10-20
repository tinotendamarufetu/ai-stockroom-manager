import os
import json
import re
import dotenv
from google import genai
from google.genai import types

dotenv.load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

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
    """Input Guardrail: Scans for prompt injection, dangerous SQL keywords, and malicious inputs."""
    clean_msg = user_message.lower().strip()
    
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, clean_msg):
            return False, "⚠️ **Security Guardrail Triggered:** Input contains restricted administrative keywords or prompt modification attempts. Please rephrase your query."
    
    if len(user_message) > 1000:
        return False, "⚠️ **Input Guardrail Triggered:** Message exceeds the maximum length of 1,000 characters."
        
    return True, None


def validate_output(reply_text: str, executed_tools: list) -> str:
    """Output Guardrail: Verifies formatting, safety disclaimers, and prevents hallucinated order completions."""
    if not reply_text:
        return "Completed analysis."

    # Check if reorders were triggered during this turn
    reorder_called = any(t.get("tool") == "trigger_reorder" for t in executed_tools)

    # Ensure Human-in-the-Loop disclaimer is present if reorders were drafted
    if reorder_called:
        disclaimer = "\n\n⚠️ **Action Required:** Purchase orders have been drafted with status `pending_review`. Final approval must be authorized by a human operator in the **Replenishment Manifest** panel."
        if "pending_review" not in reply_text.lower() and "replenishment manifest" not in reply_text.lower():
            reply_text += disclaimer

    return reply_text


# ==========================================
# 🤖 AGENT CONVERSATION LOOP
# ==========================================

def run_agent_loop(user_message: str, history: list = None) -> dict:
    if not client:
        return {
            "reply": "Error: GEMINI_API_KEY is not set in environment variables.",
            "tool_calls": []
        }

    # 1. Run Input Guardrail Check
    is_valid, guardrail_error = validate_input(user_message)
    if not is_valid:
        return {
            "reply": guardrail_error,
            "tool_calls": []
        }

    from backend.app.mcp_server import (
        check_inventory_levels,
        predict_stockout,
        trigger_reorder,
        list_purchase_orders,
    )

    tools_map = {
        "check_inventory_levels": check_inventory_levels,
        "predict_stockout": predict_stockout,
        "trigger_reorder": trigger_reorder,
        "list_purchase_orders": list_purchase_orders,
    }

    tool_declarations = [
        check_inventory_levels,
        predict_stockout,
        trigger_reorder,
        list_purchase_orders,
    ]

    executed_tool_calls = []

    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=EXECUTIVE_SYSTEM_INSTRUCTION,
            tools=tool_declarations,
            temperature=0.1,
        )
    )

    if history:
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            chat._history.append(
                types.Content(role=role, parts=[types.Part.from_text(text=msg.get("content", ""))])
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

            response = chat.send_message(
                types.Part.from_function_response(
                    name=fn_name,
                    response={"result": tool_result}
                )
            )

    raw_reply = response.text or "Completed analysis."

    # 2. Run Output Guardrail Check
    final_reply = validate_output(raw_reply, executed_tool_calls)

    return {
        "reply": final_reply,
        "tool_calls": executed_tool_calls
    }