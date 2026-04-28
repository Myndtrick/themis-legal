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

# AI Command Center — all AI calls route through this proxy
AICC_KEY = os.environ.get("AICC_KEY", "")
AICC_BASE_URL = os.environ.get(
    "AICC_BASE_URL",
    "https://aicommandcenter-production-d7b1.up.railway.app/v1",
)

# Shared secret between AICC scheduler and Themis webhook endpoints.
# AICC signs each scheduled POST with HMAC-SHA256(body, secret) in X-AICC-Signature.
AICC_SCHEDULER_SECRET = os.environ.get("AICC_SCHEDULER_SECRET", "")

# AICC short-form model names (NOT provider-native dated IDs)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_MODEL_FAST = os.environ.get("CLAUDE_MODEL_FAST", "claude-haiku-4-5")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CHROMA_PATH = os.environ.get("CHROMA_PATH", "data/chroma")
CHROMA_COLLECTION = "legal_articles"

# Embedding model used by the AICC /v1/embeddings proxy. voyage-3-large is
# what THEMIS's project has enabled today. Override via env var if you swap
# models (e.g. voyage-3-lite for cheaper indexing).
EMBEDDING_MODEL_AICC = os.environ.get("EMBEDDING_MODEL_AICC", "voyage-3-large")

# Shared bearer token for service-to-service callers (e.g. Exodus pulling
# rates). Empty string disables service-token auth — only Themis user PKCE
# tokens are then accepted by /api/rates/*. In production, generate via
# `openssl rand -base64 48` and set on Railway.
RATES_API_TOKEN = os.environ.get("RATES_API_TOKEN", "")

# AICC PKCE auth — backend verifies user tokens via AICC /auth/me.
# Distinct from AICC_BASE_URL (which has /v1 suffix for the AI proxy).
AICC_AUTH_BASE_URL = os.environ.get(
    "AICC_AUTH_BASE_URL",
    "https://aicommandcenter-production-d7b1.up.railway.app",
)
AICC_AUTH_TTL_SECONDS = int(os.environ.get("AICC_AUTH_TTL_SECONDS", "60"))
