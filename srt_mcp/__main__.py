"""Entrypoint: `python -m srt_mcp` arranca el servidor MCP por stdio."""

from __future__ import annotations

from srt_mcp.server import main

if __name__ == "__main__":
    main()
