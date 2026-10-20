# Stockroom Copilot — Amazon Developer Hackathon Product Feedback

## Track: Alexa+ (MCP & Agent Simulation)

### 1. FastMCP & Model Context Protocol (MCP Spec 2025-11-25)
* **What we used it for:** Built a self-hosted Streamable HTTP FastMCP server (`mcp_server.py`) exposing four supply-chain tools (`check_inventory_levels`, `predict_stockout`, `trigger_reorder`, `list_purchase_orders`).
* **What worked well:** Defining tool signatures, docstrings, and JSON output formatting directly via `@mcp.tool()` decorators was clean, declarative, and intuitive.
* **What needs work:** Error reporting during HTTP stream initialization could be more detailed when authorization header mismatches occur.
* **Onboarding Experience:** Smooth. The FastMCP abstraction allowed us to build production tool interfaces with minimal boilerplate.
* **Would we build with it again?** Absolutely. FastMCP is our preferred standard for decoupling agent tool capabilities from host runtime applications.

### 2. Gemini 2.5 API (`google-genai` SDK)
* **What we used it for:** Powered the multi-turn agent execution loop (`agent.py`) using dynamic tool declarations and structured function calling.
* **What worked well:** High execution speed, strong adherence to system instructions, and reliable JSON parameter extraction across tool call chains.
* **What needs work:** Clearer deprecation warnings around explicit chat session function calling vs. model-level auto-function execution.