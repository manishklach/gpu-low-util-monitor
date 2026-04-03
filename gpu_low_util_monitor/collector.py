"""Collection loop that samples all GPUs and maintains rolling summaries."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from gpu_low_util_monitor.models import DeviceIdentity, SampleReport
from gpu_low_util_monitor.nvml_adapter import NVMLBackend
from gpu_low_util_monitor.rolling_window import RollingWindow

LOGGER = logging.getLogger(__name__)


@dataclass
class CollectorConfig:
    """Runtime configuration for the collector."""

    interval_seconds: float
    window_short_seconds: int
    window_long_seconds: int


class GPUCollector:
    """Sample all visible GPUs and maintain rolling summaries per device."""

    def __init__(
        self,
        backend: NVMLBackend,
        config: CollectorConfig,
        monotonic_ns_fn: Callable[[], int] | None = None,
    ) -> None:
        self._backend = backend
        self._config = config
        self._monotonic_ns_fn = monotonic_ns_fn or time.monotonic_ns
        self._identities: list[DeviceIdentity] = []
        self._windows: dict[int, RollingWindow] = {}

    def initialize(self) -> None:
        """Initialize backend and per-device windows."""
        self._backend.initialize()
        self._identities = self._backend.device_identities()
        longest_window = max(self._config.window_short_seconds, self._config.window_long_seconds)
        self._windows = {
            identity.index: RollingWindow(longest_window + int(self._config.interval_seconds) + 5)
            for identity in self._identities
        }
        LOGGER.info("Initialized collector with %s GPU(s)", len(self._identities))

    def shutdown(self) -> None:
        """Shutdown the backend."""
        self._backend.shutdown()

    def poll_once(self) -> list[SampleReport]:
        """Poll each GPU once and compute rolling summaries."""
        reports: list[SampleReport] = []
        timestamp_ns = int(self._monotonic_ns_fn())
        for identity in self._identities:
            try:
                sample = self._backend.read_device_sample(identity, timestamp_ns)
            except Exception as exc:
                LOGGER.warning("Failed to read GPU %s (%s): %s", identity.index, identity.uuid, exc)
                continue
            window = self._windows[identity.index]
            window.append(sample)
            reports.append(
                SampleReport(
                    sample=sample,
                    short_summary=window.summarize(self._config.window_short_seconds),
                    long_summary=window.summarize(self._config.window_long_seconds),
                )
            )
        return reports
