#!/usr/bin/env bash
# Small task runner. Usage: bash scripts/dev.sh <command>
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] && . .venv/bin/activate
set -a; [ -f .env ] && . ./.env; set +a
: "${SERVER_PORT:=8100}" "${CARRIER_PORT:=8101}" "${WAREHOUSE_PORT:=8102}" "${HOSPITAL_PORT:=8103}"

case "${1:-help}" in
  check)     python scripts/check_env.py ;;
  carrier)   uvicorn mocks.carrier:app --port "$CARRIER_PORT" --reload ;;
  warehouse) uvicorn mocks.warehouse:app --port "$WAREHOUSE_PORT" --reload ;;
  hospital)  uvicorn mocks.hospital:app --port "$HOSPITAL_PORT" --reload ;;
  mocks)     uvicorn mocks.carrier:app --port "$CARRIER_PORT" &
             uvicorn mocks.warehouse:app --port "$WAREHOUSE_PORT" &
             uvicorn mocks.hospital:app --port "$HOSPITAL_PORT" &
             wait ;;
  server)    uvicorn server.app:app --port "$SERVER_PORT" --reload ;;
  agent)     shift; python -m agent.run "$@" ;;
  seed)      python scripts/seed.py ;;
  test)      pytest -q ;;
  *) echo "commands: check | carrier | warehouse | hospital | mocks | server | agent | seed | test" ;;
esac
