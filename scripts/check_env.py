"""Verifies the laptop is ready. Run: bash scripts/dev.sh check"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()
ok = True


def report(label, passed, hint=""):
    global ok
    ok = ok and passed
    print(("PASS  " if passed else "FAIL  ") + label + ("" if passed else "  -> " + hint))


uri = os.getenv("MONGODB_URI", "")
report("MONGODB_URI set", bool(uri) and "YOUR-SANDBOX" not in uri, "paste the sandbox connection string into .env")
if uri and "YOUR-SANDBOX" not in uri:
    try:
        from pymongo import MongoClient

        MongoClient(uri, serverSelectionTimeoutMS=5000).admin.command("ping")
        report("Atlas reachable", True)
    except Exception as exc:
        report("Atlas reachable", False, str(exc)[:120])

report("VOYAGE_API_KEY set", bool(os.getenv("VOYAGE_API_KEY")), "create a key at dashboard.voyageai.com")
report("VOYAGE_MODEL set", bool(os.getenv("VOYAGE_MODEL")), "pick the current model from the Voyage docs")
report("LLM_API_KEY set", bool(os.getenv("LLM_API_KEY")), "add your LLM key")
report("LLM_MODEL set", bool(os.getenv("LLM_MODEL")), "add the model name")

for module in ("fastapi", "uvicorn", "pymongo", "httpx", "voyageai"):
    try:
        __import__(module)
        report("import " + module, True)
    except ImportError:
        report("import " + module, False, "pip install -r requirements.txt")

sys.exit(0 if ok else 1)
