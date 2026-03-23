import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6-20250514")
CHROMA_PATH = os.environ.get("CHROMA_PATH", "data/chroma")
CHROMA_COLLECTION = "legal_articles"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
