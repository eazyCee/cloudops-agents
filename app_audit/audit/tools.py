import os
import json
import dotenv
import sys
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams
dotenv.load_dotenv()
# Add parent directory to path to allow imports from app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def get_gcp_oauth_token():
    """Retrieves a GCP OAuth token."""
    credentials, project_id = google.auth.default(
        scopes=[
            'https://www.googleapis.com/auth/cloud-platform'
            ]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token, project_id

def load_mcp_tools(config_path: str) -> dict:
    """Loads MCP tools based on a configuration file and returns a dict."""
    tools = {}
    if not os.path.exists(config_path):
        print(f"Warning: Config file not found at {config_path}")
        return tools

    try:
        oauth_token, project_id = get_gcp_oauth_token()
        print(project_id)
        HEADERS_WITH_OAUTH = {
            "Authorization": f"Bearer {oauth_token}",
            "x-goog-user-project": project_id
        }

        with open(config_path, 'r') as f:
            config = json.load(f)
            
        for server in config:
            name = server.get("name")
            url = server.get("url")
            auth_type = server.get("auth_type")
            
            if url and not url.startswith("PLACEHOLDER"):
                print(f"Loading MCP server: {name} via HTTP")
                
                headers = {}
                if auth_type == "gcp_oauth":
                    headers = HEADERS_WITH_OAUTH
                
                toolset = MCPToolset(
                    connection_params=StreamableHTTPConnectionParams(
                        url=url,
                        headers=headers,
                        sse_read_timeout=600.0
                    )
                )
                tools[name] = toolset
                print(f"MCP Toolset configured for {name}.")
            else:
                print(f"Skipping {name} due to placeholder URL.")
                    
    except Exception as e:
        print(f"Error loading MCP config: {e}")
        
    return tools

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
