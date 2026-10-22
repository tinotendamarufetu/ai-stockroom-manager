# Stockroom Copilot — Developer Feedback: FastMCP & Agent Infrastructure

## Track: Alexa+ (MCP & Agent Simulation)

### 1. FastMCP & Model Context Protocol (MCP Spec 2025-11-25)
* **What I used it for:** Built a self-hosted Streamable HTTP FastMCP server (`mcp_server.py`) exposing four supply-chain tools (`check_inventory_levels`, `predict_stockout`, `trigger_reorder`, `list_purchase_orders`).
* **What worked well:** Defining tool signatures, docstrings, and JSON output formatting directly via `@mcp.tool()` decorators was clean, declarative, and intuitive.
* **What needs work:** Error reporting during HTTP stream initialization could be more detailed when authorization header mismatches occur.
* **Onboarding Experience:** Smooth. The FastMCP abstraction allowed us to build production tool interfaces with minimal boilerplate.
* **Would we build with it again?** Absolutely. FastMCP is our preferred standard for decoupling agent tool capabilities from host runtime applications.

### 2. Gemini 2.5 API (`google-genai` SDK)
* **What I used it for:** Powered the multi-turn agent execution loop (`agent.py`) using dynamic tool declarations and structured function calling.
* **What worked well:** High execution speed, strong adherence to system instructions, and reliable JSON parameter extraction across tool call chains.
* **What needs work:** Clearer deprecation warnings around explicit chat session function calling vs. model-level auto-function execution.

### 3. Strengths
* **Streamable HTTP Transport:** FastMCP's SSE/Streamable HTTP support made connecting server-side agent tools to a FastAPI/Streamlit architecture straightforward and performant.
* **Tool Schema Registration:** Automatic parameter reflection from Python type hints significantly reduced boilerplate code for tools like `predict_stockout` and `trigger_reorder`.

### 4. Suggestions for SDK Improvement
* **Built-in Async SQLite / Connection Pool Helpers:** Including recommended patterns or middleware for local file-based database pooling would help developers avoid database concurrency issues when bridging FastMCP with web frameworks like FastAPI.
* **Structured Tool Output Schemas:** While returning raw strings or JSON works well, providing native Pydantic schema validation for tool responses would simplify multi-tool agent routing.

### 5. Future Roadmap
* Implementing real-time WebSockets for bidirectional activity stream updates.
* Expanding LLM multi-tool chaining for dynamic lead-time negotiations directly with supplier APIs.