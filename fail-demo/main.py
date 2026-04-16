import os
import sys
import http.server
import socketserver

# Check for environment variable
REQUIRED_VAR = "REQUIRED_CONFIG"

print(f"Checking for environment variable: {REQUIRED_VAR}")

if REQUIRED_VAR not in os.environ:
    print(f"CRITICAL ERROR: Environment variable {REQUIRED_VAR} is missing!", file=sys.stderr)
    print("This service will now fail to start.", file=sys.stderr)
    sys.exit(1)

print(f"Successfully started! {REQUIRED_VAR} is set to: {os.environ[REQUIRED_VAR]}")

PORT = int(os.environ.get("PORT", 8080))
Handler = http.server.SimpleHTTPRequestHandler

print(f"Starting dummy server on port {PORT}")
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    httpd.serve_forever()
