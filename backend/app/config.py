import os
from pathlib import Path

# Load .env file if it exists (for local development)
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
CLAUDE_MODEL_FAST = os.environ.get("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")
CHROMA_PATH = os.environ.get("CHROMA_PATH", "data/chroma")
CHROMA_COLLECTION = "legal_articles"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
NEXTAUTH_SECRET = os.environ.get("NEXTAUTH_SECRET", "dev-secret-change-me")
