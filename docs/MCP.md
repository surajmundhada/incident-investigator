# Optional read-only MCP interface

The local stdio facade exposes get_saved_investigation, list_application_configurations and search_runbooks. They call the existing API, sharing its retrieval implementation. No incident creation, cancellation, document publication, fault controls, remediation or model invocation is exposed.

The operator supplies a fixed API origin: localhost, 127.0.0.1 or Compose api. Tools cannot pass arbitrary URLs, routes or methods. SearchRequest validates runbook scope; investigation IDs are checked before constructing a path. HTTP calls have timeouts, no redirects/ambient proxies and a 500 KB response bound. Unavailable, oversized and malformed results remain explicit failures.

Outputs receive best-effort recognised-pattern credential redaction and an untrusted_reference_data label. This does not guarantee all secrets are removed. A client authorized to launch the subprocess can read the local workspace; this is not tenant authentication. The investigator's internal agent keeps its narrower incident/dependency scope and does not call its tools through MCP.

MCP adds interoperability, not diagnosis quality. Read-only annotations are hints; code owns the route allowlist. The implementation uses MCP Python SDK 2.3.0 and stdio, with no added listening port. See [SDK tools](https://py.sdk.modelcontextprotocol.io/servers/tools/) and [running a local server](https://py.sdk.modelcontextprotocol.io/run/).

With optional SDK dependencies installed, run scripts/start-mcp.ps1. A host may instead launch the project Python with `-u -m investigator.mcp_server`, PYTHONPATH pointing to backend and MCP_API_BASE_URL=http://127.0.0.1:8001. The launcher does not read .env or print setup text onto the wire. This project does not change the user's installed MCP clients automatically.

Install with `python -m pip install -r requirements-mcp.lock`. Eleven checks passed on Windows, including the real SDK in memory and a subprocess stdio exchange with a local HTTP fixture. A separate connected stdio smoke discovered the three tools, read real registered configurations and a saved synthetic case, and retrieved six runbook hits from the running API. It created no incident and made zero model calls. SDK testing exposed missing structured content for a bare dict return; explicit Pydantic response models now provide the output contract. Third-party host configuration, OAuth and network MCP hosting remain separate. See STATUS.md and scripts/verify_mcp.py.
