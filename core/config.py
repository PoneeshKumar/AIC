"""Shared settings. Every module reads config from here, never from os.environ directly."""
import os

from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "coldtrace")

VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")

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
