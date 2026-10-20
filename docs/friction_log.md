# Stockroom Copilot — Developer Friction Log

### Entry 1: FastMCP Streamable HTTP Bearer Token Injection
* **Task Attempted:** Configuring HTTP Bearer Authentication headers over Streamable HTTP transports in FastMCP.
* **Steps Taken:** Implemented standard Bearer token header validation middleware on FastAPI route mounts.
* **Expected vs. Actual:** Expected FastMCP inspector to auto-prompt for bearer credentials; actual required manual header configuration during transport initialization.
* **Severity Rating:** Medium
* **Workaround Used:** Added explicit header authentication dependency guards in `api.py`.
* **Actionable Suggestion:** Include native Bearer/API Key authentication decorators directly within the `FastMCP()` constructor.

### Entry 2: Concurrent DB Write Locks during Dual API / MCP Access
* **Task Attempted:** Executing background tool calls while UI endpoints simultaneously query dashboard metrics.
* **Steps Taken:** Launched parallel async requests across FastAPI and FastMCP.
* **Expected vs. Actual:** Default SQLite rollback journal threw sporadic `database is locked` exceptions under concurrent tool execution.
* **Severity Rating:** High
* **Workaround Used:** Initialized Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and raised connection timeout limits to 30.0 seconds.
* **Actionable Suggestion:** Default SQLite template guides to WAL mode for multi-threaded agent server architectures.