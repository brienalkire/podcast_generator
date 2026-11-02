"""Compatibility wrapper for MCP client configs made before v0.3.0 that run
this file. New configs use the `podcast-generator-mcp` command instead."""

from podcast_generator.mcp_server import main

if __name__ == "__main__":
    main()
