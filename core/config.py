"""Shared settings. Every module reads config from here, never from os.environ directly."""
import os

from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "coldtrace")
MONGODB_TIMEOUT_MS = int(os.getenv("MONGODB_TIMEOUT_MS", "3000"))  # raise it on slow venue wifi

VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "")

LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() in {"1", "true", "yes", "on"}
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "coldtrace")
LANGSMITH_AGENT_ID = os.getenv("LANGSMITH_AGENT_ID", "coldtrace-agent")
LANGSMITH_AGENT_ENVIRONMENT = os.getenv("LANGSMITH_AGENT_ENVIRONMENT", "local")

SERVER_PORT = int(os.getenv("SERVER_PORT", "8100"))
CARRIER_URL = "http://localhost:" + os.getenv("CARRIER_PORT", "8101")
WAREHOUSE_URL = "http://localhost:" + os.getenv("WAREHOUSE_PORT", "8102")
HOSPITAL_URL = "http://localhost:" + os.getenv("HOSPITAL_PORT", "8103")

# Collection names. The shapes are defined in docs/CONTRACTS.md and core/models.py.
SHIPMENTS = "shipments"
RUNS = "runs"
STEPS = "steps"
EVENTS = "events"
MEMORIES = "memories"
WORKERS = "workers"
PROPOSALS = "proposals"
