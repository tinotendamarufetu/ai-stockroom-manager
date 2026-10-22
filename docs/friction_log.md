# Stockroom Copilot — Developer Friction & Architectural Challenges Log

### 1: FastMCP Streamable HTTP Bearer Token Injection
* **Task Attempted:** Configuring HTTP Bearer Authentication headers over Streamable HTTP transports in FastMCP.
* **Steps Taken:** Implemented standard Bearer token header validation middleware on FastAPI route mounts.
* **Expected vs. Actual:** Expected FastMCP inspector to auto-prompt for bearer credentials; actual required manual header configuration during transport initialization.
* **Severity Rating:** Medium
* **Workaround Used:** Added explicit header authentication dependency guards in `api.py`.
* **Actionable Suggestion:** Include native Bearer/API Key authentication decorators directly within the `FastMCP()` constructor.

### 2: Concurrent DB Write Locks during Dual API / MCP Access
* **Task Attempted:** Executing background tool calls while UI endpoints simultaneously query dashboard metrics.
* **Steps Taken:** Launched parallel async requests across FastAPI and FastMCP.
* **Expected vs. Actual:** Default SQLite rollback journal threw sporadic `database is locked` exceptions under concurrent tool execution.
* **Severity Rating:** High
* **Workaround Used:** Initialized Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and raised connection timeout limits to 30.0 seconds.
* **Actionable Suggestion:** Default SQLite template guides to WAL mode for multi-threaded agent server architectures.

### 3. High-Concurrency SQLite File Locking
* **Challenge:** During live demonstration testing, background UI polling (`/api/dashboard/*` endpoints) executing concurrently with human approval POST requests triggered `sqlite3.OperationalError: database is locked` exceptions, causing intermittent HTTP 500 errors in Streamlit.
* **Resolution:** Re-architected SQLite connection handling across `database.py` and `api.py`. Configured Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) alongside a 5000ms busy timeout (`PRAGMA busy_timeout = 5000;`) and exponential backoff retry loops (up to 5 retries) on write operations.

### 4. FastMCP Context & Real-Time Sync
* **Challenge:** Decoupling long-running AI agent execution from immediate HTTP UI responses caused race conditions where drafted purchase orders were not instantly reflected in the dashboard UI.
* **Resolution:** Implemented atomic transaction blocks in `agent.py` that immediately write drafted purchase orders and tool execution logs to `activity_log` before returning the JSON-RPC payload, guaranteeing zero latency between agent chat responses and UI state synchronization.

### 5. Graceful UI Fallbacks for LLM Output Formatting
* **Challenge:** Variations in LLM response structure occasionally omitted Markdown tables during automated tool re-ordering.
* **Resolution:** Implemented a resilient fallback wrapper (`run_agent_workflow`) that intercepts tool outputs and directly queries the active database to construct standardized Markdown tables, ensuring strict UI contract delivery.