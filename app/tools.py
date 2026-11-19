"""MCP Toolset loader with auto-refreshing GCP OAuth headers.

Fixes token-expiration issues in long-running Cloud Run / Agent Runtime services
by supplying a `header_provider` callback to ADK's `McpToolset` so credentials
are refreshed automatically whenever the 60-minute OAuth token nears expiry.
"""

from __future__ import annotations

import json
import os
from typing import Any

import dotenv

dotenv.load_dotenv()

from .finops_tools import get_fresh_gcp_headers

# Compatible with both google-adk 1.x (MCPToolset) and 2.x (McpToolset)
try:
    from google.adk.tools.mcp_tool import McpToolset as _McpToolset
    from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams
except ImportError:
    try:
        from google.adk.tools.mcp_tool import MCPToolset as _McpToolset
        from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams
    except ImportError:
        _McpToolset = None  # type: ignore
        StreamableHTTPConnectionParams = None  # type: ignore


def _gcp_oauth_header_provider(_readonly_context: Any = None) -> dict[str, str]:
    """Return fresh GCP OAuth headers on every MCP session / request."""
    headers, _ = get_fresh_gcp_headers()
    return {
        "Authorization": headers["Authorization"],
        **(
            {"x-goog-user-project": headers["x-goog-user-project"]}
            if "x-goog-user-project" in headers
            else {}
        ),
    }


def load_mcp_tools(config_path: str) -> dict[str, Any]:
    """Load enabled Google Cloud Remote MCP toolsets from `mcp_config.json`."""
    tools: dict[str, Any] = {}
    if _McpToolset is None or StreamableHTTPConnectionParams is None:
        print(
            "Warning: ADK MCP support is unavailable. Ensure `mcp` is installed "
            "(pip install -r requirements.txt)."
        )
        return tools

    if not os.path.exists(config_path):
        print(f"Warning: MCP config file not found at {config_path}")
        return tools

    disabled_env = {
        s.strip().lower()
        for s in os.environ.get("DISABLED_MCP_SERVERS", "").split(",")
        if s.strip()
    }

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        for server in config:
            name = server.get("name", "")
            url = server.get("url", "")
            auth_type = server.get("auth_type", "")
            enabled = server.get("enabled", True)

            if not enabled or name.lower() in disabled_env:
                print(f"Skipping disabled MCP server: {name}")
                continue

            if not url or url.startswith("PLACEHOLDER"):
                print(f"Skipping {name} due to missing or placeholder URL.")
                continue

            print(f"Configuring MCP server: {name} -> {url}")
            kwargs: dict[str, Any] = {
                "connection_params": StreamableHTTPConnectionParams(
                    url=url,
                    sse_read_timeout=600.0,
                )
            }
            if auth_type == "gcp_oauth":
                kwargs["header_provider"] = _gcp_oauth_header_provider
            tool_filter = server.get("tool_filter")
            if tool_filter:
                kwargs["tool_filter"] = tool_filter

            tools[name] = _McpToolset(**kwargs)
    except Exception as exc:
        print(f"Error loading MCP config: {exc}")

    return tools


config_file = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "mcp_config.json"
)
mcp_toolsets = load_mcp_tools(config_file)

# FinOps & Billing toolsets
recommender_toolset = mcp_toolsets.get("recommender")
billing_toolset = mcp_toolsets.get("billing")
bigquery_toolset = mcp_toolsets.get("bigquery")

# CloudOps & Telemetry toolsets
logging_toolset = mcp_toolsets.get("logging")
monitoring_toolset = mcp_toolsets.get("monitoring")
gke_toolset = mcp_toolsets.get("gke")
compute_toolset = mcp_toolsets.get("compute")
cloudrun_toolset = mcp_toolsets.get("cloudrun")
