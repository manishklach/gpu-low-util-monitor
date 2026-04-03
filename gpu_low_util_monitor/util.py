"""Utility helpers for the GPU low-utilization monitor."""

from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a float to a closed interval."""
    return max(minimum, min(maximum, value))


def ensure_directory(path: Path) -> Path:
    """Create a directory tree when needed."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def utc_now_iso() -> str:
    """Return the current UTC wall-clock time as ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def dumps_compact_json(payload: dict[str, Any]) -> str:
    """Serialize JSON with stable compact formatting."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=False)


def hostname() -> str:
    """Return the current host name for tagging exports."""
    return socket.gethostname()


def configure_logging(verbose: bool) -> None:
    """Configure root logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
