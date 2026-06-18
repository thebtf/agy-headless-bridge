# Dockerfile for Glama / generic MCP hosts.
#
# Self-contained: builds and runs WITHOUT Glama's auto build-spec. Test locally:
#   docker build -t mcp-server .
#   docker run -it --rm -e MCP_PROXY_DEBUG=true -e AGY_BRIDGE_TIMEOUT=180 mcp-server
#
# The package is installed system-wide (not into a uv .venv) so `python3 -m ...`
# resolves it directly — this avoids the ModuleNotFoundError that happens when a
# venv install is launched with the global interpreter.
#
# Note: agy_ask / agy_research delegate to Google's Antigravity CLI (`agy`),
# which is a desktop app NOT present in this image. The container is for registry
# introspection / protocol checks (initialize, tools/list), which need no `agy`.

FROM node:24-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# python3 + pip, and the mcp-proxy stdio wrapper Glama uses for introspection.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates \
    && npm install -g mcp-proxy@6.4.3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# pywinpty is win32-only (sys_platform marker in pyproject) -> no Linux deps pulled.
RUN pip3 install --no-cache-dir --break-system-packages .

# mcp-proxy wraps the stdio server so Glama's inspector can introspect it.
CMD ["mcp-proxy", "--", "python3", "-m", "agy_headless_bridge.mcp_server"]
