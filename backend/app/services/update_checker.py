"""Daily law update checker service.

DEPRECATED: The auto-import behavior has been replaced by version discovery.
This module now delegates to version_discovery.run_daily_discovery().
Retained for backward compatibility with any direct callers.
"""

import logging

from app.services.version_discovery import run_daily_discovery

logger = logging.getLogger(__name__)


def check_for_updates(rate_limit_delay: float = 2.0) -> dict:
    """Check all stored laws for new versions.

    Now delegates to version discovery (metadata-only, no auto-import).
    """
    return run_daily_discovery(rate_limit_delay=rate_limit_delay)
