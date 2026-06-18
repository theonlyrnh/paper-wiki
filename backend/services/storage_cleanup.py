"""Backward-compatible no-op cleanup module.

The project used to run an automatic raw PDF cleanup loop. The new behavior is
manual deletion only, but this module remains as a compatibility shim so that
older imports do not fail if any stale code path still references it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def cleanup_enabled_users_once() -> dict:
    """Compatibility no-op for retired automatic cleanup."""
    return {"users_checked": 0, "deleted_count": 0, "freed_bytes": 0}


async def raw_pdf_cleanup_loop():
    """Compatibility no-op background loop.

    The new flow is manual deletion only. This function returns immediately so
    any stale startup import does not start background deletion.
    """
    logger.info("Raw PDF automatic cleanup is disabled; manual deletion only.")
    return
