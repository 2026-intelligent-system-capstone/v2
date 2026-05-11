import os
import sys
from pathlib import Path

os.environ["OPENAI_API_KEY"] = ""
os.environ["RAG_ENABLED"] = "false"
os.environ.setdefault("APP_SQLITE_PATH", "data/test-app.db")
os.environ.setdefault("APP_ARTIFACT_DIR", "data/test-artifacts")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
