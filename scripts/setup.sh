#!/usr/bin/env bash
# One-time setup on each laptop. Run from the repo root: bash scripts/setup.sh
set -euo pipefail

echo "== 1/4 Python environment =="
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "ok"

echo "== 2/4 .env =="
if [ ! -f .env ]; then cp .env.example .env && echo "created .env, fill it in"; else echo ".env already exists"; fi

mkdir -p .claude/agents && cp workers/*.md .claude/agents/ && echo "worker roles registered as Claude Code subagents"

echo "== 3/4 MongoDB plugin for Claude Code (Agent Skills + MCP Server) =="
if command -v claude >/dev/null 2>&1; then
  claude plugin install mongodb@claude-plugins-official || echo "plugin install failed, run it by hand inside Claude Code: /plugin install mongodb@claude-plugins-official"
else
  echo "claude CLI not found. Install Claude Code, then run: claude plugin install mongodb@claude-plugins-official"
fi

echo "== 4/4 MongoDB MCP Server connection =="
echo "Run this next and paste your sandbox connection string when asked:"
echo "    npx mongodb-mcp-server@1 setup"
echo
echo "Then verify everything with: bash scripts/dev.sh check"
