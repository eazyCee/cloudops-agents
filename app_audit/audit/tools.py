import os
import json
import sys
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams
dotenv.load_dotenv()
# Add parent directory to path to allow imports from app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.tools import load_mcp_tools, get_project_id

# Initialize GitHub MCP toolset
github_toolset = MCPToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://api.githubcopilot.com/mcp/",
        headers={
            "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN')}",
            "X-MCP-Toolsets": "all",
            "X-MCP-Readonly": "true"
        }
    )
)

# Path to config file in app directory
config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_config.json")
mcp_toolsets = load_mcp_tools(config_file)

# Expose toolsets for the agent
gke_toolset = mcp_toolsets.get("gke")
