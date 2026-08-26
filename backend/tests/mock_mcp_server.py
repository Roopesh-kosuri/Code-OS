"""mock_mcp_server.py - Standalone mock stdio MCP server for testing protocol & lifecycle."""
import json
import os
import sys
import time

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock-mcp-server", "version": "1.0.0"}
                }
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "notifications/initialized":
            continue

        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo_read",
                            "description": "Read-only test tool that echoes input",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"message": {"type": "string"}},
                                "required": ["message"]
                            }
                        },
                        {
                            "name": "write_data",
                            "description": "Mutating tool that writes data",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"data": {"type": "string"}},
                                "required": ["data"]
                            }
                        },
                        {
                            "name": "check_env",
                            "description": "Returns current environment keys",
                            "inputSchema": {"type": "object"}
                        },
                        {
                            "name": "generate_large_output",
                            "description": "Generates 120KB of text to test output capping",
                            "inputSchema": {"type": "object"}
                        }
                    ]
                }
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})

            if name == "echo_read":
                msg = args.get("message", "")
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Echo: {msg}"}],
                        "isError": False
                    }
                }
            elif name == "write_data":
                data_val = args.get("data", "")
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Written: {data_val}"}],
                        "isError": False
                    }
                }
            elif name == "check_env":
                env_keys = list(os.environ.keys())
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(env_keys)}],
                        "isError": False
                    }
                }
            elif name == "generate_large_output":
                large_text = "A" * (120 * 1024)  # 120 KB
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": large_text}],
                        "isError": False
                    }
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool '{name}' not found"}
                }

            raw = json.dumps(resp) + "\n"
            sys.stdout.write(raw)
            sys.stdout.flush()

        elif method == "crash":
            sys.exit(1)


if __name__ == "__main__":
    main()
